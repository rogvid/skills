"""Strict takes for smoke tests."""

from __future__ import annotations

from pathlib import Path

from ..utils import fresh_take_dir, fixture_server


def run_strict_web(out_root: Path) -> list[str]:
    """Record the strict web take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "strict-web")
    
    with fixture_server() as base_url:
        try:
            problems = record_strict_web(out_dir, base_url)
        except Exception as exc:
            return [f"strict-web: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def run_strict_terminal(out_root: Path) -> list[str]:
    """Record the strict terminal take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "strict-terminal")
    
    with fixture_server() as base_url:
        try:
            problems = record_strict_terminal(out_dir, base_url)
        except Exception as exc:
            return [f"strict-terminal: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    return failures


def record_strict_web(out_dir: Path, base_url: str):
    """Record a strict web demo."""
    from demo_recording import Recorder
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []


def record_strict_terminal(out_dir: Path, base_url: str):
    """Record a strict terminal demo."""
    from demo_recording import TerminalRecorder
    
    with TerminalRecorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        pass
    
    return []