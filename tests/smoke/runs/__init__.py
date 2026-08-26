"""Run functions for smoke tests."""

from .web import run_web
from .terminal import run_terminal
from .segments import run_segments
from .spotlight import run_spotlight
from .terminal_opening import run_terminal_opening
from .content import run_content
from .overlay import run_overlay
from .coverage import run_coverage
from .problems import run_web_problems, run_terminal_problems
from .strict import run_strict_web, run_strict_terminal
from .wrapper import run_wrapper
from .stills import run_stills_only
from .evidence import run_evidence
from .narration import run_narration
from .terminal_race import run_terminal_race
from .determinism import run_determinism
from .failure import run_failure

__all__ = [
    "run_web",
    "run_terminal",
    "run_segments",
    "run_spotlight",
    "run_terminal_opening",
    "run_content",
    "run_overlay",
    "run_coverage",
    "run_web_problems",
    "run_terminal_problems",
    "run_strict_web",
    "run_strict_terminal",
    "run_wrapper",
    "run_stills_only",
    "run_evidence",
    "run_narration",
    "run_terminal_race",
    "run_determinism",
    "run_failure",
]