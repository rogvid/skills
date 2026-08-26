"""Problems takes for smoke tests."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_web_problems(out_root: Path) -> list[str]:
    """Record the web problems take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "web-problems")
    
    with fixture_server() as base_url:
        try:
            problems = record_web_problems(out_dir, base_url)
        except Exception as exc:
            return [f"web-problems: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def run_terminal_problems(out_root: Path) -> list[str]:
    """Record the terminal problems take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "terminal-problems")
    
    with fixture_server() as base_url:
        try:
            problems = record_terminal_problems(out_dir, base_url)
        except Exception as exc:
            return [f"terminal-problems: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_web_problems(out_dir: Path, base_url: str):
    """Record a web problems demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=False, deterministic=True
    ) as rec:
        pass
    
    return []


def record_terminal_problems(out_dir: Path, base_url: str):
    """Record a terminal problems demo."""
    from demo_recording import TerminalRecorder
    
    with TerminalRecorder(
        out_dir, base_url=base_url, speech=False, strict=False, deterministic=True
    ) as rec:
        pass
    
    return []