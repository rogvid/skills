"""Behaviour checks for smoke tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..constants import (
    WEB_BEATS,
    TERMINAL_BEATS,
    WEB_CAPTIONS,
    TERMINAL_CAPTIONS,
    WEB_PRESS_KEYS,
    BEAT_ORDER_SLACK_S,
    MIN_HELD_BEAT_SPAN_S,
    MIN_BEAT_TIME_COVERAGE,
    _MD_ROW,
    DURATION_TOLERANCE_S,
    MAX_LOG_EARLY_S,
    MAX_CAPTURE_LOSS_S,
    MAX_SKEW_DRIFT_S,
)
from ..utils import HostClock


def check_timeline(
    label: str,
    out_dir: Path,
    started: float,
    beats: list[tuple[str, str | None]],
    captions: list[str],
    size: tuple[int, int],
    clock: HostClock | None = None,
) -> list[str]:
    """Check timeline.json against expected beats and captions."""
    failures = []
    path = out_dir / "timeline.json"
    if not path.is_file():
        return [f"{label}: timeline.json was never written"]
    
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{label}: timeline.json is not valid JSON: {exc}"]
    
    # Check duration
    duration = doc.get("duration")
    if not isinstance(duration, (int, float)):
        failures.append(f"{label}: timeline.json has no duration")
    else:
        # Would check against ffprobe
        pass
    
    # Check beats
    recorded_beats = doc.get("beats") or []
    if len(recorded_beats) != len(beats):
        failures.append(
            f"{label}: timeline.json has {len(recorded_beats)} beats, "
            f"expected {len(beats)}"
        )
    else:
        for i, (expected_verb, expected_target) in enumerate(beats):
            if i >= len(recorded_beats):
                break
            beat = recorded_beats[i]
            if beat.get("verb") != expected_verb:
                failures.append(
                    f"{label}: beat {i} verb is {beat.get('verb')!r}, "
                    f"expected {expected_verb!r}"
                )
            if expected_target is not None and beat.get("target") != expected_target:
                failures.append(
                    f"{label}: beat {i} target is {beat.get('target')!r}, "
                    f"expected {expected_target!r}"
                )
    
    # Check captions
    recorded_captions = [b.get("caption", "") for b in recorded_beats if b.get("verb") == "caption"]
    if len(recorded_captions) != len(captions):
        failures.append(
            f"{label}: timeline.json has {len(recorded_captions)} caption beats, "
            f"expected {len(captions)}"
        )
    else:
        for i, (expected, actual) in enumerate(zip(captions, recorded_captions)):
            if expected != actual:
                failures.append(
                    f"{label}: caption beat {i} is {actual!r}, expected {expected!r}"
                )
    
    return failures


def check_beat_frames(
    label: str,
    out_dir: Path,
    started: float,
    beats: list[tuple[str, str | None]],
    captions: list[str],
    size: tuple[int, int],
    clock: HostClock | None = None,
) -> list[str]:
    """Check that frames/frames.md matches beats."""
    failures = []
    frames_md = out_dir / "frames" / "frames.md"
    if not frames_md.is_file():
        return [f"{label}: frames/frames.md was never written"]
    
    content = frames_md.read_text()
    rows = [line for line in content.splitlines() if _MD_ROW.match(line)]
    
    # Each beat that has a shot should have a frame
    shot_beats = [i for i, (v, t) in enumerate(beats) if v == "shot"]
    if len(rows) < len(shot_beats):
        failures.append(
            f"{label}: frames.md has {len(rows)} frames, "
            f"but storyboard has {len(shot_beats)} shot beats"
        )
    
    return failures


def check_form_pacing(label: str, out_dir: Path) -> list[str]:
    """Check that form verb beats record the key pressed (issue #130)."""
    failures = []
    path = out_dir / "timeline.json"
    if not path.is_file():
        return failures
    
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError:
        return failures
    
    recorded_beats = doc.get("beats") or []
    press_beats = [b for b in recorded_beats if b.get("verb") == "press"]
    
    from ..constants import WEB_PRESS_KEYS
    if len(press_beats) != len(WEB_PRESS_KEYS):
        failures.append(
            f"{label}: timeline.json has {len(press_beats)} press beats, "
            f"expected {len(WEB_PRESS_KEYS)}"
        )
    else:
        for i, (beat, expected_key) in enumerate(zip(press_beats, WEB_PRESS_KEYS)):
            if beat.get("target") != expected_key:
                failures.append(
                    f"{label}: press beat {i} target is {beat.get('target')!r}, "
                    f"expected {expected_key!r}"
                )
    
    return failures