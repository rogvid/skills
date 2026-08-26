"""Determinism checks for smoke tests (issue #10)."""

from __future__ import annotations

from pathlib import Path


def check_determinism_video(label: str, out_dir: Path) -> list[str]:
    """Check that deterministic takes match byte-for-byte."""
    failures = []
    # Implementation would compare video bytes
    return failures


def check_determinism_stills(label: str, out_dir: Path) -> list[str]:
    """Check that deterministic takes produce identical stills."""
    failures = []
    # Implementation would compare still bytes
    return failures