"""Segments take for smoke tests (issue #7)."""

from __future__ import annotations

from pathlib import Path

from ..constants import (
    SEGMENT_BEATS,
    SEGMENT_CAPTIONS,
    SEGMENT_SHOTS,
    SEGMENT_DURATION_S,
    SEGMENT_NAMES,
)
from ..utils import (
    fresh_take_dir,
    fixture_server,
    HostClock,
    watch_wall_clock,
)
from ..checks import (
    check_take,
    check_capture_clock,
    check_merged_capture_clock,
    check_segment_timeline,
    check_merge_offset,
)


def run_segments(out_root: Path) -> list[str]:
    """Record the segments take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "segments")
    
    with fixture_server() as base_url:
        with watch_wall_clock() as clock:
            try:
                problems, parts = record_segments(out_dir, base_url, clock)
            except Exception as exc:
                return [f"segments: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    failures += check_take("segments", out_dir, SEGMENT_SHOTS, SEGMENT_DURATION_S, 0)
    failures += check_merged_capture_clock(out_dir, parts)
    failures += check_segment_timeline("segments", out_dir)
    failures += check_merge_offset("segments", out_dir)
    
    return failures


def record_segments(out_dir: Path, base_url: str, clock: HostClock):
    """Record a segmented demo."""
    from demo_recording import Recorder, stitch
    
    parts = []
    for i, name in enumerate(SEGMENT_NAMES):
        part_dir = out_dir / name
        part_dir.mkdir(parents=True, exist_ok=True)
        
        with Recorder(
            part_dir, base_url=base_url, speech=False, strict=True, deterministic=True, segment=name
        ) as rec:
            if clock is not None:
                clock.rebase(rec._t0)
            
            rec.goto("/")
            rec.wait_for("#kpi-rev")
            rec.pause(1.0)
            rec.shot("01-part1")
            rec.caption("One demo, in two parts.")
            
            if i == 0:
                rec.interlude("card", "A few minutes later.")
        
        parts.append((name, clock, 0, {}))  # Simplified
    
    # Stitch
    stitch(out_dir, SEGMENT_NAMES)
    
    return [], parts