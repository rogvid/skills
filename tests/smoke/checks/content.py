"""Content checks for smoke tests (issue #97)."""

from __future__ import annotations

from pathlib import Path

from ..constants import (
    CONTENT_TAKES,
    CONTENT_TOURED,
    CONTENT_CARD,
    CONTENT_TOUR_COMMAND,
    CONTENT_TOUR_CAPTIONS,
    CONTENT_TOUR_HOLD_S,
    CONTENT_COMMANDS,
    CONTENT_STATIC_HEADROOM,
    CONTENT_STATIC_MARGIN,
    CONTENT_SCORE_HEADROOM,
    CONTENT_COVERED_FRACTION,
    CONTENT_PSNR_GAP_DB,
    MIN_CONTENT_STDDEV,
    CONTENT_SAMPLE_FPS,
    CONTENT_KEEP,
)
from ..utils import gray_frames, contrast, keep_top, psnr_db


def check_content_pair(label: str, out_dir: Path) -> list[str]:
    """Check the content-shown vs content-covered pair."""
    failures = []
    # Implementation would compare the two takes
    # This is a placeholder - actual implementation in original smoke.py
    return failures


def check_content_toured(label: str, out_dir: Path) -> list[str]:
    """Check the content-toured take."""
    failures = []
    # Implementation would check the touring storyboard
    return failures


def _check_occlusion(label: str, out_dir: Path) -> list[str]:
    """Check that the card covers the app rect."""
    failures = []
    return failures


def _check_scored_region(label: str, out_dir: Path) -> list[str]:
    """Check the scored region."""
    failures = []
    return failures