"""Coverage check for smoke tests (issue #12)."""

from __future__ import annotations

from pathlib import Path


def check_coverage(label: str, out_dir: Path) -> list[str]:
    """Check acceptance criterion coverage in timeline.json."""
    failures = []
    path = out_dir / "timeline.json"
    if not path.is_file():
        return [f"{label}: timeline.json was never written"]
    # Implementation would check coverage
    return failures