"""The suite's assertion functions, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from _pixels import (
    Rect,
    card_run,
    card_strip,
    channels_apart,
    contrast,
    frame_difference,
    gray_frames,
    psnr_db,
    strip_rgb,
)

from .constants import (  # noqa: E402
    _CAPTION_JS,
    _CURSOR_BOX_JS,
    _MD_ROW,
    _PAGE_STATE_JS,
    BEAT_ORDER_SLACK_S,
    CAMERA_AFTER_S,
    CAMERA_CENTRE_BAR_PX,
    CAMERA_MIN_EVENT_S,
    CAMERA_PUSH_MIN,
    CAMERA_STILL_MAX,
    CAMERA_STRIP_MIN_H,
    CAPTION_PROBE,
    CLOCK_PROBE_ARMS,
    CLOCK_PROBE_S,
    CLOCK_SAFE_ARMS,
    CONTENT_COMMANDS,
    CONTENT_COVERED_FRACTION,
    CONTENT_KEEP,
    CONTENT_PSNR_GAP_DB,
    CONTENT_RECT_SLACK_PX,
    CONTENT_SAMPLE_FPS,
    CONTENT_SCORE_HEADROOM,
    CONTENT_STATIC_HEADROOM,
    CONTENT_STATIC_MARGIN,
    CONTENT_TAKES,
    CONTENT_TOURED,
    COVERAGE_CARD,
    COVERAGE_CRITERIA,
    COVERAGE_UNCLAIMED,
    DURATION_TOLERANCE_S,
    ENTROPY_GAP_S,
    ENTROPY_SHOTS,
    EVIDENCE_CLIPPED_TEXT,
    EVIDENCE_DIR_NAME,
    EVIDENCE_HIDDEN_TEXT,
    EVIDENCE_INVISIBLE_TEXT,
    EVIDENCE_RICH_TEXT,
    EVIDENCE_SCHEMA_EXPECTED,
    EVIDENCE_UNPAINTED_TEXT,
    FLATTENED_S,
    FRAME_CAPTION_GUARD_S,
    FROZEN_CLOCK,
    FROZEN_EPOCH_MS,
    FROZEN_ISO,
    FROZEN_LOCALE,
    FROZEN_TIMEZONE,
    HOST_CLOCK_MAX_GAP_S,
    HOST_CLOCK_MIN_STEP_S,
    LOCK_CHILD_TIMEOUT_S,
    MAX_CAPTURE_LOSS_S,
    MAX_CLOCK_RECORD_DISAGREEMENT_S,
    MAX_CLOCK_STEP_TIME_DISAGREEMENT_S,
    MAX_CROSS_SEGMENT_DRIFT_S,
    MAX_FRAME_PLACEMENT_S,
    MAX_LIVE_CLOCK_SKEW_MS,
    MAX_LOG_EARLY_S,
    MAX_SKEW_DRIFT_S,
    MIN_ALIGN_BAND_DELTA,
    MIN_BEAT_TIME_COVERAGE,
    MIN_CAPTION_BAND_DIFF,
    MIN_CLEAR_OVER_CLICK_S,
    MIN_CONTENT_STDDEV,
    MIN_GRADED_CAPTION_FRAMES,
    MIN_HELD_BEAT_SPAN_S,
    MIN_MP4_BYTES,
    MIN_OPENING_CARD_S,
    MIN_OPENING_FRAMES,
    MIN_PNG_BYTES,
    MIN_PRESS_BEAT_SPAN_S,
    MIN_SPOTLIGHT_MID_FRAMES,
    MIN_STILL_DIFF,
    NARRATION_CHANNELS,
    NARRATION_CODEC,
    NARRATION_LINES,
    NARRATION_LONG_LINE,
    NARRATION_LONG_S,
    NARRATION_LOUD_DBFS,
    NARRATION_ONSET_TOLERANCE_S,
    NARRATION_QUIET_DBFS,
    NARRATION_SAMPLE_RATE,
    NARRATION_SHORT_LINE,
    NARRATION_SHORT_S,
    NARRATION_SPAN_TOLERANCE_S,
    NARRATION_WINDOW_S,
    OPENING_BARE_MIN_LUMA,
    OPENING_CARD_AGREEMENT,
    OPENING_CARD_MAX_LUMA,
    OPENING_FIRST_FRAME_S,
    OPENING_HOLD_S,
    OPENING_SAMPLE_FPS,
    OVERLAY_CLEARED_MAX_RATIO,
    OVERLAY_SCRIM_MIN_DIFF,
    OVERLAY_TAKES,
    PROBE_ANIMATION_S,
    PROBE_CAPTION,
    PROBE_TRANSITION_S,
    SCENE_WINDOW_PAD_S,
    SMOKE_LOCK,
    SPOTLIGHT_MID_BAND,
    SPOTLIGHT_MIN_TOTAL,
    SPOTLIGHT_TARGET,
    SPOTLIGHT_WINDOW_S,
    STILLS_DECLARED_HOLD_S,
    STILLS_PACING_BUDGET_S,
    STRICT_BEAT_RE,
    SYNTHETIC_PAINT_AT,
    SYNTHETIC_SLACK_S,
    TERMINAL_REVEAL_MIN_STDDEV,
    WEB_PRESS_KEYS,
    WRAPPER_APP_CONTROL_S,
    WRAPPER_APP_MAX_DELTA,
    WRAPPER_APP_SAMPLE_S,
    WRAPPER_BAND_LIT,
    WRAPPER_BAND_MIN_S,
    WRAPPER_BAND_SWEEP_FPS,
    WRAPPER_BAND_UNLIT,
    WRAPPER_BARE_MIN_LUMA,
    WRAPPER_CAPTION,
    WRAPPER_CARD_CONTROL_MIN_GAP,
    WRAPPER_CARD_EDGE_TRIM,
    WRAPPER_CARD_FRACTIONS,
    WRAPPER_CARD_LOCATE_MAX_LUMA,
    WRAPPER_CARD_MIN_DOWN_S,
    WRAPPER_CARD_MIN_STRETCH_S,
    WRAPPER_CARD_SWEEP_FPS,
    WRAPPER_CARD_WINDOW_TOLERANCE,
    WRAPPER_FIRST_FRAME_S,
    WRAPPER_HOLD_MAX_LUMA,
    WRAPPER_LONG_CAPTION,
    WRAPPER_SECOND_MAX_LUMA,
    WRAPPER_SECOND_MIN_FRAMES,
    WRAPPER_SECOND_MIN_LUMA,
    WRAPPER_SURVIVES,
    WRAPPER_SURVIVES_SAMPLES_S,
    WRAPPER_UNREACHED,
)
from .support import (  # noqa: E402
    Beats,
    EntropyTake,
    HostClock,
    _crash_dump,
    _criterion_page_failures,
    _erroring_beats,
    _synthetic_take,
    beat_midpoints,
    blanked_copy,
    caption_appearance_s,
    caption_probe_band,
    clock_probe_report,
    content_of,
    content_rects,
    crop_png,
    digest,
    evidence_docs,
    evidence_screen_text,
    expected_loud_spans,
    frame_at,
    hole_clause,
    keep_top,
    log_early_causes,
    longest_true_run,
    loud_spans,
    mean_dbfs,
    probe_wall_clock,
    screens_differ,
    still_difference,
    video_fps,
    wrapper_pad_band,
)


def check_clock_before_recording(
    only: str | None, allow: bool, window_s: float = CLOCK_PROBE_S
) -> list[str]:
    """Refuse the timing arms on a host whose wall clock steps (issue #370).

    Returns the refusal as failure lines, or `[]` to carry on. A full run
    (`only is None`) is probed too: it reaches all three timing phases.
    """
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
        # The probe's own sampler stalled. Saying "steady" here would be the
        # catalogue's environment-agreeing assertion: a watcher that was away
        # cannot report what it did not watch.
        print(
            f"smoke: the clock probe's sampler left a {clock.max_gap * 1000:.0f} ms "
            f"gap, over its own {HOST_CLOCK_MAX_GAP_S * 1000:.0f} ms limit — it "
            f"cannot say whether the clock held still, so it says nothing and "
            f"the run goes ahead.",
            flush=True,
        )
        return []
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


def _check_clock_coverage(
    label: str, name: str, record: dict, clock: HostClock
) -> list[str]:
    """Does `capture_clock` say honestly how well it watched the take?

    Three claims, and the first is the one that had to be added (issue #247):

    1. the record **states** its coverage at all — `measured` is a bool and
       `max_gap` is a number. A record with no coverage claim is a record that
       can be wrong by ten seconds and say nothing;
    2. `measured` **agrees with its own `max_gap`** against the recorder's own
       published limit, so the flag cannot be true while the number that
       decides it says otherwise;
    3. `measured` **agrees with this harness's independent coverage**. This is
       the cross-check that does not share a mechanism: two samplers in two
       processes both stalling on the same take is a real possibility (a
       loaded box), but one stalling for seconds while the other kept a 20 ms
       interval means the stalled one is broken rather than the box is busy.
    """
    stated = record.get("measured")
    gap = record.get("max_gap")
    limit = record.get("max_gap_limit")
    if not isinstance(stated, bool):
        return [
            f"{label}: {name}'s capture_clock has no `measured` flag "
            f"({stated!r}). A wall-clock record that cannot say whether it "
            f"watched the take is one a consumer corrects a beat timestamp "
            f"with and cannot check (issue #247)"
        ]
    numeric = (
        isinstance(gap, (int, float))
        and not isinstance(gap, bool)
        and isinstance(limit, (int, float))
        and not isinstance(limit, bool)
    )
    if not numeric:
        return [
            f"{label}: {name}'s capture_clock states max_gap={gap!r} against "
            f"limit={limit!r} — the two numbers `measured` is derived from, "
            f"and without them the flag is an assertion rather than a "
            f"measurement"
        ]
    if stated != (gap <= limit):
        return [
            f"{label}: {name}'s capture_clock says measured={stated} while "
            f"its own max_gap is {gap:.3f}s against a {limit:.3f}s limit. The "
            f"flag and the number that decides it disagree, and the flag is "
            f"what a consumer reads"
        ]
    if stated and not clock.covered:
        return [
            f"{label}: {name}'s capture_clock claims it measured this take "
            f"(max_gap {gap:.3f}s) while this harness's own sampler was away "
            f"for up to {clock.max_gap:.3f}s over the same take. One of the "
            f"two was not watching, and the recorder's is the one whose "
            f"number ships in the artifact"
        ]
    if not stated and clock.covered:
        return [
            f"{label}: {name}'s capture_clock refuses to report (max_gap "
            f"{gap:.3f}s, limit {limit:.3f}s) on a take this harness sampled "
            f"cleanly (max gap {clock.max_gap:.3f}s, {clock.samples} "
            f"samples). The host was watchable and the recorder did not watch "
            f"it, so every consumer of this take is told nothing when there "
            f"was something to say"
        ]
    return []


def check_capture_clock(
    label: str, out_dir: Path, clock: HostClock, name: str = "timeline.json"
) -> list[str]:
    """`timeline.json`'s `capture_clock` against this harness's own reading.

    The one assertion that grades the recorder's new field, and the reason the
    corrections elsewhere are not circular: this harness corrects with its own
    numbers, so without this a recorder that stopped sampling would change
    nothing here and `capture_clock` could rot in silence.

    **The window is the storyboard's**, `[0, last t_end]`, and both directions
    are asserted inside it: a step this harness saw must be in the record, and
    a step in the record must have been seen. Outside it the two watchers do
    not cover the same seconds — this one keeps running through conversion,
    which the capture is not part of — so a step out there is neither's error
    and is reported rather than graded.

    **Coverage is graded before content** (issue #247). The version of this
    function that only compared totals passed on takes where both samplers
    reported `+9.09 s` against a truth of `-2.00 s`, because both were trapped
    by the same clock and therefore agreed. What that could not have caught,
    this can: `measured` false when this watcher covered the take, or
    `measured` true when the recorder's own `max_gap` says it did not.
    """
    path = out_dir / name
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{label}: {name} could not be read for capture_clock: {exc}"]
    record = doc.get("capture_clock")
    if not isinstance(record, dict):
        return [
            f"{label}: {name} has no `capture_clock` record. The video is on "
            f"the host's wall clock and the beats are on the monotonic one "
            f"(issues #18, #215); without this field nothing downstream can "
            f"tell a stepped clock from a recorder that mis-stamped a beat"
        ]
    problems = _check_clock_coverage(label, name, record, clock)
    if problems:
        return problems
    if record.get("measured") is not True:
        # Honest, and nothing further is gradeable: the recorder is saying it
        # could not watch the clock, and it has already been checked above
        # that this harness could not either.
        print(
            f"smoke: {label} capture_clock says it could not measure this "
            f"take ({record.get('note')}) — and neither could this harness "
            f"(max gap {clock.max_gap:.2f}s). Nothing to compare"
        )
        return []
    reported = record.get("total")
    if not isinstance(reported, (int, float)):
        return [
            f"{label}: capture_clock.total is {reported!r}, not a number — "
            f"a consumer correcting a beat timestamp with it would get nothing"
        ]
    listed = record.get("steps")
    if not isinstance(listed, list):
        return [
            f"{label}: capture_clock.steps is {listed!r}, not a list — the "
            f"total says how much was lost and only the steps say which beats "
            f"lost it"
        ]
    if abs(sum(float(s.get("delta", 0.0)) for s in listed) - float(reported)) > 0.001:
        return [
            f"{label}: capture_clock.total is {reported!r} but its own steps "
            f"sum to {sum(float(s.get('delta', 0.0)) for s in listed):+.4f} — "
            f"the field disagrees with itself"
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
    inside = (
        f"inside the {horizon:.1f}s the storyboard ran, this harness saw "
        f"{len(mine)} wall-clock step(s) [{clock.describe()}] and "
        f"timeline.json records {len(theirs)}"
    )
    if len(mine) != len(theirs):
        return [
            f"{label}: {inside} — `capture_clock` is not measuring the clock "
            f"the video is on, so every consumer correcting a beat timestamp "
            f"with it is being told the wrong number (issues #18, #215)"
        ]
    for (at, delta), (their_at, their_delta) in zip(
        sorted(mine), sorted(theirs), strict=True
    ):
        if abs(delta - their_delta) > MAX_CLOCK_RECORD_DISAGREEMENT_S:
            return [
                f"{label}: this harness measured a wall-clock step of "
                f"{delta * 1000:+.0f} ms at {at:.1f}s and timeline.json "
                f"records {their_delta * 1000:+.0f} ms at {their_at:.1f}s — "
                f"the same step, two different sizes, and the smaller one is "
                f"what a consumer would correct a beat timestamp by"
            ]
        if abs(at - their_at) > MAX_CLOCK_STEP_TIME_DISAGREEMENT_S:
            return [
                f"{label}: this harness put a {delta * 1000:+.0f} ms "
                f"wall-clock step at {at:.1f}s into the take and "
                f"timeline.json puts it at {their_at:.1f}s. Which beats a "
                f"step applies to is the whole of what the timestamp is for"
            ]
    print(f"smoke: {label} capture_clock agrees with the harness ({clock.describe()})")
    return []


def check_caption(b: Beats, page, expected: str) -> None:
    """Assert the caption the storyboard just set actually reached the screen.

    Captions are this skill's headline feature — the thing a viewer reads. A
    recorder that silently stops drawing them still produces a video that
    satisfies every pixel metric and explains nothing.
    """
    state = page.evaluate(_CAPTION_JS)
    if state is None:
        b.fail_if(True, "no #__demo_caption element exists — caption() drew nothing")
        return
    text, opacity = state
    b.fail_if(text != expected, f"the caption reads {text!r}, expected {expected!r}")
    # Numeric, not string equality: the bar fades over 0.3 s, so a check run
    # right after the call legitimately catches it at 0.0017 rather than 0.
    shown = float(opacity) > 0.5
    b.fail_if(
        shown != bool(expected),
        f"the caption's computed opacity is {opacity} but its text is "
        f"{expected!r} — it is in the DOM and not on screen"
        if expected
        else f"the caption's computed opacity is {opacity}; it should have "
        f"been cleared",
    )


def check_determinism(b: Beats, page, when: str, on: bool = True) -> dict:
    """What the page reports about its clock, its locale, and its motion.

    Asserted from inside the page, never from the recorder's own attributes: a
    constructor that stored `deterministic=True` and then forgot to wire it to
    the context would satisfy any check made on the Python side.
    """
    state = page.evaluate(_PAGE_STATE_JS)

    def wanted(what: str, actual: object, expected: object, why: str) -> None:
        b.fail_if(
            actual != expected,
            f"{when}, {what} is {actual!r}, expected {expected!r} — {why}",
        )

    # Pinned in every take, determinism or not: none of the three changes what
    # an app computes, and all three differ between a laptop and a CI runner.
    wanted(
        "the resolved timezone",
        state["timezone"],
        FROZEN_TIMEZONE,
        "the context's timezone is not pinned, so a recording made in "
        "Tórshavn formats dates differently from one made in CI",
    )
    wanted("the UTC offset", state["offset"], 0, "the timezone is not UTC")
    wanted(
        "the resolved locale",
        state["locale"],
        FROZEN_LOCALE,
        "the context's locale is not pinned, so numbers and dates format "
        "differently between machines",
    )
    wanted("navigator.language", state["language"], FROZEN_LOCALE, "same")
    wanted(
        "prefers-reduced-motion",
        state["reduced"],
        True,
        "the context does not request reduced motion, so an app that honours "
        "it still animates — this one is not gated on `deterministic`",
    )
    # True in both modes: these are identity, not clock readings, and the proxy
    # that freezes the clock is exactly what breaks them.
    wanted(
        "Date.prototype.constructor === Date",
        state["constructorIsDate"],
        True,
        "deep-clone and serialization helpers type-test Date this way, and "
        "misclassify every Date object when it is false",
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
            FROZEN_EPOCH_MS,
            "the page's wall clock is not frozen, so every take renders a "
            "different timestamp",
        )
        wanted(
            "new Date().toISOString()",
            state["iso"],
            FROZEN_ISO,
            "the zero-argument Date constructor is still reading the real "
            "clock even if Date.now() is frozen",
        )
        # Four clocks found running behind a frozen Date.now() in review.
        wanted(
            "Intl.DateTimeFormat().format()",
            state["intl"],
            "01/01/2025, 09:00:00 AM",
            "Intl formats from its own internal clock, which no patch of the "
            "Date global reaches — it is how apps render dates, so it is the "
            "hole that matters most",
        )
        wanted(
            "new Date().constructor.now()",
            state["constructorNow"],
            FROZEN_EPOCH_MS,
            "the prototype's constructor still points at the unfrozen Date, "
            "so one property access reaches the real clock",
        )
        wanted(
            "Object.getOwnPropertyDescriptor(Date, 'now').value()",
            state["descriptorNow"],
            FROZEN_EPOCH_MS,
            "`now` is being synthesized by a proxy trap rather than defined, "
            "so reading the descriptor hands back the real clock",
        )
        wanted(
            "performance.timeOrigin",
            state["timeOrigin"],
            FROZEN_EPOCH_MS,
            "timeOrigin is a wall-clock reading of its own, and "
            "`timeOrigin + performance.now()` is a common way to take one",
        )
        wanted(
            "a probe element's animation-duration",
            state["animation"],
            FLATTENED_S,
            "the recorder's motion rule is not reaching this page, so "
            "animation phase still varies between takes",
        )
        wanted(
            "a probe element's transition-duration",
            state["transition"],
            FLATTENED_S,
            "the recorder's motion rule is not flattening transitions — and "
            "at 0s instead of 1ms no transitionend would ever fire, which "
            "stalls every accordion, modal and wizard that waits for one",
        )
        wanted(
            "an animated ::after's animation-duration",
            state["after"],
            FLATTENED_S,
            "the motion rule does not cover pseudo-elements, and an animated "
            "::after is the most common spinner on the web",
        )
        wanted(
            "an animated ::before's animation-duration",
            state["before"],
            FLATTENED_S,
            "the motion rule does not cover pseudo-elements",
        )
    else:
        # The default. It has to leave the clock alone — not merely skip some
        # of the freezing.
        b.fail_if(
            state["now"] == FROZEN_EPOCH_MS,
            f"{when}, Date.now() still reads the frozen {FROZEN_EPOCH_MS} "
            f"although determinism was not asked for — the page's clock is "
            f"being frozen by default",
        )
        skew = abs(state["now"] - time.time() * 1000)
        b.fail_if(
            skew > MAX_LIVE_CLOCK_SKEW_MS,
            f"{when}, Date.now() reads {state['now']} — {skew / 1000:.0f}s "
            f"from this process's own clock, so the page is not on real time",
        )
        b.fail_if(
            state["intl"].startswith("01/01/2025"),
            f"{when}, Intl.DateTimeFormat().format() reads {state['intl']!r} — "
            f"the frozen instant, without determinism having been asked for",
        )
        wanted(
            "a probe element's animation-duration",
            state["animation"],
            PROBE_ANIMATION_S,
            "the motion rule is injected without determinism having been asked for",
        )
        wanted(
            "a probe element's transition-duration",
            state["transition"],
            PROBE_TRANSITION_S,
            "the motion rule is injected without determinism having been asked for",
        )
        wanted(
            "an animated ::after's animation-duration",
            state["after"],
            "3s",
            "the motion rule is reaching pseudo-elements without determinism "
            "having been asked for",
        )
    return state


def check_undrawn_pointer(b: Beats, page, when: str) -> None:
    """A take that ran no pointer verb shows no cursor dot (#185, #361).

    Separate from the byte comparison it protects, and not dominated by it:
    a dot drawn without a verb is exactly the class that made two takes of
    one storyboard differ by 69 pixels (#185), and a still comparison only
    notices it on the run where the race goes the other way. This notices
    every one, in the DOM, on every take of the determinism pair.

    Failing on a *missing element* is deliberate. A chrome document that
    stopped shipping the dot would make this check silently unable to fail,
    and a check that cannot fail is the thing this repo's review discipline
    exists to catch — even though the stills would, in that one case,
    reproduce. The dot's pixels when a verb DOES drive it are tests/pixel's
    cursor-parked golden.
    """
    box = page.evaluate(_CURSOR_BOX_JS)
    if box is None:
        b.fail_if(
            True,
            f"{when}, the chrome ships no cursor dot (#__demo_cursor is not "
            f"in the page) — with no element there is no off-screen park to "
            f"assert, and no dot for any take's pointer verbs to drive",
        )
        return
    b.fail_if(
        box["x"] + box["width"] > 0 and box["y"] + box["height"] > 0,
        f"{when}, the cursor dot sits at ({box['x']:.0f}, {box['y']:.0f}) "
        f"with no pointer verb having run — a dot drawn by something other "
        f"than the storyboard is #185's class back, and it decides whether "
        f"two takes of this storyboard produce the same pixels",
    )


def _check_video(
    label: str,
    mp4: Path,
    duration_range: tuple[float, float],
    video_rect: Rect,
) -> list[str]:
    from demo_recording.content import media_duration

    failures: list[str] = []
    size = mp4.stat().st_size
    if size < MIN_MP4_BYTES:
        failures.append(
            f"{label}: {mp4} is only {size} bytes (expected at least {MIN_MP4_BYTES})"
        )
        return failures

    seconds: float | None
    try:
        seconds = media_duration(mp4)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the run
        failures.append(f"{label}: ffprobe could not read {mp4}: {exc}")
        seconds = None
    if seconds is not None:
        low, high = duration_range
        if not low <= seconds <= high:
            failures.append(
                f"{label}: {mp4.name} is {seconds:.1f}s, expected between "
                f"{low:.0f}s and {high:.0f}s"
            )

    try:
        frames = gray_frames(mp4, video_rect, sample_fps=CONTENT_SAMPLE_FPS)
    except RuntimeError as exc:
        failures.append(f"{label}: {exc}")
        return failures
    if not frames:
        failures.append(f"{label}: no frames could be sampled from {mp4.name}")
        return failures

    # Median, not max: one good frame must not excuse a blank video. Not min
    # either — both media legitimately open on the recorder's own furniture
    # (the terminal's card, the web take's opening hold, #119/#360), which
    # `check_opening_card`/`check_wrapper_opening` grade separately, on the
    # frames this median is deliberately insensitive to.
    floor = MIN_CONTENT_STDDEV[label]
    score = statistics.median(contrast(f) for f in frames)
    if score < floor:
        failures.append(
            f"{label}: {mp4.name} has no picture where the app should be — the "
            f"median of {len(frames)} sampled frames scores {score:.1f} luma "
            f"stddev over {video_rect}, under the {floor} floor"
        )
    # "ok" only when nothing at all was wrong with this file. Printing it
    # alongside a duration failure reads as a contradiction, and a log that
    # contradicts itself is a log nobody trusts.
    if not failures and seconds is not None:
        print(
            f"smoke: {label} demo.mp4 ok ({seconds:.1f}s, {size // 1024} kB, "
            f"content {score:.1f})"
        )
    return failures


def check_content_healthy(label: str, out_dir: Path, app_rect: Rect) -> list[str]:
    """What every healthy take in this suite must say about its own picture.

    Cheap enough to hang off every take that already records, and that breadth
    is the point: the picture check has to be *wired in* on the web recorder,
    the terminal recorder and a stitched demo, and "it works on the take
    written to test it" is how a feature ships broken everywhere else.

    `app_rect` is where this harness independently believes the app sits —
    read off `rec._geom` or the live `#__term_host` at record time, never from
    the recorder's report. Comparing the two is the assertion that matters: a
    recorder scoring the whole frame, or a rect off in the chrome, produces a
    perfectly plausible `content` block and a number that means nothing (issue
    #17, and the anti-correlation measured in check_content_pair below).
    """
    failures: list[str] = []
    content = content_of(out_dir)
    if content is None:
        return [
            f"{label}: timeline.json carries no `content` — the recorder said "
            f"nothing at all about whether the recording shows anything (#97)"
        ]
    if not content.get("measured"):
        return [
            f"{label}: the recorder did not measure this take's picture — "
            f"{content.get('note')}"
        ]

    rects = content_rects(out_dir)
    if not rects:
        failures.append(
            f"{label}: this take's timeline names no scored rect at all, so "
            f"nothing says which part of the frame `score` describes"
        )
    for rect in rects:
        if len(rect) != 4:
            failures.append(f"{label}: a content rect is {rect!r}, not four numbers")
            continue
        x, y, w, h = (int(v) for v in rect)
        ax, ay, aw, ah = app_rect
        inside = ax <= x and ay <= y and x + w <= ax + aw and y + h <= ay + ah
        if not inside:
            failures.append(
                f"{label}: the recorder scored {tuple(rect)}, which is not "
                f"inside the app rect {app_rect} this harness measured — it is "
                f"grading its own window chrome, which scores well on a blank "
                f"recording (issue #17)"
            )
        elif w * h < 0.5 * aw * ah:
            failures.append(
                f"{label}: the recorder scored {tuple(rect)}, only "
                f"{100 * w * h / (aw * ah):.0f}% of the app rect {app_rect} — "
                f"too small a keyhole to say the recording shows anything"
            )

    score, floor = content.get("score"), content.get("floor")
    if not isinstance(score, (int, float)) or not isinstance(floor, (int, float)):
        failures.append(
            f"{label}: content.score is {score!r} and content.floor is "
            f"{floor!r}; a measured take must have both"
        )
    elif score < floor * CONTENT_SCORE_HEADROOM:
        failures.append(
            f"{label}: this take scores {score} over its content rect, under "
            f"{CONTENT_SCORE_HEADROOM}x the recorder's {floor} blank floor — "
            f"either the take really is nearly blank, or the floor has been "
            f"raised until it no longer separates one from the other"
        )

    still, limit = content.get("static_for"), content.get("static_limit")
    if not isinstance(still, (int, float)) or not isinstance(limit, (int, float)):
        failures.append(
            f"{label}: content.static_for is {still!r} and content.static_limit "
            f"is {limit!r}; a measured take must have both"
        )
    # Deliberately *no* assertion that `still` stays under `limit`. It used to
    # be here and it was wrong: a healthy demo narrating over a rendered screen
    # holds the measured region for longer than the limit and is supposed to,
    # which is what `content-toured` exists to prove. What a healthy take owes
    # is silence, not a small number.

    if content.get("warnings"):
        failures.append(
            f"{label}: the recorder warned about a take this suite grades as "
            f"healthy: {content['warnings']}"
        )
    if not failures:
        print(
            f"smoke: {label} content ok (score {score}, longest still "
            f"{still}s against a {limit}s limit, over {len(rects)} rect(s) "
            f"{[tuple(r) for r in rects]})"
        )
    return failures


def check_coverage(out_dir: Path) -> list[str]:
    """The coverage report says what the storyboard claimed, and no more."""
    failures: list[str] = []
    doc = json.loads((out_dir / "timeline.json").read_text())
    coverage = doc.get("coverage")
    if not isinstance(coverage, dict):
        return [
            f"coverage: this take declared {len(COVERAGE_CRITERIA)} criteria "
            f"and its timeline reports coverage={coverage!r} — nothing below "
            f"can be graded"
        ]

    if coverage.get("criteria") != COVERAGE_CRITERIA:
        failures.append(
            f"coverage: the report's criteria are "
            f"{coverage.get('criteria')!r}, not the ones the take declared. "
            f"A reviewer judges the frames against this text."
        )

    # Arm 1 — the finding.
    if coverage.get("unclaimed") != [COVERAGE_UNCLAIMED]:
        failures.append(
            f"coverage: `unclaimed` is {coverage.get('unclaimed')!r}, expected "
            f"[{COVERAGE_UNCLAIMED!r}]. The storyboard demonstrates two of "
            f"three criteria and never tags the third, so that is the one "
            f"finding this report exists to produce."
        )

    # Arm 2 — correspondence, not count. Every beat the report points at has
    # to be a beat in *this* file carrying *that* tag.
    beats = {b.get("index"): b for b in doc.get("beats") or []}
    claimed = coverage.get("claimed") or {}
    if set(claimed) != set(COVERAGE_CRITERIA):
        failures.append(
            f"coverage: `claimed` has keys {sorted(claimed)}, expected every "
            f"declared criterion ({sorted(COVERAGE_CRITERIA)}) — a consumer "
            f"iterating it must see the whole ticket, not its covered half"
        )
    for key, rows in claimed.items():
        for row in rows:
            beat = beats.get(row.get("index"))
            if beat is None:
                failures.append(
                    f"coverage: {key} points at beat {row.get('index')!r}, "
                    f"which is not a beat in this timeline"
                )
                continue
            if key not in (beat.get("ac") or []):
                failures.append(
                    f"coverage: {key} points at beat {row.get('index')} "
                    f"(`{beat.get('verb')}`), whose own `ac` is "
                    f"{beat.get('ac')!r} — the report and the beat disagree "
                    f"about what that beat claims"
                )
            if row.get("t_start") != beat.get("t_start"):
                failures.append(
                    f"coverage: {key} says beat {row.get('index')} is at "
                    f"{row.get('t_start')!r}, the beat says "
                    f"{beat.get('t_start')!r} — a reviewer scrubbing to that "
                    f"timestamp would land somewhere else"
                )
            if row.get("still") != beat.get("still"):
                failures.append(
                    f"coverage: {key} names still {row.get('still')!r} for "
                    f"beat {row.get('index')}, the beat names "
                    f"{beat.get('still')!r}"
                )

    # Arm 4 — the clause is on the screen, in the ticket's own words (#280).
    #
    # Four things have to hold together, and each alone is satisfied by a
    # broken card: the beat exists, it carries the **declared** text rather
    # than one somebody retyped, it names and claims the clause it showed, and
    # the coverage table lists it. A card carrying the wrong sentence is
    # invisible in every other artifact this take writes — `timeline.md`
    # renders the declared text whatever went on screen.
    #
    # A fifth reads the *page* rather than the beat log, and it is the only one
    # that can disagree with the recorder: the four above are read out of
    # `timeline.json`, which the recorder writes from the same values it draws
    # from. What none of the five grades is whether the clause was *legible* —
    # see tests/README.md, under the coverage axis.
    cards = [b for b in doc.get("beats") or [] if b.get("verb") == "criterion"]
    if len(cards) != 1:
        failures.append(
            f"coverage: this take raises one criterion card and its timeline "
            f"holds {len(cards)} `criterion` beats — nothing about the card "
            f"is graded below"
        )
    else:
        card = cards[0]
        declared = COVERAGE_CRITERIA[COVERAGE_CARD]
        if card.get("caption") != declared:
            failures.append(
                f"coverage: the criterion card's line is "
                f"{card.get('caption')!r}, not {COVERAGE_CARD}'s declared "
                f"{declared!r}. The card reads the criteria map so that a "
                f"second wording of a clause cannot exist"
            )
        if card.get("selector") != COVERAGE_CARD:
            failures.append(
                f"coverage: the criterion beat names {card.get('selector')!r}, "
                f"so the beat log does not say which clause was on screen"
            )
        if card.get("ac") != [COVERAGE_CARD]:
            failures.append(
                f"coverage: the criterion beat claims {card.get('ac')!r}, "
                f"expected [{COVERAGE_CARD!r}] — a card claims the clause it "
                f"shows, and only that one"
            )
        shown_by = [row.get("index") for row in claimed.get(COVERAGE_CARD) or []]
        if card.get("index") not in shown_by:
            failures.append(
                f"coverage: the clause was on screen at beat "
                f"{card.get('index')} and `claimed[{COVERAGE_CARD!r}]` lists "
                f"{shown_by!r} — the video and the coverage table disagree "
                f"about whether the ticket was quoted"
            )
        failures += _criterion_page_failures(out_dir, card, declared)

    # No beat may claim a criterion that was never declared — the report is
    # built from the beats, so an undeclared tag reaching one would be a row
    # nothing on the ticket accounts for.
    for beat in doc.get("beats") or []:
        for key in beat.get("ac") or []:
            if key not in COVERAGE_CRITERIA:
                failures.append(
                    f"coverage: beat {beat.get('index')} claims {key!r}, "
                    f"which this take never declared"
                )

    tagged = sum(1 for b in doc.get("beats") or [] if b.get("ac"))
    if coverage.get("tagged_beats") != tagged:
        failures.append(
            f"coverage: the report counts {coverage.get('tagged_beats')!r} "
            f"tagged beats; {tagged} beats carry an `ac`"
        )
    untagged = len(doc.get("beats") or []) - tagged
    if coverage.get("untagged_beats") != untagged:
        failures.append(
            f"coverage: the report counts {coverage.get('untagged_beats')!r} "
            f"untagged beats; {untagged} beats carry no `ac`"
        )

    # The markdown is what a reviewer is actually handed, so the finding has to
    # survive into it — a JSON field nobody renders is not a review gate.
    # **Not "does AC-3 appear in the file".** It appears in the table on its
    # own row whatever the report concludes, so that assertion would pass on a
    # document that had dropped the finding entirely. What has to survive into
    # the markdown is the *sentence that states it*, naming the criterion.
    md = (out_dir / "timeline.md").read_text()
    stated = [ln for ln in md.splitlines() if "no beat claiming them" in ln]
    if not stated:
        failures.append(
            "coverage: timeline.md never states the finding — the criteria "
            "nothing claimed exist in the JSON and in a table row, and "
            "nowhere in the file does a sentence say so"
        )
    elif not any(COVERAGE_UNCLAIMED in ln for ln in stated):
        failures.append(
            f"coverage: timeline.md states a finding about unclaimed criteria "
            f"without naming {COVERAGE_UNCLAIMED}: {stated!r}"
        )
    # Likewise not "does the word claimed appear" — it is a column header.
    if "not what it proved" not in md:
        failures.append(
            "coverage: timeline.md's acceptance section never says the table "
            "is what the storyboard claimed and *not what it proved*. Without "
            "that sentence a reviewer reads an author's tag as a demonstrated "
            "criterion, which is the tautology this feature exists to avoid"
        )

    if not failures:
        print(
            f"smoke: coverage ok ({len(COVERAGE_CRITERIA)} criteria, "
            f"{tagged} tagged beats, unclaimed {coverage.get('unclaimed')})"
        )
    return failures


def check_coverage_refusals(out_root: Path) -> list[str]:
    """Tagging and declaring are refused where they would produce a wrong
    report. No browser: `Recorder(...)` does not launch one until `__enter__`.
    """
    from demo_recording import Recorder
    from demo_recording.coverage import coverage_report

    failures: list[str] = []
    out = out_root / "coverage-refusals"
    out.mkdir(parents=True, exist_ok=True)

    def refuses(what: str, call, *want: type) -> None:
        try:
            call()
        except want:
            return
        except Exception as exc:  # noqa: BLE001 - the wrong error is a failure
            failures.append(
                f"coverage-refusals: {what} raised {type(exc).__name__}, "
                f"expected one of {[w.__name__ for w in want]}"
            )
            return
        failures.append(f"coverage-refusals: {what} was accepted")

    tagged = Recorder(out, criteria={"AC-1": "one"})
    refuses(
        "a tag naming an undeclared criterion",
        lambda: tagged._checked_ac("AC-9", "caption()"),
        ValueError,
    )
    refuses(
        "a list holding one undeclared criterion",
        lambda: tagged._checked_ac(["AC-1", "AC-9"], "shot()"),
        ValueError,
    )
    refuses(
        "a tag that is not a string",
        lambda: tagged._checked_ac(7, "caption()"),
        TypeError,
    )
    refuses(
        "a tag on a take that declared no criteria",
        lambda: Recorder(out)._checked_ac("AC-1", "caption()"),
        ValueError,
    )
    refuses(
        "a criterion id with a space in it",
        lambda: Recorder(out, criteria={"AC 1": "one"}),
        ValueError,
    )
    refuses(
        "a criterion declared with no text",
        lambda: Recorder(out, criteria={"AC-1": "   "}),
        ValueError,
    )

    # Accepted, and the control for every refusal above: if these raised, the
    # refusals would be passing because nothing works.
    try:
        if tagged._checked_ac(["AC-1", "AC-1"], "shot()") != ["AC-1"]:
            failures.append(
                "coverage-refusals: a criterion tagged twice on one beat is "
                "not de-duplicated, so `claimed` would list that beat twice"
            )
        if tagged._checked_ac(None, "caption()") != []:
            failures.append("coverage-refusals: an untagged beat is not accepted")
    except Exception as exc:  # noqa: BLE001
        failures.append(
            f"coverage-refusals: a valid tag raised {type(exc).__name__}: {exc}"
        )

    # A take recorded outside a ticket reports null, not an empty report: an
    # empty one reads as a take that covered nothing.
    if coverage_report({}, [{"index": 0, "verb": "goto"}]) is not None:
        failures.append(
            "coverage-refusals: a take that declared no criteria produced a "
            "coverage report instead of null — which reads as a take measured "
            "against a ticket and found to cover none of it"
        )

    if not failures:
        print("smoke: coverage refusals ok (6 refused, 3 controls accepted)")
    return failures


def check_coverage_merge() -> list[str]:
    """A stitched demo's coverage is recomputed over the *merged* beats.

    The subtle half of the feature, and unreachable from a single take: each
    segment knows only its own criteria and numbers its beats from zero. A
    merged report assembled by unioning the segments' own reports would point a
    reviewer at beat numbers that do not exist in the file they are reading,
    and could never report a criterion that *no* segment claimed — because no
    segment knows the other's ticket.
    """
    from demo_recording.coverage import _merged_coverage

    failures: list[str] = []
    docs = [
        {"coverage": {"criteria": {"AC-1": "web half", "AC-3": "neither shows this"}}},
        {"coverage": {"criteria": {"AC-2": "cli half", "AC-3": "neither shows this"}}},
    ]
    # Indices as `stitch()` renumbers them: segment two's beat 0 becomes beat 5.
    merged = [
        {
            "index": 0,
            "ac": ["AC-1"],
            "segment": "part1",
            "segment_index": 0,
            "t_start": 1.0,
            "still": None,
        },
        {
            "index": 5,
            "ac": ["AC-2"],
            "segment": "part2",
            "segment_index": 0,
            "t_start": 9.0,
            "still": None,
        },
    ]
    report = _merged_coverage(docs, merged)
    if report is None:
        return ["coverage-merge: two segments with criteria produced no report"]
    if sorted(report["criteria"]) != ["AC-1", "AC-2", "AC-3"]:
        failures.append(
            f"coverage-merge: the merged criteria are "
            f"{sorted(report['criteria'])}, not the union of the segments' — "
            f"so a criterion only one segment knew about is missing from the "
            f"ticket the joined demo is judged against"
        )
    if report["unclaimed"] != ["AC-3"]:
        failures.append(
            f"coverage-merge: `unclaimed` is {report['unclaimed']!r}, expected "
            f"['AC-3'] — the criterion neither segment claimed, which neither "
            f"segment's own report could name"
        )
    got = report["claimed"].get("AC-2") or []
    if [row.get("index") for row in got] != [5]:
        failures.append(
            f"coverage-merge: AC-2 points at beats "
            f"{[r.get('index') for r in got]}, expected [5] — the merged "
            f"index. Segment two numbers that beat 0 in its own log, and a "
            f"reviewer handed 'beat 0' would open the wrong one."
        )
    # ...and which segment that beat came from (issue #137). The index alone
    # was asserted here while `_coverage_md` renders ``beat 5 (`part2`)``, so
    # dropping the segment from the report changed nothing any check could see.
    if [row.get("segment") for row in got] != ["part2"]:
        failures.append(
            f"coverage-merge: AC-2's claim names segment "
            f"{[r.get('segment') for r in got]!r}, expected ['part2']. Beat "
            f"numbers are per-segment until the merge renumbers them, and the "
            f"coverage table is what points a conformance reviewer at a frame — "
            f"a reviewer handed a bare 'beat 5' cannot tell which segment's "
            f"recording to open (issue #137)"
        )

    # Two segments recorded against different wording for one id is a
    # storyboard mistake, and the merged report has to say so rather than
    # silently keeping whichever it saw first.
    clashing = [
        {"coverage": {"criteria": {"AC-1": "one wording"}}},
        {"coverage": {"criteria": {"AC-1": "a different wording"}}},
    ]
    clash = _merged_coverage(clashing, [])
    if not clash or clash.get("conflicts") != ["AC-1"]:
        failures.append(
            f"coverage-merge: segments declaring different text for AC-1 "
            f"produced conflicts={None if not clash else clash.get('conflicts')!r}, "
            f"expected ['AC-1'] — otherwise the merged file shows one wording "
            f"and nothing says the other existed"
        )
    if _merged_coverage([{}, {}], merged) is not None:
        failures.append(
            "coverage-merge: segments with no criteria produced a report "
            "instead of null"
        )

    if not failures:
        print(
            "smoke: coverage merge ok (union of 3 criteria, unclaimed AC-3, "
            "merged indices, 1 wording conflict named)"
        )
    return failures


def check_opening_gap(out_root: Path) -> list[str]:
    """`opening_gap` on two videos built here, not recorded (issue #119).

    The recorded takes above can only ever show one of these shapes: a web take
    always opens blank, so nothing in this suite exercises the other half of
    the function — **the blank floor**, which is the whole reason it does not
    fire on an app that painted immediately and then held still. A fixture that
    cannot reach a path does not grade the constant guarding it.

    So both shapes are synthesised, four lines of ffmpeg each, and the control
    is the one that matters: a video that is one painted picture from first
    frame to last must measure a 0.0 gap. Delete the floor and this is the
    assertion that goes red.
    """
    from demo_recording.content import opening_gap

    failures: list[str] = []
    root = out_root / "opening-gap"
    root.mkdir(parents=True, exist_ok=True)
    rect = (0, 0, 320, 180)

    blank = root / "blank-then-painted.mp4"
    _synthetic_take(blank, SYNTHETIC_PAINT_AT, 2.0)
    gap, note = opening_gap(blank, rect)
    if gap is None or abs(gap - SYNTHETIC_PAINT_AT) > SYNTHETIC_SLACK_S:
        failures.append(
            f"opening-gap: a video that is flat white until "
            f"{SYNTHETIC_PAINT_AT}s and painted after it measured a gap of "
            f"{gap!r} (note {note!r}), not {SYNTHETIC_PAINT_AT}s "
            f"+/- {SYNTHETIC_SLACK_S}s"
        )

    static = root / "painted-throughout.mp4"
    _synthetic_take(static, None, 2.0)
    gap, note = opening_gap(static, rect)
    if gap != 0.0:
        failures.append(
            f"opening-gap: a video that shows one *painted* picture for its "
            f"whole length measured a gap of {gap!r} (note {note!r}), not 0.0. "
            f"Nothing changes in it from first frame to last, so a detector "
            f"without the blank floor reads it as an opening that never "
            f"painted — and the recorder would composite a later frame over "
            f"the start of a take that never needed it."
        )

    if not failures:
        print(
            "smoke: opening-gap reads a blank opening and a static picture "
            "differently (blank-then-painted, painted-throughout)"
        )
    return failures


def scored_region_failures(label: str, app: Rect, content: dict) -> list[str]:
    """`content.rect` against the region this file independently expects.

    The assertion issue #135 found missing, and why it went missing is worth
    stating. Every other reading of the scored rect in this suite came out of
    the report it was grading: `_check_scored_region` re-derived its own
    premise from `content["rect"]`, and `check_content_pair` graded the trim by
    asking the recorder's *warning* to contain the words "caption bar" — a
    literal in `content.py`, present whatever the rect turned out to be. With
    `CONTENT_CAPTION_TRIM` set to 0.0 the recorder printed

        the app rect (74, 110, 1132, 540), which excludes the recorder's own
        caption bar

    where 540 is the untrimmed height and 432 is the trimmed one. The sentence
    was false, the artifact said it anyway, and every check above passed.

    So the expectation is built here: from the app box this harness read off
    the live element at record time, trimmed with this file's own
    `CONTENT_KEEP`. Nothing is imported from `content.py` — a check that
    recomputed the trim with the recorder's own constant would agree with
    whatever that constant was set to, which is the catalogue's "check that
    shares the bug's blind spot" wearing a geometry assertion as a disguise.
    """
    rect = content.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return [
            f"{label}: content.rect is {rect!r}, so nothing says which part of "
            f"the frame `score` and `static_for` describe"
        ]
    try:
        got = tuple(int(v) for v in rect)
    except (TypeError, ValueError):
        return [f"{label}: content.rect is {rect!r}, which is not four numbers"]
    want = keep_top(app)
    off = tuple(abs(a - b) for a, b in zip(got, want, strict=True))
    if max(off) <= CONTENT_RECT_SLACK_PX:
        return []
    return [
        f"{label}: the recorder scored the region {got}, this run expected "
        f"{want} (off by {off} px). The app box is {app} and the bottom "
        f"{1 - CONTENT_KEEP:.0%} of it is the recorder's own caption bar, "
        f"burned into the recording. Scoring that as if it were the app lets a "
        f"caption supply the contrast for a blank take on the score arm, and "
        f"lets a caption *change* count as the picture changing on the static "
        f"arm — either one turns a broken take green (issues #17 and #135)."
    ]


def check_content_pair(takes: dict[str, dict]) -> list[str]:
    """The two content takes, against each other and against the recorder.

    One storyboard, recorded twice, differing only in whether the title card is
    taken down. Every assertion here is a *comparison*, because every one of
    them has a way to pass vacuously on its own: "the covered take warns" is
    satisfied by a recorder that warns on everything, "the shown take does not"
    by a recorder that never warns, and both by a metric that is measuring the
    wrong region entirely.
    """
    failures: list[str] = []
    shown, covered = takes[CONTENT_TAKES[0]], takes[CONTENT_TAKES[1]]
    reports = {}
    for name, take in takes.items():
        content = content_of(take["out_dir"])
        if content is None or not content.get("measured"):
            failures.append(
                f"{name}: no measured `content` in timeline.json "
                f"({None if content is None else content.get('note')})"
            )
        else:
            reports[name] = content
    if len(reports) != 2:
        return failures
    shown_c, covered_c = reports[CONTENT_TAKES[0]], reports[CONTENT_TAKES[1]]

    # 0. The region every assertion below is *about*, before any of them uses
    #    it. Both takes, because the rect is read once per take and a change
    #    that moved it would move it on both.
    for name in CONTENT_TAKES:
        failures += scored_region_failures(
            name, takes[name]["info"]["app"], reports[name]
        )

    # 1. The verdicts, opposite ways round.
    if shown_c.get("warnings"):
        failures.append(
            f"{CONTENT_TAKES[0]}: the recorder warned about the take whose "
            f"card *is* taken down: {shown_c['warnings']}"
        )
    still = " ".join(str(w) for w in covered_c.get("warnings") or [])
    if "held one picture" not in still:
        failures.append(
            f"{CONTENT_TAKES[1]}: the recorder did not report a held picture "
            f"for a take whose title card covered every beat. This is issue "
            f"#91 reproduced, and `content.warnings` says {covered_c.get('warnings')!r}"
        )
    # The message must describe what was measured and must not name a cause it
    # cannot know. A warning that blames an overlay is wrong on three of this
    # suite's own healthy takes, and a confidently wrong artifact is the thing
    # #97 exists to remove — the detector must not become an instance of it.
    for banned in ("title card or modal left up", "is not visible"):
        if banned in still:
            failures.append(
                f"{CONTENT_TAKES[1]}: the warning asserts {banned!r}, a cause "
                f"the frames cannot establish — a held stretch has honest "
                f"explanations too (see {CONTENT_TOURED})"
            )
    # A claim about the *message*, and only about the message, now that
    # assertion 0 above grades the region itself. Before #135 this line was
    # the only thing in the suite that mentioned the trim, and it graded a
    # literal in `content.py` rather than the geometry that literal describes:
    # the phrase survived `CONTENT_CAPTION_TRIM = 0.0` intact, on a warning
    # whose quoted rect was the untrimmed one. Keep it — a reader still needs
    # to be told what was measured — but do not mistake it for the check.
    if "caption bar" not in still:
        failures.append(
            f"{CONTENT_TAKES[1]}: the warning does not say what region was "
            f"measured. It excludes the recorder's own caption bar, so a "
            f"reader who does not know that cannot tell what the silence means"
        )

    # 2. ...and on stderr, unasked, which is the half of the acceptance
    #    criterion no artifact can carry.
    err = covered["stderr"]
    if "WARNING" not in err or "held one picture" not in err:
        failures.append(
            f"{CONTENT_TAKES[1]}: nothing on stderr said the recording holds "
            f"still. A reviewer who does not open timeline.json gets no signal "
            f"at all. Captured stderr: {err[-400:]!r}"
        )
    if "held one picture" in shown["stderr"]:
        failures.append(
            f"{CONTENT_TAKES[0]}: stderr warned about a healthy take, so the "
            f"warning above says nothing"
        )

    # 3. The covered take really is covered, for most of its length.
    duration = json.loads((covered["out_dir"] / "timeline.json").read_text()).get(
        "duration"
    )
    held = covered_c.get("static_for") or 0.0
    if (
        isinstance(duration, (int, float))
        and held < duration * CONTENT_COVERED_FRACTION
    ):
        failures.append(
            f"{CONTENT_TAKES[1]}: the card covered the take but the recorder "
            f"reports only {held}s of held picture in {duration}s of video — "
            f"under {CONTENT_COVERED_FRACTION:.0%}. The detector is finding "
            f"changes that are not there (encoder noise, a cursor, the caption "
            f"band leaking into the rect), so it will split a long occlusion "
            f"into stretches too short to warn about"
        )

    # 4. The band the recorder's constant has to sit in, from this run's own
    #    two takes rather than from a number somebody typed.
    limit = shown_c.get("static_limit")
    healthy = shown_c.get("static_for") or 0.0
    if not isinstance(limit, (int, float)):
        failures.append(f"content: content.static_limit is {limit!r}")
    else:
        low, high = healthy * CONTENT_STATIC_HEADROOM, held * CONTENT_STATIC_MARGIN
        if not low <= limit <= high:
            failures.append(
                f"content: the recorder warns at {limit}s, outside the "
                f"[{low:.1f}, {high:.1f}]s band this run measured — a healthy "
                f"take of this storyboard holds {healthy}s and the covered one "
                f"holds {held}s. Below the band every honest demo warns; above "
                f"it, the take this check exists for does not"
            )
        else:
            print(
                f"smoke: content static limit {limit}s sits in "
                f"[{low:.1f}, {high:.1f}]s (healthy {healthy}s, covered {held}s)"
            )

    # 5. The evidence tier agrees the covered take *ran*, and the pixels
    #    disagree that any of it was shown. That pair is the whole finding of
    #    #97, and it is measured here without asking the recorder anything:
    #    ffmpeg cuts two frames from the middles of two different `run` beats
    #    and they are byte-identical.
    apart: dict[str, float | None] = {}
    for take, name, is_covered in (
        (covered, CONTENT_TAKES[1], True),
        (shown, CONTENT_TAKES[0], False),
    ):
        found, apart[name] = _check_occlusion(
            take["out_dir"], name, keep_top(take["info"]["app"]), covered=is_covered
        )
        failures += found
    held_db, moved_db = apart[CONTENT_TAKES[1]], apart[CONTENT_TAKES[0]]
    if held_db is None or moved_db is None:
        failures.append("content: one of the two takes yielded no PSNR reading")
    elif held_db - moved_db < CONTENT_PSNR_GAP_DB:
        failures.append(
            f"content: the covered take's two sampled moments are {held_db:.1f} "
            f"dB PSNR apart and the shown take's {moved_db:.1f} dB — a gap of "
            f"{held_db - moved_db:.1f} dB, under the {CONTENT_PSNR_GAP_DB} dB "
            f"one. Whatever the absolute numbers are on this encoder, the card "
            f"is not holding the video visibly stiller than the storyboard does"
        )
    else:
        print(
            f"smoke: content video held {held_db:.1f} dB against moved "
            f"{moved_db:.1f} dB — {held_db - moved_db:.1f} dB apart, over the "
            f"{CONTENT_PSNR_GAP_DB} dB gap"
        )

    # 6. The anti-correlated metric (issue #17), as a standing regression test.
    #    Scores the rect the recorder reported, which assertion 0 has already
    #    graded against this file's own expectation — read that function's
    #    docstring before moving either of them apart (issue #135).
    failures += _check_scored_region(shown, shown_c)

    # 7. The card is this recorder's own element, and it is still up when the
    #    take ends — so the recorder can report it by id rather than inferring
    #    it from luma (#163). `check_overlay_pair` grades the same reading on
    #    `#__demo_bridge`; this is the other overlay, on the other medium, and
    #    it is free because this take already exists. The *silent* direction is
    #    assertion 1 above: the shown take must carry no warning at all.
    if "#__demo_interlude" not in still:
        failures.append(
            f"{CONTENT_TAKES[1]}: this take ends with the recorder's own "
            f"interlude card on screen and `content.warnings` does not name it. "
            f"The held-picture arm reports a stretch and cannot say what caused "
            f"it; the element id is the one thing here that is exact (#163). "
            f"warnings: {covered_c.get('warnings')!r}"
        )
    if "__demo_interlude" not in err:
        failures.append(
            f"{CONTENT_TAKES[1]}: nothing on stderr named the overlay left up. "
            f"Captured stderr: {err[-400:]!r}"
        )
    if "__demo_" in shown["stderr"]:
        failures.append(
            f"{CONTENT_TAKES[0]}: stderr reported an overlay still up on the "
            f"take that took its card down: {shown['stderr'][-400:]!r}"
        )
    return failures


def check_content_toured(out_dir: Path, stderr: str, app: Rect) -> list[str]:
    """A healthy demo that holds still past the limit must be met with silence.

    The false positive this axis was blind to. `content-toured` narrates a
    rendered screen the way SKILL.md tells authors to, so the measured region
    holds one picture for longer than `static_limit` with nothing occluded.
    Four assertions, and the first two are premises the other two need:

    0. the region really is the app with its caption bar cut off, which is
       what makes "swapping captions is invisible here" true (issue #135);
    1. it really does hold past the limit — otherwise this take proves nothing
       and would keep passing after the check regressed;
    2. `content.warnings` is empty and nothing reached stderr;
    3. the stretch is populated with beats and **none of them acted on the
       app**, which is the mechanism rather than the symptom. Without it, "no
       warning" would also pass on a recorder whose static arm was simply
       switched off.
    """
    content = content_of(out_dir)
    if content is None or not content.get("measured"):
        return [
            f"{CONTENT_TOURED}: no measured `content` in timeline.json "
            f"({None if content is None else content.get('note')})"
        ]
    held, limit = content.get("static_for"), content.get("static_limit")
    if not isinstance(held, (int, float)) or not isinstance(limit, (int, float)):
        return [f"{CONTENT_TOURED}: static_for is {held!r}, limit {limit!r}"]

    failures: list[str] = []
    # Before the premise guard below, because it is the thing most likely to
    # have broken it. This take holds still *because* the caption bar is
    # outside the scored region; a rect that stopped excluding it turns every
    # caption swap into motion and cuts the stretch short (issue #135, hole 3).
    region = scored_region_failures(CONTENT_TOURED, app, content)
    failures += region
    if held < limit:
        # Two very different causes, and the remedy order matters. This guard
        # used to say only "Lengthen the touring captions", which is a remedy
        # for the fixture — a maintainer following it under a broken trim edits
        # the storyboard until the control holds again and ships a recorder
        # that counts its own caption bar as app motion. A red that names the
        # fixture for a fault in the code is worse than a red that names
        # nothing.
        cause = (
            "The scored region is wrong (see the failure above), which is the "
            "likely cause: a rect that includes the caption bar turns every "
            "caption swap into motion and chops the stretch. Fix that first "
            "and do not touch this storyboard."
            if region
            else "The scored region checks out, so this really is about the "
            "fixture: lengthen the touring captions. Check first that a "
            "caption did not wrap — a wrapped bar grows upward into the "
            "measured region and shortens the stretch the same way."
        )
        failures.append(
            f"{CONTENT_TOURED}: this take was written to hold one picture past "
            f"the recorder's {limit}s limit and only held it for {held}s, so "
            f"it does not reach the false-positive path at all — as written, "
            f"it would keep passing after the thing it grades regressed. "
            f"{cause}"
        )
    if content.get("warnings"):
        failures.append(
            f"{CONTENT_TOURED}: the recorder warned about a healthy demo that "
            f"narrates a rendered screen — nothing is occluded, the terminal is "
            f"fully drawn, and every beat in the held stretch is a caption or a "
            f"hold. The warning says {content['warnings']!r}"
        )
    if "WARNING" in stderr and "held one picture" in stderr:
        failures.append(
            f"{CONTENT_TOURED}: stderr carried a held-picture warning for a "
            f"healthy take: {stderr[-400:]!r}"
        )

    spanned = content.get("static_beats")
    if not spanned:
        failures.append(
            f"{CONTENT_TOURED}: content.static_beats is {spanned!r}. The take "
            f"held a picture for {held}s and the recorder recorded no beats "
            f"inside it, so 'no acting verb ran' is vacuous rather than true"
        )
    else:
        acting = [b for b in spanned if b.get("acting")]
        if acting:
            failures.append(
                f"{CONTENT_TOURED}: the held stretch is reported as spanning "
                f"acting verbs {[b.get('verb') for b in acting]}, but this "
                f"storyboard touches nothing after its one command — either "
                f"the classification is wrong or the stretch is misaligned "
                f"with the beat log"
            )
        elif not failures:
            print(
                f"smoke: {CONTENT_TOURED} held one picture for {held}s, over "
                f"the {limit}s limit, across "
                f"{[b.get('verb') for b in spanned]} — and the recorder said "
                f"nothing, which is correct"
            )
    return failures


def _overlay_frame(mp4: Path, at: float, rect: Rect) -> bytes | None:
    """One reduced frame of `rect` at `at` seconds, or None."""
    try:
        frames = gray_frames(mp4, rect, sample_fps=2, start=at, duration=0.6)
    except RuntimeError:
        return None
    return frames[0] if frames else None


def _overlay_scrim_delta(
    out_dir: Path, label: str, rect: Rect
) -> tuple[list[str], float | None]:
    """How much the app rect moved between the two quiet stretches of a take.

    The take pauses before the scrim goes up and again after it would have come
    down, on a screen nothing else touches. So the difference between those two
    moments **is** the scrim, and nothing else: no command ran, no caption was
    set, the clock is frozen and the only other moving thing in the frame is
    the 8x8 ticker in a corner the app rect includes and the gradient barely
    reaches.

    Sampled from `demo.mp4`, not from a still: a `shot()` is a screenshot of
    the page and would be true of a DOM nobody recorded. Issue #162's
    acceptance is about the frame.
    """
    pauses = beat_midpoints(out_dir, "pause")
    if len(pauses) != 2:
        return (
            [
                f"{label}: the take recorded {len(pauses)} pause beats, expected "
                f"2 — the two quiet stretches this reading is taken from"
            ],
            None,
        )
    mp4 = out_dir / "demo.mp4"
    before = _overlay_frame(mp4, pauses[0][1], rect)
    after = _overlay_frame(mp4, pauses[1][1], rect)
    if before is None or after is None:
        return ([f"{label}: could not sample {mp4.name} at the two pause beats"], None)
    # A control on the control: two frames of a black recording differ by 0 and
    # would read as "the scrim is gone" for the cleared take. Both frames have
    # to show something first.
    for when, frame in (("before", before), ("after", after)):
        score = contrast(frame)
        if score < MIN_CONTENT_STDDEV["web"]:
            return (
                [
                    f"{label}: the frame sampled {when} the scrim scores "
                    f"{score:.1f} luma stddev over {rect}, under the "
                    f"{MIN_CONTENT_STDDEV['web']} floor — there is no picture "
                    f"there to have been covered, so comparing the two says "
                    f"nothing"
                ],
                None,
            )
    return [], frame_difference(before, after)


def check_overlay_pair(takes: dict[str, dict]) -> list[str]:
    """The two `light`-interlude takes, against each other (#162 and #163).

    Two claims, each with the other take as its control:

    1. **The documented clear works.** `interlude("")` takes down a `light`
       scrim, so the cleared take's two quiet stretches are the same picture
       while the left-up take's are not. Neither reading means anything alone —
       "no difference" is also what a harness measuring the wrong rect reports,
       and "a difference" is also what a recorder that never cleared anything
       produces — so the bar is the ratio between them, with an absolute floor
       under the left-up take so the pair cannot both go quiet.
    2. **The recorder notices its own overlay.** The left-up take must name
       `#__demo_bridge` in `content.warnings` and on stderr, and must *not*
       print that the recording shows a picture; the cleared take must say
       nothing about any overlay. `content.score` is not consulted: it is the
       measurement #163 is about, and it runs the wrong way here.
    """
    failures: list[str] = []
    cleared, left_up = takes[OVERLAY_TAKES[0]], takes[OVERLAY_TAKES[1]]

    # 1. The frames.
    deltas: dict[str, float | None] = {}
    for name, take in takes.items():
        found, deltas[name] = _overlay_scrim_delta(
            take["out_dir"], name, keep_top(take["info"]["app"])
        )
        failures += found
    up_delta, clear_delta = deltas[OVERLAY_TAKES[1]], deltas[OVERLAY_TAKES[0]]
    if up_delta is None or clear_delta is None:
        failures.append("overlay: one of the two takes yielded no scrim reading")
    elif up_delta < OVERLAY_SCRIM_MIN_DIFF:
        failures.append(
            f"{OVERLAY_TAKES[1]}: leaving the scrim up moved the app rect by "
            f"only {up_delta:.2f} mean luma between the two quiet stretches, "
            f"under the {OVERLAY_SCRIM_MIN_DIFF} floor. This harness cannot see "
            f"the scrim at all, so the cleared take reading small proves "
            f"nothing about the clear"
        )
    elif clear_delta > up_delta * OVERLAY_CLEARED_MAX_RATIO:
        failures.append(
            f'{OVERLAY_TAKES[0]}: after the documented `interlude("")` the app '
            f"rect is still {clear_delta:.2f} mean luma from where it was "
            f"before the scrim went up — {clear_delta / up_delta:.0%} of the "
            f"{up_delta:.2f} the take that never cleared it keeps, over the "
            f"{OVERLAY_CLEARED_MAX_RATIO:.0%} bar. The scrim is still in the "
            f"recording, which is issue #162: the clear dispatched on `style`, "
            f'so the default `style="card"` took down the other overlay'
        )
    else:
        print(
            f"smoke: {OVERLAY_TAKES[0]} scrim cleared — the app rect moved "
            f"{clear_delta:.2f} mean luma across the clear against "
            f"{up_delta:.2f} for {OVERLAY_TAKES[1]}"
        )

    # 2. What the recorder said about it.
    reports = {}
    for name, take in takes.items():
        content = content_of(take["out_dir"])
        if content is None or not content.get("measured"):
            failures.append(
                f"{name}: no measured `content` in timeline.json "
                f"({None if content is None else content.get('note')})"
            )
        else:
            reports[name] = content
    if len(reports) != 2:
        return failures
    up_warnings = " ".join(
        str(w) for w in reports[OVERLAY_TAKES[1]].get("warnings") or []
    )
    clear_warnings = " ".join(
        str(w) for w in reports[OVERLAY_TAKES[0]].get("warnings") or []
    )
    if "#__demo_bridge" not in up_warnings:
        failures.append(
            f"{OVERLAY_TAKES[1]}: this take ended with the recorder's own scrim "
            f"on screen and `content.warnings` does not name it. The recorder "
            f"built that element and knows its id, so this is the one occlusion "
            f"it can report exactly (#163). warnings: "
            f"{reports[OVERLAY_TAKES[1]].get('warnings')!r}"
        )
    if "__demo_" in clear_warnings:
        failures.append(
            f"{OVERLAY_TAKES[0]}: the recorder reported an overlay still up on "
            f"the take that took its scrim down: {clear_warnings!r}"
        )
    if "__demo_bridge" not in left_up["stderr"]:
        failures.append(
            f"{OVERLAY_TAKES[1]}: nothing on stderr said the scrim was still up. "
            f"An author who never opens timeline.json gets no signal at all, "
            f"which is half of #163's acceptance. Captured stderr: "
            f"{left_up['stderr'][-400:]!r}"
        )
    # The line #163 measured being printed over three occluded takes, on the
    # stream `print_content_summary` prints it to. Both directions, because
    # "the covered take does not say it" is satisfied by a recorder that stopped
    # saying it about anything — which would cost every healthy take its only
    # unasked account of its own picture.
    if "shows a picture" not in cleared["stdout"]:
        failures.append(
            f"{OVERLAY_TAKES[0]}: the take that cleared its scrim never said "
            f"the recording shows a picture, so the covered take not saying it "
            f"proves nothing. Captured stdout: {cleared['stdout'][-400:]!r}"
        )
    if "shows a picture" in left_up["stdout"]:
        failures.append(
            f"{OVERLAY_TAKES[1]}: the recorder still says the recording shows a "
            f"picture, over a take whose last frames are its own scrim: "
            f"{left_up['stdout'][-400:]!r}"
        )
    if "__demo_" in cleared["stderr"]:
        failures.append(
            f"{OVERLAY_TAKES[0]}: stderr warned about an overlay on the take "
            f"that cleared it: {cleared['stderr'][-400:]!r}"
        )

    if not failures:
        # Printed, never asserted: this is the anti-correlation of #163, and a
        # bar in this direction would be the defect written down as a check.
        print(
            f"smoke: content.score reads "
            f"{reports[OVERLAY_TAKES[1]].get('score')} for the covered take "
            f"against {reports[OVERLAY_TAKES[0]].get('score')} for the clear "
            f"one — the picture score does not separate these, which is why "
            f"the overlay is reported by element id instead (#163)"
        )
    return failures


def check_overlay_cleared(label: str, out_dir: Path) -> list[str]:
    """This take did not end with one of the recorder's own overlays up.

    The clean-path half of #163, on an arm that is not about overlays at all.
    `check_overlay_pair` and `check_content_pair` grade the *reporting* — a
    take that leaves a card up must name it by element id — and both leave one
    up deliberately, so neither can notice a fixture that leaves one up by
    accident. Issue #168 is what that costs: the narration take raised an
    interlude in its third beat and never took it down, so every frame from
    there to the end was the card rather than the app, including both captions
    the arm exists to measure. Nothing failed. A warning was printed on an arm
    the suite then called healthy, which is how a reader learns to skim
    (`reference/limits.md`, "A demo of an error path always records a
    problem").

    Read off `content.warnings` in timeline.json — what a reader is handed —
    rather than off the stderr line that carries the same finding, and by
    element-id prefix rather than by the sentence the recorder happens to
    phrase it in.
    """
    content = content_of(out_dir)
    if content is None or not content.get("measured"):
        return [
            f"{label}: timeline.json carries no measured `content` report, so "
            f"whether this take ended with one of the recorder's own overlays "
            f"on screen was not graded at all "
            f"({None if content is None else content.get('note')})"
        ]
    still_up = [
        str(w)
        for w in content.get("warnings") or []
        if "__demo_" in str(w) or "__term_" in str(w)
    ]
    if still_up:
        return [
            f"{label}: the take ended with one of the recorder's own overlays "
            f"still on screen — {still_up[0]!r}. It is opaque and at the top of "
            f"the z-order, so every frame from the moment it went up is that "
            f"overlay and not the app, whatever else this arm measures off the "
            f'beat log. Take it down with `interlude("")` before the storyboard '
            f"ends, or say in a comment why it has to stay (issue #168)"
        ]
    return []


def _check_occlusion(
    out_dir: Path, label: str, rect: Rect, covered: bool
) -> tuple[list[str], float | None]:
    """Was the app covered for this whole take? Answered without the recorder.

    Returns (failures, the PSNR between the two sampled moments). Two
    independent readings, neither of which asks the recorder anything, and one
    control that stops both from being vacuous:

    * **the stills**, cropped to `rect` and compared byte for byte. Lossless
      PNGs of the page, so this needs no threshold at all: under a card the
      five are one file five times, and with the card down they are five files.
      This is the assertion made *here*, per take.
    * **the recording**, at the midpoints of the first and last `run` beat. The
      stills are the page and the video is what a reviewer watches; a codec
      makes byte equality impossible there, so the reading is handed back and
      compared *against the other take's* by the caller — an absolute dB bar is
      a bar tuned to one x264 build, which this suite found out by going red on
      CI at 39.8 dB after measuring 47.5 dB here.
    * **`evidence/`**, which must hold as many *different* screens as there are
      commands, either way. That is the control: it is what says the commands
      really printed different things, so that "the frames are identical" is a
      statement about the recording rather than about a storyboard that did
      nothing.

    `covered=True` is asserted for the covered take and `covered=False` for the
    shown one. Running both is what makes each mean something: a comparison
    that answered "identical" for every take would pass the first and fail the
    second.
    """
    wanted = len(CONTENT_COMMANDS)
    runs = beat_midpoints(out_dir, "run")
    if len(runs) != wanted:
        return (
            [f"{label}: the take recorded {len(runs)} run beats, expected {wanted}"],
            None,
        )
    distinct, last = screens_differ(out_dir)
    if distinct < wanted:
        return (
            [
                f"{label}: evidence/ holds {distinct} distinct screens, so the "
                f"{wanted} commands did not print {wanted} different things and "
                f"comparing their frames proves nothing"
            ],
            None,
        )

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shots = sorted((out_dir / "images").glob("*-content.png"))
        if len(shots) != wanted:
            return (
                [
                    f"{label}: {len(shots)} stills named *-content.png, expected "
                    f"{wanted}"
                ],
                None,
            )
        cropped = [crop_png(s, rect, work / f"s{n}.png") for n, s in enumerate(shots)]
        if any(c is None for c in cropped):
            return [f"{label}: a still could not be cropped to {rect}"], None
        unique = len({hashlib.sha256(c).hexdigest() for c in cropped})  # type: ignore[arg-type]
        if covered and unique != 1:
            failures.append(
                f"{label}: the {wanted} stills show {unique} different pictures "
                f"where the terminal is, so the card did not cover this take "
                f"and every assertion about occlusion here measures something "
                f"else"
            )
        if not covered and unique != wanted:
            failures.append(
                f"{label}: the {wanted} stills show only {unique} distinct "
                f"picture(s) where the terminal is, over {distinct} distinct "
                f"evidence screens ({last.splitlines()[-1][:60]!r}) — the "
                f"recording is not showing what the terminal did"
            )

        mp4 = out_dir / "demo.mp4"
        first = frame_at(mp4, runs[0][1], rect, work / "a.png")
        final = frame_at(mp4, runs[-1][1], rect, work / "b.png")
        if first is None or final is None:
            return (
                failures
                + [f"{label}: could not cut frames at the run beats' midpoints"],
                None,
            )
        quality = psnr_db(work / "a.png", work / "b.png")
    if quality is None:
        failures.append(f"{label}: ffmpeg reported no PSNR for the two frames")
    if not failures:
        print(
            f"smoke: {label} stills {unique}/{wanted} distinct where the terminal "
            f"is, video {quality:.1f} dB apart, over {distinct} evidence screens"
        )
    return failures, quality


def _check_scored_region(take: dict, content: dict) -> list[str]:
    """Prove the rect is what makes the score mean anything (issue #17).

    Blank the app out of a real recording, keeping the recorder's chrome, and
    score it twice: over the content rect, and over the whole frame. The rect
    must rank the blanked copy far *below* the healthy one; the whole frame
    must fail to — that is the measured anti-correlation this check exists to
    keep fixed, and asserting it here means a future "simplification" back to a
    whole-frame score turns red instead of quietly scoring chrome.

    **This scores the rect the recorder reported, and that is deliberate** —
    the whole-frame arm below is only a comparison if the blanked control was
    built by blanking the region the recorder actually scores. What it costs is
    stated by issue #135: on its own, this control re-derives its own premise
    from the code under test, so a change that *abandoned* the rect for the
    whole frame is caught (the anti-correlation collapses) while a change that
    **moved or grew** it is invisible — the mutated rect is compared against
    the whole frame and the comparison still holds.

    The premise is therefore asserted before this runs, by
    `scored_region_failures` at the top of `check_content_pair`, against a rect
    this file computes from the app box it read off the live element. Do not
    call this without that check in front of it.
    """
    from demo_recording import content_report

    mp4 = take["out_dir"] / "demo.mp4"
    rect = tuple(int(v) for v in content["rect"])
    frame: Rect = (0, 0, take["info"]["size"][0], take["info"]["size"][1])
    # Outside the take's own directory: a blanked demo.mp4 sitting beside the
    # real one is exactly the artifact this whole issue is about somebody
    # picking up by mistake, and a run that fails leaves the directory behind.
    with tempfile.TemporaryDirectory() as tmp:
        return _scored_region_failures(
            mp4, rect, frame, Path(tmp) / "blanked.mp4", content_report
        )


def _scored_region_failures(
    mp4: Path, rect: Rect, frame: Rect, blanked: Path, content_report
) -> list[str]:
    if not blanked_copy(mp4, rect, blanked):
        return ["content: ffmpeg could not build the blanked control"]

    healthy_rect = content_report(mp4, rect)
    blank_rect = content_report(blanked, rect)
    healthy_frame = content_report(mp4, frame)
    blank_frame = content_report(blanked, frame)
    for name, report in (
        ("healthy/rect", healthy_rect),
        ("blank/rect", blank_rect),
        ("healthy/frame", healthy_frame),
        ("blank/frame", blank_frame),
    ):
        if not report.get("measured"):
            return [f"content: {name} could not be measured — {report.get('note')}"]

    failures: list[str] = []
    floor = healthy_rect["floor"]
    if not blank_rect["score"] < floor < healthy_rect["score"]:
        failures.append(
            f"content: scored over the content rect, the blanked recording "
            f"({blank_rect['score']}) and the healthy one "
            f"({healthy_rect['score']}) do not straddle the {floor} floor — "
            f"the score arm cannot tell a blank recording from a working one"
        )
    if not blank_rect["warnings"]:
        failures.append(
            "content: a recording with its app painted flat produced no warning at all"
        )
    # The point of the rect, stated as the thing that goes wrong without it.
    if blank_frame["score"] < healthy_frame["score"]:
        failures.append(
            f"content: scored over the *whole frame*, the blanked recording "
            f"({blank_frame['score']}) already ranks below the healthy one "
            f"({healthy_frame['score']}). The anti-correlation this rect "
            f"exists for is not present in this fixture, so passing the rect "
            f"assertion above no longer demonstrates anything — rebuild the "
            f"control or drop this claim (issue #17)"
        )
    else:
        print(
            f"smoke: content rect {healthy_rect['score']} vs blanked "
            f"{blank_rect['score']} (floor {floor}); whole frame "
            f"{healthy_frame['score']} vs blanked {blank_frame['score']} — "
            f"the frame ranks the blank recording higher, the rect does not"
        )
    return failures


def check_timeline(
    label: str,
    out_dir: Path,
    started_at: float,
    expected_beats: list[tuple[str, str | None]],
    expected_captions: list[str],
    frame_size: tuple[int, int],
    expected_segments: list[str | None] | None = None,
    expected_interludes: list[str] | None = None,
    clock: HostClock | None = None,
) -> list[str]:
    """The beat log the take left behind: timeline.json and timeline.md.

    Graded on the same three axes as everything else here. That it exists and
    parses is the cheap part; that its beats are the beats the storyboard
    actually performed, and that its timestamps point at the right frames of
    demo.mp4, is the part worth having.

    Used unchanged for a *merged* timeline — the one `stitch()` writes from
    several segments' — which is the point: a demo assembled from parts has to
    be graded by the same assertions as one recorded in a single take, or the
    segmented path is a second, softer standard. `expected_segments` names the
    segment each beat was recorded in (all None for a single take), and
    `expected_interludes` the lines any `interlude` beats show.

    `clock` is this harness's own reading of the host's wall clock over the
    take (see HostClock). The video is on that clock and the beat log is not,
    so the timing probes below are measured against `t_start + clock.before
    (t_start)` and the residual is what gets graded. Passing None is the same
    as a host that never stepped, and is what every caller that does not
    record a take of its own uses.
    """
    from demo_recording.content import media_duration
    from demo_recording.timeline import TIMELINE_SCHEMA

    failures: list[str] = []
    json_path = out_dir / "timeline.json"
    md_path = out_dir / "timeline.md"
    segments_of: list[str | None] = list(
        expected_segments
        if expected_segments is not None
        else [None] * len(expected_beats)
    )
    segment_indices = _expected_segment_indices(segments_of)

    if not json_path.is_file():
        return [f"{label}: {json_path} was never written"]
    if json_path.stat().st_mtime < started_at - 1:
        return [f"{label}: {json_path} is stale — it predates this run"]
    try:
        doc = json.loads(json_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{label}: {json_path} is not valid JSON: {exc}"]

    if doc.get("schema") != TIMELINE_SCHEMA:
        failures.append(
            f"{label}: timeline.json says schema {doc.get('schema')!r}, but the "
            f"recorder package exports TIMELINE_SCHEMA {TIMELINE_SCHEMA!r}"
        )
    if doc.get("media") != "demo.mp4":
        failures.append(
            f"{label}: timeline.json describes media {doc.get('media')!r}, "
            f"expected 'demo.mp4'"
        )
    if doc.get("segment") is not None:
        failures.append(
            f"{label}: timeline.json says segment {doc.get('segment')!r}; this "
            f"file describes a whole demo, so it should be null"
        )
    # `segments` is the merge's own record of what it joined and where. A take
    # that recorded in one go must not carry it: a consumer reading it would be
    # told a single recording has parts, and the offsets it lists are exactly
    # what a later reader would trust to map a timestamp back to a file.
    if not any(segments_of) and "segments" in doc:
        failures.append(
            f"{label}: timeline.json carries a `segments` list "
            f"({doc.get('segments')!r}), but this take was recorded in one "
            f"piece — that key means the file was assembled by stitch()"
        )

    # Which clock produced the take. A still committed to a repo is otherwise a
    # picture with no record of the conditions behind it, and a future diff
    # cannot tell "the UI changed" from "the frozen instant changed" — the one
    # question this feature exists to answer. Both takes record with
    # deterministic=True, so that is what the log has to say.
    record = doc.get("determinism")
    expected_record = {
        "deterministic": True,
        "clock": FROZEN_CLOCK,
        "timezone_id": FROZEN_TIMEZONE,
        "locale": FROZEN_LOCALE,
    }
    if record != expected_record:
        failures.append(
            f"{label}: timeline.json records the take's determinism settings "
            f"as {record!r}, expected {expected_record!r} — without them a "
            f"committed still says nothing about the clock that produced it"
        )

    beats = doc.get("beats")
    if not isinstance(beats, list):
        return failures + [f"{label}: timeline.json has no `beats` list"]

    # -- the beats are the beats the storyboard performed --------------------
    actual = [(b.get("verb"), b.get("selector")) for b in beats]
    if actual != expected_beats:
        counts = (
            ""
            if len(actual) == len(expected_beats)
            else (
                f" ({len(actual)} beats logged against the "
                f"{len(expected_beats)} the storyboard performs)"
            )
        )
        failures.append(
            f"{label}: timeline.json does not log the beats the storyboard "
            f"performs{counts} — first difference at index "
            f"{_first_difference(actual, expected_beats)}. Logged {actual!r}. "
            f"Either a verb stopped recording a beat, or record_{label}() "
            f"changed and WEB_BEATS/TERMINAL_BEATS is stale."
        )
    captions = [b.get("caption") for b in beats if b.get("verb") == "caption"]
    if captions != expected_captions:
        failures.append(
            f"{label}: the captions in timeline.json are {captions!r}, the "
            f"storyboard sets {expected_captions!r}"
        )

    # Every beat, not just the caption ones, must say which caption was on
    # screen while it ran — that context is what makes a `shot` or a `click`
    # beat mean anything to a reviewer, and it is what timeline.md quotes over
    # each still. Checking only `verb == "caption"` beats is blind to it: drop
    # the recorder's `self._caption = text` and the caption beats stay perfect
    # while every other beat goes blank. Derived from the two hand-written
    # lists above, never from the log being graded.
    context = _expected_context(expected_beats, expected_captions, expected_interludes)
    if context is not None:
        logged = [b.get("caption") for b in beats]
        if logged != context:
            failures.append(
                f"{label}: beats do not carry the caption they ran under — "
                f"first difference at index {_first_difference(logged, context)}. "
                f"Logged {logged!r}."
            )

    # -- indices and timestamps ---------------------------------------------
    previous_end = 0.0
    first_start: float | None = None
    covered = 0.0
    for position, beat in enumerate(beats):
        where = f"{label}: beat {position} ({beat.get('verb')!r})"
        if beat.get("index") != position:
            failures.append(
                f"{where} carries index {beat.get('index')!r}, but sits at "
                f"position {position} in the list"
            )
        t_start, t_end = beat.get("t_start"), beat.get("t_end")
        if not isinstance(t_start, (int, float)) or not isinstance(t_end, (int, float)):
            failures.append(f"{where} has non-numeric timestamps {t_start!r}/{t_end!r}")
            continue
        if t_start < 0:
            failures.append(f"{where} starts at {t_start:.3f}s, before the video does")
        if t_end < t_start - BEAT_ORDER_SLACK_S:
            failures.append(
                f"{where} ends at {t_end:.3f}s, before it starts ({t_start:.3f}s)"
            )
        if t_start < previous_end - BEAT_ORDER_SLACK_S:
            # A stitched log is allowed to run backwards at a capture seam
            # exactly as loudly as its own artifact says (issue #263): a
            # backward step deletes wall time from a part's video without
            # touching its beat log, the merge lays the next part out by the
            # real file duration, and the recorder REPORTS the overlap in
            # `overlaps` rather than clamping timestamps to instants neither
            # clock has. So a seam the document publishes — this beat, seam
            # flagged, published size covering the observed one — is the
            # documented healthy shape on a stepping host, and an overlap
            # anywhere else, or bigger than published, still fails.
            published = any(
                rec.get("seam") is True
                and rec.get("beat") == position
                and isinstance(rec.get("overlap"), (int, float))
                and previous_end - t_start <= rec["overlap"] + BEAT_ORDER_SLACK_S
                for rec in doc.get("overlaps") or []
            )
            if not published:
                failures.append(
                    f"{where} starts at {t_start:.3f}s, before the previous "
                    f"beat ended ({previous_end:.3f}s) — the log is not "
                    f"monotonic, and timeline.json publishes no seam overlap "
                    f"covering it (#263)"
                )
        previous_end = max(previous_end, t_end)
        if first_start is None:
            first_start = t_start
        covered += max(0.0, t_end - t_start)
        # A verb that provably occupies the screen for a known minimum must
        # say so. `caption(text)` holds 0.6 + 0.34/word (>= 1.4 s) with speech
        # off and `hold()` has a 1.5 s perception floor, both enforced by the
        # recorder itself — so a beat here that reports less than a second is
        # not reporting when its verb returned.
        held = beat.get("verb") == "hold" or (
            beat.get("verb") == "caption" and beat.get("caption")
        )
        if held and t_end - t_start < MIN_HELD_BEAT_SPAN_S:
            failures.append(
                f"{where} spans {t_end - t_start:.3f}s, but the recorder holds "
                f"this verb for at least {MIN_HELD_BEAT_SPAN_S}s — `t_end` is "
                f"not being recorded when the verb returned"
            )
        # Which segment recorded this beat, and where it sat in that segment's
        # own log. `index` is renumbered by the merge, so it cannot answer
        # "which beat is this" across a stitch; `(segment, segment_index)` is
        # the pair that can, and #9 will name per-beat evidence from it. Both
        # expectations are derived from the hand-written list above.
        want_segment = segments_of[position] if position < len(segments_of) else None
        if beat.get("segment") != want_segment:
            failures.append(
                f"{where} says it was recorded in segment "
                f"{beat.get('segment')!r}, expected {want_segment!r}"
            )
        want_segment_index = (
            segment_indices[position] if position < len(segment_indices) else None
        )
        if beat.get("segment_index") != want_segment_index:
            failures.append(
                f"{where} carries segment_index {beat.get('segment_index')!r}, "
                f"expected {want_segment_index!r} — it is the beat's position "
                f"within its own segment, and unlike `index` a merge must not "
                f"renumber it (issue #22)"
            )

    # Beats run back to back, so their spans should account for essentially
    # all of the time between the first starting and the last ending. This is
    # the assertion that survives any single beat being plausible: collapse
    # every `t_end` onto its `t_start` and the coverage goes to zero while
    # every other timestamp check still passes.
    if first_start is not None and previous_end > first_start:
        elapsed = previous_end - first_start
        share = covered / elapsed
        if share < MIN_BEAT_TIME_COVERAGE:
            failures.append(
                f"{label}: the beats span {covered:.2f}s between them but cover "
                f"{first_start:.2f}s to {previous_end:.2f}s ({share:.0%} of "
                f"{elapsed:.2f}s, floor {MIN_BEAT_TIME_COVERAGE:.0%}) — `t_end` "
                f"is carrying no information about how long verbs took"
            )

    # -- the mp4 the timestamps are relative to ------------------------------
    #
    # How far the host's wall clock had stepped by a given point in the take.
    # The video is on that clock and the beats are not (issue #215), so every
    # comparison between the two below goes through this. Absent a reading the
    # correction is zero and every bar is what it was.
    #
    # **An uncovered reading is worse than no reading**, and this is where
    # issue #245's runs went red about something untrue: a watcher that was
    # away for seconds still hands out a `before()`, and subtracting it moved
    # the caption search window 1.26 s away from the caption. So an uncovered
    # clock is refused here, loudly, rather than used or silently zeroed —
    # zeroing it would grade the take against a bar it no longer meets and
    # blame the recorder for the harness's own blind spot.
    if clock is not None and not clock.covered:
        failures.append(
            f"{label}: this harness's own wall-clock watcher was away for up "
            f"to {clock.max_gap:.2f}s (limit {HOST_CLOCK_MAX_GAP_S:.2f}s, "
            f"{clock.samples} samples), so it cannot say where the video sat "
            f"under the beat log for this take. Nothing below is corrected "
            f"and nothing below is graded on alignment. This is the harness "
            f"refusing to measure, not the recorder failing (issue #247)"
        )
        clock = None
    stepped = clock.before if clock is not None else (lambda _t: 0.0)
    mp4 = out_dir / "demo.mp4"
    duration = doc.get("duration")
    if not mp4.is_file():
        failures.append(f"{label}: timeline.json describes {mp4}, which is not there")
    elif not isinstance(duration, (int, float)):
        failures.append(
            f"{label}: timeline.json has no numeric duration ({duration!r})"
        )
    else:
        try:
            probed = media_duration(mp4)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            failures.append(f"{label}: ffprobe could not read {mp4}: {exc}")
            probed = None
        if probed is not None and abs(probed - duration) > DURATION_TOLERANCE_S:
            failures.append(
                f"{label}: timeline.json says demo.mp4 is {duration}s, ffprobe "
                f"says {probed:.3f}s"
            )
        # On the *video's* clock: the beats are `time.monotonic()` and the
        # file is the host's wall clock, so a take whose host stepped has a
        # last beat past the end of a file that is exactly that much shorter
        # (issue #215). Uncorrected, this fires on a healthy recorder.
        last_end = previous_end + stepped(previous_end)
        if last_end > (probed or duration) + DURATION_TOLERANCE_S:
            failures.append(
                f"{label}: the last beat ends at {previous_end:.3f}s, which "
                f"the host's measured wall-clock steps put at {last_end:.3f}s "
                f"in the video — past the end of a {duration}s demo.mp4. The "
                f"timestamps are not on the same clock as the video, and the "
                f"clock this suite can see is not what put them there."
            )

    # -- every still a beat names is on disk ---------------------------------
    logged_stills = [b["still"] for b in beats if b.get("still")]
    for rel in logged_stills:
        if not (out_dir / rel).is_file():
            failures.append(
                f"{label}: beat still {rel!r} does not exist — timeline.json "
                f"points a reviewer at a file that was never written"
            )
    on_disk = sorted(p.name for p in (out_dir / "images").glob("*.png"))
    named = sorted(Path(rel).name for rel in logged_stills)
    if named != on_disk:
        failures.append(
            f"{label}: timeline.json names stills {named!r}, but images/ holds "
            f"{on_disk!r} — a shot() happened without a beat, or the other way"
        )

    # -- timeline.md is rendered from the same beats -------------------------
    if not md_path.is_file():
        failures.append(f"{label}: {md_path} was never written")
    elif md_path.stat().st_mtime < started_at - 1:
        failures.append(f"{label}: {md_path} is stale — it predates this run")
    else:
        markdown = md_path.read_text()
        for rel in logged_stills:
            if f"]({rel})" not in markdown:
                failures.append(
                    f"{label}: timeline.md does not embed the still {rel!r} that "
                    f"timeline.json records"
                )
        for text in (c for c in expected_captions if c):
            if text not in markdown:
                failures.append(f"{label}: timeline.md does not mention {text!r}")
        # The beat table specifically, not just "the text appears somewhere":
        # every expected caption also sits above a still in the Stills section,
        # so the whole table can go missing and the checks above still pass.
        # The table is the only place non-`shot` beats — every click, every
        # spotlight, the shape of the take — appear at all.
        rows = [ln for ln in markdown.splitlines() if _MD_ROW.match(ln)]
        if len(rows) != len(beats):
            failures.append(
                f"{label}: timeline.md's beat table has {len(rows)} rows for "
                f"{len(beats)} beats — the table is the only place a beat "
                f"without a still shows up at all"
            )
        for beat in beats:
            verb = str(beat.get("verb"))
            if not any(f"| {beat.get('index')} |" in r and verb in r for r in rows):
                failures.append(
                    f"{label}: timeline.md's beat table has no row for beat "
                    f"{beat.get('index')} ({verb!r})"
                )
                break

    # -- the acceptance criterion: timestamps point at the right frames ------
    spoken = [b for b in beats if b.get("verb") == "caption" and b.get("caption")]
    probes: list[tuple[str, dict]] = []
    if spoken:
        probes.append(("first caption", spoken[0]))
    last = next(
        (b for b in reversed(spoken) if b.get("caption") == PROBE_CAPTION), None
    )
    if last is None:
        failures.append(
            f"{label}: no beat logs the closing caption {PROBE_CAPTION!r}, so "
            f"the end of the timeline cannot be checked against the video"
        )
    elif last is not spoken[0]:
        probes.append(("closing caption", last))
    if not spoken:
        failures.append(f"{label}: no caption beats at all to time against")

    # How far the host's wall clock had stepped by each probe. The video is on
    # that clock, so this is where the beat really sits in demo.mp4 —
    # subtracted here rather than absorbed by a wider bar, because a step is a
    # *measured* quantity with a timestamp of its own and a bar is a guess
    # about all of them at once. Absent a reading, the correction is zero and
    # every bar below is what it was.
    measured: list[tuple[str, float]] = []
    for what, probe in probes:
        if not mp4.is_file() or not isinstance(probe.get("t_start"), (int, float)):
            continue
        text = probe["caption"]
        t_start = float(probe["t_start"])
        shift = stepped(t_start)
        expect_at = t_start + shift
        seen_at, note = caption_appearance_s(
            label, mp4, caption_probe_band(label, frame_size), expect_at
        )
        if seen_at is None:
            failures.append(
                f"{label}: the {what} could not be timed against demo.mp4 — {note}"
            )
            continue
        skew = seen_at - expect_at
        measured.append((what, skew))
        # Both numbers, always. The raw one is what somebody scrubbing the file
        # sees; the corrected one is what is graded. Printing only the graded
        # one would say nothing about a take that really did lose 0.8 s.
        raw = seen_at - t_start
        because = (
            f", raw {raw * 1000:+.0f} ms of which {shift * 1000:+.0f} ms is "
            f"the host's wall clock stepping"
            if abs(shift) >= HOST_CLOCK_MIN_STEP_S
            else ""
        )
        where = (
            f"timeline.json puts the {what} {text!r} at {t_start:.2f}s, the "
            f"host's measured wall-clock steps put that at {expect_at:.2f}s in "
            f"the video, and demo.mp4 shows it at {seen_at:.2f}s "
            f"({skew * 1000:+.0f} ms)"
        )
        if skew > MAX_LOG_EARLY_S:
            failures.append(
                f"{label}: {where} — the log is {skew * 1000:.0f} ms ahead of "
                f"the frame, over the {MAX_LOG_EARLY_S * 1000:.0f} ms bar. "
                f"{log_early_causes(clock, t_start)} ({note})"
            )
        elif skew < -MAX_CAPTURE_LOSS_S:
            failures.append(
                f"{label}: {where} — the video is {-skew * 1000:.0f} ms ahead "
                f"of the log **with the host's wall-clock steps already taken "
                f"out**, past the {MAX_CAPTURE_LOSS_S * 1000:.0f} ms this file "
                f"allows for everything else (the screencast's first frame, "
                f"the 40 ms sampling grid, the caption's fade). "
                f"{clock.describe() if clock else 'This take ran without a host-clock reading'}"
                f". So this is not issue #215's clock step: either TICKER_JS "
                f"stopped working, or the capture lost time some other way. "
                f"({note})"
            )
        else:
            print(
                f"smoke: {label} {what} {text!r} logged at {t_start:.2f}s, on "
                f"screen at {seen_at:.2f}s ({skew * 1000:+.0f} ms{because})"
            )

    # The sharp one: whatever the capture loses, it loses for every frame after
    # it, so both probes move together and the difference cancels. A beat
    # stamped somewhere other than where its verb ran does not.
    #
    # A host wall-clock step landing *between* the probes used to reach this
    # bar too, and used to be indistinguishable from the beat log's own error
    # — 680 ms of it was measured on this box (issue #209) and read as a
    # mid-take screencast stall. It no longer reaches here: the step is
    # timestamped, so `stepped()` above subtracts it from the probes it
    # precedes and from no others, which is exactly the distinction this bar
    # could not make for itself.
    if len(measured) == 2:
        drift = measured[1][1] - measured[0][1]
        # ...as long as both probes rode the same capture. Across a segment
        # boundary they did not, and the cancellation argument goes with it —
        # see MAX_CROSS_SEGMENT_DRIFT_S.
        same_capture = probes[0][1].get("segment") == probes[1][1].get("segment")
        bound = MAX_SKEW_DRIFT_S if same_capture else MAX_CROSS_SEGMENT_DRIFT_S
        why = (
            "Both skews above already have the host's measured wall-clock "
            "steps taken out of them, per probe — which is the one cause that "
            "used to land here and could not be told from the beat log's own "
            "(issue #215). What is left is time between beats not being "
            "measured monotonically, or a beat stamped somewhere other than "
            "where its verb ran. "
            f"{clock.describe() if clock else 'This take ran without a host-clock reading, so nothing was taken out'}."
            if same_capture
            else "These two probes are in different segments, so they rode "
            "different captures and this bar is only a flake guard — the "
            "sharp per-segment ones are in check_merge_offset()."
        )
        if abs(drift) > bound:
            failures.append(
                f"{label}: the {measured[0][0]} is {measured[0][1] * 1000:+.0f} ms "
                f"off the video and the {measured[1][0]} is "
                f"{measured[1][1] * 1000:+.0f} ms — they have drifted "
                f"{drift * 1000:+.0f} ms apart, over the "
                f"{bound * 1000:.0f} ms bar. {why}"
            )
        else:
            print(
                f"smoke: {label} beat clock holds across the take ({drift * 1000:+.0f} ms)"
            )
    if not failures:
        print(f"smoke: {label} timeline.json ok ({len(beats)} beats)")
    return failures


def _same_frame(mp4: Path, at: float, png: Path) -> bool:
    """Is `png` the frame of `mp4` at `at` seconds?

    Answered by cutting that frame again, with the same ffmpeg the recorder
    used, and comparing the bytes. Exact rather than approximate, which matters
    both ways: it resolves a single frame (40 ms), and it needs no threshold to
    argue about. What it does *not* grade is whether `at` is the right second —
    that is the midpoint check above, and the two are only worth anything
    together.

    The scale filter is the recorder's own (#343: review frames are at most
    1024 px wide, never upscaled), written out by hand here rather than
    imported — the comparison is byte-exact, so an unasked-for change to the
    recorder's filter fails this check instead of being absorbed by it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        reference = Path(tmp) / "reference.png"
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
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1024,iw)':-1",
                "-update",
                "1",
                str(reference),
            ],
            capture_output=True,
        )
        if proc.returncode != 0 or not reference.is_file():
            return False
        return (
            hashlib.sha256(reference.read_bytes()).hexdigest()
            == hashlib.sha256(png.read_bytes()).hexdigest()
        )


def _beat_span(beats: list[dict], verb: str, target: str | None) -> float | None:
    """How long the single (verb, target) beat took, or None if there is not
    exactly one of them."""
    hits = [
        b
        for b in beats
        if b.get("verb") == verb
        and b.get("selector") == target
        and isinstance(b.get("t_start"), (int, float))
        and isinstance(b.get("t_end"), (int, float))
    ]
    if len(hits) != 1:
        return None
    return float(hits[0]["t_end"]) - float(hits[0]["t_start"])


def check_form_pacing(label: str, out_dir: Path) -> list[str]:
    """The form verbs hold the frame long enough to be watched (issue #130).

    Reads `timeline.json`, which is also the artifact the issue is about: a
    storyboard that drove the page through `rec.page.keyboard` writes no beat
    here at all, so the first thing this fails on is the beat being missing.
    """
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    beats = doc.get("beats") or []
    failures: list[str] = []

    presses = [b for b in beats if b.get("verb") == "press"]
    if len(presses) != len(WEB_PRESS_KEYS):
        failures.append(
            f"{label}: timeline.json holds {len(presses)} `press` beat(s), "
            f"expected {len(WEB_PRESS_KEYS)} — either the storyboard changed "
            f"or press() stopped recording a beat, which is the whole of what "
            f"issue #130 asked for"
        )
    for beat, key in zip(presses, WEB_PRESS_KEYS, strict=False):
        # The key by name, in the log. `rec.page.keyboard.press` could not do
        # this, and it is the issue's acceptance criterion word for word.
        if beat.get("selector") != key:
            failures.append(
                f"{label}: beat {beat.get('index')} is a `press` whose target "
                f"is {beat.get('selector')!r}, expected {key!r} — the beat does "
                f"not name the key it pressed"
            )
        # `or 0.0` rather than a default: a beat whose verb raised carries a
        # null `t_end`, and reading that as zero is the honest answer here —
        # a press that did not finish did not hold anything.
        span = float(beat.get("t_end") or 0.0) - float(beat.get("t_start") or 0.0)
        if span < MIN_PRESS_BEAT_SPAN_S:
            failures.append(
                f"{label}: the `press` beat for {key!r} spans {span:.3f}s, "
                f"under the {MIN_PRESS_BEAT_SPAN_S}s bar — the key went down "
                f"and the verb returned in the same frame, so the change it "
                f"caused is on screen for less time than a saccade takes"
            )

    cleared = _beat_span(beats, "clear", "#search")
    clicked = _beat_span(beats, "click", "#refresh")
    if cleared is None or clicked is None:
        failures.append(
            f"{label}: timeline.json does not hold exactly one "
            f"clear('#search') beat and one click('#refresh') beat "
            f"(spans {cleared!r} and {clicked!r}), so what clear() costs over "
            f"a plain click cannot be measured"
        )
    elif cleared - clicked < MIN_CLEAR_OVER_CLICK_S:
        failures.append(
            f"{label}: the clear('#search') beat spans {cleared:.3f}s against "
            f"{clicked:.3f}s for click('#refresh'), a difference of "
            f"{cleared - clicked:.3f}s under the {MIN_CLEAR_OVER_CLICK_S}s bar "
            f"— clear() is doing no more than a click and a delete, so the "
            f"field empties between two frames with no selection on screen to "
            f"say where the text went"
        )
    if not failures:
        print(
            f"smoke: {label} form verbs hold the frame "
            f"({len(presses)} press beats, "
            f"clear costs {cleared - clicked:+.2f}s over a click)"
        )
    return failures


def _check_unstated_holes(
    label: str, clock, listed: list[dict], beats: dict
) -> list[str]:
    """Frames of a beat the host's clock deleted, that the sheet calls ordinary.

    A backward step of Δ takes a Δ-wide window of wall time out of the file
    (issue #256), and a beat whose midpoint falls inside one has no frame in
    `demo.mp4` at all. The recorder cuts the last frame before the gap, which
    is the only honest thing it can cut — and the sheet then has to *say* that,
    or the reviewer reads a picture of the moment before the step as a picture
    of the beat. That is what shipped: `seg-run1`'s `beat-05.png`, cut a whole
    step early, showing the previous caption, numbered for the next one.

    Only the missing direction is graded. A frame the recorder marks that this
    watcher did not find a hole for is *not* failed here: the two samplers are
    on their own 20 ms grids, and whether they agree about the steps at all is
    `check_capture_clock`'s claim, made against the record rather than against
    a derived consequence of it. For the same reason a midpoint within
    `MAX_CLOCK_STEP_TIME_DISAGREEMENT_S` of either edge of the hole is left
    alone: neither watcher knows which side of the edge it fell on.

    Pure in its inputs, and that is deliberate — a host that does not step its
    clock produces no holes and can never reach the failure below, so the only
    way anyone sees this fail is `HostClockHole` in `tests/unit` handing it a
    scripted clock. Named `_check_…` so `smoke-inject`'s roster counts it: an
    assertion site the coverage report cannot see makes that report understate
    what exists, which is the one direction a coverage claim must never fail in.
    """
    if clock is None:
        return []
    failures = []
    for frame in listed:
        beat = beats.get(frame.get("beat"))
        if beat is None or not isinstance(beat.get("t_start"), (int, float)):
            continue
        # `t_end` guarded as well as `t_start`, because a beat can reach here
        # without one — `check_beat_frames` builds `beats` straight from
        # `timeline.json` — and a harness check that raises instead of
        # reporting takes the whole arm down over a beat it had nothing to say
        # about.
        if not isinstance(beat.get("t_end"), (int, float)):
            continue
        middle = (float(beat["t_start"]) + float(beat["t_end"])) / 2
        gap = clock.hole(middle)
        near_edge = any(
            abs(middle - at) <= MAX_CLOCK_STEP_TIME_DISAGREEMENT_S
            for at, _delta in clock.steps
        )
        if gap <= MAX_CLOCK_STEP_TIME_DISAGREEMENT_S or near_edge:
            continue
        if not frame.get("no_video"):
            failures.append(
                f"{label}: beat {frame.get('beat')} runs "
                f"{beat['t_start']}-{beat['t_end']}s and this harness watched "
                f"the host's wall clock step backwards over its midpoint "
                f"({middle:.3f}s) — the video resumes {gap * 1000:.0f} ms after "
                f"it, so there is no frame of that beat in demo.mp4 at all. "
                f"{frame.get('file')} is at {frame.get('t')}s with nothing in "
                f"frames.json saying so, and a sheet that presents the last "
                f"frame before the gap as the beat's own hands the reviewer a "
                f"picture of the moment before the step (issue #256)"
            )
    return failures


def check_beat_frames(
    label: str,
    out_dir: Path,
    started_at: float,
    expected_beats: list[tuple[str, str | None]],
    expected_captions: list[str],
    frame_size: tuple[int, int],
    expected_interludes: list[str] = [],  # noqa: B006 - read-only, never mutated
    clock: HostClock | None = None,
) -> list[str]:
    """`frames/` — every beat a kept frame or a named drop, at its midpoint.

    Four claims, and the last one is the acceptance criterion of issue #8:

      * **every beat is accounted for**: a kept frame named for the beat, or
        a `deduped` entry naming which kept picture it repeats (#343) — both
        counted against the hand-written beat list rather than against the
        recorder's own idea of how many beats there were, and a dropped
        frame must be named in frames.md, matched to a kept frame under the
        threshold, and off disk;
      * **each frame is the moment it says it is** — its timestamp is the
        beat's midpoint computed here from `timeline.json`, moved onto the
        video's clock by *this harness's own* wall-clock watcher (issue #229),
        and the PNG is byte-identical to that second cut out of `demo.mp4`
        again. Only
        together: the first without the second passes a manifest that says the
        right time over the wrong picture, and the second without the first
        passes a frame faithfully cut from the wrong second;
      * **a beat the clock deleted is not presented as a frame of itself** —
        `_check_unstated_holes()`, which fires only where this harness's own
        watcher saw the wall clock step backwards over a beat's midpoint
        (issue #256);
      * **the sheet says which clock it cut them on.** On a host that never
        steps its clock the corrected instant and the uncorrected one are the
        same number, so the bullet above cannot tell a recorder that applies
        the record from one that ignores it. What it can tell is whether the
        sheet *claims* a correction it could not compute;
      * **the sheet leaks no storyboard.** `frames.md` goes to a context-free
        reviewer who is asked what story the pictures tell. A caption, a verb
        or a selector printed beside a frame answers that for them, and the
        `fps=1/3` handoff this replaces did not leak any of it;
      * **frame N shows beat N** — `_check_frame_captions()`. The two above are
        both about *placement*; a frame cut at exactly the right second of a
        video that slid under the beat log is a picture of the wrong beat, and
        neither of them can see it. This one looks at the pixels, against the
        hand-written storyboard, and says so.
    """
    from demo_recording.frames import FRAMES_SCHEMA

    failures: list[str] = []
    frames_dir = out_dir / "frames"
    json_path, md_path = frames_dir / "frames.json", frames_dir / "frames.md"
    if not json_path.is_file():
        return [f"{label}: {json_path} was never written"]
    if json_path.stat().st_mtime < started_at - 1:
        return [f"{label}: {json_path} is stale — it predates this run"]
    try:
        manifest = json.loads(json_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{label}: {json_path} is not valid JSON: {exc}"]
    if manifest.get("schema") != FRAMES_SCHEMA:
        failures.append(
            f"{label}: frames.json says schema {manifest.get('schema')!r}, but "
            f"the recorder package exports FRAMES_SCHEMA {FRAMES_SCHEMA!r}"
        )
    if manifest.get("skipped"):
        return failures + [
            f"{label}: the recorder wrote no review frames — {manifest['skipped']}"
        ]

    # -- every beat: a kept frame or a named drop, named for its beat --------
    #
    # Kept and deduplicated together must cover the hand-written beat list
    # exactly (#343). Counting only the kept frames would let a beat vanish
    # without a record; counting kept plus deduped and nothing else is what
    # makes "no beat disappears silently" a checkable sentence.
    listed = [f for f in manifest.get("frames") or [] if f.get("kind") == "beat"]
    dropped = [f for f in manifest.get("deduped") or [] if f.get("kind") == "beat"]
    wanted = [f"beat-{i:02d}.png" for i in range(len(expected_beats))]
    named = sorted(str(f.get("file")) for f in [*listed, *dropped])
    if named != wanted:
        failures.append(
            f"{label}: frames/ accounts for {named!r} (kept plus deduped) for "
            f"the {len(expected_beats)} beats the storyboard performs — first "
            f"difference at index {_first_difference(named, wanted)}"
        )
    for frame in [*listed, *dropped]:
        if frame.get("file") != f"beat-{frame.get('beat'):02d}.png":
            failures.append(
                f"{label}: frame {frame.get('file')!r} claims to be beat "
                f"{frame.get('beat')!r} — the file name and the manifest "
                f"disagree about which beat a reviewer is looking at"
            )
            break

    # -- a dropped frame is named on the sheet, matched, and off disk --------
    #
    # The threshold is written out by hand (3.0 RMSE, so mse 9.0): a bound
    # imported from the recorder would agree with whatever the recorder says.
    kept_files = {str(f.get("file")) for f in manifest.get("frames") or []}
    sheet_text = md_path.read_text() if md_path.is_file() else ""
    for drop in manifest.get("deduped") or []:
        name = str(drop.get("file"))
        if (frames_dir / name).exists():
            failures.append(
                f"{label}: {name} was deduplicated off the sheet but its PNG "
                f"is still on disk — the directory the skill hands over whole "
                f"carries a picture the manifest disowned"
            )
        if str(drop.get("matches")) not in kept_files:
            failures.append(
                f"{label}: frames.json says {name} repeats "
                f"{drop.get('matches')!r}, which is not a kept frame — the "
                f"reader is pointed at a picture that is not on the sheet"
            )
        rmse = drop.get("rmse")
        if not isinstance(rmse, (int, float)) or rmse >= 3.0:
            failures.append(
                f"{label}: {name} was dropped with rmse {rmse!r}, at or over "
                f"the 3.0 the recorder promises — the sheet withheld a frame "
                f"whose picture is not a repeat"
            )
        if f"`{name}` is not on this sheet" not in sheet_text:
            failures.append(
                f"{label}: frames.md never says {name} was left off the sheet "
                f"— the beat disappears without a printed line saying so"
            )

    on_disk = sorted(p.name for p in frames_dir.glob("*.png"))
    claimed = sorted(str(f.get("file")) for f in manifest.get("frames") or [])
    if on_disk != claimed:
        failures.append(
            f"{label}: frames.json names {claimed!r} but frames/ holds "
            f"{on_disk!r} — a frame was written without being listed, left "
            f"over from an earlier run, or the other way round"
        )
    for name in claimed:
        png = frames_dir / name
        if not png.is_file():
            failures.append(f"{label}: frames.json names {name!r}, which is not there")
        elif png.stat().st_size < MIN_PNG_BYTES:
            failures.append(
                f"{label}: frame {name} is only {png.stat().st_size} bytes "
                f"(expected at least {MIN_PNG_BYTES})"
            )

    # -- each frame is the moment it says it is ------------------------------
    #
    # The beat's midpoint is on the beat log's clock and the seek is on the
    # video's, so the instant to expect is the midpoint **plus what the host's
    # wall clock did before it** (issue #229). That correction is taken from
    # *this harness's own* watcher, never from the take's `capture_clock`: the
    # recorder cut the frames with its own record, and grading a record against
    # itself passes on whatever number it wrote.
    doc = json.loads((out_dir / "timeline.json").read_text())
    beats = {b.get("index"): b for b in doc.get("beats") or []}
    mp4 = out_dir / "demo.mp4"
    duration = float(doc.get("duration") or 0.0)
    stepped = clock.before if clock is not None else (lambda _t: 0.0)
    step_times = [at for at, _delta in (clock.steps if clock is not None else [])]
    measured = 0
    ungraded = 0
    for frame in listed:
        beat = beats.get(frame.get("beat"))
        png = frames_dir / str(frame.get("file"))
        if beat is None or not png.is_file():
            continue
        middle = (float(beat["t_start"]) + float(beat["t_end"])) / 2
        at = float(frame["t"])
        # A midpoint sitting on top of a step is not placement-gradeable: the
        # two samplers are on their own 20 ms grids and do not both know which
        # side of it the beat fell on, and a bar as wide as a step would grade
        # nothing. Counted out loud rather than dropped silently — and the
        # byte comparison below still runs on every frame.
        on_a_step = any(
            abs(middle - when) <= MAX_CLOCK_STEP_TIME_DISAGREEMENT_S
            for when in step_times
        )
        want = middle + stepped(middle)
        if on_a_step:
            ungraded += 1
        elif abs(at - want) > MAX_FRAME_PLACEMENT_S and at < duration - 0.2:
            failures.append(
                f"{label}: {frame.get('file')} was taken at {at:.3f}s, but beat "
                f"{frame.get('beat')} runs {beat['t_start']}-{beat['t_end']}s "
                f"and its midpoint sits at {want:.3f}s in the video "
                f"({middle:.3f}s on the beat log, {stepped(middle):+.3f}s of "
                f"wall clock before it) — "
                f"the frame is not the moment the sheet numbers it for."
                # ...and where that instant has no video at all, `want` is the
                # last frame before the gap and not the midpoint's own moment.
                # A reader sent to look for the beat at `want` would otherwise
                # go looking for a frame the file does not contain (#256).
                + hole_clause(clock, middle, want)
            )
        if not mp4.is_file() or not duration:
            continue
        measured += 1
        if not _same_frame(mp4, at, png):
            failures.append(
                f"{label}: {frame.get('file')} is not the frame of demo.mp4 at "
                f"the {at:.3f}s it claims — cutting that second again produces "
                f"a different picture. It is a frame of another moment, of "
                f"another take, or left over from an earlier run."
            )
    if measured < len(listed):
        failures.append(
            f"{label}: only {measured} of {len(listed)} review frames were "
            f"compared against demo.mp4 — the rest went ungraded, which is not "
            f"the same as passing"
        )

    # -- and the sheet says which clock it cut them on -----------------------
    #
    # The one half of #229 that is gradeable on a host whose clock never steps.
    # There the corrected instant and the uncorrected one are the same number,
    # so nothing above can tell them apart — but "a correction was applied" and
    # "nobody could compute one" are still two different sentences, and a sheet
    # that let them look alike would be claiming an accuracy nobody measured.
    stated = manifest.get("clock_correction")
    if not isinstance(stated, dict):
        failures.append(
            f"{label}: frames.json says nothing about the clock its frames "
            f"were cut on — a reviewer reading these timestamps cannot tell a "
            f"sheet corrected for the host's wall clock from one cut on the "
            f"raw beat log, and they are up to seconds apart"
        )
    elif clock is not None and clock.covered and not stated.get("applied"):
        failures.append(
            f"{label}: the sheet says its frames were cut uncorrected "
            f"({stated.get('note')}) on a take this harness watched to within "
            f"{clock.max_gap:.3f}s — the recorder had a record to cut them "
            f"with and did not use it"
        )
    elif md_path.is_file():
        # A deliberately weak last line, and worth saying so: this only asks
        # that the sheet mentions the clock at all — it cannot tell a sheet
        # that stated the *wrong* one of the three cases from one that stated
        # the right one. The weight is on the `applied` check above and on the
        # placement check before it; this is here so a renderer that dropped
        # the sentence entirely does not pass silently.
        if "wall clock" not in md_path.read_text():
            failures.append(
                f"{label}: frames.md never mentions the wall clock, so the "
                f"sheet a reviewer is handed states nothing about which clock "
                f"its timestamps are on (frames.json says applied="
                f"{stated.get('applied')!r})"
            )

    # -- the sheet carries no storyboard -------------------------------------
    if not md_path.is_file():
        failures.append(f"{label}: {md_path} was never written")
    else:
        markdown = md_path.read_text()
        for frame in listed:
            name = str(frame.get("file"))
            if f"]({name})" not in markdown:
                failures.append(f"{label}: frames.md does not embed {name!r}")
        spoken = {*expected_captions, *expected_interludes}
        leaked = [text for text in spoken if text and text in markdown]
        leaked += [
            target
            for _, target in expected_beats
            if target and f"`{target}`" in markdown
        ]
        if leaked:
            failures.append(
                f"{label}: frames.md hands a context-free reviewer "
                f"{sorted(set(leaked))!r} — the sheet is supposed to be the "
                f"pictures and nothing else, and every one of those tells the "
                f"reviewer what to see before they look"
            )
    for key in ("caption", "verb", "selector"):
        carrying = [f["file"] for f in manifest.get("frames") or [] if key in f]
        if carrying:
            failures.append(
                f"{label}: frames.json carries a {key!r} for {carrying[0]} — "
                f"the manifest is an index into timeline.json, and duplicating "
                f"the storyboard into it is how it ends up back on the sheet"
            )

    failures += _check_unstated_holes(label, clock, listed, beats)
    failures += _check_frame_captions(
        label,
        out_dir,
        frame_size,
        # Kept frames plus the deduplicated beats, which are graded through
        # the kept picture each one matched — see the loop's own comment.
        [*listed, *dropped],
        beats,
        _expected_context(expected_beats, expected_captions, expected_interludes),
        clock,
    )
    failures += _check_stale_frames(label, out_dir, manifest)
    failures += _check_segment_refusal(label, out_dir, doc)
    failures += _check_scene_fallback(label, out_dir, doc)

    if not failures:
        cut = (
            "on the beat log, uncorrected"
            if not (isinstance(stated, dict) and stated.get("applied"))
            else f"{stated.get('total'):+.2f}s of wall clock applied"
            if stated.get("total")
            else "on a wall clock that was watched and held still"
        )
        print(
            f"smoke: {label} frames/ ok ({len(listed)} beat frames kept, "
            f"{len(dropped)} deduplicated and named, each kept frame "
            f"byte-identical to the demo.mp4 frame it claims to be; cut {cut}"
            + (
                f", {ungraded} not placement-graded within "
                f"{MAX_CLOCK_STEP_TIME_DISAGREEMENT_S}s of a step"
                if ungraded
                else ""
            )
            + ")"
        )
    return failures


def _check_frame_captions(
    label: str,
    out_dir: Path,
    frame_size: tuple[int, int],
    listed: list[dict],
    beats: dict[int, dict],
    context: list[str] | None,
    clock: HostClock | None = None,
) -> list[str]:
    """Frame N shows beat N — measured on the pixels, one bit per frame.

    For every beat the **hand-written** storyboard says had a caption bar on
    screen, the frame must show one; for every beat it says had none, the frame
    must not. Decided without a threshold, by ranking: each frame's caption band
    is reduced and compared against the take's own first caption-off frame, and
    every captioned frame has to sit further from that baseline than every
    uncaptioned one, by at least `MIN_ALIGN_BAND_DELTA[label]`. A recorder that
    stopped drawing the bar, or extraction that returned the same picture for
    every beat, collapses the two groups into each other and the margin goes to
    zero or negative — there is nothing to tune it past.

    Frames within `FRAME_CAPTION_GUARD_S` of a caption *change* are not graded,
    and the constant's comment says why at length: the video runs ahead of the
    beat log by an amount this harness bounds but does not control (#18), so
    close to a change the two disagree about which side a frame is on and
    neither is wrong. `MIN_GRADED_CAPTION_FRAMES` and the one-of-each rule keep
    that exclusion from turning the check off.

    The guard is applied to **where the frame really sits in the story**, not
    to the timestamp it was cut at. A frame cut at the log's idea of a beat's
    midpoint shows a moment `|clock.before(t)|` later on a take whose host
    stepped its wall clock (issue #215), so measuring its distance from a
    caption change without that correction measures the wrong distance — and
    grades a frame taken from well past a change as though it were nowhere
    near one. That is #209's `beat-23.png` failure: a frame graded for a
    caption the video had already dropped, reported as "the frames do not show
    the beats they are named for". The guard's *width* is unchanged.

    The expectation comes from `_expected_context()` — the storyboard lists at
    the top of this file — and never from `timeline.json`, which is the
    recorder's own account of the same thing and is graded against those same
    lists in `check_timeline()`.
    """
    if context is None or any(
        not isinstance(f.get("beat"), int) or not 0 <= f["beat"] < len(context)
        for f in listed
    ):
        # The count and the caption list are graded above and in
        # check_timeline(); saying so a third time adds nothing, and grading a
        # misaligned pairing would report the wrong beat. Indexed by the
        # frame's own beat rather than by position, because dedupe (#343)
        # means the kept frames are a subset of the beats.
        return []

    # A change is where the expected context stops being what it was. The
    # *times* have to come from the log — it is the only record of when a beat
    # ran — but which beats are boundaries does not. Over every expected
    # beat, not only the kept frames: a boundary whose frame was deduplicated
    # away still moved the caption under its neighbours.
    changes = [
        float(beats[i]["t_start"])
        for i in range(len(context))
        if i in beats and context[i] != (context[i - 1] if i else "")
    ]

    # The band, at the size the PNGs actually are: review frames are scaled
    # to at most 1024 px wide (#343), and a band computed for the recording's
    # native size would crop a region the smaller picture does not have.
    width, height = frame_size
    factor = min(1024, width) / width
    band = caption_probe_band(label, frame_size, factor)
    stepped = clock.before if clock is not None else (lambda _t: 0.0)
    reference: bytes | None = None
    graded: list[tuple[int, str, bytes]] = []
    for frame in listed:
        # A deduplicated beat is graded through the kept frame it matched:
        # the manifest asserts the two pictures are the same, so the twin's
        # pixels stand in at the dropped beat's own timestamp and against the
        # dropped beat's own expected caption. That is not a concession — it
        # is the check on the dedupe itself: a drop that merged across a
        # caption change puts a picture of the wrong caption state under this
        # beat's expectation, and the margin collapses.
        png = out_dir / "frames" / str(frame.get("matches") or frame.get("file"))
        if not png.is_file():
            continue
        # Where the frame was cut, and where it actually sits in the story.
        # The extractor seeks demo.mp4 at the beat's midpoint moved onto the
        # video's clock by the take's own record (issue #229) — and where that
        # record could not answer, at the bare midpoint. Either way the two
        # accounts of where the frame sits can differ by the residual between
        # this watcher and the recorder's (issue #215) — and a caption
        # change *between* them is exactly the case where the sheet's label and
        # the picture disagree and neither is wrong. Grade a frame only when
        # the whole interval between the two accounts of where it is clears
        # every caption change by the guard.
        at = float(frame["t"])
        # Two accounts of where this frame sits, each kept on ITS OWN clock
        # and measured against the change on that same clock: the beat's
        # midpoint on the log's, and the cut instant on the video's (the
        # change moved there by `before(c)`, whose argument really is a
        # log-clock second). The previous form fed `at` — a video-clock
        # instant since #229 — into `before()`, and on a take whose step
        # landed inside a caption stretch the video instant read as inside
        # the hole on the wrong axis: the corrected interval missed the
        # change by ~1 s and a frame cut 60 ms from a caption clear was
        # graded (measured on a --cheap run of #361: beat 4 cut at video
        # 3.974 s = log 5.09 s, change at log 5.151 s, step -1.119 s at
        # 3.768 s). A change the two accounts straddle is distance zero —
        # that is the ambiguous case the guard exists for.
        beat_record = beats.get(int(frame["beat"])) or {}
        t_start, t_end = beat_record.get("t_start"), beat_record.get("t_end")
        log_mid = (
            (float(t_start) + float(t_end)) / 2
            if isinstance(t_start, (int, float)) and isinstance(t_end, (int, float))
            else at
        )
        near = math.inf
        for c in changes:
            log_side = log_mid - c
            video_side = at - (c + stepped(c))
            near = min(
                near,
                0.0
                if min(log_side, video_side) <= 0.0 <= max(log_side, video_side)
                else min(abs(log_side), abs(video_side)),
            )
        if near < FRAME_CAPTION_GUARD_S:
            continue
        try:
            reduced = gray_frames(png, band)
        except RuntimeError as exc:
            return [f"{label}: {exc}"]
        if not reduced:
            return [f"{label}: {png.name} decoded to no frames"]
        expected = context[int(frame["beat"])]
        graded.append((int(frame["beat"]), expected, reduced[0]))
        if reference is None and not expected:
            reference = reduced[0]

    captioned = [(b, c, g) for b, c, g in graded if c]
    bare = [(b, c, g) for b, c, g in graded if not c]
    # Three separate ways for this check to end up grading nothing, reported
    # separately. They overlap in practice — a guard wide enough to take the
    # count under the floor usually empties a class too — and a single message
    # covering all three cannot say which one fired, which makes it impossible
    # to show the floor failing on its own.
    coverage = (
        f"{len(graded)} of {len(listed)} review frames ({len(captioned)} "
        f"captioned, {len(bare)} not) sit more than {FRAME_CAPTION_GUARD_S}s "
        f"clear of a caption change"
    )
    if reference is None:
        return [
            f"{label}: {coverage}, and not one of them is a frame of an "
            f"uncaptioned beat — so there is no caption-off baseline to "
            f"measure the others against, and nothing about what the frames "
            f"*show* could be graded at all"
        ]
    if not captioned:
        return [
            f"{label}: {coverage}, and not one of them is a frame of a "
            f"captioned beat — so 'a captioned beat's frame shows a caption' "
            f"was not tested on anything"
        ]
    if len(graded) < MIN_GRADED_CAPTION_FRAMES:
        return [
            f"{label}: {coverage}, under the {MIN_GRADED_CAPTION_FRAMES} this "
            f"check needs to mean anything. Either the storyboard changed "
            f"caption too often to grade, or every frame moved onto a "
            f"boundary — which is the regression this floor is here to catch, "
            f"not a reason to lower it"
        ]

    scored = [(frame_difference(reference, g), b, c) for b, c, g in graded]
    worst_on = min(s for s in scored if s[2])
    worst_off = max(s for s in scored if not s[2])
    margin = worst_on[0] - worst_off[0]
    floor = MIN_ALIGN_BAND_DELTA[label]
    if margin < floor:
        return [
            f"{label}: beat-{worst_on[1]:02d}.png should show the caption "
            f"{worst_on[2]!r} and its caption band is only {worst_on[0]:.2f} "
            f"from the take's caption-off baseline — beat-{worst_off[1]:02d}."
            f"png, which should show no caption at all, is {worst_off[0]:.2f} "
            f"from it. The two are {margin:.2f} apart, under the {floor} floor: "
            f"the frames do not show the beats they are named for, or the "
            f"caption bar is not being drawn"
        ]
    print(
        f"smoke: {label} each review frame shows its own beat's caption state "
        f"({len(captioned)} captioned frames from {worst_on[0]:.1f}, "
        f"{len(bare)} bare ones to {worst_off[0]:.1f}; "
        f"{len(listed) - len(graded)} within {FRAME_CAPTION_GUARD_S}s of a "
        f"caption change and not graded)"
    )
    return []


def _check_stale_frames(label: str, out_dir: Path, manifest: dict) -> list[str]:
    """A re-run must take the previous run's frames off disk.

    SKILL.md advertises `beat_frames(out_dir)` as re-runnable, and step 6 tells
    a reviewer to read everything in the directory. A storyboard that lost
    beats between runs would otherwise leave frames nobody planned sitting in
    it — numbered, plausible, and from a demo that no longer exists.

    Done here rather than through a second recording: it is a pure function of
    the mp4 and the timeline, so a second call is free.
    """
    from demo_recording import beat_frames

    frames_dir = out_dir / "frames"
    planted = frames_dir / "beat-99.png"
    keep = frames_dir / "kept-by-a-human.png"
    try:
        planted.write_bytes(
            (frames_dir / str(manifest["frames"][0]["file"])).read_bytes()
        )
        keep.write_bytes(b"not ours\n")
        again = beat_frames(out_dir)
    except (OSError, IndexError, KeyError) as exc:
        return [f"{label}: could not re-run beat_frames(): {exc}"]
    failures: list[str] = []
    if planted.exists():
        failures.append(
            f"{label}: re-running beat_frames() left {planted.name} behind — a "
            f"frame from a previous take stays in the directory step 6 hands to "
            f"a reviewer"
        )
        planted.unlink()
    if not keep.exists():
        failures.append(
            f"{label}: re-running beat_frames() deleted a file it did not "
            f"write ({keep.name}) — the cleanup is supposed to be bounded to "
            f"the frames and the two manifests"
        )
    else:
        keep.unlink()
    if [f["file"] for f in again["frames"]] != [f["file"] for f in manifest["frames"]]:
        failures.append(
            f"{label}: re-running beat_frames() produced a different set of "
            f"frames from the same mp4 and timeline"
        )
    return failures


def _check_segment_refusal(label: str, out_dir: Path, doc: dict) -> list[str]:
    """A *single segment's* timeline must write no frames — and only that.

    Two properties of an unmerged segment document, both of it rather than of
    the world around it: its beats are numbered from zero, so two segments in
    one directory overwrite each other's `beat-00.png`; and its `media` is a
    `<segment>.seg.mp4`, which `stitch()` deletes on its way to demo.mp4, so
    the sheet would embed frames of a file that is gone. Neither survives the
    merge — issue #7 landed, `stitch()` renumbers the beats onto the joined
    video's clock and names demo.mp4 — which is why the *stitched* demo gets
    frames like any other take, graded by running this whole function against
    the `segments/` take rather than by arguing about it here.

    Graded by handing `beat_frames()` this take's own timeline with a segment
    name on it, into a directory of its own — no recording needed, and the
    refusal is a property of the document rather than of how it was made.
    """
    from demo_recording import beat_frames

    segment_dir = out_dir / ".segment-refusal"
    segment_dir.mkdir(exist_ok=True)
    shutil.copy(out_dir / "demo.mp4", segment_dir / "part2.seg.mp4")
    try:
        manifest = beat_frames(
            segment_dir, {**doc, "segment": "part2", "media": "part2.seg.mp4"}
        )
    except Exception as exc:  # noqa: BLE001 - refusing must not mean raising
        shutil.rmtree(segment_dir, ignore_errors=True)
        return [f"{label}: beat_frames() raised on a segment take: {exc}"]
    written = sorted(p.name for p in segment_dir.glob("frames/*"))
    shutil.rmtree(segment_dir, ignore_errors=True)
    if manifest["frames"] or written:
        return [
            f"{label}: beat_frames() wrote {written!r} for a segment take. Two "
            f"segments collide on beat-00.png, and the sheet names a "
            f".seg.mp4 that stitch() deletes."
        ]
    if not manifest.get("skipped"):
        return [
            f"{label}: beat_frames() wrote nothing for a segment take but does "
            f"not say why — a caller cannot tell that from a crash"
        ]
    return []


def _check_scene_fallback(label: str, out_dir: Path, doc: dict) -> list[str]:
    """The fallback for transitions the storyboard did not script.

    Graded directly against demo.mp4 rather than through a take, because no
    beat in either storyboard runs the SCENE_MIN_SPAN_S the recorder needs
    before it reaches for it, and stretching one to provoke it would cost every
    run the seconds. What it has to do is see the largest change a take
    contains and stay quiet where nothing moves.

    The positive half is **web only**, and that is about the medium rather than
    a convenience: the biggest thing that happens to the web frame is the
    caption bar arriving, at 0.023-0.026 against the recorder's 0.02 threshold,
    while nothing in the terminal take reaches it at all — its largest change
    is two lines of output on a dark background at 0.011 against an idle 0.004.
    At a threshold separating those, an ordinary terminal repaint would be
    reported as a cut. Issue #57.
    """
    from demo_recording.frames import SCENE_MIN_SPAN_S, scene_times

    failures: list[str] = []
    mp4 = out_dir / "demo.mp4"
    beats = doc.get("beats") or []
    duration = float(doc.get("duration") or 0.0)
    if not mp4.is_file() or not duration or not beats:
        return failures

    if label == "web":
        cuts = scene_times(mp4, 0.0, duration, limit=99)
        if not cuts:
            failures.append(
                f"{label}: scene detection finds nothing at all in "
                f"{duration:.1f}s of demo.mp4 — the fallback for unscripted "
                f"transitions cannot see the largest change the take contains"
            )
        elif not all(0.0 <= c <= duration for c in cuts):
            failures.append(
                f"{label}: scene detection reports cuts at {cuts} for a "
                f"{duration:.1f}s video — the times it returns are not in the "
                f"window it was asked about"
            )

    # The quiet half: after the last beat the recording holds one frame until
    # it stops. Starting at the last beat's *logged* end is safe in the one
    # direction that matters — the video only ever runs ahead of the beat log
    # (issue #18), so the real end of that beat is at or before this — which is
    # why the window is anchored there and not on a beat in the middle of the
    # take, where a stall slid a caption change into it on the first run.
    tail = float(beats[-1].get("t_end") or 0.0) + SCENE_WINDOW_PAD_S
    if duration - tail > 0.4:
        held = scene_times(mp4, tail, duration)
        if held:
            failures.append(
                f"{label}: scene detection reports cuts at {held} between "
                f"{tail:.2f}s and {duration:.2f}s of demo.mp4, where the take "
                f"holds its closing frame — it would fill a reviewer's frame "
                f"list with pictures of nothing happening"
            )

    # And a scene frame may only appear inside a beat long enough to hide one.
    # Vacuous while no storyboard beat reaches the threshold — tests/README.md
    # says so — and here so that a storyboard that grows one is graded.
    spans = {b.get("index"): float(b["t_end"]) - float(b["t_start"]) for b in beats}
    manifest = json.loads((out_dir / "frames" / "frames.json").read_text())
    for frame in manifest.get("frames") or []:
        if frame.get("kind") != "scene":
            continue
        if spans.get(frame.get("beat"), 0.0) < SCENE_MIN_SPAN_S:
            failures.append(
                f"{label}: {frame.get('file')} is a scene frame inside beat "
                f"{frame.get('beat')}, which spans "
                f"{spans.get(frame.get('beat'), 0.0):.2f}s — under the "
                f"{SCENE_MIN_SPAN_S}s a beat needs before it is searched"
            )
    return failures


def _expected_context(
    expected_beats: list[tuple[str, str | None]],
    expected_captions: list[str],
    expected_interludes: list[str] | None = None,
) -> list[str] | None:
    """The caption in force during each expected beat.

    A `caption` beat carries the text it sets; everything after it carries that
    text until the next one. An `interlude` beat carries its own line — it is a
    title card, not a caption — and leaves the running caption alone, which is
    also what the recorder does. Returns None if the lists disagree about how
    many captions or interludes there are, in which case the checks above
    already say so and this one has nothing to add.
    """
    verbs = [verb for verb, _ in expected_beats]
    if verbs.count("caption") != len(expected_captions):
        return None
    interludes = list(expected_interludes or [])
    if verbs.count("interlude") != len(interludes):
        return None
    context: list[str] = []
    current = ""
    pending = list(expected_captions)
    for verb in verbs:
        if verb == "caption":
            current = pending.pop(0)
        elif verb == "interlude":
            context.append(interludes.pop(0))
            continue
        context.append(current)
    return context


def _expected_segment_indices(segments: list[str | None]) -> list[int]:
    """Each beat's position within its own segment, from the segment column.

    For a single take (every entry None) this is just 0, 1, 2, … — so the
    assertion that `segment_index` matches it holds for every take here, not
    only the segmented one.
    """
    seen: dict[str | None, int] = {}
    indices: list[int] = []
    for name in segments:
        indices.append(seen.get(name, 0))
        seen[name] = seen.get(name, 0) + 1
    return indices


def _first_difference(actual: list, expected: list) -> object:
    for i, (a, e) in enumerate(zip(actual, expected, strict=False)):
        if a != e:
            return f"{i} ({a!r} vs expected {e!r})"
    return f"{min(len(actual), len(expected))} (one list simply ends)"


def check_issues(
    label: str,
    out_dir: Path,
    expected: list[dict],
    exit_codes: dict[str, int] | None = None,
) -> list[str]:
    """The problems the take noticed, as `timeline.json` records them.

    A recording is not evidence that the thing being recorded works: a demo of
    an app throwing `TypeError` on every render looks exactly like a demo of a
    healthy one. This axis grades what the recorder saw *behind* the pixels —
    the console, the network, and the exit status of every command it typed —
    and, as much as any of it, whether each problem is attributed to the beat
    that was running when it fired. "The take broke" is not a bug report; "the
    take broke during `click('#refresh')`" is.
    """
    from demo_recording.timeline import ISSUE_KINDS, STRICT_KINDS

    failures: list[str] = []
    json_path = out_dir / "timeline.json"
    if not json_path.is_file():
        return [f"{label}: {json_path} was never written"]
    try:
        doc = json.loads(json_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{label}: {json_path} is not valid JSON: {exc}"]

    beats = doc.get("beats") or []
    issues = doc.get("issues")
    if not isinstance(issues, list):
        return [
            f"{label}: timeline.json has no `issues` list ({issues!r}) — the "
            f"take recorded nothing about whether the app was working"
        ]
    if doc.get("strict") is not False:
        failures.append(
            f"{label}: timeline.json says strict={doc.get('strict')!r}; this "
            f"take is recorded with the default, which is off"
        )
    if doc.get("issue_count") != len(issues):
        failures.append(
            f"{label}: timeline.json counts {doc.get('issue_count')!r} issues "
            f"but lists {len(issues)} — nothing here should hit the cap, so "
            f"the two disagreeing means one of them is wrong"
        )
    for issue in issues:
        if issue.get("kind") not in ISSUE_KINDS:
            failures.append(
                f"{label}: timeline.json records an issue of unknown kind "
                f"{issue.get('kind')!r}, not in the package's ISSUE_KINDS"
            )
            break

    # -- the problems the storyboard deliberately caused ---------------------
    for want in expected:
        kind, needle, verb = want["kind"], want["needle"], want["verb"]
        found = [
            i
            for i in issues
            if i.get("kind") == kind and needle in str(i.get("message"))
        ]
        if not found:
            failures.append(
                f"{label}: nothing in timeline.json records the {kind} the "
                f"storyboard deliberately caused ({needle!r}). Logged: "
                f"{[(i.get('kind'), i.get('message')) for i in issues]!r}"
            )
            continue
        issue = found[0]
        index = issue.get("beat")
        if verb is None:
            # Fired where no beat was open. Naming one anyway is the failure
            # mode being guarded: a confident index and a quoted caption, both
            # invented. `beat: null` is the right answer and the only one.
            if index is not None or issue.get("verb") is not None:
                failures.append(
                    f"{label}: the {kind} {needle!r} fired between beats, with "
                    f"none open, but is attributed to beat {index!r} "
                    f"({issue.get('verb')!r}) — the attribution is invented"
                )
            continue
        # Both halves matter. `verb` alone is a string the recorder could have
        # copied from anywhere; `beat` alone is an integer that means nothing
        # on its own. Together they say the issue points at a real beat, and
        # that it is the right one.
        if not isinstance(index, int) or not 0 <= index < len(beats):
            failures.append(
                f"{label}: the {kind} {needle!r} is attributed to beat "
                f"{index!r}, which is not a beat of this take — the problem "
                f"is logged but not placed in the story"
            )
            continue
        if beats[index].get("verb") != verb or issue.get("verb") != verb:
            failures.append(
                f"{label}: the {kind} {needle!r} fired during {verb!r} but is "
                f"attributed to beat {index} "
                f"({beats[index].get('verb')!r}/{issue.get('verb')!r})"
            )
            continue
        # The caption recorded beside an issue is the one a reviewer reads as
        # context. Quoting a line that only appeared *after* the error is worse
        # than quoting none, and is exactly what naming a later beat produces.
        if "caption" in want and issue.get("caption") != want["caption"]:
            failures.append(
                f"{label}: the {kind} {needle!r} is recorded under caption "
                f"{issue.get('caption')!r}, but the line on screen when it "
                f"fired was {want['caption']!r}"
            )

    # -- every command's exit status, on the beat that ran it ----------------
    if exit_codes is not None:
        logged = {
            str(beat.get("selector")): beat.get("exit_code")
            for beat in beats
            if beat.get("verb") == "run"
        }
        if logged != exit_codes:
            failures.append(
                f"{label}: run() beats logged exit codes {logged!r}, the "
                f"storyboard's commands exit {exit_codes!r} — a command that "
                f"failed is indistinguishable from one that worked"
            )
        if "nonzero_exit" not in STRICT_KINDS:
            failures.append(
                f"{label}: the package's STRICT_KINDS is {STRICT_KINDS!r}, "
                f"which does not include 'nonzero_exit' — a failing command "
                f"is recorded but would not fail a strict take"
            )

    # -- the same problems, readable, in timeline.md -------------------------
    md_path = out_dir / "timeline.md"
    markdown = md_path.read_text() if md_path.is_file() else ""
    if issues and "## Issues" not in markdown:
        failures.append(
            f"{label}: timeline.json records {len(issues)} problem(s) but "
            f"timeline.md has no Issues section — the human-readable half of "
            f"the log says the take was fine"
        )
    for want in expected:
        if want["needle"] not in markdown:
            failures.append(f"{label}: timeline.md does not mention {want['needle']!r}")
    if exit_codes is not None and "| exit |" not in markdown:
        failures.append(
            f"{label}: timeline.md's beat table has no exit column, so a run() "
            f"whose status could not be read is invisible in the half SKILL.md "
            f"calls the take's own account of what ran"
        )

    fatal = [i for i in issues if i.get("kind") in STRICT_KINDS]
    if not fatal:
        failures.append(
            f"{label}: this take is supposed to carry problems a strict take "
            f"would refuse, and carries none — so it proves nothing about the "
            f"default tolerating them"
        )
    if not failures:
        # Reaching here at all is the assertion: the take completed, wrote
        # every artifact, and passed every other axis, while holding problems
        # that STRICT_KINDS calls fatal. That is the default-mode half of
        # "strict fails the take and the default does not".
        print(
            f"smoke: {label} timeline.json records {len(issues)} problem(s), "
            f"{len(fatal)} of them fatal under strict — take still passed"
        )
    return failures


def check_healthy(label: str, out_dir: Path) -> list[str]:
    """A take of a working app must have found nothing to report.

    This is the only assertion in the file that can fail on *over*-reporting,
    and without it the whole axis is one-directional. Every problem check is
    "at least one issue matches", which a recorder that flagged every healthy
    2xx as a fatal console error satisfies perfectly — while refusing every
    strict take of every working app ever recorded. Verified as a real gap:
    that exact injection passed the suite before this existed.

    The take is also recorded with `strict=True`, so over-reporting does not
    merely get noticed here, it aborts the take and is impossible to miss.
    """
    json_path = out_dir / "timeline.json"
    if not json_path.is_file():
        return [f"{label}: {json_path} was never written"]
    try:
        doc = json.loads(json_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{label}: {json_path} is not valid JSON: {exc}"]

    failures: list[str] = []
    if doc.get("strict") is not True:
        failures.append(
            f"{label}: timeline.json says strict={doc.get('strict')!r}; this "
            f"take is recorded strict, and its passing means nothing otherwise"
        )
    issues = doc.get("issues")
    if not isinstance(issues, list):
        failures.append(f"{label}: timeline.json has no `issues` list ({issues!r})")
    elif issues or doc.get("issue_count"):
        failures.append(
            f"{label}: nothing is wrong with the fixture app, but the take "
            f"recorded {doc.get('issue_count')!r} problem(s): "
            f"{[(i.get('kind'), i.get('message')) for i in issues]!r}. Either "
            f"the recorder reports healthy behaviour as broken — which would "
            f"refuse every strict take of every working app — or the fixture "
            f"really did break."
        )
    if not failures:
        print(f"smoke: {label} healthy app under strict=True records no problems")
    return failures


def _transition_shape(frames: list[bytes], fps: float, t_start: float) -> dict:
    """How far through a transition each frame of one spotlight window is.

    Nothing here is imported from the recorder. It is a picture, two settled
    states either side of it, and the question of whether anything was ever
    part way between them.
    """
    before, after = SPOTLIGHT_WINDOW_S
    lo = max(0, int((t_start - before) * fps))
    hi = min(len(frames), int((t_start + after) * fps) + 1)
    window = frames[lo:hi]
    if len(window) < 2:
        return {"frames": len(window), "total": 0.0, "mid": []}
    settled = window[-1]
    total = frame_difference(window[0], settled)
    low, high = SPOTLIGHT_MID_BAND
    mid = []
    if total > 0:
        for frame in window:
            share = frame_difference(frame, settled) / total
            if low < share < high:
                mid.append(round(share, 3))
    return {"frames": len(window), "total": total, "mid": mid}


def check_spotlight_transitions(
    out_dir: Path, info: dict, clock: HostClock | None = None
) -> list[str]:
    """The spotlight leaves the way it arrived (issue #111).

    Both spotlight beats are measured the same way, and the enter is the
    control: it eased before this change and eases after it, so a reading where
    only the exit passes through nothing is a reading about the exit.

    Each window is placed at its beat's timestamp moved onto the video's
    clock by the harness's own wall-clock watcher (#215) — the same
    correction every other timing reading in this file applies, added here
    after a mid-take backward step was measured sliding the exit window off
    the fade entirely.
    """
    failures: list[str] = []
    mp4 = out_dir / "demo.mp4"
    doc = json.loads((out_dir / "timeline.json").read_text())
    beats = [b for b in doc.get("beats", []) if b.get("verb") == "spotlight"]
    if len(beats) != 2:
        return [
            f"spotlight: the take logged {len(beats)} spotlight beat(s), "
            f"expected 2 (one to put the highlight up, one to take it down) — "
            f"there is nothing to measure"
        ]
    enter, clear = beats
    if enter.get("selector") != SPOTLIGHT_TARGET or clear.get("selector") is not None:
        failures.append(
            f"spotlight: the two spotlight beats target "
            f"{enter.get('selector')!r} and {clear.get('selector')!r}, expected "
            f"{SPOTLIGHT_TARGET!r} and None — they are not the enter and the "
            f"exit, so the reading below is mislabelled"
        )
    fps = video_fps(mp4)
    # One decode of the whole recording, sliced by frame index afterwards. Two
    # seeks into the same file would each carry their own rounding, and the two
    # windows would then be measured on grids that do not agree.
    frames = gray_frames(mp4, rect=info["rect"])
    stepped = clock.before if clock is not None else (lambda _t: 0.0)
    readings: dict[str, dict] = {}
    for name, beat in (("enter", enter), ("exit", clear)):
        t_start = beat.get("t_start")
        if not isinstance(t_start, (int, float)):
            failures.append(
                f"spotlight: the {name} beat has t_start {t_start!r}, so its "
                f"window cannot be placed in the video"
            )
            continue
        at = float(t_start) + stepped(float(t_start))
        readings[name] = _transition_shape(frames, fps, at)
    span = sum(SPOTLIGHT_WINDOW_S)
    for name, shape in readings.items():
        # Two ways the reading below can be about nothing, each with its own
        # message: too few frames in the window, or two ends that agree.
        want = int(span * fps * 0.6)
        if shape["frames"] < want:
            failures.append(
                f"spotlight: the {name} window holds {shape['frames']} of the "
                f"video's {len(frames)} frames, expected at least {want} at "
                f"{fps:.0f} fps — the recording is short of the window, so what "
                f"is measured in it is not the transition"
            )
        if shape["total"] < SPOTLIGHT_MIN_TOTAL:
            failures.append(
                f"spotlight: the {name} window's two ends differ by only "
                f"{shape['total']:.2f} mean luma over {info['rect']}, under the "
                f"{SPOTLIGHT_MIN_TOTAL} floor — the highlight did not go on or "
                f"did not come off in this window at all, and every fraction "
                f"computed against it is noise over noise"
            )
    if "enter" in readings and len(readings["enter"]["mid"]) < MIN_SPOTLIGHT_MID_FRAMES:
        failures.append(
            f"spotlight: the *enter* transition passed through "
            f"{len(readings['enter']['mid'])} intermediate frame(s) "
            f"{readings['enter']['mid']}, under the "
            f"{MIN_SPOTLIGHT_MID_FRAMES} bar. This is the control, not the "
            f"thing under test: either the spotlight is not being drawn, or "
            f"this take lost its `deterministic=False` and the motion rule "
            f"flattened the transition to 1 ms. Until it passes, the exit "
            f"reading below proves nothing."
        )
    if "exit" in readings:
        mid = readings["exit"]["mid"]
        if len(mid) < MIN_SPOTLIGHT_MID_FRAMES:
            failures.append(
                f"spotlight: clearing the spotlight passed through {len(mid)} "
                f"intermediate frame(s) {mid}, under the "
                f"{MIN_SPOTLIGHT_MID_FRAMES} bar, while the enter passed "
                f"through {len(readings.get('enter', {}).get('mid', []))}. The "
                f"highlight snaps out instead of easing out (issue #111) — the "
                f"clear is removing `transition` in the same frame as the "
                f"properties it is meant to animate, so the element is either "
                f"fully highlighted or fully normal and never in between."
            )
    if not failures:
        print(
            f"smoke: spotlight eases both ways (enter "
            f"{len(readings['enter']['mid'])} intermediate frames, exit "
            f"{len(readings['exit']['mid'])})"
        )
    return failures


def _strip_frame(mp4: Path, strip: Rect, at: float) -> bytes | None:
    """One frame of `strip`, at `at` seconds. `None` if the video is short."""
    frames = gray_frames(mp4, rect=strip, start=at, duration=0.08)
    return frames[0] if frames else None


def check_camera_push(
    out_dir: Path, info: dict, clock: HostClock | None = None
) -> list[str]:
    """The spotlight's camera move is in the encoded video, not only in JSON.

    `camera.py` replaced a live DOM zoom that scaled `<body>` around the
    element's own centre — the element therefore did not move, 6% of a 60 px
    chip was invisible, and what a viewer saw was the layout jittering around
    it. The push-in that replaced it scales the *composited* frame, so the
    reading that separates the two is taken where the page cannot reach: the
    strip of window chrome above the app rect.

    Three statements about that strip, each broken by a different mistake:

      * it is **still** in the quiet before the event — the control, without
        which "the chrome moved" is a claim about a take that never sits still
      * it has **moved** at the held zoom — the push itself
      * it is **back** once the event has ended — the pull, and the reason a
        camera that pushed in and stayed there is not a passing answer

    Plus the two the pixels cannot make: the take logged exactly one event
    (one spotlight interval), and that event is aimed at the element the
    storyboard lit rather than at something else on the page.

    The event's times come off `timeline.json`, where the recorder has already
    moved them onto the video's clock (`_camera_on_the_video_clock`) — the
    same correction the narration mix applies, for the same reason.
    """
    mp4 = out_dir / "demo.mp4"
    doc = json.loads((out_dir / "timeline.json").read_text())
    events = doc.get("camera") or []
    if len(events) != 1:
        return [
            f"spotlight: the take logged {len(events)} camera event(s), "
            f"expected 1 — one spotlight interval is one push-in, so there is "
            f"no move in demo.mp4 to measure (timeline.json's `camera`)"
        ]
    event = events[0]
    t_start, t_end = float(event["t_start"]), float(event["t_end"])
    failures: list[str] = []
    # Aimed at the element, before anything is read off the frames: a push
    # centred somewhere else is still a push, and every reading below would
    # pass while the viewer's eye was pulled to the wrong part of the screen.
    ex, ey, ew, eh = (float(v) for v in event["rect"])
    tx, ty, tw, th = info["rect"]
    off = math.dist((ex + ew / 2, ey + eh / 2), (tx + tw / 2, ty + th / 2))
    if off > CAMERA_CENTRE_BAR_PX:
        failures.append(
            f"spotlight: the camera event is centred "
            f"{off:.1f}px from the element the take spotlighted, over the "
            f"{CAMERA_CENTRE_BAR_PX}px bar — the move is aimed at "
            f"{event['rect']}, the element is at {list(info['rect'])}"
        )
    appy = info["app"][1]
    if appy < CAMERA_STRIP_MIN_H:
        return failures + [
            f"spotlight: the wrapper leaves {appy}px of chrome above the app "
            f"rect, under the {CAMERA_STRIP_MIN_H}px this reading needs — the "
            f"strip would be app pixels, which the page moves on its own"
        ]
    # A step inside the interval is not a camera defect and cannot be read as
    # one: the recorder corrects the event onto the video's clock, and the
    # video really is that much shorter — a 1.23 s backward step measured on
    # this repo's WSL host turned a 1.88 s push into 0.85 s of frames, which
    # never reaches full zoom no matter what the filter says. Said out loud
    # rather than dropped silently, and the centre reading above still stands:
    # it is geometry, and no clock touches it.
    stepped_through = [
        at
        for at, _delta in (clock.steps if clock is not None else [])
        if t_start - MAX_CLOCK_STEP_TIME_DISAGREEMENT_S
        <= at
        <= t_end + MAX_CLOCK_STEP_TIME_DISAGREEMENT_S
    ]
    if stepped_through:
        print(
            f"smoke: spotlight camera not measured — this host's wall clock "
            f"stepped at {', '.join(f'{at:.2f}s' for at in stepped_through)}, "
            f"inside the {t_start:.2f}-{t_end:.2f}s the push runs over, so the "
            f"video holds fewer seconds of it than the recorder rendered"
        )
        return failures
    if t_end - t_start < CAMERA_MIN_EVENT_S:
        return failures + [
            f"spotlight: the camera event runs {t_end - t_start:.2f}s, under "
            f"the {CAMERA_MIN_EVENT_S}s two eases need — the push never "
            f"reaches full zoom, so a frame from the middle of it is not the "
            f"held zoom and this reading is about nothing"
        ]
    strip: Rect = (0, 0, info["size"][0], appy)
    quiet = _strip_frame(mp4, strip, t_start - 0.8)
    before = _strip_frame(mp4, strip, t_start - 0.25)
    held = _strip_frame(mp4, strip, (t_start + t_end) / 2)
    after = _strip_frame(mp4, strip, t_end + CAMERA_AFTER_S)
    missing = [
        name
        for name, frame in (
            ("quiet", quiet),
            ("before", before),
            ("held", held),
            ("after", after),
        )
        if frame is None
    ]
    if missing:
        return failures + [
            f"spotlight: the video has no frame at the {', '.join(missing)} "
            f"instant(s) of a camera event running {t_start:.2f}-{t_end:.2f}s "
            f"— the recording is shorter than the event it claims to carry"
        ]
    still = frame_difference(quiet, before)
    pushed = frame_difference(before, held)
    pulled = frame_difference(before, after)
    if still > CAMERA_STILL_MAX:
        failures.append(
            f"spotlight: the chrome strip above the app moved {still:.2f} mean "
            f"luma in the quiet before the push, over the {CAMERA_STILL_MAX} "
            f"bar — this is the control, and until it holds, the {pushed:.2f} "
            f"read into the push is not evidence of a camera move"
        )
    if pushed < CAMERA_PUSH_MIN:
        failures.append(
            f"spotlight: the chrome strip above the app moved {pushed:.2f} "
            f"mean luma between the frame before the event and the held zoom, "
            f"under the {CAMERA_PUSH_MIN} bar. Nothing outside the app rect "
            f"moved, which is what the DOM zoom this replaced did (camera.py) "
            f"— the push is either not being rendered into demo.mp4 or is too "
            f"small to see"
        )
    if pulled > CAMERA_STILL_MAX:
        failures.append(
            f"spotlight: the chrome strip is still {pulled:.2f} mean luma "
            f"from where it was, {CAMERA_AFTER_S}s after the event ended and "
            f"over the {CAMERA_STILL_MAX} bar — the camera pushed in and did "
            f"not come back, so every frame after this spotlight is a crop of "
            f"the take"
        )
    if not failures:
        print(
            f"smoke: spotlight camera pushed in and back (chrome strip moved "
            f"{pushed:.2f} mean luma at the held zoom, {still:.2f} in the "
            f"quiet before it, {pulled:.2f} once it pulled back)"
        )
    return failures


def check_opening_card(out_dir: Path, info: dict) -> list[str]:
    """A terminal segment opens on its cover, not on a bare slot (#110).

    Three statements about one sweep of one strip of the app rect (#362
    moved it inside the window — see OPENING_STRIP_FRACTIONS), and each is
    broken by a different mistake:

      * the *first* frame is the cover — a hold that never painted leaves
        frame 0 reading the slot's white canvas;
      * no frame of the strip is ever bare — a cover cleared before xterm.js
        painted is a white flash in the window;
      * the strip stops being a flat field, and not before
        MIN_OPENING_CARD_S — a cover never taken down stays flat forever
        (#91's half of this seam, and without it the first two statements
        are equally true of a recorder that painted a rectangle and
        stopped), and one taken down early shows the terminal before the
        card could be read (#110). Structure rather than luma, because the
        revealed terminal is as dark as the cover it replaces — see
        TERMINAL_REVEAL_MIN_STDDEV for the measurement, and for why change
        against frame 0 was measured and rejected.
    """
    failures: list[str] = []
    mp4 = out_dir / "demo.mp4"
    strip = info["strip"]
    frames = gray_frames(mp4, rect=strip, sample_fps=OPENING_SAMPLE_FPS)
    luma = [sum(f) / len(f) for f in frames]
    if len(luma) < MIN_OPENING_FRAMES:
        return [
            f"terminal-opening: the strip sweep decoded {len(luma)} frames at "
            f"{OPENING_SAMPLE_FPS} fps over {strip}, under the "
            f"{MIN_OPENING_FRAMES} floor — every statement below would be "
            f"satisfied by a video too short to hold the card at all"
        ]

    def kind(value: float) -> str:
        if value <= OPENING_CARD_MAX_LUMA:
            return "card"
        if value >= OPENING_BARE_MIN_LUMA:
            return "bare"
        return "between"

    if kind(luma[0]) != "card":
        failures.append(
            f"terminal-opening: the recording's first frame reads "
            f"{luma[0]:.1f} mean luma over the strip at {strip}, which is "
            f"{kind(luma[0])!r} and not the cover (cover <= "
            f"{OPENING_CARD_MAX_LUMA}, bare slot >= "
            f"{OPENING_BARE_MIN_LUMA}). The segment opens on the slot's "
            f"canvas and the cover arrives afterwards — issue #110."
        )
    bare = [i for i, value in enumerate(luma) if kind(value) == "bare"]
    if bare:
        failures.append(
            f"terminal-opening: frame {bare[0]} "
            f"({bare[0] / OPENING_SAMPLE_FPS:.2f}s) reads "
            f"{luma[bare[0]]:.1f} mean luma over {strip} (bare >= "
            f"{OPENING_BARE_MIN_LUMA}) — the slot's canvas showed through, "
            f"so the cover came down before the terminal painted."
        )
    spread = [statistics.pstdev(f) for f in frames]
    revealed = next(
        (i for i, s in enumerate(spread) if s >= TERMINAL_REVEAL_MIN_STDDEV), None
    )
    revealed_s = None if revealed is None else revealed / OPENING_SAMPLE_FPS
    if revealed is None:
        failures.append(
            f"terminal-opening: no frame of {len(frames)} at "
            f"{OPENING_SAMPLE_FPS} fps ever reaches "
            f"{TERMINAL_REVEAL_MIN_STDDEV} luma stddev over {strip} (worst "
            f"{max(spread):.2f}) — the strip is a flat field for the whole "
            f"take, so the cover the recorder raised is never taken down "
            f"(issue #91) and the whole take is behind it."
        )
    elif revealed_s < MIN_OPENING_CARD_S:
        failures.append(
            f"terminal-opening: the strip stops being a flat field at "
            f"{revealed_s:.2f}s ({spread[revealed]:.2f} luma stddev, floor "
            f"{TERMINAL_REVEAL_MIN_STDDEV}), under the {MIN_OPENING_CARD_S}s "
            f"bar for a card held {OPENING_HOLD_S}s — the viewer sees the "
            f"terminal before the card that is supposed to be covering it."
        )
    if not failures:
        print(
            f"smoke: terminal-opening cover up from frame 0 "
            f"(luma {luma[0]:.0f}, no bare frame, max {max(luma):.0f}, "
            f"covered stddev worst {max(spread[:revealed]):.2f}), "
            f"terminal revealed from {revealed_s:.2f}s"
        )
    return failures


def check_reported_opening_card(out_dir: Path, info: dict) -> list[str]:
    """The take's **own** record of the frame it opened on (issue #235).

    Everything above grades the video. This grades what the recorder wrote
    down about it, and the difference is the whole of #235: a demo directory
    commits `record.py`, `timeline.json`, `timeline.md` and `images/` and never
    `demo.mp4` or its `.seg.mp4` parts, so the flash three separate people
    reported by watching (#110, #114's re-report, #206) is in no committed
    artifact. `check_opening_card` above sweeps a take *this suite* records, in
    a directory nobody ships. The number in `content.opening.card` is the one a
    reviewer of somebody else's demo can actually read.

    Four statements, and each is broken by a different mistake:

      * the field is **there and complete** — a recorder that measured nothing
        and said nothing leaves a reviewer back at the video;
      * the number **describes this video**, re-read here off frame zero of the
        same mp4 over this harness's own strip. A plausible constant agrees
        with itself forever otherwise, and 25.8 is a very plausible constant;
      * on this take it says **card**, which is the acceptance criterion and is
        what a card raised late breaks;
      * and it says the card was **asked for**, without which `"bare"` cannot
        be told from a segment that never wanted one.

    The second is what keeps the rest from being a document agreeing with
    itself, and its independence is deliberately narrow: the strip comes from
    `record_terminal_opening`'s own copy of the OPENING_STRIP fractions over
    the shared geometry, and the frame is decoded here rather than taken
    from the take's word for it. What it cannot see is a recorder and a
    harness making the same mistake about which strip to read; the sweep
    above, which reads the whole take rather than one frame, is what makes
    that mistake visible.

    **What is deliberately not asserted here**: that `state` follows the `luma`
    beside it. Every take this arm records opens on the card, so a `state`
    pinned to `"card"` would satisfy any such assertion — it could only fail
    together with the "it says card" statement below, which the catalogue calls
    a dominated assertion. What carries that claim instead is structural (one
    expression in `opening_card_report` derives the word from the number it
    publishes) plus `tests/unit`'s `OpeningCard`, which grades the mapping at
    both bars. `tests/README.md`'s Known gaps has it with its measurement.
    """
    from demo_recording.content import (
        OPENING_BARE_MIN_LUMA as PKG_BARE_MIN,
    )
    from demo_recording.content import (
        OPENING_CARD_MAX_LUMA as PKG_CARD_MAX,
    )

    label = "terminal-opening"
    failures: list[str] = []
    # The recorder classifies at record time against the package's copy of
    # these two bars; every statement below is written against this file's.
    # A bar quietly widened on one side has to fail here rather than pass by
    # agreeing with itself.
    if (PKG_CARD_MAX, PKG_BARE_MIN) != (OPENING_CARD_MAX_LUMA, OPENING_BARE_MIN_LUMA):
        failures.append(
            f"{label}: the recorder classifies its opening frame against "
            f"card <= {PKG_CARD_MAX}, bare >= {PKG_BARE_MIN}; this harness "
            f"grades card <= {OPENING_CARD_MAX_LUMA}, bare >= "
            f"{OPENING_BARE_MIN_LUMA} — one of them moved without the other"
        )

    doc = json.loads((out_dir / "timeline.json").read_text())
    opening = ((doc.get("content") or {}).get("opening")) or {}
    card = opening.get("card")
    if not isinstance(card, dict):
        return failures + [
            f"{label}: this take wrote content.opening.card = {card!r}, so its "
            f"timeline says nothing about the frame the segment opened on. "
            f"That is the state issue #235 is about: the mp4 is not committed "
            f"anywhere, so a reviewer with only this directory is back to "
            f"taking somebody's word for it"
        ]
    luma, state = card.get("luma"), card.get("state")
    if not isinstance(luma, (int, float)) or state not in ("card", "bare", "between"):
        return failures + [
            f"{label}: content.opening.card reports luma={luma!r} and "
            f"state={state!r} over rect={card.get('rect')!r} — no reading, so "
            f"nothing below can be graded. The take says: {card.get('note')!r}"
        ]

    # The number against the file. Read here, off frame zero, over the
    # strip this harness worked out for itself — `-t` and no `fps` filter, for
    # the reason OPENING_FIRST_FRAME_S spells out.
    try:
        first = gray_frames(
            out_dir / "demo.mp4", info["strip"], duration=OPENING_FIRST_FRAME_S
        )
    except RuntimeError as exc:
        return failures + [f"{label}: {exc}"]
    if not first:
        return failures + [
            f"{label}: nothing decoded from the first {OPENING_FIRST_FRAME_S}s "
            f"of demo.mp4 over {info['strip']}, so the reported reading has "
            f"nothing to be checked against"
        ]
    measured = sum(first[0]) / len(first[0])
    if abs(measured - luma) > OPENING_CARD_AGREEMENT:
        failures.append(
            f"{label}: the take reports its first frame at {luma} mean luma "
            f"over {card.get('rect')}, and frame zero of demo.mp4 reads "
            f"{measured:.1f} over {info['strip']} — {abs(measured - luma):.1f} "
            f"apart, over the {OPENING_CARD_AGREEMENT} these two readings of "
            f"one frame are allowed. The number in the timeline is not a "
            f"measurement of this video"
        )

    # The acceptance criterion, and the control beside it: this take asked for
    # a card, so "bare" here is the defect rather than the arrangement.
    if state != "card":
        failures.append(
            f"{label}: this take opened with TerminalRecorder(interlude=…) and "
            f"reports its first frame as {state!r} at {luma} mean luma — the "
            f"segment opens on the bare slot and the cover arrives afterwards "
            f"(issue #110), and this time the take's own report says so"
        )
    if card.get("raised") is not True:
        failures.append(
            f"{label}: content.opening.card says raised={card.get('raised')!r} "
            f"on a take constructed with interlude=… — without that flag "
            f"'bare' cannot be told from a segment that never asked for a card"
        )
    if not failures:
        print(
            f"smoke: terminal-opening reports its own opening frame as "
            f"{state} ({luma} mean luma, frame zero here reads {measured:.1f})"
        )
    return failures


def check_evidence(
    label: str,
    out_dir: Path,
    expected: list[tuple[str, str, list[str], list[str]]],
    scope: tuple[str, str, str] | None = None,
    segment: str | None = None,
) -> list[str]:
    """Issue #9's acceptance criterion, made concrete.

    "A reviewer given only the evidence files can state what was on screen
    without seeing an image" is not something a test can assert as written, so
    it is asserted as its consequence: named facts about the fixture app —
    values, labels, table rows, command output — have to be readable in the
    evidence for the beat that showed them, and the values the *previous*
    screen showed have to be gone.

    `segment` names the segment the take recorded under, so this function can
    grade a segmented take's evidence as well as a whole demo's. That is what
    puts it on `--evidence-only`, 7 s, instead of only on the 123 s and 186 s
    arms that record the two graded takes (issue #197).
    """
    beats, docs, failures = evidence_docs(label, out_dir, segment=segment)
    if not docs:
        return failures

    prefix = f"{segment}.seg." if segment else ""
    for position, (beat, doc) in enumerate(zip(beats, docs, strict=False)):
        where = f"{label}: {EVIDENCE_DIR_NAME}/{prefix}beat-{position:02d}.json"
        if doc.get("schema") != EVIDENCE_SCHEMA_EXPECTED:
            failures.append(
                f"{where} says schema {doc.get('schema')!r}, expected "
                f"{EVIDENCE_SCHEMA_EXPECTED!r}"
            )
        if doc.get("segment") != segment:
            failures.append(
                f"{where} claims segment {doc.get('segment')!r}, expected {segment!r}"
            )
        # Computed here rather than read off the take, for the same reason the
        # evidence filename is: a name taken from the file being graded agrees
        # with whatever the file says.
        media = f"{segment}.seg.mp4" if segment else "demo.mp4"
        if doc.get("media") != media:
            failures.append(
                f"{where} describes media {doc.get('media')!r}, expected {media!r}"
            )
        # The embedded beat has to be *this* beat. Without it every file could
        # hold the same screen and every fact below would still be found
        # somewhere.
        stamped = doc.get("beat") or {}
        for field in ("index", "verb", "selector", "caption", "t_start", "t_end"):
            if stamped.get(field) != beat.get(field):
                failures.append(
                    f"{where} stamps beat {field}={stamped.get(field)!r}, but "
                    f"timeline.json says {beat.get(field)!r}"
                )
        if not isinstance(doc.get("truncated"), list):
            failures.append(
                f"{where} has no `truncated` list — a reader cannot tell a "
                f"short page from a cut-off one"
            )

    def find(verb: str, target: str) -> tuple[int, dict] | None:
        hits = [
            (i, doc)
            for i, (beat, doc) in enumerate(zip(beats, docs, strict=False))
            if beat.get("verb") == verb and beat.get("selector") == target
        ]
        if len(hits) != 1:
            failures.append(
                f"{label}: {len(hits)} beats are ({verb!r}, {target!r}), so the "
                f"evidence facts written for it cannot be checked against one"
            )
            return None
        return hits[0]

    for verb, target, present, absent in expected:
        hit = find(verb, target)
        if hit is None:
            continue
        position, doc = hit
        text = evidence_screen_text(doc)
        if not text.strip():
            failures.append(
                f"{label}: beat {position} ({verb} {target!r}) captured no page "
                f"text at all — `aria`/`screen` are empty, so nothing about "
                f"what was on screen survived"
            )
            continue
        missing = [s for s in present if s not in text]
        if missing:
            failures.append(
                f"{label}: the evidence for beat {position} ({verb} {target!r}) "
                f"does not say {missing!r} was on screen. A reviewer holding "
                f"only this file cannot state what the frame showed, which is "
                f"issue #9's acceptance criterion. Captured "
                f"{len(text)} characters."
            )
        leaked = [s for s in absent if s in text]
        if leaked:
            failures.append(
                f"{label}: the evidence for beat {position} ({verb} {target!r}) "
                f"still says {leaked!r} was on screen, which belongs to an "
                f"earlier state of the page — the capture is not per-beat, it "
                f"is a stale dump reused across beats"
            )

    if scope is not None:
        selector, inside, markup = scope
        hit = find("spotlight", selector)
        if hit is not None:
            position, doc = hit
            if doc.get("scope") != selector:
                failures.append(
                    f"{label}: beat {position} spotlights {selector!r} and its "
                    f"evidence scopes to {doc.get('scope')!r} — issue #9 asks "
                    f"for the capture to be scoped to the spotlight target"
                )
            for field, wanted in (("scope_aria", inside), ("html", markup)):
                got = doc.get(field)
                if not isinstance(got, str) or wanted not in got:
                    failures.append(
                        f"{label}: beat {position}'s evidence `{field}` is "
                        f"{str(got)[:120]!r}, which does not contain {wanted!r} "
                        f"— the spotlight target's own tree and markup are "
                        f"what the scope is for"
                    )
        cleared = find("spotlight", None)  # type: ignore[arg-type]
        if cleared is not None:
            position, doc = cleared
            if doc.get("scope") is not None or doc.get("html") is not None:
                failures.append(
                    f"{label}: beat {position} clears the spotlight, but its "
                    f"evidence still scopes to {doc.get('scope')!r} with "
                    f"markup attached — the scope outlives the highlight"
                )

    if not failures:
        sizes = [
            (out_dir / b["evidence"]).stat().st_size for b in beats if b.get("evidence")
        ]
        print(
            f"smoke: {label} evidence ok ({len(docs)} beats, "
            f"{sum(sizes) // 1024} kB, largest {max(sizes)} bytes)"
        )
    return failures


def check_take(
    label: str,
    out_dir: Path,
    shots: list[str],
    duration_range: tuple[float, float],
    started_at: float,
    video_rect: Rect,
    still_rect: Rect,
    frame_size: tuple[int, int],
) -> list[str]:
    """Everything a healthy take leaves behind. Returns failure messages.

    `video_rect`/`still_rect` are where the app itself sits; the bottom fifth
    of each is dropped before scoring so the recorder's caption bar cannot
    supply the contrast for a blank app.
    """
    failures: list[str] = []
    # Before the trim: the recorder does its own, and what is asserted about
    # `content.rect` is that it lands inside the region the *app* occupies.
    app_rect = video_rect
    video_rect = keep_top(video_rect)
    still_rect = keep_top(still_rect)

    def fresh(path: Path) -> bool:
        # Belt and braces next to fresh_take_dir(): an artifact older than the
        # take that supposedly produced it is somebody else's file.
        return path.stat().st_mtime >= started_at - 1

    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        failures.append(f"{label}: {mp4} was never written")
    elif not fresh(mp4):
        failures.append(f"{label}: {mp4} is stale — it predates this run")
    else:
        failures += _check_video(label, mp4, duration_range, video_rect)

    reduced: dict[str, bytes] = {}
    for name in shots:
        png = out_dir / "images" / f"{name}.png"
        if not png.is_file():
            failures.append(f"{label}: still {png} was never captured")
            continue
        if not fresh(png):
            failures.append(f"{label}: still {png} is stale — it predates this run")
            continue
        size = png.stat().st_size
        if size < MIN_PNG_BYTES:
            failures.append(
                f"{label}: still {png} is only {size} bytes "
                f"(expected at least {MIN_PNG_BYTES})"
            )
            continue
        try:
            frames = gray_frames(png, still_rect)
        except RuntimeError as exc:
            failures.append(f"{label}: {exc}")
            continue
        if not frames:
            failures.append(f"{label}: still {png} decoded to no frames")
            continue
        score = contrast(frames[0])
        if score < MIN_CONTENT_STDDEV[label]:
            failures.append(
                f"{label}: still {name}.png is blank — it scores {score:.1f} "
                f"luma stddev over {still_rect}, under the "
                f"{MIN_CONTENT_STDDEV[label]} floor"
            )
            continue
        reduced[name] = frames[0]
        print(
            f"smoke: {label} still {name}.png ok "
            f"({size // 1024} kB, content {score:.1f})"
        )

    # Three identical screenshots satisfy every check above. They must not.
    ordered = [n for n in shots if n in reduced]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        delta = frame_difference(reduced[previous], reduced[current])
        if delta < MIN_STILL_DIFF:
            failures.append(
                f"{label}: stills {previous}.png and {current}.png are the "
                f"same picture (mean luma difference {delta:.2f}, floor "
                f"{MIN_STILL_DIFF}) — the screenshot is stale, or the beat "
                f"between them changed nothing"
            )

    # Pixel proof that the caption bar reached the screen, not just the DOM.
    # The two probe stills are the same frame with the caption off and on, so
    # any change in the caption band is the caption and nothing else.
    off, on = (out_dir / "images" / f"{n}.png" for n in CAPTION_PROBE)
    if not (off.is_file() and on.is_file()):
        failures.append(
            f"{label}: the caption probe stills {CAPTION_PROBE[0]}.png and "
            f"{CAPTION_PROBE[1]}.png were not both captured"
        )
    else:
        band = caption_probe_band(label, frame_size)
        try:
            before = gray_frames(off, band)
            after = gray_frames(on, band)
        except RuntimeError as exc:
            failures.append(f"{label}: {exc}")
        else:
            delta = frame_difference(before[0], after[0]) if before and after else 0.0
            if delta < MIN_CAPTION_BAND_DIFF[label]:
                failures.append(
                    f"{label}: setting a caption changed nothing on screen — "
                    f"the caption band moved by {delta:.2f} mean luma between "
                    f"{CAPTION_PROBE[0]}.png and {CAPTION_PROBE[1]}.png, under "
                    f"the {MIN_CAPTION_BAND_DIFF[label]} floor. The bar is in "
                    f"the DOM but is not being drawn."
                )
            else:
                print(
                    f"smoke: {label} caption is visible on screen (delta {delta:.1f})"
                )

    # What the recorder itself says about the picture (issue #97). On every
    # graded take, not only the one written for it: the check has to be wired
    # into the web recorder, the terminal recorder and `stitch()`, and each of
    # those is a separate place to have forgotten it.
    failures += check_content_healthy(label, out_dir, app_rect)

    return failures


def check_strict_failure(
    label: str, out_dir: Path, exc: BaseException | None, kinds: list[str]
) -> list[str]:
    """What a refused take must have done besides refusing.

    Three things, and the last two are the ones worth having. It has to raise
    — but it also has to say *which beat* the problem fired during, which is
    issue #3's acceptance criterion verbatim, and it has to leave the mp4, the
    stills and the timeline on disk. A broken take is precisely the one
    somebody wants to look at; failing it by destroying the evidence would be
    worse than not failing it.
    """
    from demo_recording import StrictTakeFailed
    from demo_recording.timeline import STRICT_KINDS

    failures: list[str] = []
    if exc is None:
        return [
            f"{label}: strict=True recorded a storyboard written to break in a "
            f"way STRICT_KINDS calls fatal, and the take succeeded — strict "
            f"mode does not fail anything"
        ]
    if not isinstance(exc, StrictTakeFailed):
        return [
            f"{label}: strict=True raised {type(exc).__name__} rather than "
            f"StrictTakeFailed: {exc}"
        ]

    message = str(exc)
    for kind in kinds:
        if kind not in message:
            failures.append(
                f"{label}: the strict failure does not mention the {kind} the "
                f"storyboard caused. It said: {' '.join(message.split())[:300]}"
            )
    named = STRICT_BEAT_RE.search(message)
    if named is None:
        failures.append(
            f"{label}: the strict failure never names the beat the problem "
            f"fired during — 'the take broke' is not a bug report. It said: "
            f"{' '.join(message.split())[:300]}"
        )

    json_path = out_dir / "timeline.json"
    if not (out_dir / "demo.mp4").is_file():
        failures.append(
            f"{label}: strict failed the take and no demo.mp4 was written — "
            f"the recording of the failure is the thing worth keeping"
        )
    if not json_path.is_file():
        failures.append(f"{label}: strict failed the take and wrote no timeline.json")
        return failures
    doc = json.loads(json_path.read_text())
    if doc.get("strict") is not True:
        failures.append(
            f"{label}: the refused take's timeline.json says "
            f"strict={doc.get('strict')!r}"
        )
    fatal = [i for i in (doc.get("issues") or []) if i.get("kind") in STRICT_KINDS]
    if not fatal:
        failures.append(
            f"{label}: the take was refused but its timeline.json lists no "
            f"issue of a kind in STRICT_KINDS — the verdict and the log "
            f"disagree about why"
        )
    if not failures:
        print(
            f"smoke: {label} strict=True refused the take, naming "
            f"{named.group(0) if named else '?'} ({len(fatal)} fatal issues, "
            f"artifacts kept)"
        )
    return failures


def check_wrapper_band(out_dir: Path, info: dict) -> list[str]:
    """The caption lit its band and left the app rect's pixels alone (#358).

    The geometry half of "the band and the app share no pixels" is
    `tests/unit`'s (`WrapperChrome`); this is the pixel half, read out of
    demo.mp4 the way a viewer meets it. The band is located by sweeping its
    own rect for contrast — the empty band is flat window body — rather than
    by trusting a beat timestamp through a steppable wall clock (#245).
    """
    failures = []
    mp4 = out_dir / "demo.mp4"
    geom = info["geom"]
    band: Rect = (geom["bandx"], geom["bandy"], geom["bandw"], geom["bandh"])
    app: Rect = (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
    sweep = gray_frames(mp4, rect=band, sample_fps=WRAPPER_BAND_SWEEP_FPS)
    if len(sweep) < WRAPPER_BAND_SWEEP_FPS * 3:
        return [
            f"wrapper: the band sweep decoded {len(sweep)} frames — too few "
            f"to hold a caption at all, so nothing below could fail honestly"
        ]
    lit = [contrast(f) >= WRAPPER_BAND_LIT for f in sweep]
    run = longest_true_run(lit)
    if run is None:
        return [
            f"wrapper: no frame of the caption band {band} ever reaches "
            f"{WRAPPER_BAND_LIT} contrast across "
            f"{len(sweep) / WRAPPER_BAND_SWEEP_FPS:.1f}s — the caption "
            f"{WRAPPER_CAPTION!r} never painted in its band"
        ]
    start, length = run
    if length / WRAPPER_BAND_SWEEP_FPS < WRAPPER_BAND_MIN_S:
        failures.append(
            f"wrapper: the band was lit for only "
            f"{length / WRAPPER_BAND_SWEEP_FPS:.1f}s — a flicker, not the "
            f"caption beat the timeline logs"
        )
    if start == 0:
        failures.append(
            "wrapper: the band is lit from frame 0, so there is no unlit "
            "control — nothing separates a caption in its band from a band "
            "that is simply always painted"
        )
    else:
        unlit_before = contrast(sweep[start - 1])
        # One frame back can be mid-fade; the claim is about the stretch
        # before the caption, so read the quietest frame in it.
        quietest = min(contrast(f) for f in sweep[:start])
        if quietest > WRAPPER_BAND_UNLIT:
            failures.append(
                f"wrapper: before the caption the band never drops under "
                f"{WRAPPER_BAND_UNLIT} contrast (quietest {quietest:.1f}, "
                f"frame before the stretch {unlit_before:.1f}) — the unlit "
                f"control is missing"
            )
    if lit[-1]:
        failures.append(
            "wrapper: the band is still lit in the last sampled frame — "
            "caption('') did not clear it"
        )
    # The app rect across the caption's appearance: the two instants bracket
    # the fade and nothing else, so any movement is the caption painting
    # where it must not.
    control_at = max(0.0, start / WRAPPER_BAND_SWEEP_FPS - WRAPPER_APP_CONTROL_S)
    sample_at = start / WRAPPER_BAND_SWEEP_FPS + WRAPPER_APP_SAMPLE_S
    before = gray_frames(mp4, rect=app, start=control_at, duration=0.05)
    during = gray_frames(mp4, rect=app, start=sample_at, duration=0.05)
    if not before or not during:
        failures.append(
            f"wrapper: the app rect {app} decoded no frame at "
            f"{control_at:.2f}s/{sample_at:.2f}s — the stillness claim has "
            f"nothing to read"
        )
    else:
        moved = frame_difference(before[0], during[0])
        if moved > WRAPPER_APP_MAX_DELTA:
            failures.append(
                f"wrapper: the app rect moved {moved:.2f} mean luma between "
                f"{control_at:.2f}s and {sample_at:.2f}s, over the "
                f"{WRAPPER_APP_MAX_DELTA} bar — the caption's appearance "
                f"changed pixels inside the app rect, which is the overlap "
                f"the band exists to remove (#355)"
            )
        else:
            print(
                f"wrapper: band lit {length / WRAPPER_BAND_SWEEP_FPS:.1f}s "
                f"from {start / WRAPPER_BAND_SWEEP_FPS:.1f}s, app rect moved "
                f"{moved:.2f} (bar {WRAPPER_APP_MAX_DELTA}) across the "
                f"caption's appearance"
            )
    return failures


def check_wrapper_opening(out_dir: Path, info: dict) -> list[str]:
    """The wrapper take's first frame is the opening hold (#360).

    The wrapper path has no exit-time composite, so the legacy ffmpeg
    `enable='lt(t,held)'` overlay cannot cover a blank opening — the hold is
    in the page instead, opaque from frame 0 (chrome.OPENING_HOLD_JS), and
    this reads it the way `check_opening_card` reads the terminal's: a strip
    of the frame, frame zero **exactly** (`-t`, no fps filter — the filter
    hands back a frame from mid-slot, the defect content.py records), bars
    an order of magnitude apart.

    The strip is inside the app rect, where the hold is told apart from the
    slot's white canvas (~255) and from the bare app (~226) by the window
    body's ~24. Two claims: frame zero reads the hold, and the strip later
    reads the bare app — without the second, a hold never cleared (the #91
    shape) satisfies the first forever.
    """
    mp4 = out_dir / "demo.mp4"
    geom = info["geom"]
    app: Rect = (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
    strip = card_strip(app)
    failures: list[str] = []
    first = gray_frames(mp4, rect=strip, duration=WRAPPER_FIRST_FRAME_S)
    if not first:
        return [
            f"wrapper-opening: nothing decoded from the first "
            f"{WRAPPER_FIRST_FRAME_S}s of demo.mp4 over {strip}, so what the "
            f"take opened on cannot be read"
        ]
    luma0 = sum(first[0]) / len(first[0])
    if luma0 > WRAPPER_HOLD_MAX_LUMA:
        failures.append(
            f"wrapper-opening: the wrapper take's first frame reads {luma0:.1f} "
            f"mean luma over {strip}, over the {WRAPPER_HOLD_MAX_LUMA} bar for "
            f"the opening hold — the card layer was not opaque in frame 0, so "
            f"the take opens on the slot's canvas or the loading app instead "
            f"of the hold (#360)"
        )
    sweep = gray_frames(mp4, rect=strip, sample_fps=WRAPPER_BAND_SWEEP_FPS)
    bare = [
        i
        for i, frame in enumerate(sweep)
        if sum(frame) / len(frame) >= WRAPPER_BARE_MIN_LUMA
    ]
    if not bare:
        failures.append(
            f"wrapper-opening: no frame of {len(sweep)} at "
            f"{WRAPPER_BAND_SWEEP_FPS} fps ever reads {WRAPPER_BARE_MIN_LUMA} "
            f"mean luma over {strip} — the hold (or a card) covers the app "
            f"for the whole take, so the first-frame reading above would be "
            f"satisfied by a recorder that painted a rectangle and stopped"
        )
    if not failures:
        print(
            f"wrapper-opening: frame 0 reads {luma0:.1f} over {strip} (hold "
            f"<= {WRAPPER_HOLD_MAX_LUMA}), and the app shows from "
            f"{bare[0] / WRAPPER_BAND_SWEEP_FPS:.1f}s (bare >= "
            f"{WRAPPER_BARE_MIN_LUMA})"
        )
    return failures


def check_wrapper_card(out_dir: Path, info: dict) -> list[str]:
    """The wrapper card is the window's colour on screen, uncompensated (#360).

    `check_criterion_card`'s question asked of the single-encoder path: the
    card and the window body declare **one** colour (`core.WEB_WINDOW_BODY`)
    and reach demo.mp4 through one encoder, so as encoded they must sit
    within WRAPPER_CARD_WINDOW_TOLERANCE, worst channel. Read out of the
    pixels on both sides — #297 recorded both declaration-shaped
    alternatives (pinned equal, pinned apart) as anti-patterns, and neither
    is asserted here or anywhere.

    The instants are found in the video, then tied to the log by overlap
    (`card_run`, the pixel golden's locator): a fixed fraction of the
    *logged* span lands on the card's fade when the host's clock steps
    (#245) — see the note over WRAPPER_CARD_SWEEP_FPS for the take that
    proved it.

    The premise the readings need: after the card is down, the strip must
    read as something *other* than the window body, or an app the colour of
    the card would pass with no card in the recording at all.
    """
    mp4 = out_dir / "demo.mp4"
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    cards = [b for b in doc.get("beats") or [] if b.get("verb") == "criterion"]
    if len(cards) != 1:
        return [
            f"wrapper-card: the take logged {len(cards)} criterion beats, "
            f"expected 1 — there is no card span to read"
        ]
    start, end = float(cards[0]["t_start"]), float(cards[0]["t_end"])
    geom = info["geom"]
    app: Rect = (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
    strip = card_strip(app)
    pad = wrapper_pad_band(geom)

    sweep = gray_frames(mp4, rect=strip, sample_fps=WRAPPER_CARD_SWEEP_FPS)
    dark = [sum(f) / len(f) <= WRAPPER_CARD_LOCATE_MAX_LUMA for f in sweep if len(f)]
    media_s = len(sweep) / WRAPPER_CARD_SWEEP_FPS
    run = card_run(dark, WRAPPER_CARD_SWEEP_FPS, (start, end))
    if run is None:
        return [
            f"wrapper-card: no dark stretch of the app strip {strip} "
            f"(<= {WRAPPER_CARD_LOCATE_MAX_LUMA:.0f} mean luma at "
            f"{WRAPPER_CARD_SWEEP_FPS} fps, {media_s:.1f}s of video) overlaps "
            f"the criterion beat logged at {start:.2f}-{end:.2f}s — the card "
            f"never painted"
        ]
    run_start, run_len = run
    rs = run_start / WRAPPER_CARD_SWEEP_FPS
    re_ = (run_start + run_len) / WRAPPER_CARD_SWEEP_FPS
    if run_len / WRAPPER_CARD_SWEEP_FPS < max(
        WRAPPER_CARD_MIN_STRETCH_S, 0.5 * (end - start)
    ):
        return [
            f"wrapper-card: the card stretch in the video is only "
            f"{run_len / WRAPPER_CARD_SWEEP_FPS:.1f}s ({rs:.2f}-{re_:.2f}s) "
            f"against a criterion beat logged {end - start:.1f}s long — the "
            f"card flashed rather than held"
        ]
    if media_s - re_ < WRAPPER_CARD_MIN_DOWN_S:
        return [
            f"wrapper-card: the card stretch runs to {re_:.2f}s of a "
            f"{media_s:.1f}s video — the card is never taken down, and there "
            f"is no app stretch to tell it apart from"
        ]

    control_at = re_ + (media_s - re_) * 0.5
    control = strip_rgb(mp4, control_at, strip)
    control_pad = strip_rgb(mp4, control_at, pad)
    if control is None or control_pad is None:
        return [
            f"wrapper-card: demo.mp4 decodes no frame at {control_at:.2f}s, "
            f"so there is no no-card control to compare with"
        ]
    control_gap = channels_apart(control, control_pad)
    if control_gap <= WRAPPER_CARD_CONTROL_MIN_GAP:
        return [
            f"wrapper-card: with the card down since {re_:.2f}s the strip "
            f"{strip} reads {tuple(round(v) for v in control)} at "
            f"{control_at:.2f}s, only {control_gap:.0f} levels off the window "
            f"body {tuple(round(v) for v in control_pad)} (premise bar "
            f"{WRAPPER_CARD_CONTROL_MIN_GAP}) — either the app cannot be told "
            f"from the card, or the card was never taken down"
        ]

    trim = WRAPPER_CARD_EDGE_TRIM / WRAPPER_CARD_SWEEP_FPS
    lo, hi = rs + trim, re_ - trim
    if hi <= lo:
        lo = hi = (rs + re_) / 2
    failures: list[str] = []
    gaps: list[float] = []
    for fraction in WRAPPER_CARD_FRACTIONS:
        at = lo + (hi - lo) * fraction
        card = strip_rgb(mp4, at, strip)
        body = strip_rgb(mp4, at, pad)
        if card is None or body is None:
            failures.append(
                f"wrapper-card: demo.mp4 decodes no frame at {at:.2f}s over "
                f"{strip} or {pad}"
            )
            continue
        gap = channels_apart(card, body)
        gaps.append(gap)
        if gap > WRAPPER_CARD_WINDOW_TOLERANCE:
            failures.append(
                f"wrapper-card: {at:.2f}s, inside the card's own stretch of "
                f"the video ({rs:.2f}-{re_:.2f}s), the card reads "
                f"{tuple(round(v) for v in card)} over {strip} and the window "
                f"body {tuple(round(v) for v in body)} over {pad}, {gap:.1f} "
                f"levels apart, worst channel (bar "
                f"{WRAPPER_CARD_WINDOW_TOLERANCE}). On the wrapper path the "
                f"two declare one colour and ride one encoder (#360), so this "
                f"gap means the card's field was repainted away from "
                f"core.WEB_WINDOW_BODY — the #291 mismatch a human once had "
                f"to spot by eye"
            )
    if not failures:
        print(
            f"wrapper-card: card and window body sit {max(gaps):.1f} apart, "
            f"worst channel over {len(gaps)} samples inside the card's "
            f"{rs:.2f}-{re_:.2f}s stretch (bar "
            f"{WRAPPER_CARD_WINDOW_TOLERANCE}); the no-card control reads "
            f"{control_gap:.0f} off the body (premise bar "
            f"{WRAPPER_CARD_CONTROL_MIN_GAP}) — one declared colour, one "
            f"encoder, uncompensated"
        )
    return failures


def check_wrapper_caption_survives(out_dir: Path, info: dict) -> list[str]:
    """The caption outlives the app's document, in the pixels (#360).

    The wrapper document holds the caption and never navigates, so a
    mid-take `goto()` — a full document replacement in the app iframe —
    cannot take the line off the screen, which is where the #134
    `caption_lost` class ends. Graded from the frames: the second document's
    arrival is located by its own luma band in the app rect (a run, not a
    single frame — any fade passes through any band), and the caption band
    must be lit before it and stay lit after it. The beat log must agree:
    no `caption_lost` issue anywhere (the wrapper recorder does not even
    listen for it), and the goto's own beat still reporting the line.
    """
    mp4 = out_dir / "demo.mp4"
    geom = info["geom"]
    app: Rect = (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
    band: Rect = (geom["bandx"], geom["bandy"], geom["bandw"], geom["bandh"])
    sweep = gray_frames(mp4, rect=app, sample_fps=WRAPPER_BAND_SWEEP_FPS)
    means = [sum(f) / len(f) for f in sweep]
    in_band = [
        WRAPPER_SECOND_MIN_LUMA <= value <= WRAPPER_SECOND_MAX_LUMA for value in means
    ]
    arrival: int | None = None
    for i in range(len(in_band) - WRAPPER_SECOND_MIN_FRAMES + 1):
        if all(in_band[i : i + WRAPPER_SECOND_MIN_FRAMES]):
            arrival = i
            break
    failures: list[str] = []
    if arrival is None:
        return [
            f"wrapper-survives: no {WRAPPER_SECOND_MIN_FRAMES}-frame run of "
            f"the app rect ever reads inside {WRAPPER_SECOND_MIN_LUMA}.."
            f"{WRAPPER_SECOND_MAX_LUMA} mean luma — second.html never arrived "
            f"on screen, so nothing survived anything"
        ]
    arrived_s = arrival / WRAPPER_BAND_SWEEP_FPS
    before = gray_frames(
        mp4,
        rect=band,
        start=max(0.0, arrived_s - WRAPPER_APP_CONTROL_S),
        duration=0.05,
    )
    if not before or contrast(before[0]) < WRAPPER_BAND_LIT:
        failures.append(
            f"wrapper-survives: the caption band was not lit just before the "
            f"second document arrived at {arrived_s:.1f}s (contrast "
            f"{contrast(before[0]) if before else 'unreadable'} vs bar "
            f"{WRAPPER_BAND_LIT}) — with no line up across the load, nothing "
            f"here can claim one survived it"
        )
    for offset in WRAPPER_SURVIVES_SAMPLES_S:
        at = arrived_s + offset
        frames = gray_frames(mp4, rect=band, start=at, duration=0.05)
        if not frames:
            failures.append(
                f"wrapper-survives: the band {band} decoded no frame at {at:.2f}s"
            )
            continue
        lit = contrast(frames[0])
        if lit < WRAPPER_BAND_LIT:
            failures.append(
                f"wrapper-survives: {offset:.1f}s after the second document "
                f"arrived the caption band reads {lit:.1f} contrast, under "
                f"the {WRAPPER_BAND_LIT} lit bar — the caption band went dark "
                f"across the load, which is the #134 loss the wrapper "
                f"document exists to end (#360)"
            )
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    lost = [
        issue
        for issue in doc.get("issues") or []
        if issue.get("kind") == "caption_lost"
    ]
    if lost:
        failures.append(
            f"wrapper-survives: the take recorded {len(lost)} caption_lost "
            f"issue(s) — on the wrapper path the caption cannot be destroyed "
            f"by navigation, so this record claims a loss that cannot happen"
        )
    gotos = [b for b in doc.get("beats") or [] if b.get("verb") == "goto"]
    second = [b for b in gotos if "second.html" in str(b.get("selector"))]
    if len(second) != 1:
        failures.append(
            f"wrapper-survives: {len(second)} goto beats name second.html, "
            f"expected 1 — the beat-log half of the claim has no beat to read"
        )
    elif second[0].get("caption") != WRAPPER_SURVIVES:
        failures.append(
            f"wrapper-survives: the goto beat to second.html reports caption "
            f"{second[0].get('caption')!r}, not {WRAPPER_SURVIVES!r} — the "
            f"beat log dropped a line that is still on screen"
        )
    if not failures:
        print(
            f"wrapper-survives: second.html arrives at {arrived_s:.1f}s, band "
            f"lit before and at +{WRAPPER_SURVIVES_SAMPLES_S}s after; no "
            f"caption_lost recorded, goto beat still reports the line"
        )
    return failures


def check_wrapper_evidence(out_dir: Path) -> list[str]:
    """Evidence on a wrapper take describes the app, not the recorder.

    The wrapper page's own body is chrome and one opaque iframe node, so an
    evidence capture that stayed on `rec.page` would still write plausible
    files — url, title, a well-formed aria tree — describing the recorder.
    The fixture's own heading is what tells the two apart.
    """
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    caption_beats = [
        b
        for b in doc.get("beats") or []
        if b.get("verb") == "caption" and b.get("caption") == WRAPPER_CAPTION
    ]
    if len(caption_beats) != 1:
        return [
            f"wrapper: {len(caption_beats)} beats caption {WRAPPER_CAPTION!r},"
            f" expected 1 — there is no beat to read evidence for"
        ]
    evidence_rel = caption_beats[0].get("evidence")
    if not evidence_rel:
        return ["wrapper: the caption beat carries no evidence pointer"]
    evidence = json.loads((out_dir / evidence_rel).read_text(encoding="utf-8"))
    aria = evidence.get("aria") or ""
    if "Northwind Ops" not in aria:
        return [
            f"wrapper: the caption beat's evidence aria never mentions the "
            f"fixture's own heading — evidence reads the wrapper chrome, not "
            f"the app ({out_dir / evidence_rel})"
        ]
    return []


def check_wrapper_clipped(out_dir: Path) -> list[str]:
    """The band says so when it cannot show a caption (#366's review).

    The take captions one line the band holds and one it cannot; the second
    must leave a `caption_clipped` issue naming the line and the overflow,
    and the first must leave none — over-reporting would file an issue on
    every caption of every wrapper take. The text is deliberately not capped
    or reflowed by the recorder; the record is the whole fix.
    """
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    issues = [
        issue
        for issue in doc.get("issues") or []
        if issue.get("kind") == "caption_clipped"
    ]
    failures = []
    named = [i for i in issues if i.get("caption") == WRAPPER_LONG_CAPTION]
    if not named:
        failures.append(
            f"wrapper: the {len(WRAPPER_LONG_CAPTION)}-char caption left no "
            f"caption_clipped issue — the band shaved its first and last "
            f"lines and no artifact says so, which is timeline.json claiming "
            f"a line the pixels do not show"
        )
    else:
        clipped_px = named[0].get("clipped_px")
        if not isinstance(clipped_px, (int, float)) or clipped_px <= 0:
            failures.append(
                f"wrapper: the caption_clipped issue carries clipped_px="
                f"{clipped_px!r} — without a positive reading nobody can say "
                f"how much of the line the band shaved"
            )
    fitting = [i for i in issues if i.get("caption") != WRAPPER_LONG_CAPTION]
    if fitting:
        failures.append(
            f"wrapper: caption_clipped was recorded for {len(fitting)} "
            f"caption(s) that fit their band — an issue filed on every "
            f"caption is the artifact crying wolf"
        )
    return failures


def check_wrapper_refusal(out_dir: Path, raised: BaseException | None) -> list[str]:
    """An app that refuses framing is refused by name, before any beat shows
    it (#358): a blocked iframe recorded as a demo is the artifact-lie
    outcome this arm exists to keep out.

    The take this grades records with `strict=False`, deliberately: the
    blocked navigation also logs a console error, so under strict a
    swallowed refusal would still surface as `StrictTakeFailed` and the
    completed-without-raising claim below could never fail for the reason it
    names. The refusal has to stand on its own, not lean on strict's net.
    """
    failures = []
    if raised is None:
        failures.append(
            "wrapper-refused: recording against X-Frame-Options: DENY "
            "completed without raising — the take recorded a silently blank "
            "window as a demo"
        )
    else:
        message = str(raised)
        if "X-Frame-Options" not in message or "DENY" not in message:
            failures.append(
                f"wrapper-refused: the refusal does not name the header that "
                f"caused it — a storyboard author cannot act on "
                f"{type(raised).__name__}: {message[:200]!r}"
            )
    doc_path = out_dir / "timeline.json"
    if doc_path.is_file():
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
        reached = [
            b for b in doc.get("beats") or [] if b.get("caption") == WRAPPER_UNREACHED
        ]
        if reached:
            failures.append(
                "wrapper-refused: the storyboard line after the refused goto "
                "still recorded a beat — the take went on recording after "
                "the app refused to be framed"
            )
    return failures


def check_stills_only(out_dir: Path, elapsed: float) -> list[str]:
    """Nothing here may be readable as a take, and none of it may be slow."""
    failures = []
    # The one a browser has to answer. Everything else about this folder is
    # written by code `tests/unit` reaches with a fake page; whether Chromium
    # was actually told not to capture is only visible here.
    for stray in ("demo.mp4", "frames"):
        if (out_dir / stray).exists():
            failures.append(
                f"stills-only: {stray} exists, and this run declined the "
                f"screencast — so whatever wrote it is a recording the "
                f"timeline beside it says does not exist ({stray})"
            )
    stills = sorted(p.name for p in (out_dir / "images").glob("*.png"))
    if stills != ["01-dashboard.png", "02-card.png"]:
        failures.append(
            f"stills-only: images/ holds {stills}, not both shots — the "
            f"pictures are the entire output of this mode"
        )
    doc = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    for key, want in (("mode", "stills"), ("media", None), ("duration", None)):
        if doc.get(key, "absent") != want:
            failures.append(
                f"stills-only: timeline.json says {key}={doc.get(key, 'absent')!r}, "
                f"not {want!r} — a reader cannot tell this from a take that "
                f"failed to encode"
            )
    if "content" in doc:
        failures.append(
            "stills-only: timeline.json carries `content`, which is a claim "
            "about frames this run never had"
        )
    if not (out_dir / "evidence").is_dir():
        failures.append(
            "stills-only: no evidence/ — the mode writes it, and a beat "
            "pointing at a file that is not there is the ordering #11 forbids"
        )
    if elapsed > STILLS_PACING_BUDGET_S:
        failures.append(
            f"stills-only: the run took {elapsed:.1f}s against a "
            f"{STILLS_PACING_BUDGET_S:.0f}s budget, over a storyboard "
            f"declaring {STILLS_DECLARED_HOLD_S:.0f}s of holds — the pacing "
            f"is being spent, which is the whole of what this mode saves"
        )
    print(
        f"stills-only: {len(stills)} still(s), no video, {elapsed:.1f}s "
        f"(budget {STILLS_PACING_BUDGET_S:.0f}s over "
        f"{STILLS_DECLARED_HOLD_S:.0f}s of declared holds)"
    )
    return failures


def check_entropy_stills(
    first: EntropyTake, stills: dict[str, dict[str, Path]]
) -> list[str]:
    """The two byte comparisons: across two takes, and within one take.

    Byte equality rather than a decoded-pixel tolerance, kept deliberately.
    It is the strongest form of the claim ("the still you commit today is the
    still you record next month"), it needs no threshold anybody has to
    defend, and — since issue #185 — it is a claim the take can keep: the one
    thing that was breaking it was a pointer position the storyboard did not
    set. What changed is the *report*: the difference is now stated at the
    scope the hash grades, so a failure here names its own reason instead of
    contradicting itself.
    """
    failures: list[str] = []
    for shot in ENTROPY_SHOTS:
        one, two = stills["determinism-a"][shot], stills["determinism-b"][shot]
        if digest(one) != digest(two):
            failures.append(
                f"determinism: {shot}.png differs between two takes of the "
                f"same storyboard ({digest(one)} vs {digest(two)}) — "
                f"re-recording does not reproduce the stills, so a still "
                f"cannot be diffed against the one committed last month. "
                f"{still_difference(one, two, first.still_rect)}"
            )
    # The same picture twice inside one take: the clock cannot have moved and
    # the spinner cannot have turned.
    inside = stills["determinism-a"]
    if digest(inside[ENTROPY_SHOTS[0]]) != digest(inside[ENTROPY_SHOTS[1]]):
        failures.append(
            f"determinism: {ENTROPY_SHOTS[0]}.png and {ENTROPY_SHOTS[1]}.png "
            f"differ within one take, {ENTROPY_GAP_S}s apart on a page nothing "
            f"touched — something on screen is still moving with the clock. "
            f"{still_difference(inside[ENTROPY_SHOTS[0]], inside[ENTROPY_SHOTS[1]], first.still_rect)}"
        )
    return failures


def check_evidence_omissions(
    label: str, index: int, doc: dict, aria: str | None
) -> list[str]:
    """Does this beat's evidence say what its ARIA snapshot could not carry?

    **Evidence claims to describe what the beat showed** (#9), and two shapes
    of visible text never reach `aria_snapshot()` at all: the contents of a
    rich-text editor (`contenteditable` with `role="textbox"`, whose
    accessible value is read off a `value` property a `div` does not have) and
    anything under `aria-hidden="true"`, which the attribute removes from the
    accessibility tree by definition while the pixels stay on screen. Until
    issue #353 they left no trace, so the file read as a complete account of a
    screen it had only partly seen.

    Read off the **unspotlit** beat: this is a property of the page, not of a
    scope.

    Both directions are graded, because the field can be wrong twice. Silence
    is the defect #353 is about. A probe that reports *everything* is the same
    artifact lie pointing the other way, and it is the one that gets the field
    ignored — `aria-hidden` sits on an icon wrapper somewhere on nearly every
    real page, and reporting those buries the two that matter.
    """
    failures: list[str] = []
    omits = str(doc.get("aria_omits") or "")
    aria_text = aria if isinstance(aria, str) else ""
    for what, needle in (
        ("a rich-text editor's contents", EVIDENCE_RICH_TEXT),
        ("a painted aria-hidden subtree", EVIDENCE_HIDDEN_TEXT),
    ):
        # The control first, and it is the whole reason this can be graded: if
        # the snapshot *did* carry it, `aria_omits` would be reporting an
        # omission that did not happen, and the assertion below would be
        # measuring the fixture rather than the recorder.
        if needle in aria_text:
            failures.append(
                f"{label}: {needle!r} is in beat {index}'s ARIA tree, so "
                f"{what} is not omitted after all — this fixture no longer "
                f"reproduces issue #353 and `aria_omits` is being graded "
                f"against a page that does not need it"
            )
        elif needle not in omits:
            failures.append(
                f"{label}: beat {index} shows {what} on screen and neither "
                f"`aria` nor `aria_omits` contains {needle!r}. Evidence that "
                f"omits on-screen text without saying so is an artifact "
                f"describing a screen it only partly saw (issue #353)"
            )
    for needle, why in (
        (EVIDENCE_UNPAINTED_TEXT, "`display:none`, so it was never painted"),
        (EVIDENCE_CLIPPED_TEXT, "clipped to no height, so it was never painted"),
        (EVIDENCE_INVISIBLE_TEXT, "`visibility:hidden`, so it was never painted"),
    ):
        if needle in omits:
            failures.append(
                f"{label}: beat {index}'s `aria_omits` names {needle!r}, "
                f"which is {why} — nothing was on screen, so nothing was "
                f"omitted"
            )
    return failures


def check_narration_pacing(out_dir: Path) -> list[str]:
    """A beat cannot start while the previous line is still being spoken."""
    label = "narration"
    failures: list[str] = []
    doc = json.loads((out_dir / "timeline.json").read_text())
    beats = doc.get("beats", [])

    def after(verb: str, caption: str) -> tuple[dict, dict] | None:
        for i, beat in enumerate(beats[:-1]):
            if beat.get("verb") == verb and beat.get("caption") == caption:
                return beat, beats[i + 1]
        return None

    long_pair = after("interlude", NARRATION_LONG_LINE)
    short_pair = after("caption", NARRATION_SHORT_LINE)
    if long_pair is None or short_pair is None:
        return [
            f"{label}: timeline.json has no interlude/caption pair to measure "
            f"pacing over — verbs recorded: "
            f"{[b.get('verb') for b in beats]}"
        ]

    # The long clip outlasts its beat's hold, so the *next* beat cannot begin
    # until the clip has finished. This is the only observable the pacing has:
    # `_finish_line` idles between beats, so the wait lands in the gap rather
    # than inside either one.
    line, following = long_pair
    elapsed = float(following["t_start"]) - float(line["t_start"])
    if elapsed < NARRATION_LONG_S:
        failures.append(
            f"{label}: the beat after a {NARRATION_LONG_S}s line started "
            f"{elapsed:.2f}s after it began — the recorder cut its own "
            f"narration off, and the mp4 carries a clip that outlives the "
            f"caption it belongs to"
        )

    # The control, and the reason the bar above is not "everything is slow":
    # the short clip finishes inside its hold, so nothing is added. A recorder
    # that idled a fixed amount after every line would pass the assertion above
    # and fail this one.
    line, following = short_pair
    elapsed = float(following["t_start"]) - float(line["t_start"])
    if elapsed >= NARRATION_LONG_S:
        failures.append(
            f"{label}: the beat after a {NARRATION_SHORT_S}s line was held "
            f"{elapsed:.2f}s, past even the long line's clip — the wait is not "
            f"the clip's length, so the assertion above grades nothing"
        )
    return failures


def check_narration_placement(
    out_dir: Path, lines: list, clock: HostClock
) -> list[str]:
    """Each clip is where it belongs **in the video**, read off the file (#226).

    `check_narration_audio` below asks whether the mix happened. This asks
    where it landed, and the difference is the whole of issue #226: a clip
    delayed by the offset the beat log recorded is on `time.monotonic()`, the
    video it is mixed into is stamped with the host's wall clock, and on a host
    that steps that clock the voice trails the caption it belongs to for the
    rest of the take — measured at +0.70 s on every line of one take (#18).

    Three claims, and none of them is the recorder agreeing with itself:

    1. the take's own `_lines` are what `timeline.json`'s `narration` says it
       was given, line for line;
    2. every `at` in that record is where **this harness's** wall-clock reading
       puts that instant in the video. `clock.before()` is sampled in this
       process by code the recorder cannot reach, so a recorder that stopped
       correcting, or corrected by the wrong number, disagrees with it;
    3. every clip's onset **in the encoded audio** is at that same
       independently-derived second, and every clip's span is as long as the
       tone this file seeded. Measured with `silencedetect` off the finished
       mp4, so nothing in this claim is computed from what the recorder wrote
       down — a record and a mix that agree with each other and not with the
       world fail claim 3 while satisfying claim 2, and the reverse.

    **What this cannot say on a steady host**, and it is stated rather than
    implied: where the wall clock does not step, `clock.before()` is zero, the
    correction is zero, and claims 2 and 3 hold identically for a mix that
    never corrected anything. The arithmetic of the correction is graded in
    `tests/unit` (`NarrationMix`) against scripted records; what this adds is
    that the clip really is in the file at the second the record names.

    **And what it cannot say where the clips merge.** Once a step puts one
    clip inside another, claim 3 sees one stretch and can only grade its two
    edges — a short clip moved anywhere inside a long one, or dropped from the
    mix entirely, changes neither. Measured on a real stepped take of this arm
    (lines at 2.101 s and 3.301 s, a −1.073 s step at 2.214 s): line 1 mixed
    0.772 s late reads clean, and line 1 omitted reads clean; the blind window
    is about **1.17 s**, which is inside the 0.70–1.50 s band the defect lives
    in. It needs the record to still name the right second, so claim 2 has to
    have been satisfied by a lie that is consistent with itself. This is not a
    regression — before the merge model the same regime returned "1 stretch
    for 2 lines" for a *correct* mix too, so nothing there was graded at all —
    but it is a hole, and it is in `tests/README.md`'s Known gaps.
    """
    label = "narration"
    failures: list[str] = []
    mp4 = out_dir / "demo.mp4"
    if not lines:
        return [f"{label}: the recorder logged no narration lines"]
    # **An uncovered reading is worse than no reading**, the same refusal
    # `check_timeline` makes and for the same reason (issue #245): a watcher
    # that was away for seconds still hands out a `before()`, and grading the
    # audio against it would report a voice 1.26 s out of place on a mix that
    # is exactly where it belongs. Refused loudly, and nothing below is graded
    # on alignment — this is the harness declining to measure, not the
    # recorder failing. `check_capture_clock` is what catches the other half,
    # where *both* samplers stall and agree with each other (issue #247).
    if not clock.covered:
        return failures + [
            f"{label}: this harness's own wall-clock watcher was away for up "
            f"to {clock.max_gap:.2f}s (limit {HOST_CLOCK_MAX_GAP_S:.2f}s, "
            f"{clock.samples} samples), so it cannot say where in the video a "
            f"spoken line belongs. Nothing about the mix's placement is graded "
            f"for this take. This is the harness refusing to measure, not the "
            f"recorder failing (issue #247)"
        ]
    try:
        doc = json.loads((out_dir / "timeline.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{label}: timeline.json could not be read: {exc}"]
    record = doc.get("narration")
    if not isinstance(record, dict) or not isinstance(record.get("lines"), list):
        return [
            f"{label}: timeline.json carries no `narration` record "
            f"({record!r}) on a take that spoke {len(lines)} line(s) — the "
            f"audio is the one artifact a reader cannot check against "
            f"anything else, so where it went has to be written down (#226)"
        ]
    logged = record["lines"]
    if len(logged) != len(lines):
        return [
            f"{label}: timeline.json records {len(logged)} narration line(s) "
            f"and the recorder mixed {len(lines)}"
        ]

    # (1) and (2). `before()` is this file's own correction, hand-written
    # against the documented rule and sampled by this process's watcher.
    expected: list[float] = []
    for n, ((off, _clip), line) in enumerate(zip(lines, logged, strict=True)):
        if abs(float(line.get("t", -1)) - float(off)) > 0.002:
            failures.append(
                f"{label}: timeline.json says line {n} was logged at "
                f"{line.get('t')!r}s, the recorder logged it at {off:.3f}s — "
                f"the record describes a mix of some other take's lines"
            )
        want = max(0.0, float(off) + clock.before(float(off)))
        expected.append(want)
        if abs(float(line.get("at", -1)) - want) > NARRATION_ONSET_TOLERANCE_S:
            failures.append(
                f"{label}: timeline.json puts line {n} at {line.get('at')!r}s "
                f"of demo.mp4; this harness's own wall-clock reading puts the "
                f"{off:.3f}s instant at {want:.3f}s ({clock.describe()}). The "
                f"recorder and an independent sampler disagree about where "
                f"the voice should be (issue #226)."
                # Where the instant has no video, say so rather than reporting
                # a second as though the file had one: `want` is then the last
                # moment before the gap, and the recorder is expected to have
                # clamped a line spoken during a backward step to the same
                # place (issue #256).
                + hole_clause(clock, float(off), want)
            )

    # (3). Nothing below reads the recorder's record — the file is the witness.
    duration = doc.get("duration")
    if not isinstance(duration, (int, float)):
        return failures + [
            f"{label}: timeline.json states duration={duration!r}, so there is "
            f"no length to complement the silences against"
        ]
    spans = loud_spans(mp4, float(duration))
    if spans is None:
        return failures + [
            f"{label}: ffmpeg reported no silence measurement for demo.mp4 at "
            f"all — the measurement failed, which is not the same as a track "
            f"with nothing in it"
        ]
    if len(lines) != len(NARRATION_LINES):
        return failures + [
            f"{label}: the take spoke {len(lines)} line(s) and this file "
            f"seeded {len(NARRATION_LINES)}, so there is no known clip length "
            f"to measure the stretches in the file against"
        ]
    # Where the clips should be audible: the seconds this harness derived
    # above, each carrying the length of the tone **this file** seeded — not
    # probed back off the clips, which would ask the same question of the same
    # files the recorder mixed. Overlaps merged, because a corrected mix on a
    # stepped host really does produce them; see `expected_loud_spans`.
    clips = [seconds for _text, seconds in NARRATION_LINES]
    wanted = expected_loud_spans(expected, clips)
    if len(spans) != len(wanted):
        return failures + [
            f"{label}: demo.mp4 carries {len(spans)} stretch(es) of audio "
            f"{spans} where the {len(lines)} spoken line(s) should make "
            f"{len(wanted)} {wanted}. Either two clips were mixed on top of "
            f"each other or one is missing, and every window assertion in this "
            f"arm can pass on both"
        ]
    for (start, end), (want, want_end, members) in zip(spans, wanted, strict=True):
        # Named after the lines it really covers, not after its position:
        # merging makes those two different, and a failure that names the
        # wrong line sends the reader to the wrong clip.
        whose = "line " + "+".join(str(m) for m in members)
        if abs(start - want) > NARRATION_ONSET_TOLERANCE_S:
            failures.append(
                f"{label}: {whose}'s audio starts at {start:.3f}s of "
                f"demo.mp4, {(start - want) * 1000:+.0f} ms from the "
                f"{want:.3f}s it belongs at, over the "
                f"{NARRATION_ONSET_TOLERANCE_S * 1000:.0f} ms this grades. "
                f"The voice is that far from the caption it was spoken for "
                f"(issue #226)"
            )
        if len(members) == 1:
            # **The duration, wherever a span is one clip.** An end-of-span
            # bar lets two errors cancel — an onset 110 ms early inside the
            # 120 ms bar, against a 1.85 s stretch where 1.6 s was seeded,
            # measured landing 140 ms from the wanted end and passing. That
            # widens the effective length bar from 0.15 s to 0.27 s in the
            # cancelling direction, and the length is expressible here.
            clip = clips[members[0]]
            if abs((end - start) - clip) > NARRATION_SPAN_TOLERANCE_S:
                failures.append(
                    f"{label}: {whose} occupies {end - start:.3f}s of demo.mp4 "
                    f"against a {clip:.3f}s clip — the onset is right and the "
                    f"clip is not what was mixed there"
                )
        elif abs(end - want_end) > NARRATION_SPAN_TOLERANCE_S:
            # A merged span has no single clip length to be. Its end is the
            # last clip's end, and that is the only length claim left; see the
            # Known gaps entry for what merging hides.
            failures.append(
                f"{label}: the merged stretch carrying {whose} ends at "
                f"{end:.3f}s of demo.mp4 against the {want_end:.3f}s its clips "
                f"should reach — something in it is not the clip it should be"
            )
    return failures


def check_narration_audio(out_dir: Path, lines: list, clock: HostClock) -> list[str]:
    """The mp4 carries audio where a line is, and silence where none is."""
    label = "narration"
    failures: list[str] = []
    mp4 = out_dir / "demo.mp4"

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_name,channels,sample_rate,duration",
            "-of",
            "json",
            str(mp4),
        ],
        capture_output=True,
        text=True,
    )
    streams = json.loads(probe.stdout or "{}").get("streams", [])
    if len(streams) != 1:
        return [
            f"{label}: demo.mp4 carries {len(streams)} audio streams, expected "
            f"exactly 1 — a take with narration on and no track is a silent "
            f"demo that every other artifact reports as healthy"
        ]
    stream = streams[0]
    for field, wanted in (
        ("codec_name", NARRATION_CODEC),
        ("channels", NARRATION_CHANNELS),
        ("sample_rate", str(NARRATION_SAMPLE_RATE)),
    ):
        if str(stream.get(field)) != str(wanted):
            failures.append(
                f"{label}: demo.mp4's audio {field} is {stream.get(field)!r}, "
                f"expected {wanted!r} — stitch() concatenates segments with "
                f"-c copy and cannot join streams that disagree"
            )

    # Where the first line is in the *video*. Measured from the recorder's own
    # `_lines` — that list is what `_convert` turns into `adelay` values —
    # plus this harness's own wall-clock reading, because the mix is on the
    # video's clock and the log is not (issue #226). `before()` is zero on a
    # host that did not step, so on a healthy box this is the offset it always
    # was; on one that did, aiming this window at the raw offset would measure
    # a stretch the clip had already left and report silence.
    if not lines:
        return failures + [f"{label}: the recorder logged no narration lines"]
    # Same refusal as `check_narration_placement`, for the same reason: an
    # uncovered watcher's `before()` would aim this window at a second nobody
    # measured, and report silence on a mix that is exactly where it belongs.
    if not clock.covered:
        return failures + [
            f"{label}: this harness's own wall-clock watcher was away for up "
            f"to {clock.max_gap:.2f}s ({clock.samples} samples), so the window "
            f"this measures the first line in cannot be aimed. The stream "
            f"shape above is still graded; the mix is not (issue #247)"
        ]
    first_offset = max(0.0, float(lines[0][0]) + clock.before(float(lines[0][0])))

    loud = mean_dbfs(mp4, first_offset + 0.1, NARRATION_WINDOW_S)
    if loud is None:
        failures.append(
            f"{label}: ffmpeg reported no volume for the window at "
            f"{first_offset + 0.1:.2f}s — the measurement itself failed, which "
            f"is not the same as a silent window"
        )
    elif loud < NARRATION_LOUD_DBFS:
        failures.append(
            f"{label}: the {NARRATION_WINDOW_S}s window inside the first "
            f"narration line measures {loud:.1f} dBFS, under the "
            f"{NARRATION_LOUD_DBFS} dBFS this grades — the track is there and "
            f"silent, which every other assertion in this suite reads as a "
            f"healthy take"
        )

    # The control. Before the first line there is nothing to hear, and a mix
    # that smeared one clip across the whole track — or a track of noise —
    # passes the bar above everywhere.
    if first_offset < NARRATION_WINDOW_S + 0.1:
        failures.append(
            f"{label}: the first line starts at {first_offset:.2f}s, too early "
            f"to measure a silent window before it — this take's storyboard is "
            f"supposed to leave room, so the control is missing"
        )
    else:
        quiet = mean_dbfs(mp4, 0.0, NARRATION_WINDOW_S)
        if quiet is None:
            failures.append(
                f"{label}: ffmpeg reported no volume for the opening window"
            )
        elif quiet > NARRATION_QUIET_DBFS:
            failures.append(
                f"{label}: the {NARRATION_WINDOW_S}s window *before* the first "
                f"line measures {quiet:.1f} dBFS, over the "
                f"{NARRATION_QUIET_DBFS} dBFS this grades — audio is playing "
                f"where no line was spoken, so 'loud inside a line' says "
                f"nothing about the mix"
            )
    return failures


def check_crash_take(
    label: str,
    out_dir: Path,
    started: float,
    raised: BaseException | None,
    want_exc: str,
    want_verb: str | None,
    want_screen: str,
) -> list[str]:
    """Everything a take that did not finish has to have left behind.

    `want_verb` is the verb whose beat must carry `error`, or **None** for the
    arm that fails between beats — where the requirement is the opposite one:
    no beat may claim it.
    """
    from demo_recording.content import media_duration
    from demo_recording.failure import FAILURE_MARKER

    failures: list[str] = []
    if raised is None:
        return [
            f"{label}: the storyboard was written to fail and the take "
            f"returned normally, so none of the assertions below are about "
            f"anything"
        ]
    if type(raised).__name__ != want_exc:
        failures.append(
            f"{label}: expected the storyboard's {want_exc} to propagate, got "
            f"{type(raised).__name__}: {str(raised)[:200]!r}. A recorder that "
            f"replaces the exception costs the author the message that says "
            f"what to fix."
        )

    # -- the recording it already had ---------------------------------------
    #
    # Issue #32's half of #11: the webm was in hand when the storyboard gave
    # up, and `__exit__` used to discard it along with `.video/`.
    mp4 = out_dir / "demo.mp4"
    duration: float | None = None
    if not mp4.is_file():
        failures.append(
            f"{label}: a take that crashed wrote no demo.mp4. The browser had "
            f"a webm when the storyboard gave up; converting it costs one "
            f"ffmpeg call, and in CI — where there is no screen — a crash with "
            f"no recording means blind retries."
        )
    else:
        if mp4.stat().st_size < MIN_MP4_BYTES:
            failures.append(
                f"{label}: demo.mp4 is {mp4.stat().st_size} bytes, under the "
                f"{MIN_MP4_BYTES} floor"
            )
        if mp4.stat().st_mtime < started:
            failures.append(
                f"{label}: demo.mp4 predates this run — it is a leftover, not "
                f"this take's partial recording"
            )
        try:
            duration = media_duration(mp4)
        except Exception as exc:  # noqa: BLE001 - an unprobeable mp4 is a failure
            failures.append(f"{label}: ffprobe could not read demo.mp4: {exc}")

    # -- the beat log, and the beat that raised (issue #24) ------------------
    json_path = out_dir / "timeline.json"
    doc: dict = {}
    if not json_path.is_file():
        failures.append(
            f"{label}: a take that crashed wrote no timeline.json. The beats "
            f"were in memory; the log is what says which one it died on."
        )
    else:
        doc = json.loads(json_path.read_text())
        erroring = _erroring_beats(doc)
        beats = doc.get("beats") or []
        if want_verb is None:
            if erroring:
                failures.append(
                    f"{label}: this arm fails in storyboard code between two "
                    f"verbs, and "
                    f"{[(b.get('index'), b.get('verb')) for b in erroring]!r} "
                    f"claims to have raised. Blaming a beat that returned is "
                    f"the confidently-wrong attribution the issue log's "
                    f"`beat: null` rule already refuses to make."
                )
        elif len(erroring) != 1:
            failures.append(
                f"{label}: {len(erroring)} of {len(beats)} beats carry an "
                f"`error` key, expected exactly 1 — the "
                f"{want_verb}() that raised. "
                f"{[(b.get('index'), b.get('verb')) for b in erroring]!r}. A "
                f"beat that returned must be distinguishable from one that "
                f"did not, in both directions."
            )
        else:
            beat = erroring[0]
            if beat.get("verb") != want_verb:
                failures.append(
                    f"{label}: the beat carrying `error` is "
                    f"{beat.get('verb')!r}, not the {want_verb!r} that raised"
                )
            if beat is not beats[-1]:
                failures.append(
                    f"{label}: the erroring beat is index {beat.get('index')} "
                    f"but the log has {len(beats)} beats — the take carried on "
                    f"after the verb that killed it"
                )
            error = beat.get("error")
            if not isinstance(error, dict):
                failures.append(f"{label}: beat `error` is {error!r}, not a dict")
            else:
                if error.get("type") != want_exc:
                    failures.append(
                        f"{label}: the beat's error.type is "
                        f"{error.get('type')!r}, not {want_exc!r} — reading "
                        f"timeline.json alone does not say what happened"
                    )
                if not str(error.get("message") or "").strip():
                    failures.append(
                        f"{label}: the beat's error.message is empty, so the "
                        f"log says a verb raised and nothing about what"
                    )
        # `duration` is this take's, measured off the file it just wrote.
        logged = doc.get("duration")
        if duration is None:
            pass  # already reported above
        elif not isinstance(logged, (int, float)) or isinstance(logged, bool):
            failures.append(
                f"{label}: timeline.json duration is {logged!r}, but this take "
                f"encoded a {duration:.2f}s demo.mp4"
            )
        elif abs(float(logged) - duration) > 0.25:
            failures.append(
                f"{label}: timeline.json says duration {float(logged):.2f}s "
                f"and demo.mp4 measures {duration:.2f}s — the log and the "
                f"recording are from different takes"
            )
        record = doc.get("failure")
        if not isinstance(record, dict):
            failures.append(
                f"{label}: timeline.json has no `failure` record ({record!r}), "
                f"so a reader of the beat table cannot tell this take from one "
                f"that finished"
            )
        else:
            if record.get("type") != want_exc:
                failures.append(
                    f"{label}: timeline.json's failure.type is "
                    f"{record.get('type')!r}, not {want_exc!r}"
                )
            if record.get("verb") != want_verb:
                failures.append(
                    f"{label}: timeline.json's failure.verb is "
                    f"{record.get('verb')!r}, expected {want_verb!r}"
                )
        # Every beat's `evidence` pointer has to resolve. Writing the timeline
        # on this path without writing the evidence beside it would point every
        # beat at a file that is not there.
        missing = [
            b.get("evidence")
            for b in doc.get("beats") or []
            if b.get("evidence") and not (out_dir / str(b["evidence"])).is_file()
        ]
        if missing:
            failures.append(
                f"{label}: {len(missing)} beat(s) name evidence files that do "
                f"not exist ({missing[:3]!r}) — the timeline points at nothing"
            )

    # -- failure/ (issue #11) -----------------------------------------------
    dump, why = _crash_dump(out_dir)
    if dump is None:
        failures.append(
            f"{label}: {why}. Killing a storyboard partway through has to "
            f"leave a folder from which the failing beat can be identified "
            f"without re-running."
        )
    else:
        if dump.get("failure", {}).get("type") != want_exc:
            failures.append(
                f"{label}: failure.json names "
                f"{dump.get('failure', {}).get('type')!r}, not {want_exc!r}"
            )
        # The dump and the beat log have to name the *same* beat. Two records
        # of one crash that disagree is worse than one.
        dumped = (dump.get("failure") or {}).get("beat")
        logged_beat = (doc.get("failure") or {}).get("beat") if doc else None
        if dumped != logged_beat:
            failures.append(
                f"{label}: failure/failure.json blames beat {dumped!r} and "
                f"timeline.json blames beat {logged_beat!r}"
            )
        if want_verb is None:
            if dumped is not None:
                failures.append(
                    f"{label}: the dump blames beat {dumped!r} for a failure "
                    f"that happened between beats"
                )
            if dump.get("beat") is not None:
                failures.append(
                    f"{label}: the dump carries a failing beat record "
                    f"({dump['beat'].get('verb')!r}) for a failure no beat owns"
                )
        else:
            if not isinstance(dump.get("beat"), dict):
                failures.append(
                    f"{label}: the dump carries no failing-beat record, so the "
                    f"beat has to be looked up in timeline.json by hand"
                )
            elif dump["beat"].get("verb") != want_verb:
                failures.append(
                    f"{label}: the dump's beat is {dump['beat'].get('verb')!r}, "
                    f"not the {want_verb!r} that raised"
                )
        if dump.get("media_written_by_this_take") is not True:
            failures.append(
                f"{label}: the dump says media_written_by_this_take="
                f"{dump.get('media_written_by_this_take')!r} while demo.mp4 "
                f"beside it is this take's — the two artifacts disagree"
            )
        if not isinstance(dump.get("issues"), list):
            failures.append(
                f"{label}: the dump carries no console log ({dump.get('issues')!r})"
            )

    md = out_dir / "failure" / "failure.md"
    if not md.is_file():
        failures.append(f"{label}: {md} was never written")
    elif want_verb is not None and want_verb not in md.read_text():
        failures.append(
            f"{label}: failure.md never names the {want_verb!r} that raised"
        )

    # The page text: read once, before the redaction verifier vouched for the
    # page, and written only after it passed. Graded on *content* — a file that
    # exists and says nothing about the app would pass a file-exists check.
    screen = out_dir / "failure" / "screen.txt"
    if not screen.is_file():
        failures.append(
            f"{label}: {screen} was never written — a crash dump with no "
            f"account of what was on screen is a timestamp"
        )
    elif want_screen not in screen.read_text():
        failures.append(
            f"{label}: failure/screen.txt does not contain {want_screen!r}, "
            f"which the app had rendered when the take died. It is not an "
            f"account of this page."
        )

    # The last frame, extracted from the recording rather than screenshotted
    # off the page — so it inherits the redaction guarantee whole. Graded for
    # *picture*, not existence: `_extract` writes a file for a blank video too.
    frame = out_dir / "failure" / "last-frame.png"
    if not frame.is_file():
        failures.append(f"{label}: {frame} was never written")
    else:
        if frame.stat().st_size < MIN_PNG_BYTES:
            failures.append(
                f"{label}: failure/last-frame.png is {frame.stat().st_size} "
                f"bytes, under the {MIN_PNG_BYTES} floor"
            )
        frames = gray_frames(frame)
        score = contrast(frames[0]) if frames else 0.0
        if score < MIN_CONTENT_STDDEV["web"]:
            failures.append(
                f"{label}: failure/last-frame.png scores {score:.1f} luma "
                f"stddev, under the {MIN_CONTENT_STDDEV['web']} floor — it is "
                f"a blank picture, which also means demo.mp4 is blank where it "
                f"stopped"
            )

    # -- the marker (issue #46) ---------------------------------------------
    marker = out_dir / FAILURE_MARKER
    if not marker.is_file():
        failures.append(
            f"{label}: no {FAILURE_MARKER} — somebody who only opens the "
            f"folder sees a demo.mp4 and a timeline.json and nothing that says "
            f"the take did not finish"
        )
    else:
        text = marker.read_text()
        if want_exc not in text:
            failures.append(
                f"{label}: {FAILURE_MARKER} does not name the {want_exc} that "
                f"ended the take"
            )
        if "this take's recording" not in text:
            failures.append(
                f"{label}: {FAILURE_MARKER} does not say whether demo.mp4 is "
                f"this take's, which is the one question it exists to answer"
            )

    if not failures:
        print(
            f"smoke: {label} crashed and kept everything it had — demo.mp4 "
            f"({duration:.1f}s), timeline.json, failure/ (dump, page text, "
            f"last frame), {FAILURE_MARKER}"
            if duration is not None
            else f"smoke: {label} crashed and kept its artifacts"
        )
    return failures


def check_lock_refusal(out_root: Path) -> list[str]:
    """What a run that never started leaves behind, against one that did.

    Issue #105. `main()` used to build its output directory and announce it
    *before* taking the machine lock, so a run the lock refused created an
    empty `/tmp/demo-video-smoke-*`, never removed it, and printed
    `recordings left in` naming it — directly under `smoke: FAILED`. That is
    the artifact-lying shape this whole suite exists to catch, produced by the
    suite: a reader goes looking for the failure's evidence, finds an empty
    directory, and reads it as "the recorder wrote nothing" rather than "this
    run never happened".

    **Graded as a pair, and it has to be a pair.** The refusal on its own would
    be satisfied by a `main()` that never printed the line at all, and that
    line is right and wanted on every failure of a run that *did* start — a
    failed take is debugged out of its directory. So the second child gets past
    the lock and fails, and must name its directory. What the two pin between
    them is the rule "the line follows whether this run started", which is the
    only rule that is true on both paths.

    This process holds the machine lock — every arm runs inside
    `only_one_suite()` — so the first child is refused by construction rather
    than by a fixture that has to be believed. The second is handed
    `--allow-concurrent` for the same reason: this arm records nothing, which
    is the one circumstance the flag documents.

    `--coverage-only` on both, deliberately: if the lock were somehow *not*
    held, the first child would run an 8 s arm rather than the whole suite.
    """
    # Before the split this module *was* the executable, so `__file__` named
    # it; it now names this file (#401), and the child must run the
    # executable — which sits beside the package, one directory up.
    smoke = Path(__file__).resolve().parent.parent / "smoke"
    failures: list[str] = []

    def child(*extra: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                [str(smoke), "--coverage-only", *extra],
                capture_output=True,
                text=True,
                timeout=LOCK_CHILD_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failures.append(
                f"lock: a child smoke run did not finish in "
                f"{LOCK_CHILD_TIMEOUT_S:.0f}s ({' '.join(extra) or 'no flags'})"
            )
            return None

    # -- the refused run ------------------------------------------------------
    #
    # Written from the reader's side: the reproduction in #105 is
    # `ls -d /tmp/demo-video-smoke-*`, and the claim is that a refused run adds
    # nothing to the temp directory. Matched more broadly than the prefix
    # `open_output()` uses, so a renamed prefix surfaces as a failure here
    # rather than as a check quietly looking for the wrong name.
    tmp = Path(tempfile.gettempdir())

    def litter() -> set[str]:
        return {
            p.name for p in tmp.iterdir() if "smoke" in p.name or "demo-video" in p.name
        }

    before = litter()
    refused = child()
    left = sorted(litter() - before)
    if refused is not None:
        output = refused.stdout + refused.stderr
        if "refusing to run a second smoke suite" not in output:
            failures.append(
                f"lock: a second suite started while this one holds "
                f"{SMOKE_LOCK} — the premise of everything below is that the "
                f"child is refused, and it was not. Exit {refused.returncode}, "
                f"tail: {output[-400:]!r}"
            )
        else:
            if left:
                failures.append(
                    f"lock: a run the lock refused created {left!r} in {tmp} "
                    f"and left it there. The run never recorded anything, so "
                    f"each refusal adds an empty directory nothing will ever "
                    f"reap — 85 of them, 80 MB, is what issue #105 measured"
                )
            said = [ln for ln in output.splitlines() if "recordings left in" in ln]
            if said:
                failures.append(
                    f"lock: a run the lock refused printed `recordings left "
                    f"in` under `smoke: FAILED`, naming a directory it never "
                    f"wrote to. Nothing was recorded, so there is nothing to "
                    f"read there and the line sends its reader looking: "
                    f"{said[0].strip()!r}"
                )

    # -- the run that started, and failed -------------------------------------
    #
    # The control. `fresh_take_dir` refuses a take directory this harness did
    # not create, which fails the child in about a second, past the lock and
    # with an output directory of its own — so the line the refused run must
    # not print is one this run must.
    started_root = (out_root / "lock-started").resolve()
    (started_root / "coverage").mkdir(parents=True, exist_ok=True)
    (started_root / "coverage" / "somebody-elses-file.txt").write_text(
        "Planted by check_lock_refusal so the child fails after it starts.\n"
    )
    started = child("--allow-concurrent", "--out-dir", str(started_root))
    if started is not None:
        output = started.stdout + started.stderr
        if "refusing to touch" not in output:
            failures.append(
                f"lock: the control run was supposed to get past the lock and "
                f"fail on a take directory it does not own, and did not — so "
                f"nothing here grades the failure path the `recordings left "
                f"in` line is *for*. Exit {started.returncode}, tail: "
                f"{output[-400:]!r}"
            )
        elif f"recordings left in {started_root}" not in output:
            failures.append(
                f"lock: a run that started and then failed did not say "
                f"`recordings left in {started_root}`. That line is how "
                f"somebody reading `smoke: FAILED` finds the evidence, and "
                f"suppressing it everywhere is not the fix to issue #105 — the "
                f"refusal path is. tail: {output[-400:]!r}"
            )

    if not failures:
        print(
            "smoke: lock — a refused run left nothing in "
            f"{tmp} and claimed no recordings; a run that started and failed "
            "named its directory"
        )
    return failures
