"""Narration take for smoke tests (issue #157)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_narration(out_root: Path) -> list[str]:
    """Record the narration take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "narration")
    
    with fixture_server() as base_url:
        try:
            problems, info = record_narration(out_dir, base_url)
        except Exception as exc:
            return [f"narration: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_narration(out_dir: Path, base_url: str):
    """Record a narration demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=True, strict=True, deterministic=True
    ) as rec:
        pass
    
    return [], {"lines": []}