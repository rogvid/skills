"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4

**The two recorders are imported lazily, and that is load-bearing rather than
an optimisation.** Everything else this package exposes — the timeline schema
and its two renderings, the coverage report, the content and opening
measurements, the review-frame manifest, `stitch` — is a function of documents
and files, with no third-party dependency at all. Importing any of it used to
require Playwright, because this file imported both recorders eagerly and
`core` imports Playwright at module scope.

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

from .content import (
    CONTENT_ACTING_VERBS,
    CONTENT_BLANK_FLOOR,
    CONTENT_MOVED_PIXELS,
    CONTENT_PASSIVE_VERBS,
    CONTENT_PIXEL_DELTA,
    CONTENT_SAMPLE_FPS,
    CONTENT_STATIC_WARN_S,
    OPENING_HOLD_LIMIT_S,
    OPENING_SAMPLE_FPS,
    OPENING_SEARCH_S,
    OPENING_WARN_S,
    content_rect,
    content_report,
    media_duration,
    merge_content,
    opening_gap,
    opening_report,
    opening_warning,
    print_content_summary,
)
from .coverage import coverage_report
from .failure import FAILURE_DIR, FAILURE_MARKER, FAILURE_SCHEMA
from .frames import (
    FRAMES_SCHEMA,
    SCENE_MIN_SPAN_S,
    beat_frames,
    frames_paths,
    render_frames_md,
    scene_times,
    write_beat_frames,
)
from .stitching import stitch
from .timeline import (
    EVIDENCE_DIR,
    EVIDENCE_LIMITS,
    EVIDENCE_SCHEMA,
    EVIDENCE_TRUNCATED,
    ISSUE_KINDS,
    MAX_ISSUES,
    STRICT_KINDS,
    TIMELINE_SCHEMA,
    StrictTakeFailed,
    evidence_name,
    render_timeline_md,
    timeline_paths,
    write_timeline,
)

if TYPE_CHECKING:  # the real classes, for type checkers and editors only
    from .core import tts_clip
    from .terminal import TerminalRecorder
    from .web import Recorder

# Everything that cannot be reached without Playwright. `tts_clip` is here for
# the same reason the recorders are: it lives in `core`, which imports it.
_LAZY = {
    "Recorder": ".web",
    "TerminalRecorder": ".terminal",
    "tts_clip": ".core",
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
    "CONTENT_ACTING_VERBS",
    "CONTENT_BLANK_FLOOR",
    "CONTENT_MOVED_PIXELS",
    "CONTENT_PASSIVE_VERBS",
    "CONTENT_PIXEL_DELTA",
    "CONTENT_SAMPLE_FPS",
    "CONTENT_STATIC_WARN_S",
    "EVIDENCE_DIR",
    "EVIDENCE_LIMITS",
    "EVIDENCE_SCHEMA",
    "EVIDENCE_TRUNCATED",
    "FAILURE_DIR",
    "FAILURE_MARKER",
    "FAILURE_SCHEMA",
    "FRAMES_SCHEMA",
    "ISSUE_KINDS",
    "MAX_ISSUES",
    "OPENING_HOLD_LIMIT_S",
    "OPENING_SAMPLE_FPS",
    "OPENING_SEARCH_S",
    "OPENING_WARN_S",
    "Recorder",
    "SCENE_MIN_SPAN_S",
    "STRICT_KINDS",
    "StrictTakeFailed",
    "TIMELINE_SCHEMA",
    "TerminalRecorder",
    "beat_frames",
    "content_report",
    "content_rect",
    "coverage_report",
    "evidence_name",
    "frames_paths",
    "media_duration",
    "merge_content",
    "opening_gap",
    "opening_report",
    "opening_warning",
    "print_content_summary",
    "render_frames_md",
    "render_timeline_md",
    "scene_times",
    "stitch",
    "timeline_paths",
    "tts_clip",
    "write_beat_frames",
    "write_timeline",
]
