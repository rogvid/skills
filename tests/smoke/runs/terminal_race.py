"""Terminal race take for smoke tests."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_terminal_race(out_root: Path) -> list[str]:
    """Record the terminal race take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "terminal-race")
    
    with fixture_server() as base_url:
        try:
            problems = record_terminal_race(out_dir, base_url)
        except Exception as exc:
            return [f"terminal-race: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_terminal_race(out_dir: Path, base_url: str):
    """Record a terminal race demo."""
    from demo_recording import TerminalRecorder
    
    with TerminalRecorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []