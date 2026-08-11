"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4

## What this package promises, and what it does not

**`__all__` is the storyboard surface, and nothing else** (issue #148). Six
names: the two recorders, `stitch`, the exception a strict take raises, and the
two helpers the documentation tells you to re-run on a demo you already have —
`beat_frames` to regenerate review frames, `content_report` to re-measure the
picture. Those six are what SKILL.md and `reference/` describe, and they are the
contract.

It used to be fifty. The package re-exported every threshold, schema constant
and writer the recorder owns, because the end-to-end suite in this skill's own
repository read the recorder's internals back through the front door to grade
itself — the shallow module in its plainest form, an interface as wide as its
implementation. A storyboard
author opening this file met `CONTENT_MOVED_PIXELS` before `Recorder`.

**Nothing became unreachable.** Every one of those names still lives in the
module that owns it and is imported from there:

    from demo_recording.timeline import TIMELINE_SCHEMA, render_timeline_md
    from demo_recording.content import media_duration, merge_content
    from demo_recording.frames import scene_times

That is the distinction being drawn, and it is the only one: **a test may reach
into the module it is testing; a storyboard may not.** Those suites live in
this skill's repository and are not installed with it; they import through the
owning module now. If you are consuming
`timeline.json` programmatically from outside this repository, its schema and
its renderer are `demo_recording.timeline`'s and always were — they are not
private, they are simply not part of the storyboard surface, and this package
does not promise them a stable front door.

## Why the recorders are imported lazily

Everything else this package exposes is a function of documents and files, with
no third-party dependency at all. Importing any of it used to require Playwright,
because this file imported both recorders eagerly and `core` imports Playwright
at module scope.

Two consequences followed, and both were bugs:

  * nothing could unit-test any of it without a browser installed, so the
    recorder's only check was a ten-minute end-to-end suite (issue #139);
  * `from demo_recording import Recorder` — the *web* recorder, which has no
    PTY dependency — failed at import on Windows, because `terminal` imports
    `fcntl`, `pty` and `termios` at module scope (issue #14). SKILL.md scopes
    the Unix-only constraint to terminal recording, so the code was stricter
    than the documentation promised.

`Recorder` and `TerminalRecorder` are therefore resolved on first attribute
access via PEP 562. `from demo_recording import Recorder` behaves exactly as
before; what changed is that not asking for it no longer costs a browser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .content import content_report
from .frames import beat_frames
from .stitching import stitch
from .timeline import StrictTakeFailed

if TYPE_CHECKING:  # the real classes, for type checkers and editors only
    from .terminal import TerminalRecorder
    from .web import Recorder

# Everything that cannot be reached without Playwright — which is only the two
# recorders. `tts_clip` used to be here too, for the same reason: it lived in
# `core`, which imports Playwright at module scope. It does not need one (a
# cache key is a function of three strings), so #157 moved it to `narration`,
# where `tests/unit` reaches it directly.
_LAZY = {
    "Recorder": ".web",
    "TerminalRecorder": ".terminal",
}


def __getattr__(name: str) -> object:
    """Resolve the browser-backed names on first access (PEP 562).

    The error a missing dependency produces is left exactly as Python raises
    it — `ModuleNotFoundError: No module named 'playwright'` names the thing to
    install, and wrapping it in something friendlier would only bury that.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "Recorder",
    "StrictTakeFailed",
    "TerminalRecorder",
    "beat_frames",
    "content_report",
    "stitch",
]
