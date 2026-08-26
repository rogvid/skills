"""Failure takes for smoke tests (issues #11, #20, #24, #46)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_failure(out_root: Path) -> list[str]:
    """Record the failure take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "failure")
    
    with fixture_server() as base_url:
        try:
            problems = record_failure(out_dir, base_url)
        except Exception as exc:
            return [f"failure: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_failure(out_dir: Path, base_url: str):
    """Record a failure demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []