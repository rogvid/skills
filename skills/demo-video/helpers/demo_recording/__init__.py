"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4
"""

from .core import (
    EVIDENCE_DIR,
    EVIDENCE_LIMITS,
    EVIDENCE_SCHEMA,
    EVIDENCE_TRUNCATED,
    FAILURE_DIR,
    FAILURE_MARKER,
    FAILURE_SCHEMA,
    FRAMES_SCHEMA,
    ISSUE_KINDS,
    MAX_ISSUES,
    SCENE_MIN_SPAN_S,
    SECRET_MASK,
    SECRET_MIN_LEN,
    STRICT_KINDS,
    TIMELINE_SCHEMA,
    Secret,
    SecretLeak,
    StrictTakeFailed,
    beat_frames,
    evidence_name,
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
    "Recorder",
    "SCENE_MIN_SPAN_S",
    "SECRET_MASK",
    "SECRET_MIN_LEN",
    "STRICT_KINDS",
    "Secret",
    "SecretLeak",
    "StrictTakeFailed",
    "TIMELINE_SCHEMA",
    "TerminalRecorder",
    "beat_frames",
    "evidence_name",
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
