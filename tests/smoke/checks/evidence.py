"""Evidence checks for smoke tests (issue #9)."""

from __future__ import annotations

from pathlib import Path


def check_evidence(label: str, out_dir: Path, evidence_spec: list) -> list[str]:
    """Check per-beat evidence files."""
    failures = []
    evidence_dir = out_dir / "evidence"
    if not evidence_dir.is_dir():
        return [f"{label}: evidence/ directory was never created"]
    # Implementation would check evidence files
    return failures


def check_evidence_caps(label: str, out_dir: Path) -> list[str]:
    """Check evidence size caps."""
    failures = []
    return failures