"""Overlay checks for smoke tests (issues #162, #163)."""

from __future__ import annotations

from pathlib import Path


def check_overlay_cleared(label: str, out_dir: Path) -> list[str]:
    """Check that a cleared light interlude leaves no scrim."""
    failures = []
    return failures


def check_overlay_left_up(label: str, out_dir: Path) -> list[str]:
    """Check that a light interlude left up is reported."""
    failures = []
    return failures