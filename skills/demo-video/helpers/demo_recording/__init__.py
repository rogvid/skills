"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4
"""

from .core import (
    TIMELINE_SCHEMA,
    media_duration,
    render_timeline_md,
    stitch,
    timeline_paths,
    tts_clip,
    write_timeline,
)
from .terminal import TerminalRecorder
from .web import Recorder

__all__ = [
    "TIMELINE_SCHEMA",
    "Recorder",
    "TerminalRecorder",
    "media_duration",
    "render_timeline_md",
    "stitch",
    "timeline_paths",
    "tts_clip",
    "write_timeline",
]
