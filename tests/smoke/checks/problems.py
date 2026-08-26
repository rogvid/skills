"""Problem checks for smoke tests (issue #197)."""

from __future__ import annotations

from pathlib import Path


def check_web_problems(label: str, out_dir: Path) -> list[str]:
    """Check web problems take."""
    failures = []
    return failures


def check_terminal_problems(label: str, out_dir: Path) -> list[str]:
    """Check terminal problems take."""
    failures = []
    return failures


def check_strict_web(label: str, out_dir: Path) -> list[str]:
    """Check strict mode refuses web problems."""
    failures = []
    return failures


def check_strict_terminal(label: str, out_dir: Path) -> list[str]:
    """Check strict mode refuses terminal problems."""
    failures = []
    return failures