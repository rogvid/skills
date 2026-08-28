"""Shared machinery: servers, clocks, frame and media helpers, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from _pixels import FRAME_BAND, Rect, frame_difference, gray_frames

from .constants import (  # noqa: E402
    _TICKER_STATE_JS,
    ALIGN_ARRIVAL_FRACTION,
    ALIGN_FPS,
    ALIGN_OVERSHOOT_S,
    ALIGN_POST_S,
    ALIGN_PRE_S,
    ALIGN_RESCUE_S,
    CAPTION_FADE_FRAMES,
    CLOCK_PROBE_POLL_S,
    CLOCK_PROBE_S,
    CONTENT_KEEP,
    COVERAGE_APP_MARKER,
    EVIDENCE_DIR_NAME,
    FIXTURE_DIR,
    FLATTENED_S,
    HOST_CLOCK_MAX_GAP_S,
    HOST_CLOCK_MIN_STEP_S,
    KEEP_OUT_ROOTS,
    MARKER_NAME,
    MAX_BASELINE_NOISE_FRACTION,
    MAX_CAPTURE_LOSS_S,
    MAX_CLOCK_RECORD_DISAGREEMENT_S,
    MAX_CLOCK_STEP_TIME_DISAGREEMENT_S,
    MAX_EVIDENCE_DIR_BYTES,
    MAX_EVIDENCE_FILE_BYTES,
    MAX_LOG_EARLY_S,
    MAX_MERGE_OFFSET_ERROR_S,
    MAX_UNMERGED_FIRST_BEAT_S,
    MIN_ALIGN_BAND_DELTA,
    MIN_BASELINE_FRAMES,
    NARRATION_SILENCE_DBFS,
    NARRATION_SILENCE_MIN_S,
    REAP_MIN_AGE_S,
    SEGMENT_NAMES,
    SEGMENT_OFFSET_TOLERANCE_S,
    SEGMENT_PROBES,
    SERVER_START_TIMEOUT_S,
    SMOKE_LOCK,
    TICKER_JS,
)


def web_problem_path(refused_url: str) -> str:
    """The fixture URL that breaks in all four ways this axis grades.

    Every failure is fired by the page during load, so the recorder's `goto`
    beat is still open and there is a real attribution to check. Driving them
    from the storyboard instead would fire them *between* beats, where the only
    honest answer is `beat: null` — checked separately, see BETWEEN_BEATS.
    """
    return f"/?console-error=1&bad-fetch={urllib.parse.quote(refused_url)}"


class _StoryboardFailed(RuntimeError):
    """What a storyboard raises when a sync verb gives up.

    Its own class only so the crash arm can tell "the take re-raised what the
    storyboard threw" from "something else went wrong", which a bare
    RuntimeError cannot.

    It lived inside the terminal-redaction block until #150 deleted that block.
    `run_crash_between` uses it and always did — the placement was incidental,
    and a deletion pass that trusts the block boundaries takes it.
    """


class SmokeFailure(Exception):
    """An assertion about a recording did not hold."""


def scrub_env() -> None:
    """Drop settings that would make the run depend on the operator's shell.

    Every Recorder knob reads a DEMO_VIDEO_* variable, so a developer with a
    sourced project .env would otherwise record at a different viewport, at a
    different base URL, or with narration on — and the assertions below would
    mean something different for them than for CI.
    """
    for name in [k for k in os.environ if k.startswith("DEMO_VIDEO_")]:
        del os.environ[name]
    os.environ.pop("ELEVENLABS_API_KEY", None)
    # Pin the geometry every bar in this suite was measured in — 720p, the
    # 0.80x2/3 window, the reserved caption band. The recorder's defaults
    # moved to 1080p / 0.95x0.9 / overlay pill (#403), and under those two
    # premises silently invert: the near-full-bleed window puts the band
    # outside a camera push-in's crop (so the band sweep finds the caption
    # a beat late), and WRAPPER_LONG_CAPTION wraps to two lines in a
    # 1824px band and legitimately stops clipping. This suite grades
    # recorder *mechanics*, not the defaults; the default geometry's pixels
    # are graded by tests/pixel, whose cached takes record at the defaults.
    os.environ["DEMO_VIDEO_VIEWPORT"] = "1280x720"
    os.environ["DEMO_VIDEO_WINDOW_SCALE"] = "0.80,0.66666667"
    os.environ["DEMO_VIDEO_CAPTION_OVERLAY"] = "0"


def fresh_take_dir(out_root: Path, name: str) -> Path:
    """An empty directory for one take, or a refusal.

    Emptying it is load-bearing, not tidiness. Every artifact assertion works
    by path, so a leftover demo.mp4 from a previous run grades a recorder that
    produced nothing at all as a pass — and recording repeatedly into one
    --out-dir is how a change to the recorder gets verified.

    But `--out-dir .` in a project that happens to have a `web/` directory
    would then delete somebody's source tree. So: delete only a directory that
    is absent, empty, or carries this harness's marker file. Anything else is
    a hard error naming the path.
    """
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


def keep_top(rect: Rect, fraction: float = CONTENT_KEEP) -> Rect:
    x, y, w, h = rect
    return (x, y, w, max(1, int(h * fraction)))


class Beats:
    """Collects post-condition failures without aborting the take.

    A storyboard that stops at the first bad assertion produces no video, and
    the video is two thirds of what is being graded — and CI's failure-only
    artifact upload would then have nothing to upload at the moment it is most
    wanted. So record the whole thing, then report everything that went wrong.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.problems: list[str] = []

    def expect(self, after: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            # Deliberately does NOT conclude "the interaction did not take
            # effect". A legitimate edit to tests/fixture/index.html trips
            # these too, and telling a queued-PR author that their recorder
            # change broke, when the fixture merely gained a row, is worse
            # than saying nothing.
            self.problems.append(
                f"{self.label}: after {after}, expected {wanted!r} but got "
                f"{actual!r} — either that verb had no effect, or "
                f"tests/fixture/index.html changed and this expectation is stale"
            )

    def fail_if(self, condition: bool, message: str) -> None:
        if condition:
            self.problems.append(f"{self.label}: {message}")


class HostClock:
    """CLOCK_REALTIME against CLOCK_MONOTONIC, sampled for a take's lifetime.

    Steps are held in **absolute** `time.monotonic()` seconds and put on the
    take's clock by `rebase()`, which is handed the recorder's own `_t0`. That
    matters more than it looks: this watcher starts before the browser does,
    so its zero is a second or so earlier than frame zero, and a step landing
    inside that second would otherwise be attributed to the wrong side of a
    beat. `_t0` is a `time.monotonic()` reading, not part of the measurement
    being graded — the same kind of coupling as reading `Recorder._geom` for
    the content rect.
    """

    INTERVAL_S = 0.02

    def __init__(self) -> None:
        self.raw: list[tuple[float, float]] = []  # (absolute monotonic, delta)
        # The widest interval this sampler left between two readings, and how
        # many it took. See `covered`.
        self.max_gap = 0.0
        self.samples = 0
        self._t0: float | None = None
        # Where one capture ends and the next begins, on this clock. Empty for
        # a take recorded in one piece; on a stitched demo it is where each
        # part starts, and it is load-bearing rather than bookkeeping — see
        # `before()`.
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
            # **`time.sleep`, never `self._stop.wait`** — see
            # HOST_CLOCK_MAX_GAP_S. `Event.wait`'s deadline is CLOCK_REALTIME
            # on this interpreter, so sleeping on it inside a wall-clock
            # sampler makes the sampler a function of the thing it measures.
            time.sleep(self.INTERVAL_S)

    @property
    def covered(self) -> bool:
        """Did this sampler stay close enough to its interval to be believed?

        Nothing below may correct with an uncovered reading. A step is found
        by differencing consecutive samples, so a watcher that was away for
        seconds cannot say whether the clock moved inside the gap — and
        subtracting a number nobody watched moves a search window *away* from
        the frame it is looking for, which is how issue #245's runs went red
        about something untrue.
        """
        return self.samples > 1 and self.max_gap <= HOST_CLOCK_MAX_GAP_S

    def rebase(self, t0: float) -> None:
        """Put the steps on this take's own clock — `t0` is its frame zero."""
        self._t0 = t0

    @property
    def steps(self) -> list[tuple[float, float]]:
        """(seconds from the take's frame zero, delta), rebased."""
        if self._t0 is None:
            return []
        return [(at - self._t0, delta) for at, delta in self.raw]

    @property
    def total(self) -> float:
        return sum(delta for _, delta in self.steps)

    def applied(self, t: float) -> list[tuple[float, float]]:
        """The steps that moved `t`, of the ones this take recorded.

        **Only the steps inside `t`'s own capture count.** A capture's first
        frame is where its clock starts, so a step during an earlier part
        shortened that part and nothing else — and `stitch()` lays the parts
        out by their real durations, so that shortening is already in the
        offset. Adding it again to a later part's beats would over-correct by
        a whole step. For a single take there are no boundaries and this is
        the whole list. The half a boundary cannot express — a step sampled
        *after* its own part's last frame, which sits past the next part's
        boundary and is nobody's — is kept out of the list by `joined_clock`.

        A list rather than the sum, because two of them cancel: a −1 s step
        and a +1 s step before the same beat leave `before()` at zero while
        the file still has a hole in it, and `log_early_causes` has to be able
        to tell that take from one whose clock held still.
        """
        start = max((b for b in self.boundaries if b <= t), default=0.0)
        return [(at, delta) for at, delta in self.steps if start <= at <= t]

    def in_video(self, t: float) -> tuple[float, float]:
        """(where `t` is in demo.mp4, how much of it has no video) — see below.

        Hand-written here rather than shared with the recorder: the two have
        to be able to disagree, or `capture_clock` is not being graded.
        """
        return video_instant(self.applied(t), t)

    def before(self, t: float) -> float:
        """How much the wall clock had stepped by `t` seconds into the video.

        Negative when the clock went backwards, which is the direction that
        takes wall time out of the video. A beat the log puts at `t` is at
        `t + before(t)` in demo.mp4.

        **Not simply the sum of the steps before `t`**, and the difference is a
        whole step: a backward step deletes its own width of wall time from the
        file rather than sliding it, so an instant inside that hole has no
        frame and `before()` returns what it takes to reach the last one there
        is (issue #256). `hole()` is how a caller tells that case from an
        instant the file really contains — this number alone cannot, which is
        the defect #256 is about, on the harness's side of it.
        """
        return self.in_video(t)[0] - t

    def hole(self, t: float) -> float:
        """Seconds of wall time at `t` that never reached the file, or 0.0.

        Non-zero only inside a backward step's hole, where it is the distance
        from `t` to the moment the video starts again — which is also how far
        too early `t + (the steps before t)` would have put it.
        """
        return self.in_video(t)[1]

    def describe(self) -> str:
        if not self.steps:
            return "the host's wall clock did not step during this take"
        return "the host's wall clock stepped " + ", ".join(
            f"{delta * 1000:+.0f} ms at {at:.1f}s" for at, delta in self.steps
        )


def video_instant(steps: list[tuple[float, float]], t: float) -> tuple[float, float]:
    """(where `t` is in the video, how many seconds of it have no video at all).

    The one piece of clock arithmetic this file shares between its own watcher
    and its reading of a published record, because it is not a claim about the
    recorder — it is what a wall clock does to a file. `HostClock.before` and
    `merged_clock_correction` are both hand-written *from this*, and both stay
    hand-written away from the recorder's own `timeline._placed`, which is the
    independence that matters: a correction taken from the code under test
    agrees with that code whatever it says.

    **A backward step of Δ does not slide the video. It deletes the monotonic
    window `(T, T+Δ)` from the file** (issue #256): the encoder stamps frames
    with the host's wall clock and will not write a stamp it has already
    written, so the file stalls for the width of the step instead of rewinding.
    Measured one video frame wide — `video 31.560 → 31.600 shows mono 31.644 →
    32.644`. So the video's clock is the *high-water mark* of the wall clock,
    and an instant inside a hole has no frame of its own at all: it clamps to
    the last one the file has, and the second return value says how far short
    of the naive `t + (the steps before t)` that left it.

    Everywhere outside a hole this is that sum, digit for digit, and on a host
    whose clock never steps it is the identity. Which is to say: **on a healthy
    box every line of this is dead**, and nothing an arm of this suite prints
    grades it. `HostClockHole` in `tests/unit` does, on a scripted clock.
    """
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


def hole_clause(clock, t: float, at: float) -> str:
    """What a failure adds when the instant it is about has no video. Or "".

    Both places this harness prints "the instant `t` is at `at` in the video"
    are wrong about `at` inside a hole — it is not where that instant is, it is
    the last moment the file has before the instant's own wall time was deleted
    (issue #256). Sent to `at` without this, a reader goes looking for a frame
    that is not there and concludes the harness is confused.

    One function for both messages, appended as a whole sentence rather than
    spliced into either, so the two cannot drift and so this is gradeable on
    its own: neither call site is reachable on a host whose clock holds still,
    and `HostClockHole` in `tests/unit` is the only thing that runs it.
    """
    gap = clock.hole(t) if clock is not None else 0.0
    if not gap:
        return ""
    return (
        f" There is no video of that instant at all: the host's wall clock "
        f"stepped backwards over it, so {at:.3f}s is the last moment before a "
        f"gap the video only resumes from {gap * 1000:.0f} ms later, and the "
        f"recorder is expected to have clamped to the same place (issue #256)."
    )


def log_early_causes(clock, t: float) -> str:
    """Where to look when a beat sits *ahead* of the frame showing it (#257).

    What this replaces was a verdict, not a lead: "nothing about the capture
    can move an event *later*, so this is the beat log: check where `_t0` is
    taken and where `_beat` stamps `t_start`." That is false on a take whose
    host stepped, and it is the *correction* rather than the capture that
    makes it false — a backward step of Δ deletes the window `(T, T+Δ)` from
    the file, so an instant inside that hole has no frame of its own, and a
    reading that subtracts the whole step from it instead of clamping to the
    hole's edge is left with up to a whole Δ of log-ahead (issue #256).
    Measured in issue #255 at +906, +540 and +970 ms. A reader sent to `_t0`
    and `_beat` by any of those goes hunting in the recorder's beat logging
    for a bug that is not there.

    **The lead #257 first gave instead was itself false**, which is why the
    branch below now names the hole and its width rather than a proportion. It
    said a capture could lose a fraction of the step it recorded and be
    over-shot by the difference. The muxer cannot do that: Playwright 1.62.0
    stamps `frameNumber = floor((wall_ts − first_wall_ts) · 25)` and CFR
    conversion drops frames until the wall clock climbs back, so the video's
    clock is the wall clock's **high-water mark** — measured at 97.0-100.2% of
    the recorded step over 10 steps in 9 takes, both code paths, 2-60 Hz
    paint. The three figures above were in-hole instants read as though they
    were shifts, `(t − hole_start)/Δ` and uniform on [0,1] (issue #255). The
    other cause a stepping take has is the merge seam, where a part's beats
    run past where the next part's offset puts it — published as `overlaps` in
    a stitched `timeline.json` (issue #263).

    So the take decides which cause is named first. Four answers: the three
    states this harness can be in about a host's wall clock — unmeasured,
    measured with no step reaching this beat, measured with one — and, inside
    the last, the case where the steps reaching the beat correct it by
    nothing. Two cancelling steps and a step landing on the beat itself both
    subtract 0 ms, so the over-correction cannot be what produced the skew,
    and offering it there would hand a reader a mechanism that provably did
    not run.
    Keyed on the steps `applied()` hands back rather than on the correction
    they sum to, because two steps that cancel sum to nothing and still leave
    the file short — and because a step in another capture is already in the
    offset `stitch()` laid this one out by, so it is not this beat's excuse.

    A whole sentence returned to the caller rather than spliced into either
    message, for `hole_clause`'s reason: neither call site is reachable on a
    host whose clock holds still, so `LogEarlyCause` in `tests/unit` is the
    only thing that runs the stepping branch at all.
    """
    if clock is None:
        return (
            "No wall-clock reading was kept for this take, so this harness "
            "cannot say which end is at fault: an unmeasured backward step "
            "leaves the video short and the beat log where it was, and reads "
            "from here exactly like a log stamped early. Get a reading before "
            "reading `_t0` and `_beat` (issues #215, #255)."
        )
    applied = clock.applied(t)
    if not applied:
        return (
            "No step of this beat's own capture lands before it, so nothing "
            "was subtracted from this reading and nothing in the capture can "
            "have moved the event later: this is the beat log. Check where "
            "`_t0` is taken and where `_beat` stamps `t_start`."
        )
    shift = clock.before(t)
    if abs(shift) < HOST_CLOCK_MIN_STEP_S:
        # Steps reach this beat and the correction still comes to nothing:
        # two that cancel, or one landing on the beat itself, where the
        # clamp gives back exactly what the step took. Naming the
        # over-correction here would offer a reader a mechanism that
        # provably did not run — nothing was subtracted to over-subtract.
        return (
            f"**This take's clock stepped, so the beat log is not the first "
            f"place to look**: {clock.describe()}. Nothing was subtracted "
            f"from this reading — the steps reaching this beat come to "
            f"{shift * 1000:+.0f} ms, because they cancel or because one "
            f"lands on the beat itself — so over-correction is not what "
            f"produced this skew. Neither is the beat log established as "
            f"what did: a backward step deletes its own width of wall time "
            f"from the file whether or not a later step puts the offset "
            f"back, and this harness has not read those frames. Check the "
            f"step against demo.mp4 before reading `_t0` and `_beat` "
            f"(issue #255)."
        )
    # The hole, in milliseconds, because it is the number the skew should be
    # compared against rather than a paragraph the reader has to believe: an
    # instant a backward step deleted from the file is over-corrected by
    # exactly this much when the whole step is subtracted from it instead of
    # clamping, so a skew of this size is that mechanism and a skew of some
    # other size is not.
    gap = clock.hole(t)
    inside = (
        f" **The file has no frame for this instant at all**: the step "
        f"deleted the wall time it happened in, and the video only resumes "
        f"{gap * 1000:.0f} ms later — so a reading over-corrected by the "
        f"whole step instead of clamping to the hole's edge is left with "
        f"exactly that much log-ahead (issue #256)."
        if gap
        else " This instant is outside every hole those steps left, so the "
        "video has a frame of its own for it and the correction above is the "
        "whole of what the steps took."
    )
    return (
        f"**This take's clock stepped, so the beat log is not the first place "
        f"to look**: {clock.describe()}, and {shift * 1000:+.0f} ms of that "
        f"was subtracted from this reading.{inside} A step is never lost by "
        f"halves — the video's clock is the wall clock's high-water mark, "
        f"measured at 97.0-100.2% of the recorded step over 10 steps in 9 "
        f"takes — so the two things that produce a skew here are the hole "
        f"above and, on a stitched log, the merge seam, where a part's beats "
        f"run past where the next part's offset puts it and `overlaps` in "
        f"timeline.json says so (issues #255, #263). Check the step against "
        f"demo.mp4 before reading `_t0` and `_beat`."
    )


def joined_clock(parts: list[tuple[HostClock, float]]) -> HostClock:
    """The clock of a video stitched from several captures.

    `parts` is (that capture's clock, where its video starts in the joined
    one). Nothing is mutated: each part keeps its own clock, because that is
    what grades that part's own `capture_clock` and its own `.seg.mp4`.

    **A step past the end of its own part's video is dropped**, and that is the
    whole of what `before()`'s boundaries cannot express. Each watcher runs for
    its part's whole `with` block, which outlives the frames: the encode, the
    conversion and the timeline write all happen after the last one. A step
    landing in that tail moved nothing — the next capture's first frame starts
    its own clock, which is `record_segments`' own reason for one watcher per
    segment — but on the joined clock it sits past the next part's boundary,
    and `before()` keys on time, so it would be handed to that part's beats.

    Measured, on the run that found it: a -876 ms step at 7.2 s of a part whose
    video is 6.88 s put the closing caption's search window 876 ms away from the
    frame, and the arm went red about something untrue. The same caption, in the
    same file, was timed to -20 ms by `check_merge_offset` — which corrects from
    the stitched `timeline.json`, where the recorder had stopped sampling before
    the step and the merge attributes what is left per capture (issue #225).
    Nothing is dropped from the *part's own* clock, which still grades that
    part's `capture_clock` over the window both watchers cover.
    """
    joined = HostClock()
    joined._t0 = 0.0
    # Coverage joins as the *worst* part's, so a joined clock is only believed
    # when every watcher that fed it kept its interval — see `covered`.
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


@contextmanager
def watch_wall_clock() -> Iterator[HostClock]:
    """Sample the host's wall clock for as long as a take is recording."""
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


def probe_wall_clock(window_s: float = CLOCK_PROBE_S) -> HostClock:
    """Watch the host's wall clock for `window_s`, recording nothing else.

    **Deliberately the same `HostClock` the takes are graded with**, and that
    is not the catalogue's "check that shares the bug's blind spot". This
    probe's question is not *does the host step* in the abstract — it is *will
    the sampler that grades the next take see a step*, and the only instrument
    that can answer that is the sampler itself. A second implementation here
    could disagree with the one that matters, and the disagreement would be
    the probe's, not the host's.

    The window is wall-clock time spent doing nothing, which is the cost of
    the whole feature. See `CLOCK_PROBE_S`.
    """
    with watch_wall_clock() as clock:
        deadline = time.monotonic() + window_s
        while time.monotonic() < deadline:
            time.sleep(CLOCK_PROBE_POLL_S)
    return clock


def clock_probe_report(
    steps: list[tuple[float, float]],
    window_s: float,
    refused: tuple[str, ...],
    safe: tuple[str, ...],
) -> list[str]:
    """What the probe saw, as lines. Empty when the clock held still.

    Pure, and separate from `probe_wall_clock` for the usual reason: the
    interesting behaviour is what a reader is told, and a test that had to
    wait forty seconds for a real host to misbehave would grade the wait.

    `steps` is `HostClock.steps` — (seconds from the probe's start, delta).
    """
    if not steps:
        return []
    sizes = ", ".join(f"{delta * 1000:+.0f} ms" for _, delta in steps)
    at = ", ".join(f"{t:.1f} s" for t, _ in steps)
    lines = [
        f"the host's wall clock stepped {len(steps)} "
        f"{'time' if len(steps) == 1 else 'times'} in {window_s:.0f} s of "
        f"watching: {sizes}, at {at} into the probe.",
    ]
    if len(steps) >= 2:
        gaps = [b - a for (a, _), (b, _) in zip(steps, steps[1:], strict=False)]
        mean = sum(gaps) / len(gaps)
        lines.append(
            f"Cadence: one step every {mean:.1f} s "
            f"({', '.join(f'{g:.1f} s' for g in gaps)} between them)."
        )
    else:
        # One step is not a cadence, and saying so is the point: a reader
        # handed "every 40 s" from a single observation would size a timeout
        # against a number this probe never measured.
        lines.append(
            f"One step is not a cadence — this {window_s:.0f} s window saw "
            f"one, so how often it happens is not measured here."
        )
    lines += [
        "",
        "A backward step takes that much wall time out of demo.mp4 and leaves "
        "the beat log where it was, so every timing bar in "
        f"{' and '.join(refused)} reads a skew that is this host's and not the "
        "recorder's. Refusing before recording rather than after (issue #370).",
        "",
        f"Safe to run on this host anyway: {' '.join(safe)}. None of them "
        "grades a beat log against a video.",
        "",
        "To record regardless — a run that needs this cannot be read as a "
        "verdict — pass --allow-stepping-clock.",
    ]
    return lines


def merged_clock_correction(record: object, beat: dict) -> float:
    """What a reader of a stitched `timeline.json` **alone** corrects a beat by.

    Hand-written from the envelope's documentation in `timeline.py`, never
    imported from `stitching.py`: a reader assembled out of the merge's own
    code agrees with that code whatever it says, which is the catalogue's
    "check that shares the bug's blind spot". The documented rule is the steps
    of *this beat's own capture*, up to this beat — not the running total, and
    not an earlier part's, whose lost wall time is already in the offsets the
    merge laid the parts out by — clamped to the last instant the file has
    where a backward step deleted this one (`video_instant`, issue #256).

    **The hole arithmetic is shared with `HostClock.before`, and that narrows
    what the comparison in `check_merged_capture_clock` grades**: a bug in
    `video_instant` cancels on both sides of it. What is left there is what
    that check is for — whether the *record* attributes its steps to the right
    capture — and the arithmetic itself is graded against hand-written numbers
    by `HostClockHole` in `tests/unit`.
    """
    if not isinstance(record, dict):
        return 0.0
    t_start = beat.get("t_start")
    if not isinstance(t_start, (int, float)):
        return 0.0
    steps = []
    for step in record.get("steps") or []:
        if not isinstance(step, dict):
            continue
        at, delta = step.get("t"), step.get("delta")
        if not isinstance(at, (int, float)) or not isinstance(delta, (int, float)):
            continue
        if step.get("segment") == beat.get("segment"):
            steps.append((float(at), float(delta)))
    return video_instant(steps, float(t_start))[0] - float(t_start)


def check_merged_capture_clock(
    out_dir: Path, parts: list[tuple[str, HostClock, float, object]]
) -> list[str]:
    """A stitched demo's own answer to "where in the video is this beat" (#225).

    Graded off `demo.mp4`'s `timeline.json` and nothing else, because that is
    all a consumer has: `stitch()` removes the parts and their beat logs, so a
    measurement that only ever reached a `<segment>.seg.timeline.json` is one
    nobody downstream will read. `parts` is (name, that capture's clock, where
    its video starts in the stitched one, that part's own record as its log
    held it before the merge) — the offsets taken with ffprobe off the parts
    rather than read out of the file being graded.

    The last claim is the measured one: for every beat, what a reader
    reconstructs from the merged record has to be what this harness measured on
    that beat's *own* capture — which includes a step in an earlier part
    correcting nothing here, the half a merge gets wrong by accumulating (see
    `joined_clock`). It says nothing on a host whose wall clock never steps, so
    the merge's arithmetic is *also* graded directly, on a scripted clock, by
    `MergedCaptureClock` in `tests/unit`. Everything above it holds on any host.

    A beat that starts within `MAX_CLOCK_STEP_TIME_DISAGREEMENT_S` of a step is
    skipped and counted, not graded: two samplers on their own 20 ms grids do
    not both know which side of that beat the step fell on, and widening the
    bar to a step's width instead would leave it grading nothing.
    """
    path = out_dir / "timeline.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"segments: timeline.json could not be read for capture_clock: {exc}"]
    # Before the merged record, and whether or not there is one: that field
    # goes null the moment any part is missing its own, and the parts that
    # *were* measured must not go with it. Graded against each segment's log as
    # it stood on disk before the merge, so a record that arrives empty, or
    # belonging to the other part, fails the same way.
    failures: list[str] = []
    carried = doc.get("segments")
    if not isinstance(carried, list) or len(carried) != len(parts):
        return [
            f"segments: the stitched timeline.json's `segments` is {carried!r}, "
            f"expected one record per part — the per-part clocks live there and "
            f"nothing below can be attributed without them"
        ]
    for (name, _clock, _offset, own), kept in zip(parts, carried, strict=True):
        if kept.get("capture_clock") != own:
            failures.append(
                f"segments: the merged `segments` record for {name} carries "
                f"capture_clock {kept.get('capture_clock')!r}, but "
                f"{name}.seg.timeline.json measured {own!r}. That record is what "
                f"is left to read when the merged one goes null, and a stitched "
                f"demo that lost one part's clock must not lose the parts that "
                f"were measured (issue #225)"
            )
    record = doc.get("capture_clock")
    # A part that could not watch its own clock is the one case where a null
    # merged record is the *right* answer rather than a lost one — see
    # `_merge_capture_clock`. Say which part, and stop: there is nothing here
    # to attribute (issue #247).
    unmeasured = [
        name
        for name, _clock, _offset, own in parts
        if not isinstance(own, dict) or own.get("measured") is not True
    ]
    if unmeasured and record is None:
        print(
            f"smoke: segments the merged capture_clock is null because "
            f"{', '.join(unmeasured)} could not measure its own wall clock — "
            f"which is the merge refusing to say a part nobody watched held "
            f"still"
        )
        return failures
    if not isinstance(record, dict):
        return failures + [
            f"segments: the stitched timeline.json has no merged `capture_clock` "
            f"record ({record!r}). stitch() takes the parts and their beat logs "
            f"away with it, so what is left is a beat log on the monotonic "
            f"clock, a video on the host's wall clock, and nothing to reconcile "
            f"them with (issues #18, #215, #225)"
        ]
    if unmeasured:
        failures.append(
            f"segments: the merged capture_clock reports "
            f"measured={record.get('measured')!r} while "
            f"{', '.join(unmeasured)} could not measure its own clock. A "
            f"merged record that folds an unwatched part into a total reads "
            f"as 'that part's clock held still', which nobody established "
            f"(issue #247)"
        )
    steps, total = record.get("steps"), record.get("total")
    if not isinstance(steps, list) or not isinstance(total, (int, float)):
        return failures + [
            f"segments: the merged `capture_clock` is steps={steps!r}, "
            f"total={total!r} — a reader correcting a beat timestamp with that "
            f"gets nothing"
        ]
    summed = sum(float(s.get("delta", 0.0)) for s in steps if isinstance(s, dict))
    if abs(summed - float(total)) > 0.001:
        failures.append(
            f"segments: the merged capture_clock.total is {total!r} but its own "
            f"steps sum to {summed:+.4f} — the merged field disagrees with "
            f"itself, and a consumer reading only the total corrects by a "
            f"different amount from one reading the steps"
        )
    wanted = [round(offset, 3) for _name, _clock, offset, _own in parts]
    boundaries = record.get("boundaries")
    if (
        not isinstance(boundaries, list)
        or len(boundaries) != len(wanted)
        or any(
            not isinstance(b, (int, float))
            or abs(float(b) - w) > SEGMENT_OFFSET_TOLERANCE_S
            for b, w in zip(boundaries, wanted, strict=False)
        )
    ):
        failures.append(
            f"segments: the merged capture_clock says its captures start at "
            f"{boundaries!r}; ffprobe puts them at {wanted!r}. Those are what "
            f"tell a reader which steps apply to which beats, and a merged "
            f"record whose captures all start at zero hands the first "
            f"segment's steps to the second segment's beats — over-correcting "
            f"every one of them by a whole step (issue #225)"
        )
    names = {name for name, _clock, _offset, _own in parts}
    stray = [
        step
        for step in steps
        if not isinstance(step, dict) or step.get("segment") not in names
    ]
    if stray:
        failures.append(
            f"segments: {len(stray)} of {len(steps)} merged capture_clock "
            f"step(s) name no capture of this demo ({stray[:2]!r}; the parts "
            f"are {sorted(names)}). A step is sampled for as long as its "
            f"capture runs, which is longer than the video that capture "
            f"produced, so a step's merged timestamp can fall past the next "
            f"part's boundary — which capture measured it is the only "
            f"attribution a reader can trust"
        )

    unresolvable = 0
    for name, clock, offset, _own in parts:
        # Both this harness's steps and the record's, on this part's own clock:
        # a beat that starts within a sampler's reach of a step is one the two
        # watchers genuinely cannot agree about — they are on their own 20 ms
        # grids, so which *side* of the beat the step fell on is not a fact
        # either of them has. Skipped rather than absorbed into a wider bar,
        # because a bar wide enough for a whole step grades nothing at all: the
        # beats after a step are still 0.78 s apart from the beats before it,
        # and those are what carry the claim.
        near = [at for at, _delta in clock.steps] + [
            float(step["t"]) - offset
            for step in steps
            if isinstance(step, dict)
            and step.get("segment") == name
            and isinstance(step.get("t"), (int, float))
        ]
        for beat in doc.get("beats") or []:
            if beat.get("segment") != name or not isinstance(
                beat.get("t_start"), (int, float)
            ):
                continue
            local = float(beat["t_start"]) - offset
            if any(
                abs(at - local) <= MAX_CLOCK_STEP_TIME_DISAGREEMENT_S for at in near
            ):
                unresolvable += 1
                continue
            measured = clock.before(local)
            read = merged_clock_correction(record, beat)
            if abs(measured - read) > MAX_CLOCK_RECORD_DISAGREEMENT_S:
                failures.append(
                    f"segments: beat {beat.get('index')} of {name} is logged at "
                    f"{float(beat['t_start']):.2f}s, and a reader with only the "
                    f"stitched timeline.json would place it {read * 1000:+.0f} "
                    f"ms from there in demo.mp4 — this harness watched that "
                    f"capture's own wall clock and makes it "
                    f"{measured * 1000:+.0f} ms ({clock.describe()}). The "
                    f"merged record is the only thing a consumer has, and a "
                    f"step belongs to the capture that measured it: an earlier "
                    f"part's is already in this part's offset (issue #225)"
                )
                break
    if not failures:
        print(
            f"smoke: segments the stitched timeline.json places every beat on "
            f"its own capture's clock ({len(steps)} step(s) merged, boundaries "
            f"{boundaries}"
            + (
                f", {unresolvable} beat(s) too close to a step for the two "
                f"samplers to resolve)"
                if unresolvable
                else ")"
            )
        )
    return failures


def start_ticker(b: Beats, page) -> None:
    """Inject TICKER_JS and confirm it is running *and* opted out."""
    page.evaluate(TICKER_JS)
    state = page.evaluate(_TICKER_STATE_JS)
    # If it silently failed to attach, every timing number below becomes a
    # measurement of Chromium's screencast luck instead of the beat log.
    if state is None:
        b.fail_if(
            True,
            "the compositor ticker did not attach — timing measurements in "
            "this take are not trustworthy (see TICKER_JS)",
        )
        return
    b.fail_if(
        state["name"] != "__smoke_ticker"
        or state["duration"] == "0s"
        or state["state"] != "running",
        f"the compositor ticker is not animating (animation-name "
        f"{state['name']!r}, duration {state['duration']!r}, play-state "
        f"{state['state']!r}) — the page will go idle during this take, the "
        f"screencast will drop wall time (issue #18), and every timing number "
        f"below becomes a measurement of luck. If the recorder's determinism "
        f"CSS stopped honouring data-demo-video-animate, this is where it "
        f"shows up (see TICKER_JS)",
    )
    b.fail_if(
        state["control"] != FLATTENED_S,
        f"a control element with the ticker's animation and no "
        f"data-demo-video-animate reports animation-duration "
        f"{state['control']!r}, expected {FLATTENED_S!r} — the recorder's "
        f"determinism CSS is not being applied to this page, so the ticker "
        f"running proves nothing about the opt-out and app animations are not "
        f"being frozen. (Both takes record with deterministic=True precisely "
        f"so this can be asserted; the default does not inject the rule.)",
    )


class EntropyTake(NamedTuple):
    """One recording of the entropy storyboard, and what it rendered."""

    problems: list[str]
    out_dir: Path
    clock: str  # the wall clock the page printed, as text
    still_rect: Rect  # where the entropy panel sits in the framed frame
    video_rect: Rect  # the same rect — stills and video share one geometry
    spin_rect: Rect  # just the spinning shape, in the same coordinates


def content_of(out_dir: Path, name: str = "timeline.json") -> dict | None:
    """The `content` report out of a take's timeline, or None if there is none."""
    path = out_dir / name
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    got = doc.get("content")
    return got if isinstance(got, dict) else None


def content_rects(out_dir: Path) -> list[list]:
    """Every rect this take's timeline claims to have scored.

    One for a single take; one per part for a stitched demo, whose envelope
    reports `rect: null` on purpose — two segments can be two media with two
    geometries, and inventing a single rect for the join would be a number that
    describes neither.
    """
    doc = json.loads((out_dir / "timeline.json").read_text())
    found = []
    for content in [doc.get("content")] + [
        record.get("content") for record in doc.get("segments") or []
    ]:
        if isinstance(content, dict) and isinstance(content.get("rect"), list):
            found.append(content["rect"])
    return found


def _synthetic_take(path: Path, painted_at: float | None, seconds: float) -> None:
    """A tiny mp4 that opens blank and paints at `painted_at` — or never blank.

    `painted_at=None` writes a video that is one *painted* picture from its
    first frame to its last: the control, and the only thing that separates
    "opened on nothing" from "opened on something and held still".
    """
    common = ["ffmpeg", "-y", "-v", "error"]
    # Colour bars rather than `testsrc2`: they are a *static* picture, which is
    # exactly the control this needs. `testsrc2` animates, so a video made of
    # it changes every frame and could not tell a blank opening from a painted
    # one that holds still — the very distinction being graded.
    bars = f"smptebars=s=320x180:r=25:d={seconds:.2f}"
    encode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", str(path)]
    if painted_at is None:
        subprocess.run([*common, "-f", "lavfi", "-i", bars, *encode], check=True)
        return
    subprocess.run(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s=320x180:r=25:d={seconds:.2f}",
            "-f",
            "lavfi",
            "-i",
            bars,
            "-filter_complex",
            f"[0:v][1:v]overlay=enable='gte(t,{painted_at:.2f})'[v]",
            "-map",
            "[v]",
            *encode,
        ],
        check=True,
    )


def _criterion_page_failures(out_dir: Path, card: dict, declared: str) -> list[str]:
    """Was the clause on the screen, and not only in the beat log? (issue #280)

    Not a helper for tidiness — a different *source*. Every other assertion
    about the card reads `timeline.json`, which the recorder writes out of the
    same values it drew from; they agree by construction and would all pass on
    a verb that logged a perfect beat and evaluated nothing. The evidence
    file's `chrome` field is read out of the wrapper document's DOM at the
    end of the beat (#361) — the card is the recorder's furniture and lives
    there, not in the app's aria — so it is an artifact that can disagree.

    **`chrome` and not the file.** The evidence envelope also carries a copy
    of the beat record, caption and all, so searching the whole document would
    find the clause on a take whose card never reached the browser — the
    catalogue's wrong-scope search, in the file written to avoid it. The
    `chrome` read is visibility-gated in the page (opacity, display), so a
    card toggled to opacity 0 leaves the field without its line.

    It still grades **presence, not legibility**: a card rendered off-frame or
    under an app overlay puts exactly this text in exactly this read. That
    gap is stated in tests/README.md rather than papered over — and the
    card's *pixels* are check_wrapper_card's, in the same arm.
    """
    path = card.get("evidence")
    if not path:
        return [
            "coverage: the criterion beat names no evidence file, so nothing "
            "here reads the page — every other assertion about the card is "
            "the beat log agreeing with itself"
        ]
    on_disk = out_dir / path
    if not on_disk.is_file():
        return [f"coverage: the criterion beat's evidence {path} was not written"]
    doc = json.loads(on_disk.read_text())
    aria = doc.get("aria")
    # The haystack, before anything is claimed about it. An empty or stubbed
    # snapshot makes "the clause is not in it" fire for the wrong reason and
    # "the clause is in it" impossible; the marker is a string the fixture page
    # renders and nothing in this harness writes.
    if not isinstance(aria, str) or COVERAGE_APP_MARKER not in aria:
        return [
            f"coverage: the criterion beat's evidence ({path}) carries no "
            f"snapshot of the fixture page, so whether the capture read a "
            f"live screen cannot be established, and the chrome read below "
            f"would prove nothing"
        ]
    chrome = doc.get("chrome")
    if not isinstance(chrome, str) or declared not in chrome:
        return [
            f"coverage: {declared!r} is not in the on-screen chrome text the "
            f"criterion beat recorded ({path} carries chrome={chrome!r}) — "
            f"the beat log says a card carried the clause and the screen the "
            f"recorder was driving never showed those words"
        ]
    return []


def blanked_copy(mp4: Path, rect: Rect, out: Path) -> bool:
    """`mp4` with `rect` painted flat black — a real recording, blank where the
    app was.

    The known-bad input the picture check has to be run against, and it has to
    be *this* shape rather than a synthesized flat video: the whole finding
    behind issue #17 is that the recorder's own chrome dominates a whole-frame
    score, so the control must keep the chrome and lose only the app. A flat
    video has no chrome and proves nothing about which region is being scored.
    """
    x, y, w, h = rect
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vf",
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-r",
            "25",
            str(out),
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and out.is_file()


def frame_at(mp4: Path, at: float, rect: Rect, out: Path) -> bytes | None:
    """`rect` of the frame of `mp4` at `at` seconds, as PNG bytes.

    Cropped, and to a rect this harness derived itself — the recorder's report
    is not consulted. Two things outside the app rect change on every take of
    this suite and neither is the demo: the caption bar, and TICKER_JS's 8x8
    corner element, which exists precisely to keep the screencast painting
    while the storyboard idles. A whole-frame comparison would find every pair
    of frames different and quietly prove nothing.
    """
    x, y, w, h = rect
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(mp4),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(out),
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not out.is_file():
        return None
    return out.read_bytes()


def beat_midpoints(out_dir: Path, verb: str) -> list[tuple[int, float]]:
    """(index, midpoint) for every beat with this verb, in order."""
    doc = json.loads((out_dir / "timeline.json").read_text())
    got: list[tuple[int, float]] = []
    for beat in doc.get("beats") or []:
        if beat.get("verb") != verb:
            continue
        start, end = beat.get("t_start"), beat.get("t_end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            got.append((int(beat.get("index", len(got))), (start + end) / 2))
    return got


def screens_differ(out_dir: Path) -> tuple[int, str]:
    """How many distinct screens this take's evidence recorded, and one of them.

    Deliberately the *text* tier: `evidence/*.json` is what a reviewing agent
    reads, and on the take issue #97 came from it was completely correct while
    the recording showed nothing. Reading it here is how this harness knows the
    covered take's commands really ran — independently of any pixel.
    """
    seen: list[str] = []
    for path in sorted((out_dir / "evidence").glob("beat-*.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        text = evidence_screen_text(doc).strip()
        if text and text not in seen:
            seen.append(text)
    return len(seen), (seen[-1] if seen else "")


def crop_png(src: Path, rect: Rect, out: Path) -> bytes | None:
    """`rect` of a PNG, losslessly, as bytes."""
    x, y, w, h = rect
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(out),
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not out.is_file():
        return None
    return out.read_bytes()


def caption_probe_band(
    label: str, frame_size: tuple[int, int], factor: float = 1.0
) -> Rect:
    """Where this medium's caption paints, at `factor` times the frame size.

    Every medium's caption paints in the wrapper chrome's reserved band
    below the app rect — web and segments since #358/#361, terminal since
    #362 — and reading the legacy full-width bottom strip dilutes its
    change with ~7x of static chrome: measured 2.68 mean luma over the
    strip for a caption whose own band moves by an order of magnitude
    more. The arithmetic is `chrome_geometry`'s, duplicated at native size
    (the loop-vs-suite rule: policy is not imported), then scaled, because
    the geometry's even-pixel rounding does not commute with scaling.
    `label` no longer dispatches; it stays so a failure message's caller
    reads the same as the checks it feeds.
    """
    del label
    width, height = frame_size
    appw = int(width * 0.80) & ~1
    apph = int(height * 2 / 3) & ~1
    winw = appw + 2 * 14
    winh = 36 + 14 + apph + 96 + 14
    winx = (width - winw) // 2
    winy = (height - winh) // 2
    return (
        round((winx + 14) * factor),
        round((winy + 36 + 14 + apph) * factor),
        round(appw * factor),
        round(96 * factor),
    )


def caption_appearance_s(
    label: str, mp4: Path, band: Rect, expect_at: float
) -> tuple[float | None, str]:
    """When the probe caption really shows up in the video, in seconds.

    Returns (seconds, note) — seconds is None when the measurement could not
    be made, and `note` says why, or reports the numbers behind the answer.

    `expect_at` is where the caller expects the caption **in the video's own
    clock**, which is not the beat's `t_start` on a host whose wall clock
    stepped: see HostClock. Centring the window there rather than on `t_start`
    is what keeps the window in the same place relative to the *picture* — the
    probe's quiet run-up slid by the same amount the probe did — instead of
    reaching back past the previous caption's fade on stepped takes and
    reporting a busy run-up (issue #215).

    The storyboard leaves PROBE_QUIET_S of caption-band quiet before the probe
    caption, so within this window the caption band changes for one reason
    only. Sample it every frame from before the beat to after it, and take the
    first frame that has travelled ALIGN_ARRIVAL_FRACTION of the way from the
    quiet baseline to where the band ends up. Deliberately *not* "the first
    frame that differs at all": the bar fades in over 0.3 s, so the first
    perturbed frame and the fully-drawn one are a third of a second apart and
    only one of them is a defensible answer.
    """
    t_start = expect_at
    start = max(0.0, t_start - ALIGN_PRE_S)
    span = (t_start - start) + ALIGN_POST_S
    try:
        frames = gray_frames(
            mp4, band, sample_fps=ALIGN_FPS, start=start, duration=span
        )
    except RuntimeError as exc:
        return None, str(exc)
    if len(frames) < ALIGN_FPS // 2:
        return None, f"only {len(frames)} frames could be sampled around {t_start:.2f}s"

    baseline = frames[0]
    travel = [frame_difference(baseline, f) for f in frames]
    settled = sum(travel[-3:]) / 3
    floor = MIN_ALIGN_BAND_DELTA[label]
    if settled < floor:
        return None, _explain_flat_window(label, mp4, band, t_start, settled, floor)
    # Find the arrival on the travel fraction alone, then validate the baseline
    # using only the frames *before* it. Deriving a noise floor from a fixed
    # prefix of the window instead looks right and is not: a take that lost
    # capture time early puts the caption a few frames into the window, the
    # "quiet" prefix then straddles the caption's own step, and the run reports
    # a busy run-up for a page that never moved. Measured once, on a take whose
    # video had slid 440 ms.
    threshold = settled * ALIGN_ARRIVAL_FRACTION
    arrived = next((i for i, d in enumerate(travel) if d > threshold), None)
    if arrived is None:
        return None, (
            f"the caption band settles at {settled:.2f} but no frame in the "
            f"window crossed {threshold:.2f} — the band never reaches a state "
            f"it holds, so there is nothing to time"
        )
    # Validate the baseline on frames that are genuinely *before* the caption:
    # not the ones immediately preceding the arrival, which are the caption's
    # own 0.3 s fade partway up. Measuring those instead reports a busy run-up
    # on every take whose fade happened to be captured as a ramp rather than a
    # jump — it reads a fifth of `settled`, by construction just under the
    # arrival threshold.
    usable = arrived - CAPTION_FADE_FRAMES
    if usable < MIN_BASELINE_FRAMES:
        return None, (
            f"the caption arrives {arrived / ALIGN_FPS:.2f}s into a "
            f"{ALIGN_PRE_S:.2f}s run-up, so the video is "
            f"{(ALIGN_PRE_S - arrived / ALIGN_FPS) * 1000:.0f} ms ahead of the "
            f"beat log — further than this window can measure and still leave "
            f"{MIN_BASELINE_FRAMES} frames of baseline in front of the "
            f"caption's own fade. The window already reaches "
            f"{ALIGN_OVERSHOOT_S * 1000:.0f} ms past the "
            f"{MAX_CAPTURE_LOSS_S * 1000:.0f} ms of capture loss this file "
            f"tolerates, so a slide this size is the capture and not the "
            f"measurement (issue #18)"
        )
    noise = max(travel[1:usable], default=0.0)
    if noise > settled * MAX_BASELINE_NOISE_FRACTION:
        return None, (
            f"the caption band wanders by {noise:.2f} before the caption "
            f"arrives, against a settled {settled:.2f} — the run-up was not "
            f"quiet, so there is no baseline to measure from"
        )
    if arrived == 0:
        return None, (
            f"the caption band was already changed at the very first sampled "
            f"frame ({start:.2f}s), {ALIGN_PRE_S}s before the beat says the "
            f"caption was set — nothing about this window is a baseline"
        )
    return start + arrived / ALIGN_FPS, (
        f"band travelled {settled:.1f}, noise {noise:.2f}, "
        f"arrival threshold {threshold:.2f}"
    )


def _explain_flat_window(
    label: str, mp4: Path, band: Rect, t_start: float, settled: float, floor: float
) -> str:
    """Why the caption band did not move in the window around `t_start`.

    Two very different things look identical from inside ALIGN_PRE_S: the
    caption was never drawn, or the video slid so far under the beat log that
    the whole window is already past it. Saying the first when it is the second
    accuses the recorder of losing a caption that is plainly on screen. So
    widen the search before concluding anything.
    """
    unmeasurable = (
        f"the caption band did not move in the {ALIGN_PRE_S + ALIGN_POST_S:.1f}s "
        f"around {t_start:.2f}s ({settled:.2f} mean luma, under the {floor} floor)"
    )
    wide_start = max(0.0, t_start - ALIGN_RESCUE_S)
    try:
        frames = gray_frames(
            mp4,
            band,
            sample_fps=ALIGN_FPS,
            start=wide_start,
            duration=(t_start - wide_start) + ALIGN_RESCUE_S,
        )
    except RuntimeError as exc:
        return f"{unmeasurable}, and the wider search failed too: {exc}"
    if len(frames) < ALIGN_FPS:
        return f"{unmeasurable}, and too little video remains to search wider"

    # Rising edges anywhere in +/- ALIGN_RESCUE_S. If the caption is on screen
    # at all, one of them is it, and the nearest says how far the video slid.
    steps = [frame_difference(frames[i - 1], frames[i]) for i in range(1, len(frames))]
    peak = max(steps)
    if peak < floor * ALIGN_ARRIVAL_FRACTION:
        return (
            f"{unmeasurable}. Nothing moves in the caption band for "
            f"{ALIGN_RESCUE_S:.0f}s either side either, so the caption really "
            f"was never drawn — this is not a timing problem."
        )
    edges = [wide_start + i / ALIGN_FPS for i, s in enumerate(steps, 1) if s > peak / 2]
    nearest = min(edges, key=lambda t: abs(t - t_start))
    return (
        f"{unmeasurable}, but the band does change at {nearest:.2f}s — "
        f"{(nearest - t_start) * 1000:+.0f} ms away, outside the "
        f"{ALIGN_PRE_S:.1f}s search window. The video has slid out from under "
        f"the beat log by more than the window can see, so the skew cannot be "
        f"measured (not that the caption is missing). The window is already "
        f"centred on where the host's measured wall-clock steps put this beat "
        f"in the video, so this slide is something else — see issues #18 "
        f"and #215."
    )


def video_fps(mp4: Path) -> float:
    """The recording's own frame rate, from the container.

    Read rather than assumed, and the frames below are decoded at the source's
    rate rather than through an `fps=` filter. A resample onto a grid that does
    not share the video's phase duplicates frames, and a duplicated frame is
    indistinguishable from a frame in which nothing moved — which is exactly
    the thing being measured. Sampling this measurement's own artefact was
    worth two readings of the same healthy take that differed by half.
    """
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "csv=p=0",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    num, _, den = out.partition("/")
    rate = float(num) / float(den or 1)
    if not 1.0 <= rate <= 240.0:
        raise SmokeFailure(f"{mp4} reports an implausible frame rate {out!r}")
    return rate


def evidence_docs(
    label: str, out_dir: Path, segment: str | None = None
) -> tuple[list[dict], list[dict], list[str]]:
    """(beats, evidence documents, failures) for one take, paired by index.

    The pairing is the structural half of this axis: every beat in
    timeline.json must name an evidence file, that file must exist, and
    `evidence/` must hold nothing the log does not name — the same
    both-directions check the stills already get, and for the same reason. A
    dangling pointer sends a reviewer to a file that was never written; an
    orphan file is a beat the log forgot.

    The expected filename is *computed here*, deliberately, and that is not the
    anti-pattern SKILL.md warns a reader about. A reader has to follow the
    `evidence` pointer, because nothing promises them the naming; a test that
    followed the pointer alone would agree with whatever name the recorder
    chose. Both are graded: the pointer must say what this function computed,
    and the file the pointer names must be the one on disk.
    """
    failures: list[str] = []
    stem = f"{segment}.seg.timeline" if segment else "timeline"
    timeline = out_dir / f"{stem}.json"
    if not timeline.is_file():
        return [], [], [f"{label}: {timeline.name} was never written"]
    beats = json.loads(timeline.read_text()).get("beats") or []
    directory = out_dir / EVIDENCE_DIR_NAME
    if not directory.is_dir():
        return (
            beats,
            [],
            [
                f"{label}: no {EVIDENCE_DIR_NAME}/ directory — the take recorded "
                f"{len(beats)} beats and wrote an account of none of them"
            ],
        )
    prefix = f"{segment}.seg." if segment else ""
    docs: list[dict] = []
    for position, beat in enumerate(beats):
        # Computed here rather than imported, so a change to how evidence is
        # named fails loudly instead of being agreed with.
        wanted = f"{EVIDENCE_DIR_NAME}/{prefix}beat-{position:02d}.json"
        if beat.get("evidence") != wanted:
            failures.append(
                f"{label}: beat {position} ({beat.get('verb')!r}) points at "
                f"evidence {beat.get('evidence')!r}, expected {wanted!r}"
            )
        path = out_dir / (beat.get("evidence") or wanted)
        if not path.is_file():
            failures.append(
                f"{label}: beat {position} ({beat.get('verb')!r}) names "
                f"evidence {path.name!r}, which was never written"
            )
            continue
        size = path.stat().st_size
        if size > MAX_EVIDENCE_FILE_BYTES:
            failures.append(
                f"{label}: {path.name} is {size} bytes, over the "
                f"{MAX_EVIDENCE_FILE_BYTES}-byte ceiling — the per-field caps "
                f"are not being applied"
            )
        try:
            docs.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            failures.append(f"{label}: {path.name} is not valid JSON: {exc}")
    # Only files this take's naming owns. A multi-segment demo writes all its
    # segments into one evidence/, so another segment's files are neither this
    # take's orphans nor its business.
    mine = re.compile(rf"^{re.escape(prefix)}beat-\d+\.json$")
    on_disk = sorted(p.name for p in directory.glob("*.json") if mine.match(p.name))
    named = sorted(Path(b["evidence"]).name for b in beats if b.get("evidence"))
    if on_disk != named:
        failures.append(
            f"{label}: {EVIDENCE_DIR_NAME}/ holds {on_disk!r} but the beats "
            f"name {named!r} — a beat captured nothing, or something was "
            f"captured that no beat owns"
        )
    total = sum(
        p.stat().st_size for p in directory.glob("*.json") if mine.match(p.name)
    )
    if total > MAX_EVIDENCE_DIR_BYTES:
        failures.append(
            f"{label}: {EVIDENCE_DIR_NAME}/ is {total // 1024} kB over "
            f"{len(named)} beats, past the {MAX_EVIDENCE_DIR_BYTES // 1024} kB "
            f"bar — evidence is meant to be capped, not to outgrow the mp4"
        )
    return beats, docs, failures


def evidence_screen_text(doc: dict) -> str:
    """Only the part of an evidence document that describes the *screen*.

    Deliberately excludes the embedded beat record. Every caption is in
    `beat.caption` already, so searching the whole file for one would pass on a
    recorder that captured no page text at all — the assertion has to be about
    what the page said, not about the log quoting itself.
    """
    return "\n".join(
        str(doc.get(field) or "")
        for field in ("aria", "scope_aria", "html", "screen", "chrome")
    )


def refused_url() -> str:
    """A URL nothing will answer.

    free_port() binds only long enough to be told a number and lets go, so a
    request to it is refused at connect rather than answered — which is the
    `request_failed` shape, distinct from the 404 that `http_error` grades.
    """
    return f"http://127.0.0.1:{free_port()}/refused"


def longest_true_run(flags: list[bool]) -> tuple[int, int] | None:
    """(start, length) of the longest contiguous True stretch, or None.

    tests/pixel's `longest_run`, duplicated for the same reason its
    thresholds are: the loop and the suite must not import each other.
    """
    best: tuple[int, int] | None = None
    start: int | None = None
    for i, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if best is None or i - start > best[1]:
                best = (start, i - start)
            start = None
    return best


def wrapper_pad_band(geom: dict) -> Rect:
    """The strip of flat window body a wrapper card is compared against.

    The window's **bottom pad** — between the caption band's end and the
    window's bottom edge — because it is the one stretch of bare window body
    a wrapper frame always shows: the pad between the app rect and the
    window's bottom is the caption band here, which carries a bubble
    whenever a line is up. Inset from the pad's own edges — the outermost
    rows blend into the drop shadow and the band above.
    """
    pad_top = geom["bandy"] + geom["bandh"]
    pad_bottom = geom["winy"] + geom["winh"]
    fx, fw = FRAME_BAND
    return (
        geom["bandx"] + int(geom["bandw"] * fx),
        pad_top + 2,
        max(8, int(geom["bandw"] * fw)),
        max(2, pad_bottom - pad_top - 4),
    )


def last_frame(mp4: Path, rect: Rect) -> bytes | None:
    """The final second of a recording, reduced over `rect`, last frame first
    available. Both takes end on the same static page, so this is the frame
    they should agree on."""
    from demo_recording.content import media_duration

    try:
        seconds = media_duration(mp4)
    except Exception:  # noqa: BLE001 - the caller reports a missing measurement
        return None
    frames = gray_frames(
        mp4, rect, sample_fps=4, start=max(0.0, seconds - 1.0), duration=1.0
    )
    return frames[-1] if frames else None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def png_size(path: Path) -> tuple[int, int]:
    """A PNG's pixel dimensions, read straight out of its IHDR."""
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SmokeFailure(f"{path} is not a PNG, so it cannot be a still")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _decode_rgb(path: Path) -> bytes:
    """A still's pixels, full resolution, no crop and no reduction."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SmokeFailure(
            f"ffmpeg could not decode {path}: "
            f"{proc.stderr.decode(errors='replace').strip()[:300]}"
        )
    return proc.stdout


def still_difference(one: Path, two: Path, panel: Rect) -> str:
    """Where two stills differ, in the same scope the byte comparison grades.

    Deliberately *not* `gray_frames`: that crops to a rect and reduces to
    160x90, so beside a whole-file hash it answers a different question and
    reads ~0 for almost any answer to the one that was asked. Issue #185 is
    what that costs. A real 69-pixel difference — the recorder's cursor dot,
    at the top-left corner of the frame — was reported as "0.00 mean luma over
    the entropy panel", because the panel starts 160 px to the right of the
    dot and could not have contained it. Three CI runs and a bisect of `main`
    went into a difference the diagnostic had ruled out by construction. Two
    further traps in the same line: the reduction to 160x90 flattens a whole
    turn of the spinner to 0.76 even when the difference *is* in the panel,
    and a mean over 14 400 cells cannot distinguish a few loud pixels from
    none at all.

    So: whole frame, native resolution, and both scopes stated — how much
    differs, where, and how much of it is inside the thing this take exists to
    grade. The one distinction the old line could never draw is drawn first:
    identical pixels behind differing bytes is a PNG *encoding* difference and
    not a picture difference, and the two want opposite fixes.
    """
    wide, high = png_size(one)
    if (wide, high) != png_size(two):
        return (
            f"the two stills are not the same size ({wide}x{high} against "
            f"{png_size(two)[0]}x{png_size(two)[1]}), so no pixel of one "
            f"corresponds to a pixel of the other"
        )
    first, second = _decode_rgb(one), _decode_rgb(two)
    if first == second:
        return (
            f"all {wide * high} decoded pixels are identical — the difference "
            f"is in the PNG encoding and not in the picture, so nothing that "
            f"was recorded changed"
        )
    stride = wide * 3
    xs: list[int] = []
    ys: list[int] = []
    worst = 0
    for y in range(high):
        row_a = first[y * stride : (y + 1) * stride]
        row_b = second[y * stride : (y + 1) * stride]
        if row_a == row_b:
            continue
        for x in range(wide):
            i = x * 3
            if row_a[i : i + 3] != row_b[i : i + 3]:
                xs.append(x)
                ys.append(y)
                worst = max(
                    worst,
                    max(
                        abs(p - q)
                        for p, q in zip(row_a[i : i + 3], row_b[i : i + 3], strict=True)
                    ),
                )
    px, py, pw, ph = panel
    inside = sum(
        1
        for x, y in zip(xs, ys, strict=True)
        if px <= x < px + pw and py <= y < py + ph
    )
    return (
        f"{len(xs)} of {wide * high} pixels differ, bounded by x "
        f"{min(xs)}-{max(xs)} and y {min(ys)}-{max(ys)}, largest channel "
        f"delta {worst}; {inside} of them are inside the entropy panel at x "
        f"{px}-{px + pw}, y {py}-{py + ph}, and {len(xs) - inside} are not"
    )


def _plant_mp4(path: Path) -> bytes:
    """A small, real, decodable mp4 at `path`. Returns its bytes.

    Exists for one assertion, and that assertion could not fail without it.
    `beat_frames()` returns `skipped = "there is no demo.mp4 to extract frames
    from"` **before** it creates `frames/`, so on a take that was refused —
    which never converts its webm — "no review frames survived" was true no
    matter what the exit path did. Removing the `if clean:` guard that is
    supposed to keep frames off a refused take changed nothing observable:
    there was nothing to extract from either way. Planting a real recording
    first makes the guard the only thing standing between the refusal and a
    `frames/` directory, which is what the check claims to be grading.

    Deliberately not a stub of arbitrary bytes: `beat_frames()` writes its two
    manifests even when every extraction fails, so a stub would prove the
    directory appeared rather than that frames of a video were taken out of it.
    """
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:s=320x180:d=2:r=25",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


def _segment_parts(out_dir: Path) -> list[str]:
    """Everything on disk a segment owns, by name."""
    return sorted(p.name for p in out_dir.glob("*.seg.*"))


def _probe_beat(doc: dict, text: str, segment: str | None = None) -> dict | None:
    """The beat that set `text`, in a segment's own log or the merged one."""
    for beat in doc.get("beats") or []:
        if beat.get("verb") != "caption" or beat.get("caption") != text:
            continue
        if segment is None or beat.get("segment") == segment:
            return beat
    return None


def check_merge_offset(
    out_dir: Path,
    frame_size: tuple[int, int],
    clocks: list[HostClock] | None = None,
) -> list[str]:
    """#7's acceptance criterion, per segment, with capture loss cancelled.

    Every segment carries a caption with a quiet run-up (`SEGMENT_PROBES`), and
    each one is timed **twice**: in that segment's own `.seg.mp4` against that
    segment's own beat log, and in the stitched `demo.mp4` against the merged
    one. `stitch()` copies the streams, so those are literally the same frames
    carrying the same screencast capture loss — the *difference* between the
    two skews is `offset_true - offset_recorded` for that segment, and nothing
    else.

    **One probe per segment, not one per demo.** Timing only the last
    segment's caption measures only the last cumulative offset: a constant
    shift applied to segment one's beats leaves the final offset exact and
    goes unseen, and with three or more segments every intermediate offset has
    no pixel measurement at all. Injecting +350 ms onto segment one passed
    this file when it timed one beat.

    Each segment's own skew is graded too, against the same directional bars a
    single take gets. That is the half the differential cannot see: it cancels
    capture loss on purpose, so a segment whose *own* video has slid away from
    its *own* beat log — a stall, or a bad clock — divides out of it exactly.
    Together they say where the merge put a beat and where the recording put
    it, separately, per capture.

    Deliberately *not* computed from the durations the merge wrote down: that
    would be the harness re-doing the recorder's arithmetic and agreeing with
    it. This reads pixels out of two videos.
    """
    band = caption_probe_band("segments", frame_size)
    demo = out_dir / "demo.mp4"
    merged_json = out_dir / "timeline.json"
    failures: list[str] = []
    # One reading comes out of the part and one out of the stitched demo, but
    # they are the same frames of the same capture, so the same wall-clock
    # steps moved both (issue #215). Correcting them by the same amount leaves
    # the differential below exactly where it was and makes each segment's own
    # skew — the half the differential cancels on purpose — mean something.
    per_segment = dict(zip(SEGMENT_NAMES, clocks or [], strict=False))

    for name, text in zip(SEGMENT_NAMES, SEGMENT_PROBES, strict=True):
        part = out_dir / f"{name}.seg.mp4"
        segment_json = out_dir / f"{name}.seg.timeline.json"
        # Reported rather than raised: this runs after a keep_parts=True
        # stitch, so a file missing here is one that stitch already failed to
        # keep, and crashing on it would bury the failure that explains why.
        missing = [
            p.name for p in (part, demo, segment_json, merged_json) if not p.is_file()
        ]
        if missing:
            failures.append(
                f"segments: {missing!r} is not on disk after "
                f"stitch(keep_parts=True), so {name}'s beats cannot be measured "
                f"against the segment they came from"
            )
            continue
        alone = _probe_beat(json.loads(segment_json.read_text()), text)
        stitched = _probe_beat(json.loads(merged_json.read_text()), text, name)
        if alone is None or stitched is None:
            failures.append(
                f"segments: {name}'s probe caption {text!r} is logged in "
                f"{segment_json.name}={alone is not None} / the merged timeline "
                f"(as a {name} beat)={stitched is not None} — it has to be in "
                f"both for that segment's offset to be measurable at all"
            )
            continue
        if alone.get("segment_index") != stitched.get("segment_index"):
            failures.append(
                f"segments: {name}'s probe caption is beat "
                f"{alone.get('segment_index')!r} of {name} in that segment's own "
                f"log but {stitched.get('segment_index')!r} in the merged one — "
                f"the two files disagree about which beat this is"
            )
            continue

        readings: dict[str, float] = {}
        segment_clock = per_segment.get(name)
        shift = (
            segment_clock.before(float(alone["t_start"]))
            if segment_clock and isinstance(alone.get("t_start"), (int, float))
            else 0.0
        )
        # The stitched reading corrects with the **artifact's** own answer,
        # rebuilt from the merged timeline.json alone, where the part's
        # reading corrects with this harness's. That asymmetry is the point of
        # issue #225: `stitch()` deletes the parts, so a consumer has only the
        # merged record, and the differential below is what says the two agree.
        # On a host whose clock never stepped both are zero and this measures
        # exactly what it measured before — the merge's offset arithmetic.
        merged_shift = merged_clock_correction(
            json.loads(merged_json.read_text()).get("capture_clock"), stitched
        )
        for what, media, t_start, correction in (
            ("in its own segment", part, alone.get("t_start"), shift),
            ("in the stitched demo", demo, stitched.get("t_start"), merged_shift),
        ):
            if not isinstance(t_start, (int, float)):
                readings.clear()
                failures.append(f"segments: {name}'s probe has no t_start {what}")
                break
            # The same frames, moved by the same steps — this segment's, not
            # the demo's running total. What differs between the two readings
            # is *who says so*: the part is corrected by this harness's own
            # measurement, the stitched demo by what its merged timeline.json
            # tells a reader who has nothing else (issue #225).
            seen_at, note = caption_appearance_s(
                "segments", media, band, float(t_start) + correction
            )
            if seen_at is None:
                readings.clear()
                failures.append(
                    f"segments: {name}'s probe caption could not be timed {what} "
                    f"({media.name}) — {note}"
                )
                break
            readings[what] = seen_at - float(t_start) - correction
        if len(readings) != 2:
            continue

        own, joined = readings["in its own segment"], readings["in the stitched demo"]
        error = joined - own
        if abs(error) > MAX_MERGE_OFFSET_ERROR_S:
            failures.append(
                f"segments: {name}'s probe caption sits {own * 1000:+.0f} ms off "
                f"its beat in {part.name} but {joined * 1000:+.0f} ms off it in "
                f"demo.mp4 — the merge moved that beat {error * 1000:+.0f} ms "
                f"away from the frame it names, past the "
                f"{MAX_MERGE_OFFSET_ERROR_S * 1000:.0f} ms bar. Both readings are "
                f"of the same frames, so capture loss (issue #18) cancels here "
                f"and what is left is what the merged artifact says about "
                f"{name}: its offset, which must be the parts' real ffprobe "
                f"durations in order, and the merged `capture_clock` the "
                f"stitched reading above was corrected by (issue #225)."
            )
            continue
        # The other half, per capture: this segment's own video against this
        # segment's own log, on the same directional bars a single take gets.
        # The differential above divides this out by construction.
        if own > MAX_LOG_EARLY_S or own < -MAX_CAPTURE_LOSS_S:
            # Which end to name is the same question `check_timeline` asks,
            # and it has the same two answers: a negative skew is capture
            # loss, and a positive one is the beat log *only* on a take whose
            # clock held still (issue #257).
            which = (
                log_early_causes(segment_clock, float(alone["t_start"]))
                if own > MAX_LOG_EARLY_S
                else "The video is ahead of the log, which is capture loss "
                "(issues #18 and #215)."
            )
            failures.append(
                f"segments: {name}'s probe caption is {own * 1000:+.0f} ms off "
                f"its beat *within {part.name}*, outside the "
                f"{-MAX_CAPTURE_LOSS_S * 1000:.0f}…{MAX_LOG_EARLY_S * 1000:+.0f} ms "
                f"a single capture is allowed, with the host's measured "
                f"wall-clock steps already taken out. The merge is not "
                f"involved — this segment's own beat log and its own video "
                f"disagree. {which}"
            )
            continue
        print(
            f"smoke: segments {name}'s probe caption is {error * 1000:+.0f} ms "
            f"from where its own segment puts it ({own * 1000:+.0f} ms in "
            f"{part.name}, {joined * 1000:+.0f} ms in demo.mp4)"
        )
    return failures


def stitch_segments(
    out_dir: Path,
    frame_size: tuple[int, int],
    clocks: list[HostClock] | None = None,
) -> list[str]:
    """Stitch the recorded segments, twice, and grade what that produced.

    Twice because `keep_parts` has two directions and both are load-bearing:
    the first stitch must leave every part *and its beat log* behind, since
    re-stitching after re-recording one expensive segment is the entire reason
    that flag exists — and the second, at the default, must take them away
    together. A `.seg.timeline.json` outliving its `.seg.mp4` is issue #21: it
    names a file that no longer exists, and the next stitch cannot tell that
    stale log from a fresh one.

    The merged timeline itself is graded by `check_timeline()`, the same
    function that grades a single take. What is here is only what is true of a
    merge and of nothing else.
    """
    from demo_recording import stitch
    from demo_recording.content import media_duration

    failures: list[str] = []
    demo = out_dir / "demo.mp4"
    merged_json = out_dir / "timeline.json"

    # -- what the segments left behind, before any of it is merged -----------
    before = _segment_parts(out_dir)
    wanted = sorted(
        f"{name}.seg.{suffix}"
        for name in SEGMENT_NAMES
        for suffix in ("mp4", "timeline.json", "timeline.md")
    )
    if before != wanted:
        return [
            f"segments: after recording, the take directory holds {before!r}, "
            f"expected {wanted!r} — each segment writes its own mp4 and its own "
            f"beat log beside it, and the merge below has nothing to read "
            f"otherwise"
        ]
    if demo.exists() or merged_json.exists():
        failures.append(
            f"segments: {demo.name}/{merged_json.name} exist before stitch() "
            f"was called — every assertion below would be grading a file this "
            f"run did not produce"
        )

    # A segment's beats are relative to that segment's own start. Asserted
    # before the merge so that the merged timestamps being large means
    # something: if the second segment's log already started at 8 s, a stitch
    # that offset nothing at all would look exactly like a correct one.
    durations: list[float] = []
    segment_docs: list[dict] = []
    for name in SEGMENT_NAMES:
        part = out_dir / f"{name}.seg.mp4"
        durations.append(media_duration(part))
        doc = json.loads((out_dir / f"{name}.seg.timeline.json").read_text())
        segment_docs.append(doc)
        if doc.get("segment") != name or doc.get("media") != part.name:
            failures.append(
                f"segments: {name}.seg.timeline.json says segment "
                f"{doc.get('segment')!r} / media {doc.get('media')!r}, expected "
                f"{name!r} / {part.name!r}"
            )
        first = (doc.get("beats") or [{}])[0].get("t_start")
        if not isinstance(first, (int, float)) or first > MAX_UNMERGED_FIRST_BEAT_S:
            failures.append(
                f"segments: {name}.seg.timeline.json's first beat starts at "
                f"{first!r}s, which is not a timestamp relative to that "
                f"segment's own start — the merge below is then unmeasurable"
            )
    print(
        f"smoke: segments recorded {len(SEGMENT_NAMES)} parts, each with its "
        f"own beat log ("
        + ", ".join(
            f"{n} {d:.1f}s" for n, d in zip(SEGMENT_NAMES, durations, strict=True)
        )
        + ")"
    )

    # -- keep_parts=True: the parts and their logs both survive ---------------
    stitch(out_dir, SEGMENT_NAMES, keep_parts=True)
    kept = _segment_parts(out_dir)
    if kept != wanted:
        # A hard stop: everything below re-reads the parts, and "they were
        # deleted" is the answer, not a second failure about their contents.
        return failures + [
            f"segments: stitch(keep_parts=True) left {kept!r}, expected the "
            f"parts untouched ({wanted!r}) — re-recording one segment and "
            f"re-stitching is what that flag is for, and it needs the beat logs "
            f"as much as the mp4s"
        ]
    if not merged_json.is_file():
        return failures + [
            "segments: stitch() wrote no timeline.json next to demo.mp4 — the "
            "segments' beat logs were not merged at all"
        ]
    first_merge = json.loads(merged_json.read_text())

    # While the parts are still here: the acceptance criterion, measured
    # against both videos so the screencast's own error cancels.
    failures += check_merge_offset(out_dir, frame_size, clocks)

    # -- the default: parts and logs go together (issue #21) ------------------
    stitch(out_dir, SEGMENT_NAMES)
    left = _segment_parts(out_dir)
    if left:
        failures.append(
            f"segments: after stitch() at the default keep_parts=False, "
            f"{left!r} are still on disk. A .seg.timeline.json whose .seg.mp4 "
            f"has been deleted names a file that no longer exists, and the next "
            f"stitch cannot tell it from a fresh one (issue #21)"
        )
    second_merge = json.loads(merged_json.read_text())
    if second_merge.get("beats") != first_merge.get("beats"):
        failures.append(
            "segments: re-stitching the same parts produced different beats — "
            "the merge is not a function of what is on disk, so a re-stitch "
            "after re-recording one segment cannot be trusted"
        )

    # What a consumer of the stitched artifact can do about the clock its
    # video is on — graded here, after the parts and their own logs are gone,
    # because that is the state a reader of demo.mp4 finds it in (issue #225).
    # The offsets are the ffprobe durations measured above, before the merge,
    # not the ones the file being graded wrote down.
    if clocks:
        offsets: list[float] = []
        running = 0.0
        for probed in durations:
            offsets.append(running)
            running += probed
        failures += check_merged_capture_clock(
            out_dir,
            [
                (name, clock, offset, doc.get("capture_clock"))
                for name, clock, offset, doc in zip(
                    SEGMENT_NAMES, clocks, offsets, segment_docs, strict=True
                )
            ],
        )

    # -- every field of the records the merge wrote, against its sources ------
    #
    # All six, not the two that are interesting. `beats`, `recorder` and
    # `determinism` are what SKILL.md tells a reader to fall back to when the
    # top level says "mixed" or null, so an unasserted one is a documented
    # source of truth that nothing checks: both were injected — `beats`
    # hardcoded to 0, `recorder` to "Bogus" — and the suite passed.
    records = second_merge.get("segments")
    if not isinstance(records, list) or len(records) != len(SEGMENT_NAMES):
        failures.append(
            f"segments: the merged timeline's `segments` is {records!r}, "
            f"expected one record per part in order — it is what maps a "
            f"merged timestamp back to the file it came from"
        )
        return failures
    offset = 0.0
    for record, name, probed, doc in zip(
        records, SEGMENT_NAMES, durations, segment_docs, strict=True
    ):
        if record.get("segment") != name or record.get("media") != f"{name}.seg.mp4":
            failures.append(
                f"segments: merged `segments` record {record!r} is not part "
                f"{name!r} — the parts are listed out of order, or renamed"
            )
        for field, wanted_value in (("duration", probed), ("offset", offset)):
            value = record.get(field)
            if (
                not isinstance(value, (int, float))
                or abs(value - wanted_value) > SEGMENT_OFFSET_TOLERANCE_S
            ):
                failures.append(
                    f"segments: merged `segments` says {name} {field} "
                    f"{value!r}s; ffprobe makes it {wanted_value:.3f}s. The "
                    f"offsets have to be the encoder's own durations — nominal "
                    f"storyboard timing puts every later beat past its frame "
                    f"(issue #18)"
                )
        # Carried over from the segment's own log, so it is graded against that
        # log rather than against a number this file made up. `beats` is
        # checked against the segment's beat count *and* against how many of
        # that segment's beats actually reached the merged list — the two can
        # only differ if the merge dropped or duplicated some.
        merged_from_segment = sum(
            1 for b in (second_merge.get("beats") or []) if b.get("segment") == name
        )
        for field, wanted_value in (
            ("beats", len(doc.get("beats") or [])),
            ("recorder", doc.get("recorder")),
            ("determinism", doc.get("determinism")),
        ):
            if record.get(field) != wanted_value:
                failures.append(
                    f"segments: merged `segments` says {name} {field} "
                    f"{record.get(field)!r}, but {name}.seg.timeline.json says "
                    f"{wanted_value!r} — SKILL.md points a reader at these "
                    f"records for exactly the per-segment truth the top-level "
                    f"envelope cannot carry once segments disagree"
                )
        if record.get("beats") != merged_from_segment:
            failures.append(
                f"segments: merged `segments` says {name} contributed "
                f"{record.get('beats')!r} beats, but {merged_from_segment} beats "
                f"in the merged list carry that segment"
            )
        offset += probed

    total = media_duration(demo) if demo.is_file() else 0.0
    if abs(total - offset) > SEGMENT_OFFSET_TOLERANCE_S:
        failures.append(
            f"segments: the parts are {offset:.2f}s of video between them but "
            f"demo.mp4 is {total:.2f}s — the offsets do not tile the stitched "
            f"video, so beats in the last segment cannot line up with it"
        )
    if not failures:
        print(
            f"smoke: segments stitched {len(SEGMENT_NAMES)} parts into a "
            f"{total:.1f}s demo.mp4 and merged their beat logs "
            f"({len(second_merge.get('beats') or [])} beats); keep_parts=True "
            f"kept every part and its log, the default removed them"
        )
    return failures


def mean_dbfs(mp4: Path, start: float, seconds: float) -> float | None:
    """Mean volume of one window of the mp4's audio, in dBFS.

    `None` when ffmpeg reported no measurement at all, which is a different
    failure from a quiet window and is reported as one.
    """
    done = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-ss",
            f"{start}",
            "-t",
            f"{seconds}",
            "-i",
            str(mp4),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", done.stderr)
    return float(match.group(1)) if match else None


def loud_spans(mp4: Path, duration: float) -> list[tuple[float, float]] | None:
    """(start, end) of every stretch of `mp4` that carries audio.

    Read off the encoded file with `silencedetect` and complemented here, so
    what comes back is where a clip really is rather than where anything says
    it is. `None` when ffmpeg produced no silence report at all — a
    measurement that failed is not a file with no audio in it, and the two
    must not arrive as the same answer.

    **`-v info`, deliberately.** `silencedetect` writes through ffmpeg's
    logger at INFO level, and `-v error` throws it away — which would make
    this function return "one span covering the whole file" on every take,
    silently, forever.
    """
    done = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
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
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", done.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", done.stderr)]
    if not starts and not ends:
        return None
    # Every silence as a closed interval, then the gaps between them. A file
    # that opens loud has no `silence_start` at 0; one that ends loud has a
    # trailing `silence_start` with no `silence_end`, which closes at the
    # duration.
    silences = [
        (start, ends[i] if i < len(ends) else duration)
        for i, start in enumerate(starts)
    ]
    spans: list[tuple[float, float]] = []
    at = 0.0
    for start, end in silences:
        if start - at > NARRATION_SILENCE_MIN_S:
            spans.append((round(at, 3), round(start, 3)))
        at = max(at, end)
    if duration - at > NARRATION_SILENCE_MIN_S:
        spans.append((round(at, 3), round(duration, 3)))
    return spans


def expected_loud_spans(
    starts: list[float], lengths: list[float], gap: float = NARRATION_SILENCE_MIN_S
) -> list[tuple[float, float, tuple[int, ...]]]:
    """Where the clips should be audible in the mix, overlaps merged.

    Returns `(start, end, the lines that span covers)`. **The membership is
    load-bearing twice.** A span built from one clip can still be graded on
    that clip's *duration* — two errors that cancel, an onset 110 ms early
    against a clip 250 ms too long, satisfy an end-of-span bar and not a
    duration one. And a failure has to name the line the reader should go and
    listen to: with three lines and one merged pair, the second span is line 2
    and calling it "line 1" sends them to the wrong clip.

    **Not one span per clip**, and the difference is the phenomenon this arm
    exists for. A backward wall-clock step shortens the *video* and not the
    *audio*: the recorder waited line 0's clip out in monotonic time, but the
    seconds the step deleted are not in the file to wait through, so a mix
    corrected onto the video's clock can start line 1 while line 0 is still
    playing. The two then sum into one continuous stretch, which is what
    `silencedetect` reports and therefore what this has to predict.

    Measured on a real stepped take of this arm, 2026-08-09: a −1.073 s step at
    2.214 s put line 1's onset at 2.228 s, inside line 0's 1.028–2.628 s clip,
    and `demo.mp4` carried **one** stretch for two lines. A model of "two lines,
    two stretches" fails that take — the correction was right and the harness
    was wrong, which is the direction that costs a real defect its diagnosis.

    Written as a pure function so `tests/unit` can grade the overlap case,
    which no box produces on demand.
    """
    spans: list[tuple[float, float, tuple[int, ...]]] = []
    ordered = sorted(
        enumerate(zip(starts, lengths, strict=True)), key=lambda pair: pair[1][0]
    )
    for index, (start, length) in ordered:
        if spans and start - spans[-1][1] <= gap:
            first, end, members = spans[-1]
            spans[-1] = (first, max(end, start + length), (*members, index))
        else:
            spans.append((start, start + length, (index,)))
    return [(round(a, 3), round(b, 3), members) for a, b, members in spans]


def _crash_dump(out_dir: Path) -> tuple[dict | None, str]:
    """(failure/failure.json, the reason it is missing)."""
    path = out_dir / "failure" / "failure.json"
    if not path.is_file():
        return None, f"{path} was never written"
    try:
        return json.loads(path.read_text()), ""
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"{path} is not valid JSON: {exc}"


def _erroring_beats(doc: dict) -> list[dict]:
    return [b for b in (doc.get("beats") or []) if "error" in b]


@contextmanager
def only_one_suite(allow_concurrent: bool) -> Iterator[None]:
    """Hold the machine-wide suite lock, or refuse."""
    handle = open(SMOKE_LOCK, "w")  # noqa: SIM115 - held for the whole run
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            others = subprocess.run(
                ["pgrep", "-af", "smoke"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            mine = str(os.getpid())
            lines = [
                ln
                for ln in others.splitlines()
                if "tests/smoke" in ln and not ln.startswith(f"{mine} ")
            ]
            print(
                f"smoke: ANOTHER RUN HOLDS {SMOKE_LOCK}.\n"
                f"  Two suites on one machine share the CPU and the software "
                f"encoder, and the timing bars in this file (REDACT_DURATION_S, "
                f"MAX_BLANK_RUN_S) fail on a recorder that is working — see "
                f"issue #78. A red run under contention is worse than no run.\n"
                + (
                    "  Looks like: " + "\n               ".join(lines) + "\n"
                    if lines
                    else "  (pgrep found no other tests/smoke; the holder may "
                    "have a different command line.)\n"
                )
                + "  Wait for it, or pass --allow-concurrent if you know the "
                "other run is not recording.",
                file=sys.stderr,
            )
            if not allow_concurrent:
                raise SmokeFailure(
                    "refusing to run a second smoke suite on this machine"
                ) from None
        yield
    finally:
        handle.close()


def out_roots_to_reap(
    entries: list[tuple[Path, float]],
    now: float,
    keep: int = KEEP_OUT_ROOTS,
    min_age_s: float = REAP_MIN_AGE_S,
) -> list[Path]:
    """Which previous runs' directories this run may remove.

    Pure, and separated from the filesystem for exactly that reason: the
    interesting behaviour is the budget arithmetic, and a test that had to
    stage real directories with faked mtimes would grade the staging.
    """
    young = [(p, m) for p, m in entries if now - m < min_age_s]
    old = sorted(
        ((p, m) for p, m in entries if now - m >= min_age_s),
        key=lambda pm: pm[1],
        reverse=True,
    )
    room = max(0, keep - len(young))
    return [p for p, _ in old[room:]]


def reap_previous_out_roots() -> None:
    """Apply `out_roots_to_reap` to this host's temp directory."""
    entries: list[tuple[Path, float]] = []
    for path in Path(tempfile.gettempdir()).glob("demo-video-smoke-*"):
        try:
            if path.is_dir():
                entries.append((path, path.stat().st_mtime))
        except OSError:
            continue  # vanished under us, or not ours to read
    for stale in out_roots_to_reap(entries, time.time()):
        shutil.rmtree(stale, ignore_errors=True)


def open_output(args: argparse.Namespace) -> tuple[Path, bool]:
    """This run's output directory, and whether the run owns it.

    Called from **inside** `only_one_suite()`, which is the whole of issue
    #105: a run the lock refuses has not started, and a directory it will
    never write to is not evidence of anything. Creating it first left an
    empty `/tmp/demo-video-smoke-*` behind for every refused run — 85 of them,
    80 MB, over three days of ordinary work — and named it in a
    `recordings left in` line printed directly under `smoke: FAILED`.
    """
    if args.out_dir:
        out_root = args.out_dir.resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        return out_root, False
    # Before this run's own directory exists, so it is never a candidate.
    reap_previous_out_roots()
    return Path(tempfile.mkdtemp(prefix="demo-video-smoke-")), True
