"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4
"""

from .core import (
    FRAMES_SCHEMA,
    ISSUE_KINDS,
    MAX_ISSUES,
    SCENE_MIN_SPAN_S,
    SECRET_MASK,
    STRICT_KINDS,
    TIMELINE_SCHEMA,
    Secret,
    SecretLeak,
    StrictTakeFailed,
    beat_frames,
    frames_paths,
    media_duration,
    render_frames_md,
    render_timeline_md,
    scene_times,
    stitch,
    timeline_paths,
    tts_clip,
    write_beat_frames,
    write_timeline,
)
from .terminal import TerminalRecorder
from .web import Recorder

__all__ = [
    "FRAMES_SCHEMA",
    "ISSUE_KINDS",
    "MAX_ISSUES",
    "SCENE_MIN_SPAN_S",
    "SECRET_MASK",
    "STRICT_KINDS",
    "TIMELINE_SCHEMA",
    "Recorder",
    "Secret",
    "SecretLeak",
    "StrictTakeFailed",
    "TerminalRecorder",
    "beat_frames",
    "frames_paths",
    "media_duration",
    "render_frames_md",
    "render_timeline_md",
    "scene_times",
    "stitch",
    "timeline_paths",
    "tts_clip",
    "write_beat_frames",
    "write_timeline",
]
