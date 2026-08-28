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
import sys
import termios
import time
from collections import deque
from pathlib import Path

from .chrome import chrome_geometry, chrome_html, opening_hold_script
from .content import content_rect, opening_card_report
from .core import _beat_verb, _DemoBase, _env

_ASSETS = Path(__file__).parent.parent / "assets" / "xterm"

# Terminal window theme (Catppuccin Mocha) — a cohesive, well-loved palette
# that reads as a polished dev terminal rather than a bare console. This is
# the *content's* colour, a parameter of the chrome's slot, not chrome
# (#355's design record): the window frame around it comes from chrome.py,
# shared with the web recorder since #362.
_TERM_THEME = {
    "background": "#181825",
    "foreground": "#cdd6f4",
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

# The terminal window's body — the fill the shared chrome paints the window,
# the opening hold and the card layer with on a terminal take, and the
# xterm.js slot content's own background. One name so the four cannot drift:
# it is the theme's background on purpose, because the old bespoke window
# (`_TERM_HOST_JS`, retired by #362) painted its body from the theme too and
# the seam between window pad and terminal screen is invisible only while
# the two agree. Numerically equal to `core.WEB_WINDOW_BODY` today; kept as
# its own name because it is the *theme's* colour, a content parameter.
TERM_WINDOW_BODY = _TERM_THEME["background"]

# Mounts xterm.js in the shared chrome's content slot (#362) — the same
# `#__chrome_slot` the web recorder mounts its app iframe into. The window
# around it (background, title bar, pads, caption band, card layer) is
# chrome.py's; this script only fills the slot. The host div keeps the id
# `__term_host` so every geometry consumer that reads the live element
# (issue #97) reads the same one it always has. The fit addon derives
# cols/rows from the slot's size; they are read back to size the PTY so
# TUIs lay out correctly.
#
# History: until #362 this file carried `_TERM_HOST_JS`, a second
# hand-maintained copy of the window chrome (bar 40 px against the shared
# 36, radius 12 against 14, its own gradient and shadow, fixed 70/74 insets
# against computed pads). #355's addendum retired it: one chrome, two
# mounts.
_TERM_MOUNT_JS = """
window.__demoTermInit = (opts) => {
  const slot = document.getElementById('__chrome_slot');
  const host = document.createElement('div');
  host.id = '__term_host';
  host.style.cssText = 'position: absolute; inset: 0; padding: 12px 14px;'
    + ' box-sizing: border-box; background: ' + opts.theme.background + ';';
  slot.appendChild(host);

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

# -- opening on a card (issue #110, re-based on the shared chrome by #362) ----
#
# A terminal segment that opens with `interlude()` shows a flash of bare
# terminal first, and it is structural rather than a pacing mistake:
# `__enter__` starts Chromium's screencast when it creates the page, and a
# storyboard cannot paint anything before its own first statement. Measured on
# the reference demo: six frames — ~0.30 s — of an empty window with a lone
# prompt at the head of part2 (#110, #207).
#
# What covers that gap since #362 is the chrome's **opening hold**
# (chrome.OPENING_HOLD_JS): an opaque field in the window's own colour over
# the app rect, up in frame 0 from an init script — earlier than any Python
# statement can reach, earlier than `pty.openpty()`, earlier than xterm.js is
# injected — exactly the web recorder's #360 pattern, one implementation for
# both media. The whole of the recorder's setup happens behind it, and the
# hold is cleared when the terminal has something to show (the shell's first
# prompt), the same contract as the web path's first `goto()`.
#
# `TerminalRecorder(interlude="…")` still opens the segment on intent rather
# than on a covered pause: the clause is raised in the chrome's card layer
# (`__demoInterlude`, over the hold — chrome.py's stacking puts the card
# above it) as the first thing `_start()` does after the chrome document is
# up, so its 450 ms fade runs over the hold's flat field, never over the
# recorder's setup. The card renders on the app rect in the window's own
# body colour — the shared card layer, not the full-bleed `#1c1a17` field
# the retired `_OPENING_CARD_JS` init script used to build (#362 states the
# visual change; #291's palette history is on `core.WEB_WINDOW_BODY`).
#
# The other end of the seam is unchanged: #91 was this card left up for the
# rest of a take. A card the recorder raises is a card the recorder clears —
# see `_open_on_card`.
OPENING_CARD_HOLD_S = 2.8

# Where the opening frame is read back off the finished video (issue #235):
# a strip of the **app rect**, as fractions of it. A band across the top,
# where a shell's first rows land, starting near the left edge — terminal
# text hugs the left column, and a strip inset the way the web card strip
# is (`tests/_pixels.CARD_STRIP`) was measured missing every glyph of a
# short command (travel 0.01 against frame 0 on a healthy take). Inset a
# slot-padding's worth from the left and top so the strip never reads the
# slot's own edge blend, and kept above the centred clause card's text.
#
# Inside the app rect, where until #362 it was a strip of background beside
# the bespoke window: the shared chrome's card layer covers the app rect and
# nothing else, so the background beside the window never changes and can no
# longer say what the take opened on. What frame 0 shows there now is the
# opening hold (or the clause card over it) — the window's own dark body —
# against the defect's reading: the slot's white canvas, or the unheld
# pastel background, both an order of magnitude of luma away.
OPENING_STRIP = (0.01, 0.04, 0.90, 0.16)  # x, y, w, h as fractions of the app rect

# Named keys -> the bytes a terminal program expects. Ctrl-<letter> is
# handled generically (C-a..C-z -> 0x01..0x1a).
_KEYMAP = {
    "Enter": "\r",
    "Return": "\r",
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

    `interlude="…"` opens the segment on a title card in the chrome's card
    layer, raised over the opening hold before any storyboard statement runs
    and cleared by the recorder when `interlude_hold` seconds are up. Use it
    instead of an `interlude()` as the storyboard's first statement: the
    storyboard's first statement is already ~290 ms too late (issue #110).
    Either way the take opens covered — the hold is up in frame 0 (#360's
    pattern, shared since #362) — so a bare terminal is never on screen.
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
        speech_stability: float | None = None,
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
        ticket: str | None = None,
        stills_only: bool | None = None,
        pace: float | None = None,
        intro: str | None = None,
        outro: str | None = None,
        window_title: str | None = None,
        window_scale: float | tuple[float, float] | None = None,
        caption_overlay: bool | None = None,
        preview: bool | None = None,
        preset: str | None = None,
        allow_private: bool | None = None,
        type_delay_ms: int = 45,
        interlude: str | None = None,
        interlude_hold: float = OPENING_CARD_HOLD_S,
    ) -> None:
        # A branded, distinctive default prompt so wait_for_prompt's marker
        # is unlikely to collide with command output.
        prompt = terminal_prompt or _env("TERMINAL_PROMPT") or "❯ "
        # This medium defaults to the reserved band even though the base
        # defaults to the overlay pill (#403): a shell keeps its prompt on
        # the bottom rows, exactly where the pill rides, so the overlay
        # would sit on the one line a terminal take is usually about. An
        # explicit parameter or DEMO_VIDEO_CAPTION_OVERLAY still wins.
        if caption_overlay is None and _env("CAPTION_OVERLAY") is None:
            caption_overlay = False
        # This medium's opening card is `interlude=`, raised before capture
        # and cleared by its own hold. An `intro=` accepted and ignored here
        # would be a setting that does nothing, so it is refused with the way
        # out named — the same posture as every other authoring error.
        if intro is not None:
            raise RuntimeError(
                "TerminalRecorder has no intro= — open on a title card with "
                "TerminalRecorder(interlude=...) instead, which this medium "
                "raises before capture starts and clears itself"
            )
        if outro is not None:
            raise RuntimeError(
                "TerminalRecorder has no outro= — close on a card with "
                "rec.interlude(...) and leave it up, which this medium "
                "records as the segment's last frame"
            )
        super().__init__(
            out_dir,
            segment=segment,
            accent_rgb=accent_rgb,
            terminal_title=terminal_title,
            terminal_prompt=prompt,
            viewport=viewport,
            speech=speech,
            voice_id=voice_id,
            speech_model=speech_model,
            speech_stability=speech_stability,
            strict=strict,
            deterministic=deterministic,
            clock=clock,
            timezone_id=timezone_id,
            locale=locale,
            evidence=evidence,
            criteria=criteria,
            ticket=ticket,
            allow_private=allow_private,
            stills_only=stills_only,
            pace=pace,
            intro=intro,
            outro=outro,
            window_title=window_title,
            window_scale=window_scale,
            caption_overlay=caption_overlay,
            preview=preview,
            preset=preset,
        )
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
        # The card this segment opens on, if it opens on one. See the
        # "opening on a card" section header above.
        self._opening = interlude
        self._opening_hold = interlude_hold
        # Where the xterm.js screen sits in the frame, read off the live
        # element once the terminal exists (issue #97). See `_content_rect`.
        self._host_box: tuple[int, int, int, int] | None = None

    # -- setup / teardown ---------------------------------------------------

    def _init_context(self, context) -> None:
        # The shared chrome's opening hold (#360, mounted here by #362): it
        # paints the chrome background on the initial document — the #25
        # white-flash guard, now one script for both media — and holds an
        # opaque field in the window's own colour over the app rect from
        # frame 0, so the whole of this recorder's setup (the PTY, the
        # xterm.js injection, the shell's first prompt) happens behind it.
        # An init script because that runs on Chromium's initial empty
        # document, earlier than any Python statement can reach.
        context.add_init_script(
            opening_hold_script(
                chrome_geometry(
                    self._size["width"],
                    self._size["height"],
                    width_scale=self._window_scale[0],
                    height_scale=self._window_scale[1],
                    caption_overlay=self._caption_overlay,
                ),
                window_body=TERM_WINDOW_BODY,
            )
        )

    def _chrome_title(self) -> str:
        """What the wrapper window's title bar says: the take's
        `window_title` when it has one, this medium's branded
        `terminal_title` when it does not."""
        return self._window_title or self._terminal_title

    def _start(self) -> None:
        # The chrome document first, so the recorded pixels are the shared
        # window from the earliest paint after frame 0's hold. `self._geom`
        # is `chrome_geometry`'s dict — the one shape every geometry consumer
        # reads, web and terminal alike (#362).
        self._geom = chrome_geometry(
            self._size["width"],
            self._size["height"],
            width_scale=self._window_scale[0],
            height_scale=self._window_scale[1],
            caption_overlay=self._caption_overlay,
        )
        self.page.set_content(
            chrome_html(
                self._geom,
                title=self._chrome_title(),
                window_body=TERM_WINDOW_BODY,
                accent=self._accent,
                caption_font_px=self._caption_font_px,
            )
        )
        # `set_content` wrote a new document, which took the motion rule with
        # it — and this medium's content lives in that document. See
        # `_freeze_motion_here`.
        self._freeze_motion_here()
        if self._opening is not None:
            # The clause, in the chrome's card layer, raised before anything
            # else this method does: its fade runs over the opening hold's
            # flat field (the card layer stacks above the hold), never over
            # the recorder's setup — #110's point, on #360's machinery.
            self.page.evaluate("t => window.__demoInterlude(t)", self._opening)

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
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Mount xterm.js in the chrome's content slot and read back its grid.
        self.page.add_style_tag(content=(_ASSETS / "xterm.css").read_text())
        self.page.add_script_tag(content=(_ASSETS / "xterm.js").read_text())
        self.page.add_script_tag(content=(_ASSETS / "addon-fit.js").read_text())
        # `@xterm/addon-serialize` was vendored and injected here too, and
        # nothing ever instantiated `SerializeAddon` (#54). The one path that
        # reads screen text back out of xterm.js is `window.__termText()`, over
        # `term.buffer.active` — what `_screen()`, `wait_for_text()` and
        # `wait_for_prompt()` all use. Deleted rather than kept against a future
        # artifact: it cost 16 kB of third-party JS parsed into every terminal
        # take, and a reader of this method reasonably assumed it did something.
        # A serialized dump of the buffer beside `timeline.json` is a feature
        # somebody can propose on its own; it was never this.
        self.page.add_script_tag(content=_TERM_MOUNT_JS)
        dims = self.page.evaluate(
            "o => window.__demoTermInit(o)",
            {
                "theme": _TERM_THEME,
                "cursor": f"rgb({self._accent})",
                "fontSize": self._font_size,
            },
        )
        self._set_winsize(int(dims["rows"]), int(dims["cols"]))
        self._read_host_box()
        # Just enough to catch the shell's first prompt. The dwell happens
        # behind the opening hold (and the clause card, when there is one),
        # so nothing bare is on screen for the length of this to matter to.
        self._idle(0.15)
        if self._opening is not None:
            self._open_on_card()
        else:
            # The terminal has something to show — the shell's prompt — so
            # the opening hold comes down, exactly as the web recorder's
            # first goto() clears it: the hold is up from frame 0 and the
            # medium's first content is what takes it down (#360, #362).
            self.page.evaluate("() => window.__demoChromeHoldClear()")

    def _read_host_box(self) -> None:
        """Remember where `#__term_host` is, for the picture check (issue #97).

        Read here, off the live element, rather than derived from
        `chrome_geometry`: the host fills the chrome's content slot, but its
        own padding and the slot's placement both live in stylesheets, so a
        change to either would silently move the rect a hardcoded copy
        claimed to describe. Read **once**, at `_start()`, because nothing
        after this resizes it and the page is gone by the time the mp4
        exists.

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
                int(box["x"]),
                int(box["y"]),
                int(box["width"]),
                int(box["height"]),
            )

    def _opening_card_rect(self) -> tuple[int, int, int, int] | None:
        """The strip of the app rect the opening frame is read off (#235).

        `OPENING_STRIP` of `chrome_geometry`'s app rect — inside the window,
        where until #362 it was a strip of background beside the bespoke
        one. The section header over `OPENING_STRIP` says why it moved: the
        shared chrome's card layer covers the app rect and nothing else, so
        the background outside the window never changes and frame 0 is told
        apart *here* — the hold or the clause card (the window's own dark
        body) against the slot's unheld canvas, an order of magnitude of
        luma away.

        None when the chrome geometry was never built — a take that died
        before `_start()` has no frame worth describing, and inventing a
        rect there would produce a confident number about the wrong pixels.
        """
        geom = getattr(self, "_geom", None)
        if not geom:
            return None
        fx, fy, fw, fh = OPENING_STRIP
        return (
            geom["appx"] + int(geom["appw"] * fx),
            geom["appy"] + int(geom["apph"] * fy),
            max(8, int(geom["appw"] * fw)),
            max(8, int(geom["apph"] * fh)),
        )

    def _opening_card(self) -> dict | None:
        """What this segment's first frame showed (issue #235).

        The medium's half of `_DemoBase._opening_card`, and the reason the
        hook exists here rather than in the base: the opening this take
        reads is its own — the hold, or the clause card the constructor's
        `interlude=` raised over it. The web recorder answers None; its
        opening hold is graded by this repository's `tests/smoke
        --wrapper-only` instead.

        Reported and not enforced — nothing here appends to `warnings`, raises
        or refuses. See "the frame a terminal segment opens on" in `content`
        for the loaded-runner reading that decided that.

        Answered on **every** terminal take, not only one opened with
        `interlude=`: since #362 both arrangements open dark (the hold is
        unconditional), so `"bare"` here is always the defect — a hold that
        never painted — and `raised` says whether a clause was on it.
        """
        return opening_card_report(
            self._media_path(),
            self._opening_card_rect(),
            raised=self._opening is not None,
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
        """Hold the card `_start()` raised, then take it down.

        Everything before this ran behind the opening hold and the clause
        card over it — the PTY, the xterm.js injection, the shell's first
        prompt — which is the point: the segment opens on intent rather than
        on an empty window (issue #110).

        Taking it down is the other half of the same seam. #91 was this card
        left up for the rest of a take because a storyboard remembered
        `interlude(text)` and not `interlude("")`; a card the recorder raises
        is a card the recorder clears, and there is no ordering left for a
        storyboard to get wrong.

        The hold beneath goes down in the same breath — invisible under the
        opaque card, so the card's fade reveals the terminal rather than a
        second flat field a viewer would read as a stuck screen.

        It records an ordinary `interlude` beat, so a merged timeline reads the
        same whether the card came from here or from the verb.
        """
        text = self._opening or ""
        clip = self._prepare_line(text)
        with self._beat("interlude", selector="card", caption=text):
            self._start_line(clip)
            self.pause(self._opening_hold)
            self.page.evaluate(
                "() => { window.__demoChromeHoldClear(); window.__demoInterlude(''); }"
            )
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
                self._fd,
                termios.TIOCSWINSZ,
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
            kept.append(text[cut : match.start()])
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
        expected = beat.get("expect_exit", 0)
        if code != expected:
            command = beat.get("selector")
            # Named against what was *expected*, not against zero, so a
            # storyboard that declared 2 and got 1 is told what it was
            # promised rather than being handed the generic message.
            wanted = "" if expected == 0 else f", expected {expected}"
            self._note_issue(
                "nonzero_exit",
                f"{command!r} exited {code}{wanted}",
                beat=beat,
                exit_code=code,
                command=command,
            )

    def _hold_frame(self, seconds: float) -> None:
        """Hold the frame while pumping program output, so long-running
        commands keep scrolling on screen instead of freezing.

        `_hold_frame` and not `_idle`: the base seals `_idle` so a stills-only
        run cannot be paced by a medium that forgot about it (#372). Nothing
        is lost by not running here in that mode — the PTY is drained by
        `_screen()`, which is what `wait_for_text` and `wait_for_prompt` call
        on every pass of their own loops."""
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
    def run(self, command: str, expect_exit: int = 0) -> None:
        """Type a shell command visibly and press Enter. Pair with
        wait_for_prompt() to wait for it to finish.

        The beat this records gains an `exit_code` once the shell's prompt
        comes back — usually during the following wait_for_prompt(), which is
        why the pairing is not merely a suggestion. A command whose status is
        not `expect_exit` logs a `nonzero_exit` issue, and fails the take
        under strict=True.

        **`expect_exit` is for a failure that is the demonstration** (#405).
        A storyboard showing that a bad argument is refused has to run a
        command that exits non-zero — that *is* the feature — and before this
        existed such a take could not rehearse, because `demo-rehearse` pins
        `strict=True` and strict read every non-zero exit as a defect. The
        declaration is per call and it is a number rather than a flag: a
        storyboard promising 2 and getting 1 has still found something, and
        `run(cmd, expect_exit=True)` could not say so.

        It is deliberately not a way to silence a failing command. Declaring
        the wrong number still fails, and declaring 0 — the default — is the
        behaviour every existing storyboard already has.

        Type example values. Nothing here hides what the PTY echoes — see
        "What this records, and what it does not defend against" in SKILL.md."""
        self._type(command)
        beat = self._beats[-1] if self._beats else None
        if beat is not None:
            beat["exit_code"] = None
            # Recorded on the beat, so `timeline.json` carries the promise
            # beside the result and a reader can see the take meant it.
            if expect_exit:
                beat["expect_exit"] = expect_exit
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
        """Wait until the rendered screen (visible text + scrollback, ANSI
        resolved by xterm.js rather than stripped by a regex) matches `pattern`
        (a regex, searched). `^` and `$` anchor to individual screen lines
        (re.MULTILINE). Robust for TUIs, which repaint continuously and emit no
        clean 'done' line."""
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

    def _before_shot(self) -> None:
        """Pump pending output so the still is of the latest screen state.

        A hook rather than a `shot` override (#147): `shot` writes the beat
        and the `ac` claim the coverage report is built from, and a medium
        that owned the whole method could drop either without anything
        noticing. All this medium needs is the flush.
        """
        self._pump()

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
