"""demo-video recorders.

Storyboards import from here:

    from demo_recording import Recorder          # web apps
    from demo_recording import TerminalRecorder   # CLIs / TUIs
    from demo_recording import stitch             # concat segments -> demo.mp4
"""

from .core import media_duration, stitch, tts_clip
from .terminal import TerminalRecorder
from .web import Recorder

__all__ = [
    "Recorder",
    "TerminalRecorder",
    "stitch",
    "media_duration",
    "tts_clip",
]
