"""Evidence take for smoke tests (issue #9)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_evidence(out_root: Path) -> list[str]:
    """Record the evidence take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "evidence")
    
    with fixture_server() as base_url:
        try:
            problems = record_evidence(out_dir, base_url)
        except Exception as exc:
            return [f"evidence: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_evidence(out_dir: Path, base_url: str):
    """Record an evidence demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []