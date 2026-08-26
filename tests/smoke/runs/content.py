"""Content take for smoke tests (issue #97)."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_content(out_root: Path) -> list[str]:
    """Record the content take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "content")
    
    with fixture_server() as base_url:
        try:
            problems = record_content(out_dir, base_url)
        except Exception as exc:
            return [f"content: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_content(out_dir: Path, base_url: str):
    """Record a content demo."""
    from demo_recording import TerminalRecorder
    
    with TerminalRecorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []