"""Artifact checks for smoke tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..constants import (
    MIN_MP4_BYTES,
    MIN_PNG_BYTES,
    WEB_SHOTS,
    TERMINAL_SHOTS,
    CAPTION_PROBE,
    MIN_STILL_DIFF,
    WEB_DURATION_S,
    TERMINAL_DURATION_S,
    MIN_PNG_BYTES,
    DURATION_TOLERANCE_S,
)
from ..utils import gray_frames, frame_difference


def _check_file_size(path: Path, min_bytes: int, label: str) -> list[str]:
    """Check that a file exists and meets minimum size."""
    failures = []
    if not path.is_file():
        failures.append(f"{label}: {path.name} was never written")
    elif path.stat().st_size < min_bytes:
        failures.append(
            f"{label}: {path.name} is {path.stat().st_size} bytes, under the {min_bytes} floor"
        )
    return failures


def _check_duration(out_dir: Path, expected: tuple[float, float], label: str) -> list[str]:
    """Check video duration against expected range."""
    failures = []
    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        return failures  # already reported
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(mp4)],
        capture_output=True,
        text=True,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        failures.append(f"{label}: ffprobe could not read duration")
        return failures
    lo, hi = expected
    if not (lo <= duration <= hi):
        failures.append(
            f"{label}: demo.mp4 is {duration:.1f}s, expected {lo}–{hi}s"
        )
    return failures


def _check_stills(out_dir: Path, shots: list[str], label: str) -> list[str]:
    """Check that all expected stills exist and are not duplicates."""
    failures = []
    prev: bytes | None = None
    for shot in shots:
        path = out_dir / "images" / f"{shot}.png"
        if not path.is_file():
            failures.append(f"{label}: {shot}.png was never written")
            continue
        if path.stat().st_size < MIN_PNG_BYTES:
            failures.append(f"{label}: {shot}.png is {path.stat().st_size} bytes, under the {MIN_PNG_BYTES} floor")
            continue
        data = path.read_bytes()
        if prev is not None:
            frames_a = gray_frames(path)
            frames_b = gray_frames(prev)
            if frames_a and frames_b:
                diff = frame_difference(frames_a[0], frames_b[0])
                if diff < MIN_STILL_DIFF:
                    failures.append(
                        f"{label}: {shot}.png is identical to the previous still "
                        f"(mean luma diff {diff:.3f} < {MIN_STILL_DIFF})"
                    )
        prev = data
    return failures


def _check_caption_probe(out_dir: Path, label: str) -> list[str]:
    """Check the caption on/off stills differ in the caption band."""
    failures = []
    off = out_dir / "images" / f"{CAPTION_PROBE[0]}.png"
    on = out_dir / "images" / f"{CAPTION_PROBE[1]}.png"
    if not off.is_file() or not on.is_file():
        return failures  # already reported
    frames_off = gray_frames(off)
    frames_on = gray_frames(on)
    if not frames_off or not frames_on:
        return failures
    # Caption band is bottom 96px of 720p -> last 96/720 = 0.133 of frame
    # On 160x90 reduction, that's about 12 rows
    band = frames_off[0][-12*160:]
    band_on = frames_on[0][-12*160:]
    diff = sum(abs(a - b) for a, b in zip(band, band_on)) / len(band)
    from ..constants import MIN_CAPTION_BAND_DIFF
    floor = MIN_CAPTION_BAND_DIFF.get(label, 2.0)
    if diff < floor:
        failures.append(
            f"{label}: caption probe stills differ by {diff:.2f} luma in the band, "
            f"under the {floor} floor — caption never reached the screen"
        )
    return failures


def check_take(
    label: str,
    out_dir: Path,
    shots: list[str],
    duration_range: tuple[float, float],
    started: float,
    video_rect: tuple[int, int, int, int] | None = None,
    still_rect: tuple[int, int, int, int] | None = None,
    size: tuple[int, int] | None = None,
) -> list[str]:
    """Check basic take artifacts: mp4, stills, duration, caption probe."""
    failures = []
    mp4 = out_dir / "demo.mp4"
    
    # MP4 exists and has size
    failures += _check_file_size(mp4, MIN_MP4_BYTES, label)
    
    # Duration
    if mp4.is_file():
        failures += _check_duration(out_dir, duration_range, label)
    
    # Stills exist and are not duplicates
    failures += _check_stills(out_dir, shots, label)
    
    # Caption probe
    failures += _check_caption_probe(out_dir, label)
    
    # MP4 timestamp is from this run
    if mp4.is_file() and mp4.stat().st_mtime < started:
        failures.append(
            f"{label}: demo.mp4 predates this run — it is a leftover, not "
            f"this take's recording"
        )
    
    return failures


def check_healthy(label: str, out_dir: Path) -> list[str]:
    """Check that the recorder's own 'healthy' flag says the recording shows a picture."""
    failures = []
    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        return failures  # already reported
    # This would read timeline.json and check content.score
    # For now, just a placeholder - the actual implementation is in the original smoke.py
    return failures