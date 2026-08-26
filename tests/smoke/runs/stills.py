"""Stills-only take for smoke tests (issue #372)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_stills_only(out_root: Path) -> list[str]:
    """Record the stills-only take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "stills")
    
    with fixture_server() as base_url:
        try:
            problems = record_stills_only(out_dir, base_url)
        except Exception as exc:
            return [f"stills: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_stills_only(out_dir: Path, base_url: str):
    """Record a stills-only demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True, stills_only=True
    ) as rec:
        pass
    
    return []