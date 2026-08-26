"""Spotlight take for smoke tests (issue #111)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_spotlight(out_root: Path) -> list[str]:
    """Record the spotlight take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "spotlight")
    
    with fixture_server() as base_url:
        try:
            problems = record_spotlight(out_dir, base_url)
        except Exception as exc:
            return [f"spotlight: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_spotlight(out_dir: Path, base_url: str):
    """Record a spotlight demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=False
    ) as rec:
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        rec.spotlight("#kpi-rev")
        rec.hold(1.5)
        rec.spotlight(None)
    
    return []