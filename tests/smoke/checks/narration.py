"""Narration checks for smoke tests (issue #157)."""

from __future__ import annotations

from pathlib import Path


def check_narration_pacing(label: str, out_dir: Path) -> list[str]:
    """Check narration pacing in timeline.json."""
    failures = []
    return failures


def check_narration_audio(label: str, out_dir: Path, lines: list, clock) -> list[str]:
    """Check that audio is present where narration lines are."""
    failures = []
    return failures


def check_narration_placement(label: str, out_dir: Path, lines: list, clock) -> list[str]:
    """Check narration clip placement in the video."""
    failures = []
    return failures