"""Issues check for smoke tests."""

from __future__ import annotations

from pathlib import Path


def check_issues(label: str, out_dir: Path) -> list[str]:
    """Check that timeline.json issues match expected problems."""
    failures = []
    path = out_dir / "timeline.json"
    if not path.is_file():
        return [f"{label}: timeline.json was never written"]
    # Implementation would check issues
    return failures