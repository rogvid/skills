"""demo-video recorders.

from demo_recording import Recorder          # web apps
from demo_recording import TerminalRecorder  # CLIs, REPLs, TUIs
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .recorder import Recorder
    from .terminal import TerminalRecorder

__all__ = ["Recorder", "TerminalRecorder"]


def __getattr__(name: str) -> object:
    # Lazy, so importing the web recorder never needs the Unix-only PTY modules.
    if name == "Recorder":
        from .recorder import Recorder

        return Recorder
    if name == "TerminalRecorder":
        from .terminal import TerminalRecorder

        return TerminalRecorder
    raise AttributeError(name)
