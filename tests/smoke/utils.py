"""Utility functions for the smoke test suite."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import math
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from .constants import (
    FIXTURE_DIR,
    HELPERS_DIR,
    MARKER_NAME,
    SERVER_START_TIMEOUT_S,
    REPO_ROOT,
    CAPTION_PROBE,
    PROBE_QUIET_S,
    ALIGN_POST_S,
    ALIGN_FPS,
    MAX_BASELINE_NOISE_FRACTION,
    CAPTION_FADE_FRAMES,
    MIN_BASELINE_FRAMES,
    ALIGN_OVERSHOOT_S,
    ALIGN_PRE_S,
    ALIGN_RESCUE_S,
    ALIGN_ARRIVAL_FRACTION,
    MIN_ALIGN_BAND_DELTA,
    MIN_CONTENT_STDDEV,
    MIN_CAPTION_BAND_DIFF,
    MIN_STILL_DIFF,
    KEEP_OUT_ROOTS,
    REAP_MIN_AGE_S,
    SMOKE_LOCK,
    HOST_CLOCK_MAX_GAP_S,
    HOST_CLOCK_MIN_STEP_S,
    CONTENT_SAMPLE_FPS,
    CONTENT_KEEP,
    CONTENT_STATIC_HEADROOM,
    CONTENT_STATIC_MARGIN,
    CONTENT_SCORE_HEADROOM,
    CONTENT_COVERED_FRACTION,
    CONTENT_PSNR_GAP_DB,
    OVERLAY_SCRIM_MIN_DIFF,
    OVERLAY_CLEARED_MAX_RATIO,
    OVERLAY_HOLD_S,
    OVERLAY_QUIET_S,
    SPOTLIGHT_PAD_PX,
    SPOTLIGHT_MID_BAND,
    MIN_SPOTLIGHT_MID_FRAMES,
    SPOTLIGHT_MIN_TOTAL,
    SPOTLIGHT_WINDOW_S,
    SPOTLIGHT_HOLD_S,
    SPOTLIGHT_DURATION_S,
    MIN_SPOTLIGHT_CLEAR_S,
    CAMERA_PUSH_MIN,
    CAMERA_STILL_MAX,
    CAMERA_STRIP_MIN_H,
    CAMERA_MIN_EVENT_S,
    CAMERA_AFTER_S,
    CAMERA_CENTRE_BAR_PX,
    OPENING_CARD_MAX_LUMA,
    OPENING_BARE_MIN_LUMA,
    OPENING_STRIP_FRACTIONS,
    TERMINAL_REVEAL_MIN_STDDEV,
    MIN_OPENING_CARD_S,
    MIN_OPENING_FRAMES,
    OPENING_CARD_AGREEMENT,
    OPENING_HOLD_S,
    OPENING_SAMPLE_FPS,
    OPENING_DURATION_S,
    EVIDENCE_LIMITS_EXPECTED,
    EVIDENCE_MARKER,
    EVIDENCE_TRUNCATED_MAX,
    MAX_EVIDENCE_FILE_BYTES,
    MAX_EVIDENCE_DIR_BYTES,
    WEB_EVIDENCE,
    WEB_EVIDENCE_SCOPE,
    TERMINAL_EVIDENCE,
    EVIDENCE_TAKE_FACTS,
    NARRATION_LOUD_DBFS,
    NARRATION_QUIET_DBFS,
    NARRATION_WINDOW_S,
    NARRATION_SILENCE_DBFS,
    NARRATION_SILENCE_MIN_S,
    NARRATION_ONSET_TOLERANCE_S,
    NARRATION_SPAN_TOLERANCE_S,
    NARRATION_CODEC,
    NARRATION_CHANNELS,
    NARRATION_SAMPLE_RATE,
    NARRATION_LINES,
    NARRATION_KEY,
    NARRATION_VOICE_ID,
    NARRATION_MODEL_ID,
    NARRATION_STABILITY,
    NARRATION_HOLD_S,
    NARRATION_LONG_LINE,
    NARRATION_LONG_S,
    NARRATION_SHORT_LINE,
    NARRATION_SHORT_S,
    STRICT_CAPTION,
    STRICT_BEAT_RE,
    TERMINAL_FAILING_COMMAND,
    TERMINAL_UNWAITED,
    TERMINAL_PROBLEM_EXIT_CODES,
    WEB_PROBLEM_ISSUES,
    TERMINAL_PROBLEM_ISSUES,
    TERMINAL_RACE_COMMAND,
    TERMINAL_RACE_EXIT,
    TERMINAL_RACE_DELAY_S,
    TERMINAL_RACE_SHELL,
    BETWEEN_BEATS,
    BETWEEN_BEATS_JS,
    LATE_BOOM,
    LATE_BOOM_CAPTION,
    LATE_BOOM_JS,
    LATE_BOOM_HOLD_S,
    MISSING_PATH,
    WEB_BEATS,
    WEB_PRESS_KEYS,
    TERMINAL_BEATS,
    WEB_CAPTIONS,
    TERMINAL_CAPTIONS,
    WEB_SHOTS,
    TERMINAL_SHOTS,
    WEB_DURATION_S,
    TERMINAL_DURATION_S,
    SEGMENT_NAMES,
    SEGMENT_BEATS,
    SEGMENT_BEAT_SEGMENTS,
    SEGMENT_CAPTIONS,
    SEGMENT_INTERLUDES,
    SEGMENT_PROBES,
    SEGMENT_SHOTS,
    SEGMENT_DURATION_S,
    ENTROPY_SHOTS,
    ENTROPY_SETTLE_S,
    ENTROPY_GAP_S,
    MAX_TAKE_VIDEO_DELTA,
    MIN_LIVE_VIDEO_DELTA,
    MIN_LIVE_STILL_DELTA,
    OVERLAY_TAKES,
    OVERLAY_LABEL,
    CONTENT_TAKES,
    CONTENT_TOURED,
    CONTENT_CARD,
    CONTENT_TOUR_COMMAND,
    CONTENT_TOUR_CAPTIONS,
    CONTENT_TOUR_HOLD_S,
    CONTENT_COMMANDS,
    PROBE_CAPTION,
    SMOKE_LOCK,
    LOCK_CHILD_TIMEOUT_S,
    EXPENSIVE_ARMS,
    MAX_UNWATCHED_CAPTURE_LOSS_S,
)

# This module re-exports utilities from constants and adds additional functions


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def fixture_server() -> Iterator[str]:
    """Serve tests/fixture on a free port; always shut it down."""
    if not (FIXTURE_DIR / "index.html").is_file():
        raise SmokeFailure(f"fixture app missing: {FIXTURE_DIR / 'index.html'}")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(FIXTURE_DIR),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + SERVER_START_TIMEOUT_S
        while True:
            if proc.poll() is not None:
                raise SmokeFailure(
                    f"fixture server exited immediately (code {proc.returncode}) "
                    f"— port {port} may already be in use"
                )
            try:
                with urllib.request.urlopen(base_url, timeout=1) as resp:
                    if resp.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            if time.time() > deadline:
                raise SmokeFailure(
                    f"fixture server did not answer on {base_url} within "
                    f"{SERVER_START_TIMEOUT_S:.0f}s"
                )
            time.sleep(0.1)
        print(f"smoke: serving {FIXTURE_DIR} at {base_url}")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def scrub_env() -> None:
    """Drop settings that would make the run depend on the operator's shell."""
    for name in [k for k in os.environ if k.startswith("DEMO_VIDEO_")]:
        del os.environ[name]
    os.environ.pop("ELEVENLABS_API_KEY", None)


def fresh_take_dir(out_root: Path, name: str) -> Path:
    """An empty directory for one take, or a refusal."""
    take = out_root / name
    if take.exists():
        if not take.is_dir():
            raise SmokeFailure(f"{take} exists and is not a directory")
        if list(take.iterdir()) and not (take / MARKER_NAME).is_file():
            raise SmokeFailure(
                f"refusing to touch {take}: it is not empty and carries no "
                f"{MARKER_NAME} marker, so this harness did not create it. "
                f"Each take needs its own empty directory — point --out-dir "
                f"somewhere this run owns."
            )
        shutil.rmtree(take)
    take.mkdir(parents=True)
    (take / MARKER_NAME).write_text(
        "Written by tests/smoke. Its presence means this directory may be "
        "deleted and recreated by the next run.\n"
    )
    return take


def keep_top(rect: tuple[int, int, int, int], fraction: float = CONTENT_KEEP) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return (x, y, w, max(1, int(h * fraction)))


class Beats:
    """Collects post-condition failures without aborting the take."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.problems: list[str] = []

    def expect(self, after: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            self.problems.append(
                f"{self.label}: after {after}, expected {wanted!r} but got "
                f"{actual!r} — either that verb had no effect, or "
                f"tests/fixture/index.html changed and this expectation is stale"
            )

    def fail_if(self, condition: bool, message: str) -> None:
        if condition:
            self.problems.append(f"{self.label}: {message}")


class SmokeFailure(Exception):
    """An assertion about a recording did not hold."""


@contextmanager
def only_one_suite(allow_concurrent: bool) -> Iterator[None]:
    """Machine-wide lock so only one smoke suite runs at a time."""
    lock_path = Path(SMOKE_LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if not allow_concurrent:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise SmokeFailure(
            f"another smoke suite holds {SMOKE_LOCK} — "
            f"pass --allow-concurrent to run anyway (timing bars will fail)"
        )
    finally:
        if not allow_concurrent:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def mean_dbfs(mp4: Path, start_s: float, duration_s: float) -> float | None:
    """Mean volume of `mp4` in dBFS over `[start_s, start_s+duration_s]`."""
    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(start_s),
            "-t",
            str(duration_s),
            "-i",
            str(mp4),
            "-af",
            "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    for line in probe.stdout.splitlines():
        if line.startswith("lavfi.astats.Overall.RMS_level="):
            try:
                return float(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


def loud_spans(mp4: Path, duration: float) -> list[tuple[float, float]] | None:
    """Stretches of audio in `mp4` louder than NARRATION_SILENCE_DBFS."""
    from .constants import NARRATION_SILENCE_DBFS, NARRATION_SILENCE_MIN_S

    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-af",
            f"silencedetect=n={NARRATION_SILENCE_DBFS}dB:d={NARRATION_SILENCE_MIN_S}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    spans: list[tuple[float, float]] = []
    silence_start = 0.0
    for line in probe.stderr.splitlines():
        if "silence_start" in line:
            try:
                silence_start = float(line.split("silence_start:")[1].split("|")[0].strip())
            except (IndexError, ValueError):
                pass
        elif "silence_end" in line:
            try:
                silence_end = float(line.split("silence_end:")[1].split("|")[0].strip())
                if silence_end > silence_start:
                    spans.append((silence_start, silence_end))
            except (IndexError, ValueError):
                pass
    if not spans:
        return [(0.0, duration)]
    loud: list[tuple[float, float]] = []
    prev_end = 0.0
    for start, end in spans:
        if start > prev_end:
            loud.append((prev_end, start))
        prev_end = end
    if prev_end < duration:
        loud.append((prev_end, duration))
    return loud


def expected_loud_spans(
    expected: list[float], clips: list[float]
) -> list[tuple[float, float, list[int]]]:
    """Where the clips should be audible in the file."""
    spans: list[tuple[float, float, list[int]]] = []
    i = 0
    while i < len(expected):
        start = expected[i]
        end = start + clips[i]
        members = [i]
        i += 1
        while i < len(expected) and expected[i] < end + 0.05:
            end = max(end, expected[i] + clips[i])
            members.append(i)
            i += 1
        spans.append((start, end, members))
    return spans


def gray_frames(mp4: Path, fps: int = 1) -> list:
    """Extract grayscale frames from video at `fps`."""
    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vf",
            f"fps={fps},scale=160:90,format=gray",
            "-f",
            "image2pipe",
            "-c:v",
            "rawvideo",
            "-",
        ],
        capture_output=True,
    )
    if probe.returncode != 0:
        return []
    w, h = 160, 90
    frame_bytes = w * h
    frames = []
    for i in range(0, len(probe.stdout), frame_bytes):
        chunk = probe.stdout[i : i + frame_bytes]
        if len(chunk) == frame_bytes:
            frames.append(chunk)
    return frames


def frame_difference(a: bytes, b: bytes) -> float:
    """Mean absolute luma difference between two frames."""
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def psnr_db(a: bytes, b: bytes) -> float:
    """PSNR in dB between two frames."""
    mse = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    if mse == 0:
        return float("inf")
    return 10 * math.log10(255 * 255 / mse)


def contrast(frames: list, rect: tuple[int, int, int, int]) -> float:
    """Luma standard deviation over `rect` across `frames`."""
    x, y, w, h = rect
    values = []
    for f in frames:
        for row in range(y, y + h):
            for col in range(x, x + w):
                values.append(f[row * 160 + col])
    if not values:
        return 0.0
    return statistics.stdev(values) if len(values) > 1 else 0.0


def strip_rgb(mp4: Path, rect: tuple[int, int, int, int], fps: int = 1) -> list:
    """Extract RGB frames from `mp4` over `rect` at `fps`."""
    x, y, w, h = rect
    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vf",
            f"fps={fps},crop={w}:{h}:{x}:{y}",
            "-f",
            "image2pipe",
            "-c:v",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    if probe.returncode != 0:
        return []
    frame_bytes = w * h * 3
    frames = []
    for i in range(0, len(probe.stdout), frame_bytes):
        chunk = probe.stdout[i : i + frame_bytes]
        if len(chunk) == frame_bytes:
            frames.append(chunk)
    return frames


def channels_apart(a: list, b: list) -> float:
    """Mean absolute difference per channel between two frame lists."""
    total = 0
    count = 0
    for fa, fb in zip(a, b):
        total += sum(abs(x - y) for x, y in zip(fa, fb))
        count += len(fa)
    return total / count if count else 0.0


def card_run(strips: list, threshold: float) -> tuple[float, float]:
    """Find the longest contiguous run where all frames are under threshold."""
    longest_start = 0.0
    longest_duration = 0.0
    current_start = 0.0
    current_duration = 0.0
    for i, strip in enumerate(strips):
        if strip < threshold:
            if current_duration == 0:
                current_start = i
            current_duration += 1
        else:
            if current_duration > longest_duration:
                longest_duration = current_duration
                longest_start = current_start
            current_duration = 0
    if current_duration > longest_duration:
        longest_duration = current_duration
        longest_start = current_start
    return longest_start, longest_duration


def card_strip(frames: list, rect: tuple[int, int, int, int]) -> list:
    """Luma mean of `rect` for each frame."""
    x, y, w, h = rect
    means = []
    for f in frames:
        total = 0
        count = 0
        for row in range(y, y + h):
            for col in range(x, x + w):
                total += f[row * 160 + col]
                count += 1
        means.append(total / count if count else 0)
    return means


Rect = tuple[int, int, int, int]
FRAME_BAND = 96


class HostClock:
    """CLOCK_REALTIME against CLOCK_MONOTONIC, sampled for a take's lifetime."""

    INTERVAL_S = 0.02

    def __init__(self) -> None:
        self.raw: list[tuple[float, float]] = []
        self.max_gap = 0.0
        self.samples = 0
        self._t0: float | None = None
        self.boundaries: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        previous = time.time() - time.monotonic()
        last = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - last)
            last = now
            self.samples += 1
            offset = time.time() - time.monotonic()
            delta = offset - previous
            if abs(delta) >= HOST_CLOCK_MIN_STEP_S:
                self.raw.append((now, delta))
            previous = offset
            time.sleep(self.INTERVAL_S)

    @property
    def covered(self) -> bool:
        return self.samples > 1 and self.max_gap <= HOST_CLOCK_MAX_GAP_S

    def rebase(self, t0: float) -> None:
        self._t0 = t0

    @property
    def steps(self) -> list[tuple[float, float]]:
        if self._t0 is None:
            return []
        return [(at - self._t0, delta) for at, delta in self.raw]

    @property
    def total(self) -> float:
        return sum(delta for _, delta in self.steps)

    def applied(self, t: float) -> list[tuple[float, float]]:
        start = max((b for b in self.boundaries if b <= t), default=0.0)
        return [(at, delta) for at, delta in self.steps if start <= at <= t]

    def in_video(self, t: float) -> tuple[float, float]:
        return video_instant(self.applied(t), t)

    def before(self, t: float) -> float:
        return self.in_video(t)[0] - t

    def hole(self, t: float) -> float:
        return self.in_video(t)[1]

    def describe(self) -> str:
        if not self.steps:
            return "the host's wall clock did not step during this take"
        return "the host's wall clock stepped " + ", ".join(
            f"{delta * 1000:+.0f} ms at {at:.1f}s" for at, delta in self.steps
        )


def video_instant(steps: list[tuple[float, float]], t: float) -> tuple[float, float]:
    running = 0.0
    edge = -math.inf
    for at, delta in sorted(steps):
        if at > t:
            break
        edge = max(edge, at + running)
        running += delta
    shifted = t + running
    reached = max(shifted, edge)
    return reached, reached - shifted


@contextmanager
def watch_wall_clock() -> Iterator[HostClock]:
    clock = HostClock()
    clock._t0 = time.monotonic()
    clock._thread = threading.Thread(
        target=clock._run, name="smoke-host-clock", daemon=True
    )
    clock._thread.start()
    try:
        yield clock
    finally:
        clock._stop.set()
        clock._thread.join(timeout=1.0)


def probe_wall_clock(window_s: float = 40.0) -> HostClock:
    with watch_wall_clock() as clock:
        deadline = time.monotonic() + window_s
        while time.monotonic() < deadline:
            time.sleep(0.1)
    return clock


def joined_clock(parts: list[tuple[HostClock, float]]) -> HostClock:
    joined = HostClock()
    joined._t0 = 0.0
    joined.max_gap = max((clock.max_gap for clock, _o in parts), default=0.0)
    joined.samples = min((clock.samples for clock, _o in parts), default=0)
    ends = [offset for _clock, offset in parts[1:]] + [None]
    joined.raw = [
        (at + offset, delta)
        for (clock, offset), end in zip(parts, ends, strict=True)
        for at, delta in clock.steps
        if end is None or at + offset < end
    ]
    joined.boundaries = [offset for _clock, offset in parts]
    return joined


def hole_clause(clock, t: float, at: float) -> str:
    gap = clock.hole(t) if clock is not None else 0.0
    if not gap:
        return ""
    return (
        f" There is no video of that instant at all: the host's wall clock "
        f"stepped backwards over it, so {at:.3f}s is the last moment before a "
        f"gap the video only resumes from {gap * 1000:.0f} ms later, and the "
        f"recorder is expected to have clamped to the same place."
    )


def log_early_causes(clock, t: float) -> str:
    if clock is None:
        return (
            "No wall-clock reading was kept for this take, so this harness "
            "cannot say which end is at fault: an unmeasured backward step "
            "leaves the video short and the beat log where it was, and reads "
            "from here exactly like a log stamped early."
        )
    applied = clock.applied(t)
    if not applied:
        return (
            "No step of this beat's own capture lands before it, so nothing "
            "was subtracted from this reading and nothing in the capture can "
            "have moved the event later: this is the beat log."
        )
    shift = clock.before(t)
    if abs(shift) < 0.005:
        return (
            f"**This take's clock stepped**: {clock.describe()}. Nothing was "
            f"subtracted from this reading — the steps reaching this beat "
            f"come to {shift * 1000:+.0f} ms, because they cancel or because "
            f"one lands on the beat itself — so over-correction is not what "
            f"produced this skew."
        )
    gap = clock.hole(t)
    inside = (
        f" **The file has no frame for this instant at all**: the step "
        f"deleted the wall time it happened in, and the video only resumes "
        f"{gap * 1000:.0f} ms later — so a reading over-corrected by the "
        f"whole step instead of clamping to the hole's edge is left with "
        f"exactly that much log-ahead."
        if gap
        else " This instant is outside every hole those steps left, so the "
        "video has a frame of its own for it and the correction above is the "
        "whole of what the steps took."
    )
    return (
        f"**This take's clock stepped, so the beat log is not the first place "
        f"to look**: {clock.describe()}, and {shift * 1000:+.0f} ms of that "
        f"was subtracted from this reading.{inside}"
    )


_CAPTION_JS = """() => {
  const ids = ['__demo_caption', '__demo_caption2'];
  const el = document.getElementById(ids[window.__demoCapLayer || 0]);
  if (!el) return null;
  return [el.textContent, getComputedStyle(el).opacity];
}"""


def check_caption(b: Beats, page, expected: str) -> None:
    state = page.evaluate(_CAPTION_JS)
    if state is None:
        b.fail_if(True, "no #__demo_caption element exists — caption() drew nothing")
        return
    text, opacity = state
    b.fail_if(text != expected, f"the caption reads {text!r}, expected {expected!r}")
    shown = float(opacity) > 0.5
    b.fail_if(
        shown != bool(expected),
        f"the caption's computed opacity is {opacity} but its text is "
        f"{expected!r} — it is in the DOM and not on screen"
        if expected
        else f"the caption's computed opacity is {opacity}; it should have "
        f"been cleared",
    )


TICKER_JS = """() => {
  if (document.getElementById('__smoke_ticker')) return;
  const style = document.createElement('style');
  style.textContent =
    '@keyframes __smoke_ticker{0%{opacity:.02}100%{opacity:.06}}';
  document.head.appendChild(style);
  const el = document.createElement('div');
  el.id = '__smoke_ticker';
  el.style.cssText = 'position:fixed;top:0;left:0;width:8px;height:8px;'
    + 'background:#808080;z-index:2147483647;pointer-events:none;'
    + 'animation:__smoke_ticker .18s steps(2) infinite';
  el.setAttribute('data-demo-video-animate', '');
  document.body.appendChild(el);
}"""

_TICKER_STATE_JS = """() => {
  const el = document.getElementById('__smoke_ticker');
  if (!el) return null;
  const style = getComputedStyle(el);
  const control = document.createElement('div');
  control.style.cssText = 'position:fixed;top:-99px;left:-99px;width:1px;'
    + 'height:1px;animation:__smoke_ticker .18s steps(2) infinite';
  document.body.appendChild(control);
  const controlDuration = getComputedStyle(control).animationDuration;
  control.remove();
  return {name: style.animationName, duration: style.animationDuration,
          state: style.animationPlayState, control: controlDuration};
}"""


def start_ticker(b: Beats, page) -> None:
    page.evaluate(TICKER_JS)
    state = page.evaluate(_TICKER_STATE_JS)
    if state is None:
        b.fail_if(
            True,
            "the compositor ticker did not attach — timing measurements in "
            "this take are not trustworthy",
        )
        return
    b.fail_if(
        state["name"] != "__smoke_ticker"
        or state["duration"] == "0s"
        or state["state"] != "running",
        f"the compositor ticker is not animating",
    )
    b.fail_if(
        state["control"] != "0.001s",
        f"a control element with the ticker's animation and no "
        f"data-demo-video-animate reports animation-duration "
        f"{state['control']!r}, expected '0.001s'",
    )


_PageState_JS = """() => {
  let sheet = document.getElementById('__smoke_probe_css');
  if (!sheet) {
    sheet = document.createElement('style');
    sheet.id = '__smoke_probe_css';
    sheet.textContent =
      '#__smoke_probe::after{content:"";animation:__smoke_probe 3s linear infinite}'
      + '#__smoke_probe::before{content:"";animation:__smoke_probe 4s linear infinite}';
    document.head.appendChild(sheet);
  }
  const probe = document.createElement('div');
  probe.id = '__smoke_probe';
  probe.style.cssText = 'position:fixed;top:-99px;left:-99px;width:1px;'
    + 'height:1px;animation:__smoke_probe 2s linear infinite;'
    + 'transition:opacity 5s linear';
  document.body.appendChild(probe);
  const style = getComputedStyle(probe);
  const animation = style.animationDuration;
  const transition = style.transitionDuration;
  const after = getComputedStyle(probe, '::after').animationDuration;
  const before = getComputedStyle(probe, '::before').animationDuration;
  probe.remove();
  return {
    now: Date.now(),
    iso: new Date().toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
    language: navigator.language,
    offset: new Date().getTimezoneOffset(),
    reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
    animation: animation,
    transition: transition,
    after: after,
    before: before,
    intl: new Intl.DateTimeFormat('en-US', {year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'UTC'}).format(),
    constructorNow: new Date().constructor.now(),
    constructorIsDate: Date.prototype.constructor === Date,
    descriptorNow: Object.getOwnPropertyDescriptor(Date, 'now').value(),
    nowIsStable: Date.now === Date.now,
    nowName: Date.now.name,
    timeOrigin: Math.round(performance.timeOrigin),
    monotonic: typeof document.timeline.currentTime === 'number'
      ? document.timeline.currentTime : performance.now(),
  };
}"""


def check_determinism(b: Beats, page, when: str, on: bool = True) -> dict:
    state = page.evaluate(_PageState_JS)

    def wanted(what: str, actual: object, expected: object, why: str) -> None:
        b.fail_if(
            actual != expected,
            f"{when}, {what} is {actual!r}, expected {expected!r} — {why}",
        )

    wanted(
        "the resolved timezone",
        state["timezone"],
        "UTC",
        "the context's timezone is not pinned",
    )
    wanted("the UTC offset", state["offset"], 0, "the timezone is not UTC")
    wanted(
        "the resolved locale",
        state["locale"],
        "en-US",
        "the context's locale is not pinned",
    )
    wanted("navigator.language", state["language"], "en-US", "same")
    wanted(
        "prefers-reduced-motion",
        state["reduced"],
        True,
        "the context does not request reduced motion",
    )
    wanted(
        "Date.prototype.constructor === Date",
        state["constructorIsDate"],
        True,
        "deep-clone and serialization helpers type-test Date this way",
    )
    wanted(
        "Date.now === Date.now",
        state["nowIsStable"],
        True,
        "`now` is being minted fresh on every read instead of defined once",
    )
    wanted(
        "Date.now.name",
        state["nowName"],
        "now",
        "`now` has been replaced by an anonymous function",
    )

    if on:
        wanted(
            "Date.now()",
            state["now"],
            1735722000000,
            "the page's wall clock is not frozen",
        )
        wanted(
            "new Date().toISOString()",
            state["iso"],
            "2025-01-01T09:00:00.000Z",
            "the zero-argument Date constructor is still reading the real clock",
        )
        wanted(
            "Intl.DateTimeFormat().format()",
            state["intl"],
            "01/01/2025, 09:00:00 AM",
            "Intl formats from its own internal clock",
        )
        wanted(
            "new Date().constructor.now()",
            state["constructorNow"],
            1735722000000,
            "the prototype's constructor still points at the unfrozen Date",
        )
        wanted(
            "Object.getOwnPropertyDescriptor(Date, 'now').value()",
            state["descriptorNow"],
            1735722000000,
            "`now` is being synthesized by a proxy trap rather than defined",
        )
        wanted(
            "performance.timeOrigin",
            state["timeOrigin"],
            1735722000000,
            "timeOrigin is a wall-clock reading of its own",
        )
        wanted(
            "a probe element's animation-duration",
            state["animation"],
            "0.001s",
            "the recorder's motion rule is not reaching this page",
        )
        wanted(
            "a probe element's transition-duration",
            state["transition"],
            "0.001s",
            "the recorder's motion rule is not flattening transitions",
        )
        wanted(
            "an animated ::after's animation-duration",
            state["after"],
            "0.001s",
            "the motion rule does not cover pseudo-elements",
        )
        wanted(
            "an animated ::before's animation-duration",
            state["before"],
            "0.001s",
            "the motion rule does not cover pseudo-elements",
        )
    else:
        b.fail_if(
            state["now"] == 1735722000000,
            f"{when}, Date.now() still reads the frozen 1735722000000 "
            f"although determinism was not asked for",
        )
        skew = abs(state["now"] - time.time() * 1000)
        b.fail_if(
            skew > 5 * 60 * 1000,
            f"{when}, Date.now() reads {state['now']} — {skew / 1000:.0f}s "
            f"from this process's own clock",
        )
        b.fail_if(
            state["intl"].startswith("01/01/2025"),
            f"{when}, Intl.DateTimeFormat().format() reads {state['intl']!r} — "
            f"the frozen instant, without determinism having been asked for",
        )
        wanted(
            "a probe element's animation-duration",
            state["animation"],
            "2s",
            "the motion rule is injected without determinism having been asked for",
        )
        wanted(
            "a probe element's transition-duration",
            state["transition"],
            "5s",
            "the motion rule is injected without determinism having been asked for",
        )
        wanted(
            "an animated ::after's animation-duration",
            state["after"],
            "3s",
            "the motion rule is reaching pseudo-elements without determinism "
            "having been asked for",
        )
        wanted(
            "an animated ::before's animation-duration",
            state["before"],
            "4s",
            "the motion rule is reaching pseudo-elements without determinism "
            "having been asked for",
        )
    return state


_CURSOR_BOX_JS = """() => {
  const d = document.getElementById('__demo_cursor');
  if (!d) return null;
  const r = d.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
}"""


def check_undrawn_pointer(b: Beats, page, when: str) -> None:
    box = page.evaluate(_CURSOR_BOX_JS)
    if box is None:
        b.fail_if(
            True,
            f"{when}, the chrome ships no cursor dot — "
            f"with no element there is no off-screen park to assert",
        )
        return
    b.fail_if(
        box["x"] + box["width"] > 0 and box["y"] + box["height"] > 0,
        f"{when}, the cursor dot sits at ({box['x']:.0f}, {box['y']:.0f}) "
        f"with no pointer verb having run",
    )


def out_roots_to_reap(
    entries: list[tuple[Path, float]],
    now: float,
    keep: int = KEEP_OUT_ROOTS,
    min_age_s: float = REAP_MIN_AGE_S,
) -> list[Path]:
    young = [(p, m) for p, m in entries if now - m < min_age_s]
    old = sorted(
        ((p, m) for p, m in entries if now - m >= min_age_s),
        key=lambda pm: pm[1],
        reverse=True,
    )
    room = max(0, keep - len(young))
    return [p for p, _ in old[room:]]


def reap_previous_out_roots() -> None:
    entries: list[tuple[Path, float]] = []
    for path in Path(tempfile.gettempdir()).glob("demo-video-smoke-*"):
        try:
            if path.is_dir():
                entries.append((path, path.stat().st_mtime))
        except OSError:
            continue
    for stale in out_roots_to_reap(entries, time.time()):
        shutil.rmtree(stale, ignore_errors=True)


def open_output(args: argparse.Namespace) -> tuple[Path, bool]:
    if args.out_dir:
        out_root = args.out_dir.resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        return out_root, False
    reap_previous_out_roots()
    return Path(tempfile.mkdtemp(prefix="demo-video-smoke-")), True


def check_clock_before_recording(
    only: str | None, allow: bool, window_s: float = 40.0
) -> list[str]:
    from .constants import CLOCK_PROBE_ARMS, CLOCK_SAFE_ARMS

    if allow or not (only is None or only in CLOCK_PROBE_ARMS):
        return []
    if window_s <= 0:
        return []
    refused = CLOCK_PROBE_ARMS if only is None else (only,)
    print(
        f"smoke: watching the wall clock for {window_s:.0f}s before recording "
        f"(issue #370)...",
        flush=True,
    )
    clock = probe_wall_clock(window_s)
    if not clock.covered:
        print(
            f"smoke: the clock probe's sampler left a {clock.max_gap * 1000:.0f} ms "
            f"gap, over its own {HOST_CLOCK_MAX_GAP_S * 1000:.0f} ms limit — it "
            f"cannot say whether the clock held still, so it says nothing and "
            f"the run goes ahead.",
            flush=True,
        )
        return []
    from .checks.lock import clock_probe_report
    lines = clock_probe_report(clock.steps, window_s, refused, CLOCK_SAFE_ARMS)
    if not lines:
        print(
            f"smoke: wall clock steady over {window_s:.0f}s "
            f"({clock.samples} samples, widest gap "
            f"{clock.max_gap * 1000:.0f} ms) — timing arms may run.",
            flush=True,
        )
        return []
    return ["\n    ".join(lines)]


@contextmanager
def only_one_suite(allow_concurrent: bool) -> Iterator[None]:
    lock_path = Path(SMOKE_LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if not allow_concurrent:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise SmokeFailure(
            f"another smoke suite holds {SMOKE_LOCK} — "
            f"pass --allow-concurrent to run anyway (timing bars will fail)"
        )
    finally:
        if not allow_concurrent:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)