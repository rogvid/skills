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
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time
from collections import deque
from collections.abc import Sequence
from pathlib import Path

from .content import content_rect
from .core import INTERLUDE_CSS, INTERLUDE_ID, _beat_verb, _DemoBase, _env

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

# -- opening on a card (issue #110) ------------------------------------------
#
# A terminal segment that opens with `interlude()` shows a flash of bare
# terminal first, and the gap is structural rather than a pacing mistake:
# `__enter__` starts Chromium's screencast when it creates the page, and a
# storyboard cannot paint anything before its own first statement. Measured on
# the reference demo: the segment's first frame at 37.76 s, the card at
# 38.05 s, and an empty window with a lone prompt in between. The web recorder
# does not show it only because it has nothing on screen until `goto()` — there
# is no "before" to flash.
#
# So the card stops being something a storyboard has to remember to do first
# and becomes a property of the recorder: `TerminalRecorder(interlude="…")`
# paints it from an **init script**, which runs before the page's own scripts
# on every document including Chromium's initial one. That is earlier than any
# Python statement can reach — earlier than `pty.openpty()`, earlier than
# xterm.js is injected — so the card is up in the recording's first frame and
# the whole of the recorder's own setup happens behind it.
#
# It is also the answer to the *other* end of the same seam. #91 was this card
# left up for the rest of a take, because a storyboard remembered
# `interlude(text)` and not `interlude("")`. A card the recorder raises is a
# card the recorder clears — see `_open_on_card`.
#
# It builds the element rather than calling `__demoInterlude`, and the whole
# difference is one line: the card is appended **already opaque**.
# `__demoInterlude` creates it at `opacity: 0` and raises it, which is a 450 ms
# fade — and a card that fades in over the recorder's setup is showing exactly
# what it exists to cover. An element whose computed opacity has been 1 since
# it entered the tree has no transition to run, so that is structural here
# rather than a flag somebody could turn off. Everything else about it — the
# id, the styling — is core's, so `interlude("")` finds this element and fades
# it out like any other.
#
# (What the suite can say about that last point is limited, and tests/README.md
# says where: on this box the fade-in variant is invisible in the recording
# too, because injecting xterm.js takes longer than 450 ms and Chromium's
# screencast has emitted nothing by then. Being opaque by construction is what
# keeps that from being the thing holding the fix up.)
_OPENING_CARD_JS = """
(() => {
  const build = () => {
    // `document.body` is null on Chromium's initial empty document, where init
    // scripts first run — the same guard the background paint above needs, and
    // for the same reason (issue #25).
    if (!document.body || document.getElementById('__ID__')) return;
    const el = document.createElement('div');
    el.id = '__ID__';
    el.style.cssText = '__CSS__';
    el.style.opacity = '1';
    el.textContent = __TEXT__;
    document.body.appendChild(el);
  };
  if (document.body) build();
  else addEventListener('DOMContentLoaded', build);
})();
"""

# How long the opening card is held before it fades, when nothing says
# otherwise. The same default `interlude()` uses, because it is the same card
# doing the same job.
OPENING_CARD_HOLD_S = 2.8

# Named keys -> the bytes a terminal program expects. Ctrl-<letter> is
# handled generically (C-a..C-z -> 0x01..0x1a).
_KEYMAP = {
    "Enter": "\r", "Return": "\r", "Tab": "\t", "Space": " ",
    "Escape": "\x1b", "Esc": "\x1b", "Backspace": "\x7f", "Delete": "\x1b[3~",
    "Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D",
    "Home": "\x1b[H", "End": "\x1b[F", "PageUp": "\x1b[5~", "PageDown": "\x1b[6~",
}

# Exit-status side channel.
#
# `run()` cannot know how its command ended: the command is still running when
# the verb returns, and there is exactly one pipe out of the PTY — the same one
# the recording is made of. Asking (`echo $?`) would type a line the viewer can
# see, which is a demo artifact nobody asked for.
#
# So the shell says it in its prompt, invisibly. PS1 is prefixed with an OSC
# escape carrying `$?` **and `\#`, bash's command number**, which bash expands
# per prompt, wrapped in \[...\] so readline still measures the prompt
# correctly. _pump() strips the sequence out of the byte stream before xterm.js
# ever sees it, so nothing about the recording changes.
#
# The command number is what makes the status trustworthy rather than merely
# usually right, and every part of it was measured against a real PTY:
#
#   * the shell prints a prompt at startup, before any command — that marker
#     carries number 1 and belongs to nothing. It is discarded as the first
#     marker seen, whenever it arrives, which is what makes a slow shell on a
#     loaded box unable to hand its startup 0 to the first run().
#   * a prompt redrawn without a command running — an empty Enter, a Ctrl-C at
#     an idle prompt — repeats the previous number (measured: empty Enter stays
#     at 2, Ctrl-C at an idle prompt stays at 4 while reporting status 130).
#     A marker that does not advance the number is discarded.
#   * commands the storyboard did not wait for still complete in order, so
#     `run` beats queue and each advancing marker claims the oldest
#     (measured: `sleep 1.2` then `(exit 9)` typed straight after yields
#     (0, 5) then (9, 6), and the queue assigns them 0 and 9 respectively).
#
# Bash-shaped, like the rest of this recorder (`--norc --noprofile -i`, PS1/PS2
# from the environment). A shell that does not expand `$?` in its prompt simply
# never emits a marker, and every `exit_code` stays null rather than wrong.
#
# The namespace is not a security boundary: a program that deliberately prints
# this exact sequence can hand the recorder any exit status it likes. It is a
# demo recorder driving a program the storyboard chose, not a sandbox.
_EXIT_PS1 = "\\[\\e]777;demo-video-exit;$?;\\#\\a\\]"
_EXIT_OSC = "\x1b]777;demo-video-exit;"
_EXIT_RE = re.compile(re.escape(_EXIT_OSC) + r"(-?\d+);(\d+)\x07")




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

    `interlude="…"` opens the segment on a full-screen title card, raised
    before capture starts and cleared by the recorder when `interlude_hold`
    seconds are up. Use it instead of an `interlude()` as the storyboard's
    first statement: the storyboard's first statement is already ~290 ms too
    late, and the viewer sees an empty terminal before the card (issue #110).
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
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
        type_delay_ms: int = 45,
        interlude: str | None = None,
        interlude_hold: float = OPENING_CARD_HOLD_S,
    ) -> None:
        # A branded, distinctive default prompt so wait_for_prompt's marker
        # is unlikely to collide with command output.
        prompt = terminal_prompt or _env("TERMINAL_PROMPT") or "❯ "
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model, strict=strict,
            deterministic=deterministic, clock=clock,
            timezone_id=timezone_id, locale=locale, evidence=evidence,
            criteria=criteria,
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
        # Exit-status side channel: run() beats still waiting for a status, in
        # the order they were typed; the last command number seen (None until
        # the shell's startup prompt arrives); and any half-arrived marker held
        # back between reads (a 65 KB read can split the sequence anywhere).
        self._pending_runs: deque[dict] = deque()
        self._exit_seq: int | None = None
        self._exit_tail = ""
        # When the PTY last produced a byte.
        self._last_data_at = time.monotonic()
        # The card this segment opens on, if it opens on one. See
        # _OPENING_CARD_JS.
        self._opening = interlude
        self._opening_hold = interlude_hold
        # Where the xterm.js screen sits in the frame, read off the live
        # element once the terminal exists (issue #97). See `_content_rect`.
        self._host_box: tuple[int, int, int, int] | None = None

    # -- setup / teardown ---------------------------------------------------

    def _init_context(self, context) -> None:
        # Paint the background from the very first frame, so the brief
        # about:blank + xterm-injection period isn't a white flash (it would
        # otherwise show between a preceding segment and the terminal).
        # `documentElement` is null on Chromium's initial empty document, where
        # init scripts first run — dereferencing it there threw an uncaught
        # TypeError on every single take, and took the background paint this
        # exists to apply down with it (issue #25). Guarded like `body` below
        # it, and applied again once the document is real.
        context.add_init_script(
            "(() => { const bg = '__BG__';"
            " const paint = (el) => { if (el) el.style.background = bg; };"
            " paint(document.documentElement);"
            " const b = () => { paint(document.documentElement); paint(document.body); };"
            " if (document.body) b(); else addEventListener('DOMContentLoaded', b); })();"
            .replace("__BG__", _TERM_BG)
        )
        # After the background paint and before anything else: the card is
        # opaque and covers the whole viewport, so what is behind it only has
        # to be the right colour for the fade *out*. Registered here rather
        # than evaluated in `_start()` because `_start()` navigates
        # (`goto("about:blank")`), and an init script is the only thing that
        # survives a navigation and precedes the first paint of what follows
        # it.
        if self._opening is not None:
            context.add_init_script(
                _OPENING_CARD_JS.replace("__ID__", INTERLUDE_ID)
                .replace("__CSS__", INTERLUDE_CSS)
                .replace("__TEXT__", json.dumps(self._opening))
            )

    def _start(self) -> None:
        master, slave = pty.openpty()
        self._fd = master
        env = os.environ.copy()
        env["PS1"] = _EXIT_PS1 + self._terminal_prompt
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
        self._read_host_box()
        # Just enough to catch the shell's first prompt. It used to be kept
        # short so a segment opening on a transition would not dwell on a bare
        # terminal; with `interlude=` that dwell happens behind the card, and
        # without it there is no card for the length of this to matter to.
        self._idle(0.15)
        if self._opening is not None:
            self._open_on_card()

    def _read_host_box(self) -> None:
        """Remember where `#__term_host` is, for the picture check (issue #97).

        Read here, off the live element, rather than derived from the window
        CSS: `_TERM_HOST_JS` positions the window with fixed insets and the
        xterm.js fit addon decides the rest, so a change to either would
        silently move the rect a hardcoded copy claimed to describe. Read
        **once**, at `_start()`, because nothing after this resizes it and the
        page is gone by the time the mp4 exists.

        Failure is not fatal and not silent: `content_report` says the picture
        was not measured, which is a truthful artifact. Refusing a take because
        a bounding box could not be read would be the check costing somebody
        the recording it exists to describe.
        """
        try:
            box = self.page.locator("#__term_host").bounding_box()
        except Exception as exc:  # noqa: BLE001 - a measurement is not a take
            print(
                f"demo-video: WARNING — could not read the terminal's box "
                f"({type(exc).__name__}: {exc}), so this take's timeline will "
                f"say the picture was not measured.",
                file=sys.stderr,
            )
            return
        if box:
            self._host_box = (
                int(box["x"]), int(box["y"]),
                int(box["width"]), int(box["height"]),
            )

    def _content_rect(self) -> tuple[int, int, int, int] | None:
        """The xterm.js screen's region of the frame (issue #97).

        A terminal take frames itself *in the page* and `_postprocess` is a
        no-op, so page coordinates are video coordinates: the context is
        created with `record_video_size == viewport`. Everything outside this
        box — the pastel background, the window chrome, the title bar — is the
        recorder's own drawing and never changes, which is precisely what a
        whole-frame score would end up measuring (issue #17).
        """
        if self._host_box is None:
            return None
        return content_rect(self._host_box)

    def _open_on_card(self) -> None:
        """Hold the card the init script raised, then take it down.

        Everything before this ran behind it — the PTY, the xterm.js
        injection, the shell's first prompt — which is the point: the segment
        opens on intent rather than on an empty window (issue #110).

        Taking it down is the other half of the same seam. #91 was this card
        left up for the rest of a take because a storyboard remembered
        `interlude(text)` and not `interlude("")`; a card the recorder raises
        is a card the recorder clears, and there is no ordering left for a
        storyboard to get wrong.

        It records an ordinary `interlude` beat, so a merged timeline reads the
        same whether the card came from here or from the verb.
        """
        text = self._opening or ""
        clip = self._prepare_line(text)
        with self._beat("interlude", selector="card", caption=text):
            self._start_line(clip)
            self.pause(self._opening_hold)
            self.page.evaluate("() => window.__demoInterlude('')")
            self.pause(0.6)

    def _stop(self) -> None:
        # Whatever _take_exit_markers held back as a possible half-marker was
        # withheld from the terminal, not dropped — flush it before the page
        # goes away, or the last frame is missing bytes the program did write.
        tail, self._exit_tail = self._exit_tail, ""
        if tail:
            try:
                self._write_out(tail)
            except Exception:  # noqa: BLE001 - teardown, the page may be gone
                pass
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
            # Decoder first (a UTF-8 sequence can straddle a read), exit
            # markers second — the recorder's own side channel, never rendered.
            self._last_data_at = time.monotonic()
            self._write_out(self._take_exit_markers(self._decoder.decode(data)))

    def _write_out(self, text: str) -> None:
        """The one door into the terminal. Everything on screen came through
        here."""
        if text:
            self.page.evaluate("d => window.__termWrite(d)", text)


    def _failure_screen(self) -> str | None:
        """The rendered terminal buffer, for `failure/screen.txt` (issue #11).

        The same string `wait_for_text` matches against — visible rows and scrollback, ANSI
        already resolved by xterm.js. For a TUI that is the entire account of
        what went wrong, and a reviewer cannot get it out of a frame.

        Called from `__exit__` after `_stop()`, which is the only slot where
        it is complete: `_stop()` has flushed whatever the exit-marker reader
        was holding back. It does not re-pump — the fd is closed by then — so
        this is xterm.js's buffer as the recording ends on it.
        """
        return str(self.page.evaluate("() => window.__termText()"))

    def _take_exit_markers(self, text: str) -> str:
        """Strip the PS1 exit-status markers out of `text`, recording each.

        The stream is chopped at arbitrary byte offsets, so a marker can span
        two reads; anything at the tail that could still become one is held
        back rather than passed through to the terminal.
        """
        text = self._exit_tail + text
        self._exit_tail = ""
        if _EXIT_OSC[0] not in text:
            return text
        kept: list[str] = []
        cut = 0
        for match in _EXIT_RE.finditer(text):
            kept.append(text[cut:match.start()])
            cut = match.end()
            self._record_exit_code(int(match.group(1)), int(match.group(2)))
        rest = text[cut:]
        start = rest.rfind(_EXIT_OSC[0])
        if start != -1:
            candidate = rest[start:]
            unfinished = _EXIT_OSC.startswith(candidate) or (
                candidate.startswith(_EXIT_OSC) and "\x07" not in candidate
            )
            if unfinished:
                self._exit_tail = candidate
                rest = rest[:start]
        kept.append(rest)
        return "".join(kept)

    def _record_exit_code(self, code: int, seq: int) -> None:
        """Attribute a status to the oldest run() still waiting for one.

        `seq` is the shell's command number, and every discard below is a
        status that would otherwise have been written onto the wrong beat:

          * the first marker of the session is the startup prompt, which
            reports the shell's own 0 and belongs to no command;
          * a marker that does not advance the number is a prompt redrawn
            without a command running (empty Enter, Ctrl-C at an idle prompt),
            and its status likewise belongs to nothing;
          * anything else claims the oldest outstanding run(), which is the
            right one even when the storyboard typed several commands without
            waiting between them — the shell still executes them in order.

        A marker arriving with nothing outstanding is a command the storyboard
        did not run (a `send()` that reached the shell, say) and is dropped.
        """
        if self._exit_seq is None:
            self._exit_seq = seq
            return
        if seq <= self._exit_seq:
            return
        self._exit_seq = seq
        if not self._pending_runs:
            return
        beat = self._pending_runs.popleft()
        beat["exit_code"] = code
        if code != 0:
            command = beat.get("selector")
            self._note_issue(
                "nonzero_exit",
                f"{command!r} exited {code}",
                beat=beat, exit_code=code, command=command,
            )

    def _idle(self, seconds: float) -> None:
        """Hold the frame while pumping program output, so long-running
        commands keep scrolling on screen instead of freezing."""
        end = time.monotonic() + seconds
        while True:
            self._pump()
            # _pump() only reaches Playwright when the program wrote something,
            # so a quiet hold would deliver no page events and leave issue
            # attribution pointing at whatever beat came next.
            self._pump_events()
            remaining = end - time.monotonic()
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

    @_beat_verb("run")
    def run(self, command: str) -> None:
        """Type a shell command visibly and press Enter. Pair with
        wait_for_prompt() to wait for it to finish.

        The beat this records gains an `exit_code` once the shell's prompt
        comes back — usually during the following wait_for_prompt(), which is
        why the pairing is not merely a suggestion. A command that exits
        non-zero also logs a `nonzero_exit` issue, and fails the take under
        strict=True.

        Type example values. Nothing here hides what the PTY echoes — see
        "What this records, and what it does not defend against" in SKILL.md."""
        self._type(command)
        beat = self._beats[-1] if self._beats else None
        if beat is not None:
            beat["exit_code"] = None
            # A queue, not a slot: two run()s with no wait between them are
            # legitimate (`run("sleep 5")` then `run("deploy")`), and a slot
            # would hand the first command's status to the second beat and
            # drop the second command's entirely.
            self._pending_runs.append(beat)
        self._write("\r")
        self._idle(0.2)

    @_beat_verb("send")
    def send(self, text: str, enter: bool = True) -> None:
        """Type a response to the running program (an answer to a prompt, a
        REPL expression). enter=False to send the keystrokes without Return.

        The PTY echoes what it is given, so this is on camera. A program that
        turns echo off — a real `getpass` — shows nothing either way, which is
        the program's doing and not this recorder's."""
        self._type(text)
        if enter:
            self._write("\r")
        self._idle(0.2)

    @_beat_verb("key", lambda args, kwargs: " ".join(args) or None)
    def key(self, *names: str) -> None:
        """Send keys to a TUI. Each argument is one of: a named key ("Up"
        "Down" "Left" "Right" "Enter" "Tab" "Escape" "Home" "End" "PageUp"
        "PageDown" "Backspace" "Delete" "Space"); a Ctrl combo "C-<letter>"
        (e.g. "C-c"); or a single literal character ("q", "j", "/").

        The beat records the keys joined by spaces, so a value spelled out one
        keystroke at a time is in the log that way as well as on screen."""
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

    @_beat_verb("wait_for_text")
    def wait_for_text(self, pattern: str, timeout_s: float = 60) -> None:
        """Wait until the rendered screen (visible text + scrollback,
        ANSI-stripped) matches `pattern` (a regex, searched). `^` and `$`
        anchor to individual screen lines (re.MULTILINE). Robust for TUIs,
        which repaint continuously and emit no clean 'done' line."""
        rx = re.compile(pattern, re.MULTILINE)
        deadline = time.monotonic() + timeout_s
        while True:
            text = self._screen()
            if rx.search(text):
                self.pause(0.2)
                return
            if time.monotonic() > deadline:
                tail = text[-1000:]
                raise RuntimeError(
                    f"timed out after {timeout_s}s waiting for /{pattern}/. "
                    f"Screen tail:\n{tail}"
                )
            time.sleep(0.05)

    @_beat_verb("wait_for_prompt")
    def wait_for_prompt(self, timeout_s: float = 60) -> None:
        """Wait until the shell prompt returns after a run() — i.e. the
        command finished. A special case of wait_for_text keyed on the
        branded prompt marker."""
        deadline = time.monotonic() + timeout_s
        while True:
            text = self._screen()
            if self._at_idle_prompt(text):
                self.pause(0.2)
                return
            if self._child_done:
                return  # the shell itself exited
            if time.monotonic() > deadline:
                tail = text[-1000:]
                raise RuntimeError(
                    f"timed out after {timeout_s}s waiting for the prompt "
                    f"({self._prompt_marker!r}). Screen tail:\n{tail}"
                )
            time.sleep(0.05)

    # -- capture ------------------------------------------------------------

    def shot(self, name: str, ac: str | Sequence[str] | None = None) -> Path:
        """Still for the written guide -> images/<name>.png (pumps pending
        output first so the latest screen state is captured).

        `ac` is passed straight through — a terminal take records against a
        ticket exactly like a web one, and a criterion demonstrated on the
        command line is the ordinary reason a demo has a terminal half.
        """
        self._pump()
        return super().shot(name, ac=ac)

    # -- evidence (issue #9) ------------------------------------------------

    def _evidence_payload(self) -> dict:
        """The rendered screen at the end of this beat.

        `_screen()` is what `wait_for_text` already matches against: xterm.js's
        own view of the buffer, ANSI sequences resolved rather than stripped by
        a regex, visible rows and scrollback both. It is the terminal's exact
        analogue of the web recorder's ARIA snapshot — what a reader would see,
        with none of the paint.

        **Nothing here is hidden, and that is the documented behaviour rather
        than an oversight.** This recorder does not defend against a secret
        reaching the screen — a command that prints one writes it here
        verbatim, the same exposure the recording itself already has, in a
        form that greps. SKILL.md says so where an author will read it, at the
        top of the file.
        """
        return {"screen": self._screen()}
