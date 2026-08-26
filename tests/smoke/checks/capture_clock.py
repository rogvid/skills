"""Capture clock checks for smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from ..constants import (
    MAX_CLOCK_RECORD_DISAGREEMENT_S,
    MAX_CLOCK_STEP_TIME_DISAGREEMENT_S,
    HOST_CLOCK_MIN_STEP_S,
)
from ..utils import HostClock, video_instant, joined_clock


def _check_clock_coverage(
    label: str, name: str, record: dict, clock: HostClock
) -> list[str]:
    """Check that capture_clock honestly reports its coverage."""
    failures = []
    stated = record.get("measured")
    gap = record.get("max_gap")
    limit = record.get("max_gap_limit")
    
    if not isinstance(stated, bool):
        failures.append(
            f"{label}: {name}'s capture_clock has no `measured` flag "
            f"({stated!r})"
        )
    
    numeric = (
        isinstance(gap, (int, float))
        and not isinstance(gap, bool)
        and isinstance(limit, (int, float))
        and not isinstance(limit, bool)
    )
    if not numeric:
        failures.append(
            f"{label}: {name}'s capture_clock states max_gap={gap!r} against "
            f"limit={limit!r}"
        )
    
    if stated != (gap <= limit):
        failures.append(
            f"{label}: {name}'s capture_clock says measured={stated} while "
            f"its own max_gap is {gap:.3f}s against a {limit:.3f}s limit"
        )
    
    if stated and not clock.covered:
        failures.append(
            f"{label}: {name}'s capture_clock claims it measured this take "
            f"(max_gap {gap:.3f}s) while this harness's own sampler was away "
            f"for up to {clock.max_gap:.3f}s"
        )
    
    if not stated and clock.covered:
        failures.append(
            f"{label}: {name}'s capture_clock refuses to report (max_gap "
            f"{gap:.3f}s, limit {limit:.3f}s) on a take this harness sampled "
            f"cleanly (max gap {clock.max_gap:.3f}s, {clock.samples} samples)"
        )
    
    return failures


def check_capture_clock(
    label: str, out_dir: Path, clock: HostClock, name: str = "timeline.json"
) -> list[str]:
    """Check timeline.json's capture_clock against harness's own reading."""
    failures = []
    path = out_dir / name
    if not path.is_file():
        return [f"{label}: {name} could not be read for capture_clock"]
    
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{label}: {name} could not be read for capture_clock: {exc}"]
    
    record = doc.get("capture_clock")
    if not isinstance(record, dict):
        return [
            f"{label}: {name} has no `capture_clock` record"
        ]
    
    failures += _check_clock_coverage(label, name, record, clock)
    if failures:
        return failures
    
    if record.get("measured") is not True:
        return []
    
    reported = record.get("total")
    if not isinstance(reported, (int, float)):
        return [f"{label}: capture_clock.total is {reported!r}, not a number"]
    
    listed = record.get("steps")
    if not isinstance(listed, list):
        return [f"{label}: capture_clock.steps is {listed!r}, not a list"]
    
    if abs(sum(float(s.get("delta", 0.0)) for s in listed) - float(reported)) > 0.001:
        return [
            f"{label}: capture_clock.total is {reported!r} but its own steps "
            f"sum to {sum(float(s.get('delta', 0.0)) for s in listed):+.4f}"
        ]
    
    beats = doc.get("beats") or []
    horizon = max(
        (float(b["t_end"]) for b in beats if isinstance(b.get("t_end"), (int, float))),
        default=0.0,
    )
    mine = [(at, d) for at, d in clock.steps if 0.0 <= at <= horizon]
    theirs = [
        (float(s.get("t", -1.0)), float(s.get("delta", 0.0)))
        for s in listed
        if 0.0 <= float(s.get("t", -1.0)) <= horizon
    ]
    
    if len(mine) != len(theirs):
        return [
            f"{label}: harness saw {len(mine)} wall-clock step(s) and "
            f"timeline.json records {len(theirs)}"
        ]
    
    for (at, delta), (their_at, their_delta) in zip(sorted(mine), sorted(theirs)):
        if abs(delta - their_delta) > MAX_CLOCK_RECORD_DISAGREEMENT_S:
            return [
                f"{label}: harness measured {delta * 1000:+.0f} ms at {at:.1f}s "
                f"and timeline.json records {their_delta * 1000:+.0f} ms at {their_at:.1f}s"
            ]
        if abs(at - their_at) > MAX_CLOCK_STEP_TIME_DISAGREEMENT_S:
            return [
                f"{label}: harness put step at {at:.1f}s, "
                f"timeline.json at {their_at:.1f}s"
            ]
    
    return []


def check_merged_capture_clock(
    out_dir: Path, parts: list[tuple[str, HostClock, float, object]]
) -> list[str]:
    """Check a stitched demo's merged capture_clock."""
    failures = []
    path = out_dir / "timeline.json"
    if not path.is_file():
        return [f"segments: timeline.json could not be read for capture_clock"]
    
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"segments: timeline.json could not be read for capture_clock: {exc}"]
    
    # Check per-part records are preserved
    carried = doc.get("segments")
    if not isinstance(carried, list) or len(carried) != len(parts):
        return [
            f"segments: the stitched timeline.json's `segments` is {carried!r}, "
            f"expected one record per part"
        ]
    
    for (name, _clock, _offset, own), kept in zip(parts, carried):
        if kept.get("capture_clock") != own:
            failures.append(
                f"segments: the merged `segments` record for {name} carries "
                f"capture_clock {kept.get('capture_clock')!r}, but "
                f"{name}.seg.timeline.json measured {own!r}"
            )
    
    record = doc.get("capture_clock")
    unmeasured = [
        name
        for name, _clock, _offset, own in parts
        if not isinstance(own, dict) or own.get("measured") is not True
    ]
    
    if unmeasured and record is None:
        return failures
    
    if not isinstance(record, dict):
        return failures + [
            f"segments: the stitched timeline.json has no merged `capture_clock` record"
        ]
    
    if unmeasured:
        failures.append(
            f"segments: the merged capture_clock reports "
            f"measured={record.get('measured')!r} while "
            f"{', '.join(unmeasured)} could not measure its own clock"
        )
    
    return failures