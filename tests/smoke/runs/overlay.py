"""Overlay take for smoke tests (issues #162, #163)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_overlay(out_root: Path) -> list[str]:
    """Record the overlay take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "overlay")
    
    with fixture_server() as base_url:
        try:
            problems = record_overlay(out_dir, base_url)
        except Exception as exc:
            return [f"overlay: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_overlay(out_dir: Path, base_url: str):
    """Record an overlay demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []