"""TerminalRecorder: a real shell under a PTY, drawn by xterm.js in the page.

    with TerminalRecorder(HERE) as rec:
        rec.caption("One command scaffolds the project.")
        rec.run("mytool init demo-app")
        rec.run("python3", wait=False)       # interactive: don't wait for the prompt
        rec.send("1 + 1")
        rec.key("C-d")

Unix only (Python's `pty`).
"""

from __future__ import annotations

import codecs
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time
from pathlib import Path

from .recorder import _env, _Take

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "xterm"
THEME = {
    "background": "#181825",
    "foreground": "#cdd6f4",
    "cursor": "#f5e0dc",
    "cursorAccent": "#181825",
    "selectionBackground": "#414458",
    "black": "#45475a",
    "red": "#f38ba8",
    "green": "#a6e3a1",
    "yellow": "#f9e2af",
    "blue": "#89b4fa",
    "magenta": "#f5c2e7",
    "cyan": "#94e2d5",
    "white": "#bac2de",
    "brightBlack": "#585b70",
    "brightRed": "#f38ba8",
    "brightGreen": "#a6e3a1",
    "brightYellow": "#f9e2af",
    "brightBlue": "#89b4fa",
    "brightMagenta": "#f5c2e7",
    "brightCyan": "#94e2d5",
    "brightWhite": "#a6adc8",
}
KEYS = {
    "Enter": "\r",
    "Tab": "\t",
    "Space": " ",
    "Escape": "\x1b",
    "Esc": "\x1b",
    "Backspace": "\x7f",
    "Delete": "\x1b[3~",
    "Up": "\x1b[A",
    "Down": "\x1b[B",
    "Right": "\x1b[C",
    "Left": "\x1b[D",
    "Home": "\x1b[H",
    "End": "\x1b[F",
    "PageUp": "\x1b[5~",
    "PageDown": "\x1b[6~",
}
# The prompt reports each command's exit status in an invisible escape
# sequence, which is also how the recorder knows the prompt is back.
_MARK = "\x1b]777;demo;"
_MARK_RE = re.compile(re.escape(_MARK) + r"(-?\d+)\x07")
_PS1 = "\\[\\e]777;demo;$?\\a\\]"

_PAGE = """<html><head><style>{css}
html,body{{margin:0;height:100%;background:{bg};overflow:hidden}}
#t{{position:absolute;inset:0;padding:14px 16px;box-sizing:border-box}}
</style></head><body><div id="t"></div></body></html>"""
_MOUNT = """opts => {
  const term = new Terminal({fontSize: opts.fontSize, lineHeight: 1.15, scrollback: 5000,
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace',
    cursorBlink: false, theme: opts.theme});
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById('t'));
  fit.fit();
  window.__term = term;
  window.__text = () => {
    const b = term.buffer.active, out = [];
    for (let i = 0; i < b.length; i++) { const l = b.getLine(i); out.push(l ? l.translateToString(true) : ''); }
    return out.join('\\n');
  };
  return {cols: term.cols, rows: term.rows};
}"""


class TerminalRecorder(_Take):
    """Records a CLI, REPL or full-screen TUI in a real terminal."""

    theme = "dark"
    default_viewport = (1024, 576)

    def __init__(
        self,
        out_dir: str | Path | None = None,
        *,
        shell: str | None = None,
        prompt: str = "❯ ",
        font_size: int = 15,
        cwd: str | Path | None = None,
        env: dict | None = None,
        **options,
    ) -> None:
        super().__init__(out_dir, **options)
        self._shell = shell or _env("TERMINAL_SHELL", "/bin/bash")
        self._prompt = prompt
        self._font_size = font_size
        self._cwd = str(cwd) if cwd else None
        self._env = env or {}
        self._fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending = ""
        self._prompts = 0
        self._run_seen = 0
        self._last_output = time.time()

    def _default_title(self) -> str:
        return "terminal"

    def _start(self) -> None:
        css = (ASSETS / "xterm.css").read_text()
        self.page.set_content(_PAGE.format(css=css, bg=THEME["background"]))
        self.page.add_script_tag(content=(ASSETS / "xterm.js").read_text())
        self.page.add_script_tag(content=(ASSETS / "addon-fit.js").read_text())
        dims = self.page.evaluate(_MOUNT, {"theme": THEME, "fontSize": self._font_size})
        master, slave = pty.openpty()
        fcntl.ioctl(
            master, termios.TIOCSWINSZ, struct.pack("HHHH", dims["rows"], dims["cols"], 0, 0)
        )
        env = dict(os.environ, **self._env)
        env.update(
            PS1=_PS1 + self._prompt, PS2="> ", TERM="xterm-256color", PAGER="cat", GIT_PAGER="cat"
        )
        env.setdefault("LANG", "C.UTF-8")
        self._proc = subprocess.Popen(
            [self._shell, "--norc", "--noprofile", "-i"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            env=env,
            cwd=self._cwd,
            close_fds=True,
        )
        os.close(slave)
        fcntl.fcntl(master, fcntl.F_SETFL, fcntl.fcntl(master, fcntl.F_GETFL) | os.O_NONBLOCK)
        self._fd = master
        self._wait_prompt(0, 10)
        self.screencast.start()
        self._real(0.15)

    def _stop(self) -> None:
        super()._stop()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def _tick(self) -> None:
        if self._fd is None:
            return
        chunks = []
        while True:
            try:
                ready, _, _ = select.select([self._fd], [], [], 0)
                data = os.read(self._fd, 65536) if ready else b""
            except OSError:
                data = b""
            if not data:
                break
            chunks.append(self._decoder.decode(data))
        if chunks:
            self._last_output = time.time()
            self.page.evaluate("d => window.__term.write(d)", self._strip_marks("".join(chunks)))

    def _strip_marks(self, text: str) -> str:
        text = self._pending + text
        self._pending = ""
        for match in _MARK_RE.finditer(text):
            self._prompts += 1
            code = int(match.group(1))
            if self._prompts > 1 and code != 0:
                self._problems.append(f"exit {code} after: {self._step}")
        text = _MARK_RE.sub("", text)
        cut = text.rfind("\x1b]")
        if cut != -1 and "\x07" not in text[cut:] and _MARK.startswith(text[cut:][: len(_MARK)]):
            self._pending, text = text[cut:], text[:cut]
        return text

    def _screen(self) -> str:
        self._tick()
        return str(self.page.evaluate("() => window.__text()"))

    def _failure_detail(self) -> str:
        try:
            tail = [line for line in self._screen().splitlines() if line.strip()][-12:]
        except Exception:  # noqa: BLE001
            return ""
        return "  last lines on screen:\n" + "\n".join("    " + line for line in tail)

    def _write(self, data: str) -> None:
        if self._fd is not None:
            os.write(self._fd, data.encode())

    def _type(self, text: str) -> None:
        assert self.clock is not None
        start = time.time()
        for ch in text:
            self._write(ch)
            self._real(0.012)
        self._real(0.05)
        self.clock.retime(start, min(3.0, max(0.3, len(text) * 0.055)) * self.pace)

    def _wait_prompt(self, seen: int, timeout_s: float) -> None:
        deadline = time.time() + timeout_s
        while self._prompts <= seen:
            if time.time() > deadline:
                raise TimeoutError(f"the prompt did not come back within {timeout_s}s")
            self._real(0.03)

    # -- verbs ------------------------------------------------------------------

    def run(self, command: str, wait: bool = True, timeout_s: float = 60) -> None:
        """Type a command and press Enter. By default, wait for the prompt to
        come back; `wait=False` for programs that stay running."""
        self._mark(f"run {command!r}")
        seen = self._run_seen = self._prompts
        self._type(command)
        self._write("\r")
        if wait:
            with self._app_time():
                self._wait_prompt(seen, timeout_s)
        self._settle()

    def send(self, text: str, enter: bool = True) -> None:
        """Type into whatever is running (a REPL, a prompt)."""
        self._mark(f"send {text!r}")
        self._type(text)
        if enter:
            self._write("\r")
        self._settle()

    def key(self, *names: str) -> None:
        """Press keys: "Enter", "Up", "C-c", or a single character."""
        self._mark(f"key {' '.join(names)}")
        for name in names:
            seq = KEYS.get(name)
            if seq is None:
                ctrl = re.fullmatch(r"[Cc]-([a-zA-Z])", name)
                if ctrl:
                    seq = chr(ord(ctrl.group(1).lower()) - 96)
                elif len(name) == 1:
                    seq = name
                else:
                    raise ValueError(f"unknown key {name!r}")
            self._keys.append(
                {"start": self._now(), "end": self._now() + 0.9 * self.pace, "text": name}
            )
            self._write(seq)
            self._real(0.15)
        self._settle()

    def wait_for_text(self, pattern: str, timeout_s: float = 60) -> None:
        """Wait until `pattern` (a regex) is on screen."""
        self._mark(f"wait_for_text {pattern!r}")
        rx = re.compile(pattern, re.MULTILINE)
        with self._app_time():
            deadline = time.time() + timeout_s
            while not rx.search(self._screen()):
                if time.time() > deadline:
                    raise TimeoutError(f"{pattern!r} did not appear within {timeout_s}s")
                self._real(0.05)
        self._real(0.1)

    def wait_for_prompt(self, timeout_s: float = 60) -> None:
        """Wait for the shell prompt after `run(..., wait=False)`."""
        self._mark("wait_for_prompt")
        with self._app_time():
            self._wait_prompt(self._run_seen, timeout_s)
        self._real(0.1)

    def wait_for_quiet(self, quiet_s: float = 1.0, timeout_s: float = 60) -> None:
        """Wait until the program has printed nothing for `quiet_s`."""
        self._mark("wait_for_quiet")
        with self._app_time():
            deadline = time.time() + timeout_s
            while time.time() - self._last_output < quiet_s:
                if time.time() > deadline:
                    break
                self._real(0.05)
