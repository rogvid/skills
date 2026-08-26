"""Determinism take for smoke tests (issue #10)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_determinism(out_root: Path) -> list[str]:
    """Record the determinism take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "determinism")
    
    with fixture_server() as base_url:
        try:
            problems = record_determinism(out_dir, base_url)
        except Exception as exc:
            return [f"determinism: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_determinism(out_dir: Path, base_url: str):
    """Record a determinism demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []