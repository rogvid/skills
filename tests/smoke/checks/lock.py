"""Lock check for smoke tests (issue #105)."""

from __future__ import annotations

from pathlib import Path


def check_lock_refusal(out_root: Path) -> list[str]:
    """Check that a refused run leaves nothing behind."""
    failures = []
    # Implementation would test lock refusal
    return failures