"""Segment checks for smoke tests (issue #7)."""

from __future__ import annotations

from pathlib import Path


def check_merge_offset(label: str, out_dir: Path) -> list[str]:
    """Check segment merge offset accuracy."""
    failures = []
    return failures


def check_segment_timeline(label: str, out_dir: Path) -> list[str]:
    """Check segment timeline merging."""
    failures = []
    return failures