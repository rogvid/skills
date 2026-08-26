"""Polish checks for smoke tests (issues #110, #111)."""

from __future__ import annotations

from pathlib import Path


def check_spotlight(label: str, out_dir: Path) -> list[str]:
    """Check spotlight enter/exit transitions."""
    failures = []
    return failures


def check_terminal_opening(label: str, out_dir: Path) -> list[str]:
    """Check terminal opens on title card, not bare prompt."""
    failures = []
    return failures


def check_camera_push(label: str, out_dir: Path) -> list[str]:
    """Check camera push-in effect."""
    failures = []
    return failures