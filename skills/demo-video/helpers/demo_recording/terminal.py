"""TerminalRecorder — records a CLI or TUI running in a real terminal.

The program runs under a PTY; its output is rendered by a vendored xterm.js
terminal inside the same headless Chromium page the web recorder uses, so
every bit of the recording/narration substrate (video, captions, speech,
segments, stills) is reused unchanged. Only the interaction verbs differ.

    from demo_recording import TerminalRecorder

    with TerminalRecorder(Path(__file__).parent) as rec:
        rec.caption("Scaffold a project in one command.")
        rec.run("openui-gen init my-app")
        rec.wait_for_prompt()
        rec.shot("01-done")
        rec.send("y")                       # answer an interactive prompt
        rec.key("Down", "Down", "Enter")    # drive a TUI

Unix only: the PTY is Python's stdlib `pty`, which has no Windows support.
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

from .core import _DemoBase, _env

_ASSETS = Path(__file__).parent.parent / "assets" / "xterm"

# Terminal window theme (Catppuccin Mocha) — a cohesive, well-loved palette
# that reads as a polished dev terminal rather than a bare console.
_TERM_THEME = {
    "background": "#181825", "foreground": "#cdd6f4",
    "cursorAccent": "#181825",
    "selectionBackground": "#414458",
    "black": "#45475a", "red": "#f38ba8", "green": "#a6e3a1",
    "yellow": "#f9e2af", "blue": "#89b4fa", "magenta": "#f5c2e7",
    "cyan": "#94e2d5", "white": "#bac2de",
    "brightBlack": "#585b70", "brightRed": "#f38ba8", "brightGreen": "#a6e3a1",
    "brightYellow": "#f9e2af", "brightBlue": "#89b4fa",
    "brightMagenta": "#f5c2e7", "brightCyan": "#94e2d5",
    "brightWhite": "#a6adc8",
}

# Host page: render the terminal inside a floating, rounded window with a
# title bar and traffic-light buttons, centered on a soft pastel gradient so
# the eye has an obvious frame to follow (full-bleed is hard to read). The
# fit addon derives cols/rows from the window's inner size; they are read
# back to size the PTY so TUIs lay out correctly.
_TERM_HOST_JS = """
window.__demoTermInit = (opts) => {
  document.documentElement.style.height = '100%';
  document.body.style.cssText =
    'margin:0; height:100%; overflow:hidden; background:' + opts.bg + ';';

  const win = document.createElement('div');
  win.id = '__term_win';
  win.style.cssText = `
    position: fixed; top: 70px; left: 74px; right: 74px; bottom: 70px;
    display: flex; flex-direction: column; border-radius: 12px;
    overflow: hidden; background: ${opts.theme.background};
    box-shadow: 0 30px 80px rgba(20,16,40,.38), 0 6px 18px rgba(20,16,40,.28);
  `;
  const bar = document.createElement('div');
  bar.style.cssText = `
    display: flex; align-items: center; gap: 8px; height: 40px;
    padding: 0 14px; background: #232334; flex: 0 0 auto;
    font: 13px/1 ui-monospace, monospace; color: #9399b2;
  `;
  const dot = (c) => `<span style="width:12px;height:12px;border-radius:50%;
    display:inline-block;background:${c}"></span>`;
  bar.innerHTML =
    dot('#ff5f57') + dot('#febc2e') + dot('#28c840') +
    `<span style="flex:1;text-align:center;letter-spacing:.02em">${opts.title}</span>` +
    `<span style="width:44px"></span>`;
  win.appendChild(bar);

  const host = document.createElement('div');
  host.id = '__term_host';
  host.style.cssText = 'flex: 1 1 auto; min-height: 0; padding: 12px 14px;';
  win.appendChild(host);
  document.body.appendChild(win);

  const term = new Terminal({
    fontSize: opts.fontSize,
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace',
    fontWeight: 400, fontWeightBold: 600,
    cursorBlink: true, convertEol: false, scrollback: 5000,
    lineHeight: 1.12, letterSpacing: 0,
    theme: Object.assign({}, opts.theme, { cursor: opts.cursor }),
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(host);
  fit.fit();
  window.__term = term;
  window.__termWrite = (d) => term.write(d);
  window.__termText = () => {
    const buf = term.buffer.active;
    const out = [];
    for (let i = 0; i < buf.length; i++) {
      const line = buf.getLine(i);
      out.push(line ? line.translateToString(true) : '');
    }
    return out.join('\\n');
  };
  return { cols: term.cols, rows: term.rows };
};
"""

# Soft, low-saturation pastel gradient behind the window — present enough to
# frame the terminal, calm enough not to pull focus.
_TERM_BG = "linear-gradient(135deg, #f6d5f0 0%, #d7e3fb 52%, #cdeede 100%)"

# Named keys -> the bytes a terminal program expects. Ctrl-<letter> is
# handled generically (C-a..C-z -> 0x01..0x1a).
_KEYMAP = {
    "Enter": "\r", "Return": "\r", "Tab": "\t", "Space": " ",
    "Escape": "\x1b", "Esc": "\x1b", "Backspace": "\x7f", "Delete": "\x1b[3~",
    "Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D",
    "Home": "\x1b[H", "End": "\x1b[F", "PageUp": "\x1b[5~", "PageDown": "\x1b[6~",
}


class TerminalRecorder(_DemoBase):
    """Records a terminal session (CLI, REPL, or full-screen TUI).

    The recorder launches an interactive shell whose prompt (PS1) it sets to
    `terminal_prompt`, so `wait_for_prompt()` has a reliable marker. Drive it
    with `run` (a command + Enter), `send` (typed input), and `key` (named
    keys for TUIs); synchronize with `wait_for_prompt` and `wait_for_text`.
    Captions, interludes, stills, segments, and speech are inherited.

    Geometry: the recording size (viewport) drives the xterm.js grid via the
    fit addon; the resulting cols/rows are pushed to the PTY winsize so TUIs
    render correctly. `font_size` tunes how much fits on screen.
    """

    def __init__(
        self,
        out_dir=None,
        shell: str | None = None,
        font_size: int | None = None,
        segment: str | None = None,
        accent_rgb: tuple[int, int, int] | None = None,
        terminal_title: str | None = None,
        terminal_prompt: str | None = None,
        viewport: tuple[int, int] | None = None,
        speech: bool | None = None,
        voice_id: str | None = None,
        speech_model: str | None = None,
        type_delay_ms: int = 45,
    ) -> None:
        # A branded, distinctive default prompt so wait_for_prompt's marker
        # is unlikely to collide with command output.
        prompt = terminal_prompt or _env("TERMINAL_PROMPT") or "❯ "
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model,
        )
        # Match the web recorder's effective caption height. Web composites
        # its page into a scaled, centered window, lifting its bottom:44px
        # caption to ~89px in the final frame; the terminal isn't composited,
        # so raise its caption to the same height for uniform placement.
        self._caption_bottom_px = 88
        self._shell = shell or _env("TERMINAL_SHELL") or "/bin/bash"
        fs = font_size
        if fs is None:
            raw = _env("TERMINAL_FONT_SIZE", "15")
            fs = int(raw) if raw and raw.isdigit() else 15
        self._font_size = fs
        self._type_delay = type_delay_ms / 1000.0
        self._prompt_marker = self._terminal_prompt.strip() or self._terminal_prompt
        self._fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._child_done = False

    # -- setup / teardown ---------------------------------------------------

    def _init_context(self, context) -> None:
        # Paint the background from the very first frame, so the brief
        # about:blank + xterm-injection period isn't a white flash (it would
        # otherwise show between a preceding segment and the terminal).
        context.add_init_script(
            "(() => { const bg = '__BG__';"
            " document.documentElement.style.background = bg;"
            " const b = () => { if (document.body) document.body.style.background = bg; };"
            " if (document.body) b(); else addEventListener('DOMContentLoaded', b); })();"
            .replace("__BG__", _TERM_BG)
        )

    def _start(self) -> None:
        master, slave = pty.openpty()
        self._fd = master
        env = os.environ.copy()
        env["PS1"] = self._terminal_prompt
        env["PS2"] = "> "
        env["TERM"] = "xterm-256color"
        env.setdefault("LANG", "C.UTF-8")
        # A real PTY makes tools page their output (git, man, systemctl → less),
        # which holds the terminal and hangs wait_for_prompt. Disable paging by
        # default; a storyboard can still demo a pager deliberately with keys.
        env["PAGER"] = "cat"
        env["GIT_PAGER"] = "cat"
        env["SYSTEMD_PAGER"] = "cat"
        # --norc/--noprofile so the exported PS1 is what shows; -i for an
        # interactive shell (job control, line editing) as a user would see.
        self._proc = subprocess.Popen(
            [self._shell, "--norc", "--noprofile", "-i"],
            stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, env=env, close_fds=True,
        )
        os.close(slave)
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Build the xterm.js terminal in the page and read back its geometry.
        self.page.goto("about:blank")
        self.page.add_style_tag(content=(_ASSETS / "xterm.css").read_text())
        self.page.add_script_tag(content=(_ASSETS / "xterm.js").read_text())
        self.page.add_script_tag(content=(_ASSETS / "addon-fit.js").read_text())
        self.page.add_script_tag(
            content=(_ASSETS / "addon-serialize.js").read_text()
        )
        self.page.add_script_tag(content=_TERM_HOST_JS)
        dims = self.page.evaluate(
            "o => window.__demoTermInit(o)",
            {"bg": _TERM_BG, "theme": _TERM_THEME,
             "title": self._terminal_title,
             "cursor": f"rgb({self._accent})",
             "fontSize": self._font_size},
        )
        self._set_winsize(int(dims["rows"]), int(dims["cols"]))
        # Just enough to catch the shell's first prompt — keep it short so a
        # segment that opens with a transition doesn't dwell on a bare, empty
        # terminal before the transition covers it.
        self._idle(0.15)

    def _stop(self) -> None:
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        fd = getattr(self, "_fd", None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            self._fd = None

    def _set_winsize(self, rows: int, cols: int) -> None:
        # Setting TIOCSWINSZ on the master signals SIGWINCH to the child,
        # so a TUI already running re-lays-out to the new size.
        if self._fd is not None:
            fcntl.ioctl(
                self._fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )

    # -- PTY <-> page pump --------------------------------------------------

    def _pump(self) -> None:
        """Drain whatever the program has written and render it. Called
        continuously while holding a frame, so output scrolls live."""
        if self._fd is None:
            return
        for _ in range(4096):
            try:
                r, _, _ = select.select([self._fd], [], [], 0)
            except (OSError, ValueError):
                self._child_done = True
                return
            if not r:
                return
            try:
                data = os.read(self._fd, 65536)
            except OSError:
                # EIO on Linux when the child closes the slave — end of output.
                self._child_done = True
                return
            if not data:
                self._child_done = True
                return
            text = self._decoder.decode(data)
            if text:
                self.page.evaluate("d => window.__termWrite(d)", text)

    def _idle(self, seconds: float) -> None:
        """Hold the frame while pumping program output, so long-running
        commands keep scrolling on screen instead of freezing."""
        end = time.time() + seconds
        while True:
            self._pump()
            remaining = end - time.time()
            if remaining <= 0:
                return
            time.sleep(min(0.04, remaining))

    def _screen(self) -> str:
        self._pump()
        return self.page.evaluate("() => window.__termText()")

    def _at_idle_prompt(self, text: str) -> bool:
        """True when the shell is sitting at an empty prompt (command
        finished). Keys on the *last* non-empty line being exactly the
        prompt marker with nothing typed after it — robust to programs
        that clear/repaint the screen (top, TUIs), which erase earlier
        prompt lines and defeat any prompt-counting scheme."""
        lines = [ln for ln in text.split("\n") if ln.strip()]
        return bool(lines) and lines[-1].strip() == self._prompt_marker

    # -- input --------------------------------------------------------------

    def _write(self, data: str) -> None:
        if self._fd is not None:
            os.write(self._fd, data.encode())

    def _type(self, text: str) -> None:
        """Type visibly, key by key — the PTY echoes each character back, so
        it appears on screen as typed (no separate animation needed)."""
        for ch in text:
            self._write(ch)
            self._idle(self._type_delay)

    def run(self, command: str) -> None:
        """Type a shell command visibly and press Enter. Pair with
        wait_for_prompt() to wait for it to finish."""
        self._type(command)
        self._write("\r")
        self._idle(0.2)

    def send(self, text: str, enter: bool = True) -> None:
        """Type a response to the running program (an answer to a prompt, a
        REPL expression). enter=False to send the keystrokes without Return."""
        self._type(text)
        if enter:
            self._write("\r")
        self._idle(0.2)

    def key(self, *names: str) -> None:
        """Send keys to a TUI. Each argument is one of: a named key ("Up"
        "Down" "Left" "Right" "Enter" "Tab" "Escape" "Home" "End" "PageUp"
        "PageDown" "Backspace" "Delete" "Space"); a Ctrl combo "C-<letter>"
        (e.g. "C-c"); or a single literal character ("q", "j", "/")."""
        for name in names:
            seq = _KEYMAP.get(name)
            if seq is None:
                m = re.fullmatch(r"[Cc]-([a-zA-Z])", name)
                if m:
                    seq = chr(ord(m.group(1).lower()) - 96)  # C-a -> 0x01
                elif len(name) == 1:
                    seq = name  # a literal keystroke: "q", "j", "/"
                else:
                    raise ValueError(f"unknown key {name!r}")
            self._write(seq)
            self._idle(0.12)

    # -- synchronization ----------------------------------------------------

    def wait_for_text(self, pattern: str, timeout_s: float = 60) -> None:
        """Wait until the rendered screen (visible text + scrollback,
        ANSI-stripped) matches `pattern` (a regex, searched). `^` and `$`
        anchor to individual screen lines (re.MULTILINE). Robust for TUIs,
        which repaint continuously and emit no clean 'done' line."""
        rx = re.compile(pattern, re.MULTILINE)
        deadline = time.time() + timeout_s
        while True:
            text = self._screen()
            if rx.search(text):
                self.pause(0.2)
                return
            if time.time() > deadline:
                tail = text[-1000:]
                raise RuntimeError(
                    f"timed out after {timeout_s}s waiting for /{pattern}/. "
                    f"Screen tail:\n{tail}"
                )
            time.sleep(0.05)

    def wait_for_prompt(self, timeout_s: float = 60) -> None:
        """Wait until the shell prompt returns after a run() — i.e. the
        command finished. A special case of wait_for_text keyed on the
        branded prompt marker."""
        deadline = time.time() + timeout_s
        while True:
            text = self._screen()
            if self._at_idle_prompt(text):
                self.pause(0.2)
                return
            if self._child_done:
                return  # the shell itself exited
            if time.time() > deadline:
                tail = text[-1000:]
                raise RuntimeError(
                    f"timed out after {timeout_s}s waiting for the prompt "
                    f"({self._prompt_marker!r}). Screen tail:\n{tail}"
                )
            time.sleep(0.05)

    # -- capture ------------------------------------------------------------

    def shot(self, name: str) -> Path:
        """Still for the written guide -> images/<name>.png (pumps pending
        output first so the latest screen state is captured)."""
        self._pump()
        return super().shot(name)
