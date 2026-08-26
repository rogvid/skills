"""The arms `run_phases` selects between, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from _pixels import Rect, contrast, frame_difference, gray_frames

from .checks import (  # noqa: E402
    _check_video,
    check_beat_frames,
    check_camera_push,
    check_capture_clock,
    check_content_pair,
    check_content_toured,
    check_coverage,
    check_coverage_merge,
    check_coverage_refusals,
    check_crash_take,
    check_entropy_stills,
    check_evidence,
    check_evidence_omissions,
    check_form_pacing,
    check_healthy,
    check_issues,
    check_narration_audio,
    check_narration_pacing,
    check_narration_placement,
    check_opening_card,
    check_opening_gap,
    check_overlay_cleared,
    check_overlay_pair,
    check_reported_opening_card,
    check_spotlight_transitions,
    check_stills_only,
    check_strict_failure,
    check_take,
    check_timeline,
    check_wrapper_band,
    check_wrapper_caption_survives,
    check_wrapper_card,
    check_wrapper_clipped,
    check_wrapper_evidence,
    check_wrapper_opening,
    check_wrapper_refusal,
)
from .constants import (  # noqa: E402
    BETWEEN_BEATS_JS,
    CONTENT_TAKES,
    CONTENT_TOURED,
    CRASH_CAPTION,
    CRASH_SCREEN_TERMINAL,
    CRASH_SCREEN_WEB,
    CRASH_SELECTOR,
    ENTROPY_SHOTS,
    EVIDENCE_ATTR_RENDERED,
    EVIDENCE_ATTR_TARGET,
    EVIDENCE_BLOAT_ID,
    EVIDENCE_BLOAT_ITEMS,
    EVIDENCE_BLOAT_JS,
    EVIDENCE_DIR_NAME,
    EVIDENCE_LIMITS_EXPECTED,
    EVIDENCE_MARKER,
    EVIDENCE_MIN_ARIA_CHARS,
    EVIDENCE_RENDERED_TEXT,
    EVIDENCE_SCHEMA_EXPECTED,
    EVIDENCE_SEGMENT,
    EVIDENCE_SOURCE_ID,
    EVIDENCE_SOURCE_JS,
    EVIDENCE_SOURCE_RENDERED,
    EVIDENCE_SOURCE_SCRIPT,
    EVIDENCE_SOURCE_SRCDOC,
    EVIDENCE_STALE_MARK,
    EVIDENCE_TAKE_FACTS,
    EVIDENCE_TRUNCATED_MAX,
    LATE_BOOM_CAPTION,
    LATE_BOOM_HOLD_S,
    LATE_BOOM_JS,
    MAX_TAKE_VIDEO_DELTA,
    MIN_CONTENT_STDDEV,
    MIN_LIVE_STILL_DELTA,
    MIN_LIVE_VIDEO_DELTA,
    NARRATION_ONSET_TOLERANCE_S,
    OPENING_DURATION_S,
    OVERLAY_TAKES,
    REPO_ROOT,
    SEGMENT_BEAT_SEGMENTS,
    SEGMENT_BEATS,
    SEGMENT_CAPTIONS,
    SEGMENT_DURATION_S,
    SEGMENT_INTERLUDES,
    SEGMENT_NAMES,
    SEGMENT_SHOTS,
    SPOTLIGHT_DURATION_S,
    STALE_MARK,
    STILLS_CAPTION,
    STILLS_CLAUSE,
    STRICT_CAPTION,
    TERMINAL_BEATS,
    TERMINAL_CAPTIONS,
    TERMINAL_DURATION_S,
    TERMINAL_EVIDENCE,
    TERMINAL_FAILING_COMMAND,
    TERMINAL_PROBLEM_EXIT_CODES,
    TERMINAL_PROBLEM_ISSUES,
    TERMINAL_RACE_COMMAND,
    TERMINAL_RACE_DELAY_S,
    TERMINAL_RACE_EXIT,
    TERMINAL_RACE_SHELL,
    TERMINAL_SHOTS,
    TERMINAL_UNWAITED,
    WEB_BEATS,
    WEB_CAPTIONS,
    WEB_DURATION_S,
    WEB_EVIDENCE,
    WEB_EVIDENCE_SCOPE,
    WEB_PROBLEM_ISSUES,
    WEB_SHOTS,
    WRAPPER_UNREACHED,
)
from .records import (  # noqa: E402
    _record_content_take,
    record_content,
    record_content_toured,
    record_coverage,
    record_entropy,
    record_narration,
    record_overlay,
    record_segments,
    record_spotlight,
    record_terminal,
    record_terminal_opening,
    record_web,
    record_wrapper,
    refusing_fixture_server,
)
from .support import (  # noqa: E402
    EntropyTake,
    HostClock,
    _plant_mp4,
    _StoryboardFailed,
    digest,
    evidence_docs,
    fixture_server,
    fresh_take_dir,
    joined_clock,
    keep_top,
    last_frame,
    refused_url,
    stitch_segments,
    watch_wall_clock,
    web_problem_path,
)


def run_web(out_root: Path) -> list[str]:
    out_dir = fresh_take_dir(out_root, "web")
    started = time.time()
    with fixture_server() as base_url:
        try:
            # The host's wall clock, watched for exactly as long as the take is
            # recording. demo.mp4 is on that clock and the beat log is not, so
            # every timing reading below is corrected by this (issue #215).
            with watch_wall_clock() as clock:
                problems, geom, size = record_web(out_dir, base_url, clock)
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"web: Recorder raised {type(exc).__name__}: {exc}"]
    # One rect for video and stills alike: the wrapper page is the recording
    # (#358/#361), so a still is the framed frame and the app sits at the
    # same place in both — the "stills are full-bleed, video is windowed"
    # mismatch died with the composite.
    app_rect: Rect = (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
    return (
        problems
        + check_take(
            "web",
            out_dir,
            WEB_SHOTS,
            WEB_DURATION_S,
            started,
            app_rect,
            app_rect,
            size,
        )
        + check_capture_clock("web", out_dir, clock)
        + check_timeline(
            "web", out_dir, started, WEB_BEATS, WEB_CAPTIONS, size, clock=clock
        )
        + check_beat_frames(
            "web", out_dir, started, WEB_BEATS, WEB_CAPTIONS, size, clock=clock
        )
        + check_evidence("web", out_dir, WEB_EVIDENCE, WEB_EVIDENCE_SCOPE)
        # The form verbs' pacing (issue #130), read off the same beat log the
        # two checks above read for their contents.
        + check_form_pacing("web", out_dir)
        # What the take opens on (#119 → #360): frame 0 must be the opening
        # hold and the app must show later — the same claims the wrapper arm
        # grades, on the long take whose beat/frame alignment is already
        # graded above. The deleted composite's ffmpeg hold had its own
        # check here; the in-page hold is graded by the same pixel reading
        # on every path now.
        + check_wrapper_opening(out_dir, {"geom": geom})
        # No browser and no recording — two synthesised videos, run here
        # because this is the phase whose acceptance criterion it belongs to.
        + check_opening_gap(out_root)
        + check_healthy("web", out_dir)
    )


def run_spotlight(out_root: Path) -> list[str]:
    """The spotlight's enter and exit, in a take that records real motion."""
    out_dir = fresh_take_dir(out_root, "spotlight")
    with fixture_server() as base_url:
        try:
            # Watched for the same reason the web take is (#215): the two
            # transition windows below are placed at beat timestamps, and a
            # backward step between the enter and the exit deletes its own
            # width of video out from under the later window — measured on
            # this arm, a -1.07 s step at 0.789 s of a 6 s take left the exit
            # window reading a stretch the fade had already left.
            with watch_wall_clock() as clock:
                problems, info = record_spotlight(out_dir, base_url, clock)
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"spotlight: Recorder raised {type(exc).__name__}: {exc}"]
    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        return problems + [f"spotlight: {mp4} was never written"]
    return (
        problems
        + _check_video("spotlight", mp4, SPOTLIGHT_DURATION_S, keep_top(info["app"]))
        + check_spotlight_transitions(out_dir, info, clock)
        # The same interval, one layer out: what the spotlight put on the page
        # is graded above, and what the camera did to the frame around it here.
        + check_camera_push(out_dir, info, clock)
        + check_healthy("spotlight", out_dir)
    )


def run_terminal_opening(out_root: Path) -> list[str]:
    """A terminal segment that opens on a card rather than on a bare prompt."""
    out_dir = fresh_take_dir(out_root, "terminal-opening")
    try:
        problems, info = record_terminal_opening(out_dir)
    except Exception as exc:  # noqa: BLE001 - a raising take is a failure
        return [
            f"terminal-opening: TerminalRecorder raised {type(exc).__name__}: {exc}"
        ]
    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        return problems + [f"terminal-opening: {mp4} was never written"]
    return (
        problems
        + _check_video(
            "terminal-opening", mp4, OPENING_DURATION_S, keep_top(info["app"])
        )
        + check_opening_card(out_dir, info)
        # The same frame, from the other side: what the *take* says it opened
        # on, which is the only account of it a demo directory ever ships
        # (issue #235).
        + check_reported_opening_card(out_dir, info)
        + check_healthy("terminal-opening", out_dir)
    )


def run_content(out_root: Path) -> list[str]:
    """Three takes: card taken down, card left up, and a narrated hold.

    The first two are issue #97's acceptance criterion — take 1 of the
    reference demo, where a title card covered 24.3 s of a 60.2 s recording and
    every artifact reported a healthy take.

    The third is the false positive that criterion does not cover, and it is
    the reason this phase is not just a pair. A healthy demo touring a rendered
    screen holds the measured region for longer than the covered take does; a
    check that warned on duration alone would call it broken, in
    `timeline.json`, naming a cause that never happened.
    """
    problems: list[str] = []
    takes: dict[str, dict] = {}
    previous = Path.cwd()
    # `ls -1` is one of the beats; pin the shell's directory so the take does
    # not depend on where the suite was started.
    os.chdir(REPO_ROOT)
    try:
        for name, cleared in zip(CONTENT_TAKES, (True, False), strict=True):
            found, take = _record_content_take(
                out_root,
                name,
                lambda out_dir, cleared=cleared: record_content(
                    out_dir, cleared=cleared
                ),
            )
            problems += found
            if take:
                takes[name] = take
        toured_problems, toured = _record_content_take(
            out_root, CONTENT_TOURED, record_content_toured
        )
        problems += toured_problems
    finally:
        os.chdir(previous)
    if problems:
        return problems
    # `check_verb_classification()` used to sit in this chain; it moved to
    # tests/unit (#392) — a static scrape graded microseconds faster on every
    # push than post-merge behind these arms.
    return check_content_pair(takes) + check_content_toured(
        toured["out_dir"], toured["stderr"], toured["info"]["app"]
    )


def run_overlay(out_root: Path) -> list[str]:
    """Two takes: a `light` scrim taken down with the documented call, and one
    left up (issues #162 and #163)."""
    problems: list[str] = []
    takes: dict[str, dict] = {}
    with fixture_server() as base_url:
        for name, cleared in zip(OVERLAY_TAKES, (True, False), strict=True):
            found, take = _record_content_take(
                out_root,
                name,
                lambda out_dir, cleared=cleared: record_overlay(
                    out_dir, base_url, cleared=cleared
                ),
            )
            problems += found
            if take:
                takes[name] = take
    if problems:
        return problems
    return check_overlay_pair(takes)


def run_coverage(out_root: Path) -> list[str]:
    """Acceptance-criterion coverage (issue #12): one take, two unit arms."""
    out_dir = fresh_take_dir(out_root, "coverage")
    with fixture_server() as base_url:
        try:
            problems, geom = record_coverage(out_dir, base_url)
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"coverage: Recorder raised {type(exc).__name__}: {exc}"]
    if not (out_dir / "timeline.json").is_file():
        return problems + ["coverage: the take wrote no timeline.json"]
    return (
        problems
        + check_coverage(out_dir)
        # The card's colour, single-encoder (#360/#361): the same reading the
        # wrapper arm makes, on the take that raises a criterion card anyway.
        + check_wrapper_card(out_dir, {"geom": geom})
        + check_coverage_refusals(out_root)
        + check_coverage_merge()
    )


def run_web_problems(out_root: Path) -> list[str]:
    """A short take of a page broken in four ways, under the default.

    Deliberately not the graded take: the reference demo should be a recording
    of a working app, and a fixture hook gets a take of its own. Everything
    interesting here is in timeline.json, so nothing about the video is graded.
    """
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "web-problems")
    dead = refused_url()
    with fixture_server() as base_url:
        try:
            with Recorder(out_dir, base_url=base_url, speech=False) as rec:
                rec.goto(web_problem_path(dead))
                rec.wait_for("#kpi-rev")

                # No beat is open here. Whatever this logs must come back with
                # `beat: null` rather than the closed `wait_for` above it.
                # In the app document: the problems have to be the app's, and
                # page-level listeners hear an iframe's console errors and
                # failed requests exactly as they heard the page's own.
                rec.app.evaluate(BETWEEN_BEATS_JS)

                rec.caption(LATE_BOOM_CAPTION)
                # Armed *before* the hold, fired one second into it. Nothing
                # else in the take reaches Playwright during that second.
                rec.app.evaluate(LATE_BOOM_JS)
                rec.pause(LATE_BOOM_HOLD_S)
                rec.caption("The caption after the boom.")
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"web-problems: Recorder raised {type(exc).__name__}: {exc}"]
    return check_issues("web-problems", out_dir, WEB_PROBLEM_ISSUES)


def run_terminal_problems(out_root: Path) -> list[str]:
    """A short take of commands that fail, under the default."""
    if os.name != "posix":
        return []
    from demo_recording import TerminalRecorder

    out_dir = fresh_take_dir(out_root, "terminal-problems")
    try:
        with TerminalRecorder(out_dir, speech=False) as rec:
            rec.caption("Exit codes are recorded.")
            rec.run("echo ok")
            rec.wait_for_prompt(timeout_s=15)
            rec.run(TERMINAL_FAILING_COMMAND)
            rec.wait_for_prompt(timeout_s=15)
            # Two commands, one wait. The shell buffers the second and runs it
            # after the first, so both statuses arrive — in order, and to
            # different beats. This pair is the regression, not decoration.
            rec.run(TERMINAL_UNWAITED[0])
            rec.run(TERMINAL_UNWAITED[1])
            rec.wait_for_prompt(timeout_s=20)
    except Exception as exc:  # noqa: BLE001 - a raising take is a failure
        return [
            f"terminal-problems: TerminalRecorder raised {type(exc).__name__}: {exc}"
        ]
    return check_issues(
        "terminal-problems",
        out_dir,
        TERMINAL_PROBLEM_ISSUES,
        exit_codes=TERMINAL_PROBLEM_EXIT_CODES,
    )


def run_terminal_race(out_root: Path) -> list[str]:
    """A shell too slow to have prompted before run() types.

    Its own take because the condition has to be manufactured: on a normal box
    the startup prompt always beats the first command, so every other take
    here passes whether or not the recorder handles this. Removing the guard
    and running the rest of the suite is a pass — measured.
    """
    if os.name != "posix":
        return []
    from demo_recording import TerminalRecorder

    label = "terminal-race"
    out_dir = fresh_take_dir(out_root, label)
    shell = out_dir / "slow-shell"
    shell.write_text(
        TERMINAL_RACE_SHELL.replace("__DELAY__", str(TERMINAL_RACE_DELAY_S))
    )
    shell.chmod(0o755)
    try:
        with TerminalRecorder(
            out_dir, speech=False, shell=str(shell), type_delay_ms=0
        ) as rec:
            rec.run(TERMINAL_RACE_COMMAND)
            rec.wait_for_prompt(timeout_s=25)
    except Exception as exc:  # noqa: BLE001 - a raising take is a failure
        return [f"{label}: TerminalRecorder raised {type(exc).__name__}: {exc}"]

    doc = json.loads((out_dir / "timeline.json").read_text())
    logged = {
        str(b.get("selector")): b.get("exit_code")
        for b in doc.get("beats", [])
        if b.get("verb") == "run"
    }
    if logged != {TERMINAL_RACE_COMMAND: TERMINAL_RACE_EXIT}:
        return [
            f"{label}: a shell that took {TERMINAL_RACE_DELAY_S}s to start made "
            f"run() log {logged!r}, not "
            f"{{{TERMINAL_RACE_COMMAND!r}: {TERMINAL_RACE_EXIT}}}. The startup "
            f"prompt's own status was taken for the command's — a wrong exit "
            f"code, which passes strict, rather than a missing one."
        ]
    print(
        f"smoke: {label} exit status survives a shell that starts "
        f"{TERMINAL_RACE_DELAY_S}s late (logged {TERMINAL_RACE_EXIT})"
    )
    return []


def run_strict_web(out_root: Path) -> list[str]:
    """strict=True over the page that throws: the take must not pass."""
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "web-strict")
    dead = refused_url()
    raised: BaseException | None = None
    with fixture_server() as base_url:
        try:
            with Recorder(out_dir, base_url=base_url, speech=False, strict=True) as rec:
                rec.goto(web_problem_path(dead))
                rec.wait_for("#kpi-rev")
                rec.caption(STRICT_CAPTION)
        except Exception as exc:  # noqa: BLE001 - the raise is the assertion
            raised = exc
    return check_strict_failure(
        "web-strict", out_dir, raised, ["console_error", "page_error"]
    )


def run_strict_terminal(out_root: Path) -> list[str]:
    """strict=True over a command that exits 3: the take must not pass."""
    if os.name != "posix":
        return []
    from demo_recording import TerminalRecorder

    out_dir = fresh_take_dir(out_root, "terminal-strict")
    raised: BaseException | None = None
    try:
        with TerminalRecorder(out_dir, speech=False, strict=True) as rec:
            rec.caption(STRICT_CAPTION)
            rec.run(TERMINAL_FAILING_COMMAND)
            rec.wait_for_prompt(timeout_s=15)
    except Exception as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    return check_strict_failure("terminal-strict", out_dir, raised, ["nonzero_exit"])


def run_stills_only(out_root: Path) -> list[str]:
    """A stills-only run against the fixture: no video, and no time spent."""
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "stills-only")
    started = time.monotonic()
    with fixture_server() as base_url:
        try:
            with Recorder(
                out_dir,
                base_url=base_url,
                speech=False,
                strict=True,
                stills_only=True,
                criteria={"AC-1": STILLS_CLAUSE},
            ) as rec:
                rec.goto("/")
                rec.wait_for("#kpi-rev")
                rec.criterion("AC-1", hold=4.0)
                rec.interlude("")
                rec.caption(STILLS_CAPTION, ac="AC-1")
                rec.shot("01-dashboard", ac="AC-1")
                rec.pause(4.0)
                rec.interlude("A card, held for three seconds.", hold=3.0)
                rec.shot("02-card")
                rec.interlude("")
        except Exception as exc:  # noqa: BLE001 - a raising take is the failure
            return [f"stills-only: recording raised {type(exc).__name__}: {exc}"]
    return check_stills_only(out_dir, time.monotonic() - started)


def run_wrapper(out_root: Path) -> list[str]:
    """The wrapper pair (#358): the healthy take, then the refused one."""
    from demo_recording import Recorder

    failures: list[str] = []
    out_dir = fresh_take_dir(out_root, "wrapper")
    try:
        with fixture_server() as base_url:
            info = record_wrapper(out_dir, base_url)
    except _StoryboardFailed as exc:
        return [f"wrapper: {exc}"]
    except Exception as exc:  # noqa: BLE001 - a raising take is the failure
        return [f"wrapper: recording raised {type(exc).__name__}: {exc}"]
    failures += check_wrapper_band(out_dir, info)
    failures += check_wrapper_opening(out_dir, info)
    failures += check_wrapper_card(out_dir, info)
    failures += check_wrapper_caption_survives(out_dir, info)
    failures += check_wrapper_evidence(out_dir)
    failures += check_wrapper_clipped(out_dir)

    refused_dir = fresh_take_dir(out_root, "wrapper-refused")
    raised: BaseException | None = None
    with refusing_fixture_server() as base_url:
        try:
            # strict=False on purpose — see check_wrapper_refusal: the
            # refusal must not need strict's console-error net to surface.
            with Recorder(
                refused_dir,
                base_url=base_url,
                speech=False,
                strict=False,
            ) as rec:
                rec.goto("/")
                rec.caption(WRAPPER_UNREACHED)
        except Exception as exc:  # noqa: BLE001 - the raise is the assertion
            raised = exc
    failures += check_wrapper_refusal(refused_dir, raised)
    return failures


def run_determinism(out_root: Path) -> list[str]:
    """Record one storyboard three times and compare the recordings.

    Two takes with the recorder's determinism controls on have to produce the
    same pixels; a third with `deterministic=False` has to produce different
    ones. The third is not a nicety — without it "the two takes match" is also
    true of a recorder that produced two blank videos, and of a harness
    comparing two files it never wrote.
    """
    plan = (
        ("determinism-a", True),
        ("determinism-b", True),
        ("determinism-off", False),
    )
    takes: dict[str, EntropyTake] = {}
    with fixture_server() as base_url:
        for name, on in plan:
            out_dir = fresh_take_dir(out_root, name)
            try:
                takes[name] = record_entropy(out_dir, base_url, on)
            except Exception as exc:  # noqa: BLE001 - a raising take is a failure
                return [
                    f"{name}: Recorder(deterministic={on}) raised "
                    f"{type(exc).__name__}: {exc}"
                ]

    failures: list[str] = []
    for take in takes.values():
        failures += take.problems
    first, second, live = (
        takes["determinism-a"],
        takes["determinism-b"],
        takes["determinism-off"],
    )

    # Liveness before identity. Two blank recordings are identical too, and a
    # missing file compares equal to another missing file in every scheme that
    # forgets to look. Only *this* list short-circuits the comparisons below —
    # a take whose page reported the wrong clock still has stills worth
    # comparing, and reporting both is how the cause and the effect show up in
    # one run.
    liveness: list[str] = []
    stills: dict[str, dict[str, Path]] = {}
    for name, take in takes.items():
        stills[name] = {}
        for shot in ENTROPY_SHOTS:
            png = take.out_dir / "images" / f"{shot}.png"
            if not png.is_file():
                liveness.append(f"{name}: still {png} was never captured")
                continue
            # The whole frame, on the floor the rest of the harness already
            # calibrated for web stills (healthy 15.5-16.9, blank 0.1-1.1).
            # That the *panel* carries signal is covered by the two "with the
            # controls off, this much moves" floors further down, both of
            # which have been watched to fail.
            frames = gray_frames(png)
            score = contrast(frames[0]) if frames else 0.0
            if score < MIN_CONTENT_STDDEV["web"]:
                liveness.append(
                    f"{name}: {shot}.png is blank — the whole frame scores "
                    f"{score:.1f} luma stddev, under the "
                    f"{MIN_CONTENT_STDDEV['web']} floor, so there is nothing "
                    f"in it for the comparisons below to be about"
                )
                continue
            stills[name][shot] = png
        mp4 = take.out_dir / "demo.mp4"
        if not mp4.is_file():
            liveness.append(f"{name}: {mp4} was never written")
    if liveness:
        return failures + liveness

    # -- the clock the page rendered -----------------------------------------
    if first.clock != second.clock:
        failures.append(
            f"determinism: two takes of one storyboard rendered different "
            f"clocks — {first.clock!r} and {second.clock!r}. The page's wall "
            f"clock is not frozen, so nothing dated survives a re-record."
        )
    elif live.clock == first.clock:
        failures.append(
            f"determinism: the take recorded with the recorder's *default* "
            f"settings rendered the same clocks {live.clock!r} as the frozen "
            f"takes — either the default freezes the clock (it must not; the "
            f"freeze changes what clock-reading apps do and is opt-in), or all "
            f"four readings are ones this harness is not actually varying"
        )
    else:
        print("smoke: determinism froze all four clocks identically in both takes")
        for line in first.clock.splitlines():
            print(f"smoke:   frozen  {line}")
        for line in live.clock.splitlines():
            print(f"smoke:   default {line}")

    # -- the stills, byte for byte -------------------------------------------
    still_failures = check_entropy_stills(first, stills)
    reproduced = not still_failures
    failures += still_failures

    # ...and the same two stills with the controls off, which is what makes
    # every comparison above capable of failing.
    off = stills["determinism-off"]
    live_delta = frame_difference(
        gray_frames(off[ENTROPY_SHOTS[0]], live.spin_rect)[0],
        gray_frames(off[ENTROPY_SHOTS[1]], live.spin_rect)[0],
    )
    if digest(off[ENTROPY_SHOTS[0]]) == digest(off[ENTROPY_SHOTS[1]]):
        failures.append(
            f"determinism: recorded with the recorder's default settings, "
            f"{ENTROPY_SHOTS[0]}.png and {ENTROPY_SHOTS[1]}.png are still "
            f"byte-identical — the page is not moving even with nothing "
            f"pinned, so the byte comparison above proves nothing"
        )
    elif live_delta < MIN_LIVE_STILL_DELTA:
        failures.append(
            f"determinism: recorded with the recorder's default settings the "
            f"two stills differ by only {live_delta:.2f} mean luma over the "
            f"spinner, under the {MIN_LIVE_STILL_DELTA} floor — the fixture is "
            f"barely varying, so the equality asserted above is nearly free"
        )
    # Only now, and only if the comparisons above actually held. Printing this
    # next to a "01-entropy.png differs" failure — which an earlier revision
    # did, because the print sat in the `else` of the *liveness* branch — makes
    # the log contradict itself, and a log that contradicts itself is one
    # nobody reads.
    elif reproduced:
        print(
            f"smoke: determinism stills reproduce byte for byte across takes "
            f"(the same two stills move {live_delta:.1f} over the spinner "
            f"with the recorder's default settings)"
        )

    # -- the video, where bytes cannot be compared ---------------------------
    closing = {
        name: last_frame(take.out_dir / "demo.mp4", take.video_rect)
        for name, take in takes.items()
    }
    if any(f is None for f in closing.values()):
        failures.append(
            "determinism: could not sample the closing frame of every take, so "
            "the recordings themselves went ungraded"
        )
    else:
        same = frame_difference(closing["determinism-a"], closing["determinism-b"])
        different = frame_difference(
            closing["determinism-a"], closing["determinism-off"]
        )
        if same > MAX_TAKE_VIDEO_DELTA:
            failures.append(
                f"determinism: the closing frames of two takes of one "
                f"storyboard differ by {same:.2f} mean luma over the entropy "
                f"panel, over the {MAX_TAKE_VIDEO_DELTA} bar — the recording "
                f"itself does not reproduce"
            )
        if different < MIN_LIVE_VIDEO_DELTA:
            failures.append(
                f"determinism: a deterministic take and a default-settings "
                f"take differ by only {different:.2f} mean luma over the "
                f"entropy panel, under the {MIN_LIVE_VIDEO_DELTA} floor — this "
                f"comparison cannot see the difference the controls make, so "
                f"the {same:.2f} above is not evidence of anything"
            )
        if same <= MAX_TAKE_VIDEO_DELTA and different >= MIN_LIVE_VIDEO_DELTA:
            print(
                f"smoke: determinism demo.mp4 reproduces (takes differ by "
                f"{same:.2f}, against {different:.2f} with the default "
                f"settings)"
            )
    if not failures:
        print("smoke: determinism ok (3 takes)")
    return failures


def run_segments(out_root: Path) -> list[str]:
    """Record a demo in two parts, stitch it, and grade the merged log.

    The merged timeline is handed to `check_timeline()` — the same function,
    the same assertions, including the measured one — because a segmented demo
    that is graded more softly than a single take is a segmented demo nobody
    can trust. What is extra here is `stitch_segments()`.
    """
    from demo_recording.content import media_duration

    out_dir = fresh_take_dir(out_root, "segments")
    started = time.time()
    with fixture_server() as base_url:
        try:
            problems, video_rect, still_rect, size, clocks = record_segments(
                out_dir, base_url
            )
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"segments: Recorder raised {type(exc).__name__}: {exc}"]
        # Before `stitch()`, which removes the parts and their logs unless
        # asked to keep them: each segment's own `capture_clock` is only on
        # disk until then, and the merged envelope carries none (`stitch()`
        # does not merge the field — see tests/README.md, Known gaps).
        for name, part in zip(SEGMENT_NAMES, clocks, strict=True):
            problems += check_capture_clock(
                f"segments/{name}", out_dir, part, f"{name}.seg.timeline.json"
            )
        # Each segment watched its own capture; the stitched demo lays them end
        # to end, so each part's steps sit that far along the merged clock
        # (issue #215). The offsets are ffprobe's, taken off the parts *before*
        # stitch() is allowed to remove them, rather than read out of the
        # merged envelope this run is grading.
        placed: list[tuple[HostClock, float]] = []
        offset = 0.0
        for name, part in zip(SEGMENT_NAMES, clocks, strict=True):
            try:
                placed.append((part, offset))
                offset += media_duration(out_dir / f"{name}.seg.mp4")
            except (subprocess.CalledProcessError, ValueError, OSError):
                # No part durations, no merged clock. Correcting with the wrong
                # offsets is worse than not correcting: the bar falls back to
                # MAX_UNWATCHED_CAPTURE_LOSS_S and the failure says so.
                placed = []
                break
        clock: HostClock | None = joined_clock(placed) if placed else None
        try:
            problems += stitch_segments(out_dir, size, clocks)
        except Exception as exc:  # noqa: BLE001 - a raising stitch is a failure
            problems.append(f"segments: stitch() raised {type(exc).__name__}: {exc}")
    return (
        problems
        + check_take(
            "segments",
            out_dir,
            SEGMENT_SHOTS,
            SEGMENT_DURATION_S,
            started,
            video_rect,
            still_rect,
            size,
        )
        + check_timeline(
            "segments",
            out_dir,
            started,
            SEGMENT_BEATS,
            SEGMENT_CAPTIONS,
            size,
            expected_segments=SEGMENT_BEAT_SEGMENTS,
            expected_interludes=SEGMENT_INTERLUDES,
            clock=clock,
        )
        + check_beat_frames(
            "segments",
            out_dir,
            started,
            SEGMENT_BEATS,
            SEGMENT_CAPTIONS,
            size,
            SEGMENT_INTERLUDES,
            clock=clock,
        )
        + check_healthy("segments", out_dir)
    )


def run_evidence(out_root: Path) -> list[str]:
    """The evidence take: what a beat's page text carries, and what it caps.

    Graded on `evidence/` alone — no video, no stills, no timing.

    **Most of this arm used to be about masking** and went with it (#150): the
    byte sweep for registered values, the "renders outside the mask" controls,
    the rotating-card refusal, the withheld-markup and entity-escaping shapes,
    and the mask-before-cap ordering. Per-beat evidence is not a masking
    feature and survives whole, so what is left had to be *written* rather than
    inherited — the assertions below are new, and each names the property it
    grades rather than the leak it used to prevent.

    Three things are graded, and the first exists because of the other two:

    1. **the page text is real.** Every assertion here is about the content of
       a captured snapshot, and all of them are satisfied by an empty one. So
       a control asserts that text the fixture visibly renders is in the ARIA
       tree, before anything else is claimed about it.
    2. **the markup serializer drops what was never on screen** — inline
       script text, `srcdoc`, and value-bearing attributes. This survives #142
       for a reason unrelated to secrets (an attribute nothing renders was in
       no frame and no still, so serializing it would make evidence the only
       place it exists), and it never had a check of its own — the old ones
       reached it through the mask.
    3. **truncation is marked, never silent**, on all three text fields.
    """
    from demo_recording import Recorder
    from demo_recording.timeline import EVIDENCE_LIMITS, EVIDENCE_SCHEMA

    label = "evidence"
    failures: list[str] = []
    # The package's own constants against the ones written at the top of this
    # file. Everything below is a statement about those numbers, so a cap
    # quietly widened by ten has to fail here rather than pass by agreeing
    # with itself.
    if dict(EVIDENCE_LIMITS) != EVIDENCE_LIMITS_EXPECTED:
        failures.append(
            f"{label}: the package caps evidence at {dict(EVIDENCE_LIMITS)!r}, "
            f"this harness grades {EVIDENCE_LIMITS_EXPECTED!r} — one of them "
            f"moved without the other"
        )
    if EVIDENCE_SCHEMA != EVIDENCE_SCHEMA_EXPECTED:
        failures.append(
            f"{label}: the package exports EVIDENCE_SCHEMA {EVIDENCE_SCHEMA!r}, "
            f"this harness grades {EVIDENCE_SCHEMA_EXPECTED!r}"
        )

    # `screen` is the terminal's field, and no take here bloats a TUI far
    # enough to reach a 12 000-character budget — so its cap is graded as the
    # contract of the function that applies it, and this file says plainly
    # that that is a unit check rather than a recording. The other three are
    # graded end to end below.
    from demo_recording.timeline import _cap_text

    for field, limit in sorted(EVIDENCE_LIMITS_EXPECTED.items()):
        short, cut = _cap_text("x" * (limit - 1), limit)
        if cut or short != "x" * (limit - 1):
            failures.append(
                f"{label}: _cap_text() cut text already inside the {field} "
                f"budget ({cut} characters removed)"
            )
        long, cut = _cap_text("y" * (limit + 500), limit)
        if cut != 500:
            failures.append(
                f"{label}: _cap_text() says it removed {cut} characters from a "
                f"{field}-sized field 500 over its budget"
            )
        if EVIDENCE_MARKER not in long or not long.startswith("y" * limit):
            failures.append(
                f"{label}: _cap_text() on a {field}-sized field returned "
                f"{long[-60:]!r} — a cut with no marker where it stops"
            )
        if len(long) > limit + EVIDENCE_TRUNCATED_MAX:
            failures.append(
                f"{label}: _cap_text() left {len(long)} characters for a {limit} budget"
            )

    out_dir = fresh_take_dir(out_root, label)
    # A previous take's evidence, planted. `record.py` is committed precisely so
    # it can be re-run into the same folder, and a re-record with fewer beats
    # would otherwise leave the old files sitting beside the new ones, named as
    # beats this take never recorded. Two files, because the clearing has to be
    # scoped: one this take's naming owns and one belonging to another segment
    # of the same demo, which must survive — deleting that would break a
    # multi-segment re-record.
    (out_dir / EVIDENCE_DIR_NAME).mkdir(parents=True, exist_ok=True)
    stale = out_dir / EVIDENCE_DIR_NAME / f"{EVIDENCE_SEGMENT}.seg.beat-99.json"
    stale.write_text(json.dumps({"aria": EVIDENCE_STALE_MARK}) + "\n")
    other = out_dir / EVIDENCE_DIR_NAME / "othersegment.seg.beat-00.json"
    other.write_text(json.dumps({"aria": "another segment's beat"}) + "\n")

    with fixture_server() as base_url:
        try:
            with Recorder(
                out_dir,
                base_url=base_url,
                speech=False,
                segment=EVIDENCE_SEGMENT,
            ) as rec:
                rec.goto("/?evidence=1")
                rec.wait_for(EVIDENCE_ATTR_TARGET)
                # 0 — the page, unspotlit and unbloated. The control for
                # everything else: its ARIA tree has to hold text the fixture
                # renders, and it must not already be truncated.
                rec.pause(0.3)
                # 1 — an element whose attributes carry strings it never
                # renders, next to text it does.
                rec.spotlight(EVIDENCE_ATTR_TARGET)
                rec.pause(0.3)
                # 2 — an element holding an inline <script> and a srcdoc
                # iframe. Injected rather than added to the fixture: what is
                # being graded is the serializer, and the fixture has no
                # element of this shape that a spotlight can name.
                rec.app.evaluate(EVIDENCE_SOURCE_JS, EVIDENCE_SOURCE_ID)
                rec.spotlight(f"#{EVIDENCE_SOURCE_ID}")
                rec.pause(0.3)
                # 3 — the caps.
                rec.app.evaluate(EVIDENCE_BLOAT_JS, EVIDENCE_BLOAT_ITEMS)
                rec.spotlight(f"#{EVIDENCE_BLOAT_ID}")
                rec.pause(0.3)
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return failures + [f"{label}: Recorder raised {type(exc).__name__}: {exc}"]

    if stale.exists():
        failures.append(
            f"{label}: {stale.name} survived a re-record into the same "
            f"directory. It is a previous take's evidence, named for a beat "
            f"this take never recorded — and re-recording into the same folder "
            f"is how this skill is meant to be used."
        )
    if not other.exists():
        failures.append(
            f"{label}: {other.name} was deleted. It belongs to another segment "
            f"of the same demo, which a re-record of *this* segment must "
            f"leave alone — otherwise re-recording one segment throws away the "
            f"evidence for all the others."
        )

    # Issue #9's acceptance criterion, on the arm that can afford to grade it
    # (#197). `check_evidence` owns the envelope, the per-beat stamping, the
    # pointer/orphan pairing and "the facts that beat showed are readable in
    # that beat's file"; everything below this call is about the *content* of
    # four particular beats and is this take's own job.
    failures += check_evidence(
        label, out_dir, EVIDENCE_TAKE_FACTS, segment=EVIDENCE_SEGMENT
    )

    beats, docs, problems = evidence_docs(label, out_dir, segment=EVIDENCE_SEGMENT)
    # `problems` are already in `failures` — `check_evidence` above called the
    # same helper — so they are not appended a second time. A broken pointer is
    # one finding, not two.
    if problems or not docs:
        return failures
    pauses = [
        (i, doc)
        for i, (beat, doc) in enumerate(zip(beats, docs, strict=False))
        if beat.get("verb") == "pause"
    ]
    if len(pauses) != 4:
        return failures + [
            f"{label}: {len(pauses)} pause beats, expected 4 — the take is not "
            f"the take this grades"
        ]
    plain_i, plain = pauses[0]
    attrs_i, attrs = pauses[1]
    source_i, source = pauses[2]
    capped_i, capped = pauses[3]

    # -- the control: there is a page in here at all -------------------------
    #
    # The catalogue's vacuous sweep, and it is not hypothetical here: every
    # assertion below is an absence ("this attribute is not in the markup"),
    # and an absence is satisfied by a null field. This is the one assertion
    # that fails if the capture wrote nothing.
    aria = plain.get("aria")
    if not isinstance(aria, str) or len(aria) < EVIDENCE_MIN_ARIA_CHARS:
        failures.append(
            f"{label}: beat {plain_i}'s ARIA tree is "
            f"{len(aria or '') if isinstance(aria, (str, type(None))) else '?'} "
            f"characters, under the {EVIDENCE_MIN_ARIA_CHARS} this grades. "
            f"Every check below is an absence, and an absence holds trivially "
            f"in an empty file."
        )
    elif EVIDENCE_RENDERED_TEXT not in aria:
        failures.append(
            f"{label}: beat {plain_i}'s ARIA tree does not contain "
            f"{EVIDENCE_RENDERED_TEXT!r}, which the fixture renders on screen. "
            f"Whatever was captured, it is not this page."
        )
    if plain.get("scope") is not None:
        failures.append(
            f"{label}: beat {plain_i} scopes to {plain.get('scope')!r} with no "
            f"spotlight up — `scope`, `scope_aria` and `html` are the "
            f"spotlight target's and are null when there is none"
        )
    for field in ("scope_aria", "html"):
        if plain.get(field) is not None:
            failures.append(
                f"{label}: beat {plain_i} carries `{field}` with no spotlight "
                f"up, and it is the spotlight target's or nothing"
            )

    failures += check_evidence_omissions(label, plain_i, plain, aria)

    # -- markup: what was never on screen is not in it ------------------------
    if attrs.get("scope") != EVIDENCE_ATTR_TARGET:
        failures.append(
            f"{label}: beat {attrs_i} scopes to {attrs.get('scope')!r}, "
            f"expected {EVIDENCE_ATTR_TARGET!r}"
        )
    markup = str(attrs.get("html") or "")
    if EVIDENCE_ATTR_RENDERED not in markup:
        failures.append(
            f"{label}: beat {attrs_i}'s `html` is {markup[:160]!r}, which does "
            f"not contain the text the element actually renders — the markup "
            f"was not captured, so the attribute assertions below prove nothing"
        )
    for attr in ("data-token", "data-cfg"):
        if attr in markup:
            failures.append(
                f"{label}: beat {attrs_i}'s `html` still carries {attr!r}. "
                f"Nothing renders it, so it was in no frame, no still, no "
                f"caption and no narration clip — serializing it here makes "
                f"evidence the only place it exists."
            )

    # -- markup: source is not screen ----------------------------------------
    #
    # `<script>` text and `srcdoc` are the two shapes that put whole documents
    # into a file describing one element. This is the arm #142 left without a
    # check: the old ones reached the same code through the mask, so deleting
    # the mask deleted the only thing watching a serializer that still has this
    # job.
    if source.get("scope") != f"#{EVIDENCE_SOURCE_ID}":
        failures.append(
            f"{label}: beat {source_i} scopes to {source.get('scope')!r}, "
            f"expected the injected source-bearing element"
        )
    source_html = str(source.get("html") or "")
    if EVIDENCE_SOURCE_RENDERED not in source_html:
        failures.append(
            f"{label}: beat {source_i}'s `html` is {source_html[:160]!r} and "
            f"does not hold the text the element renders, so what it does not "
            f"hold says nothing"
        )
    for what, needle in (
        ("inline script text", EVIDENCE_SOURCE_SCRIPT),
        ("a srcdoc document", EVIDENCE_SOURCE_SRCDOC),
        ("the srcdoc attribute", "srcdoc"),
        ("a <script> tag", "<script"),
    ):
        if needle in source_html:
            failures.append(
                f"{label}: beat {source_i}'s `html` carries {what} "
                f"({needle!r}). It is source, not screen — nobody put it on "
                f"the page, and evidence describes what was on the page."
            )

    # -- the caps ------------------------------------------------------------
    if plain.get("truncated"):
        failures.append(
            f"{label}: beat {plain_i} ran before anything was appended to the "
            f"page and its evidence is already marked truncated "
            f"{plain.get('truncated')!r} — the marker means nothing if it is "
            f"always there"
        )
    if len(plain.get("aria") or "") >= EVIDENCE_LIMITS_EXPECTED["aria"]:
        failures.append(
            f"{label}: beat {plain_i}'s aria is "
            f"{len(plain.get('aria') or '')} characters before the page was "
            f"bloated, so the untruncated case is not being exercised"
        )
    if capped.get("scope") != f"#{EVIDENCE_BLOAT_ID}":
        failures.append(
            f"{label}: beat {capped_i} scopes to {capped.get('scope')!r}, "
            f"expected the bloated element — its markup is what the html cap is "
            f"being graded on"
        )
    # All three text fields, not the two that were easiest to reach: a cap
    # applied to `aria` and not to `scope_aria` is a cap on a third of what a
    # spotlight beat writes.
    for field in ("aria", "scope_aria", "html"):
        limit = EVIDENCE_LIMITS_EXPECTED[field]
        text = capped.get(field)
        if not isinstance(text, str):
            failures.append(
                f"{label}: beat {capped_i} captured no `{field}` at all, so the "
                f"cap on it is untested"
            )
            continue
        if field not in (capped.get("truncated") or []):
            failures.append(
                f"{label}: beat {capped_i}'s `{field}` is {len(text)} "
                f"characters against a {limit} cap, and `truncated` is "
                f"{capped.get('truncated')!r} — it was cut and does not say so"
            )
        if EVIDENCE_MARKER not in text:
            failures.append(
                f"{label}: beat {capped_i}'s `{field}` was cut with no marker "
                f"where it stops. It ends {text[-80:]!r}, which reads as a page "
                f"that simply ended there."
            )
        # Cut *to* the budget, not merely somewhere under a ceiling: the marker
        # is the only thing allowed past it.
        allowed = limit + EVIDENCE_TRUNCATED_MAX
        if not limit < len(text) <= allowed:
            failures.append(
                f"{label}: beat {capped_i}'s `{field}` is {len(text)} "
                f"characters, expected the {limit}-character budget plus a "
                f"marker (at most {allowed})"
            )

    if not failures:
        print(
            f"smoke: {label} ok ({len(docs)} beats as "
            f"{EVIDENCE_SEGMENT}.seg.beat-NN.json, {len(aria or '')} chars of "
            f"page text on the control beat, source and unrendered attributes "
            f"out of the markup, all three fields capped and marked)"
        )
    return failures


def run_narration(out_root: Path) -> list[str]:
    """Speech end to end, from a seeded cache: pacing and the audio mix."""
    out_dir = fresh_take_dir(out_root, "narration")
    with fixture_server() as base_url:
        try:
            # The host's wall clock, watched for exactly as long as the take
            # records. demo.mp4 is on that clock, the beat log is not, and
            # since #226 the *audio* is on it too — so where a clip belongs is
            # a question this watcher has to answer independently of the
            # recorder's own record.
            with watch_wall_clock() as clock:
                problems, info = record_narration(out_dir, base_url, clock)
        except Exception as exc:  # noqa: BLE001 - a raising take is a failure
            return [f"narration: Recorder raised {type(exc).__name__}: {exc}"]
    mp4 = out_dir / "demo.mp4"
    if not mp4.is_file():
        return problems + [f"narration: {mp4} was never written"]
    failures = (
        problems
        + check_narration_pacing(out_dir)
        + check_narration_audio(out_dir, info["lines"], clock)
        + check_narration_placement(out_dir, info["lines"], clock)
        # The other half of the coverage question, and the one neither check
        # above can ask: they refuse when *this* watcher was away, which leaves
        # the case where both samplers stalled, both reported nothing, and
        # agreed (issue #247). This is the cross-check that grades the
        # recorder's own `capture_clock` against this harness's — and since
        # #226 that record is what the audio's placement is derived from, so
        # the arm that mixes speech is a place it belongs.
        + check_capture_clock("narration", out_dir, clock)
        + check_healthy("narration", out_dir)
        + check_overlay_cleared("narration", out_dir)
    )
    if not failures:
        offsets = ", ".join(f"{off:.2f}s" for off, _ in info["lines"])
        print(
            f"smoke: narration ok ({len(info['lines'])} lines spoken from a "
            f"seeded cache at {offsets}, no key sent, audio present where a "
            f"line is and silent before the first, every clip's onset within "
            f"{NARRATION_ONSET_TOLERANCE_S * 1000:.0f} ms of where the record "
            f"says it went; {clock.describe()})"
        )
    return failures


def run_terminal(out_root: Path) -> list[str]:
    if os.name != "posix":
        print(
            "smoke: SKIPPING the terminal take — TerminalRecorder needs a PTY "
            f"and this is {os.name!r}, not a Unix platform.",
            file=sys.stderr,
        )
        return []
    out_dir = fresh_take_dir(out_root, "terminal")
    started = time.time()
    # The shell starts in the process cwd, and `ls -1` is one of the beats —
    # pin it to the repo root so the take does not depend on where it was run.
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        # The terminal records the same Chromium page through the same
        # screencast, so it is on the same host wall clock (issue #215).
        with watch_wall_clock() as clock:
            problems, video_rect, still_rect, size = record_terminal(out_dir, clock)
    except Exception as exc:  # noqa: BLE001 - a raising take is a failure
        return [f"terminal: TerminalRecorder raised {type(exc).__name__}: {exc}"]
    finally:
        os.chdir(previous)
    return (
        problems
        + check_take(
            "terminal",
            out_dir,
            TERMINAL_SHOTS,
            TERMINAL_DURATION_S,
            started,
            video_rect,
            still_rect,
            size,
        )
        + check_capture_clock("terminal", out_dir, clock)
        + check_timeline(
            "terminal",
            out_dir,
            started,
            TERMINAL_BEATS,
            TERMINAL_CAPTIONS,
            size,
            clock=clock,
        )
        + check_beat_frames(
            "terminal",
            out_dir,
            started,
            TERMINAL_BEATS,
            TERMINAL_CAPTIONS,
            size,
            clock=clock,
        )
        + check_evidence("terminal", out_dir, TERMINAL_EVIDENCE)
        + check_healthy("terminal", out_dir)
    )


def run_crash_web(out_root: Path, base_url: str) -> list[str]:
    """A web verb that raises. The common case, and the one #11 is written for."""
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "crash-web")
    started = time.time()
    raised: BaseException | None = None
    try:
        with Recorder(out_dir, base_url=base_url, speech=False) as rec:
            rec.goto("/")
            rec.caption(CRASH_CAPTION)
            rec.wait_for(CRASH_SELECTOR, timeout_s=2)
    except BaseException as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    return check_crash_take(
        "crash-web",
        out_dir,
        started,
        raised,
        "TimeoutError",
        "wait_for",
        CRASH_SCREEN_WEB,
    )


def run_crash_terminal(out_root: Path) -> list[str]:
    """The same, where the page text is the only account of what went wrong.

    A TUI's state is not recoverable from a frame, and `TerminalRecorder` has
    no `redact()` at all — so `failure/screen.txt` is both the most useful
    thing in the dump and the one that has to be read before the final
    redaction check rather than after it.
    """
    if os.name != "posix":
        return []
    from demo_recording import TerminalRecorder

    out_dir = fresh_take_dir(out_root, "crash-terminal")
    started = time.time()
    raised: BaseException | None = None
    try:
        with TerminalRecorder(out_dir, speech=False) as rec:
            rec.caption(CRASH_CAPTION)
            rec.run(f"echo {CRASH_SCREEN_TERMINAL}")
            rec.wait_for_prompt(timeout_s=20)
            rec.wait_for_text("this-text-never-appears", timeout_s=3)
    except BaseException as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    return check_crash_take(
        "crash-terminal",
        out_dir,
        started,
        raised,
        "RuntimeError",
        "wait_for_text",
        CRASH_SCREEN_TERMINAL,
    )


def run_crash_interrupt(out_root: Path, base_url: str) -> list[str]:
    """Ctrl-C while the frame is held.

    `KeyboardInterrupt` is a `BaseException`, so `except Exception` around the
    beat body would let it through unrecorded and every guard written for
    `Exception` misses it. A real SIGINT arrives inside the `time.sleep` in
    `_hold_frame`, which is where `pause()` spends its whole beat — so
    `_hold_frame` is where it is raised from here. The beat is a real `pause` beat, opened and
    closed by the recorder's own decorator.
    """
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "crash-interrupt")
    started = time.time()
    raised: BaseException | None = None
    try:
        with Recorder(out_dir, base_url=base_url, speech=False) as rec:
            rec.goto("/")
            rec.caption(CRASH_CAPTION)

            def _sigint(_seconds: float) -> None:
                raise KeyboardInterrupt("operator gave up on a hung demo")

            rec._hold_frame = _sigint  # type: ignore[method-assign]
            rec.pause(1.0)
    except BaseException as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    return check_crash_take(
        "crash-interrupt",
        out_dir,
        started,
        raised,
        "KeyboardInterrupt",
        "pause",
        CRASH_SCREEN_WEB,
    )


def run_crash_between(out_root: Path, base_url: str) -> list[str]:
    """A failure in storyboard code, where no beat may honestly be blamed.

    The inverse of every other arm: what is graded is that nothing claims it.
    Blaming the last beat that *returned* is the same confidently-wrong
    attribution the issue log refuses to make, and it would be believed — the
    dump is what somebody reads instead of re-running.
    """
    from demo_recording import Recorder

    out_dir = fresh_take_dir(out_root, "crash-between")
    started = time.time()
    raised: BaseException | None = None
    try:
        with Recorder(out_dir, base_url=base_url, speech=False) as rec:
            rec.goto("/")
            rec.caption(CRASH_CAPTION)
            # Not inside a verb: the recorder is idle and no beat is open.
            raise _StoryboardFailed("the storyboard's own code gave up")
    except BaseException as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    return check_crash_take(
        "crash-between",
        out_dir,
        started,
        raised,
        "_StoryboardFailed",
        None,
        CRASH_SCREEN_WEB,
    )


def run_stale_media(out_root: Path, base_url: str) -> list[str]:
    """A take that writes a beat log and no mp4, next to a previous run's mp4.

    Issue #20 exactly: `_timeline_doc` probed `demo.mp4` whenever the file
    existed, so a take that encoded nothing reported *the previous take's*
    duration beside this take's beats — and `stitch()` offsets every later
    segment's beats by that number.

    Reaching the state honestly took some care. Conversion is the only
    remaining way a take writes a timeline and no mp4, so the arm makes the
    conversion fail for a reason that happens to real people: a `demo.mp4` this
    process may read and may not overwrite. Nothing here is monkeypatched, the
    recorder runs unmodified, and both halves of the premise are asserted below
    — the planted file has to survive, and it has to be probeable. Without the
    second, `duration: null` would also be true of a broken fix, and the
    assertion would grade nothing.
    """
    from demo_recording import Recorder
    from demo_recording.content import media_duration
    from demo_recording.failure import FAILURE_MARKER

    out_dir = fresh_take_dir(out_root, "stale-media")
    mp4 = out_dir / "demo.mp4"
    planted = _plant_mp4(mp4)
    try:
        planted_duration = media_duration(mp4)
    except Exception as exc:  # noqa: BLE001 - without this the arm is vacuous
        return [
            f"stale-media: the planted demo.mp4 is not probeable ({exc}), so "
            f"'duration is null' would be true however _timeline_doc behaves"
        ]
    os.chmod(mp4, 0o444)
    try:
        with open(mp4, "ab"):
            pass
    except OSError:
        pass
    else:
        os.chmod(mp4, 0o644)
        return [
            "stale-media: this process can still write a mode-444 file (are "
            "you root?), so ffmpeg would overwrite the planted recording and "
            "this arm would exercise nothing. Run the suite as a normal user."
        ]

    failures: list[str] = []
    raised: BaseException | None = None
    noise = io.StringIO()
    try:
        with contextlib.redirect_stderr(noise):
            with Recorder(out_dir, base_url=base_url, speech=False) as rec:
                rec.goto("/")
                rec.caption(CRASH_CAPTION)
    except BaseException as exc:  # noqa: BLE001 - the raise is the assertion
        raised = exc
    finally:
        os.chmod(mp4, 0o644)
    said = noise.getvalue()
    print(said, file=sys.stderr, end="")

    if raised is None:
        failures.append(
            "stale-media: ffmpeg could not have written demo.mp4 and the take "
            "reported success"
        )
    # The premise, both halves.
    if not mp4.is_file() or mp4.read_bytes() != planted:
        failures.append(
            "stale-media: the planted demo.mp4 was overwritten after all, so "
            "the take did encode one and every assertion below is about the "
            "wrong thing"
        )
    json_path = out_dir / "timeline.json"
    if not json_path.is_file():
        failures.append(
            "stale-media: a failed conversion took the beat log with it. The "
            "beats were in memory and are still right; only the duration is "
            "unknowable."
        )
    else:
        doc = json.loads(json_path.read_text())
        logged = doc.get("duration")
        if logged is not None:
            failures.append(
                f"stale-media: this take encoded no mp4, and timeline.json "
                f"reports duration {logged!r} — the planted recording measures "
                f"{planted_duration:.2f}s, so that is a previous run's number "
                f"printed beside this run's beats"
            )
        if doc.get("beats"):
            pass
        else:
            failures.append("stale-media: the timeline has no beats at all")
    # The stderr half of #20's fix: "say so on stderr".
    #
    # Matched on the *timeline writer's* two sentences rather than on
    # `"duration: null"` anywhere in the output, and that is not fussiness.
    # The first version searched the whole stderr blob for `duration: null` and
    # `previous run's` — and passed with the message deleted, because the
    # conversion warning a few lines earlier happens to contain both phrases.
    # Fault injection caught it; a whole-document search for a claim about one
    # message grades nothing.
    for phrase in (
        "this take encoded no mp4, so timeline.json says duration: null",
        "this timeline does not describe it",
    ):
        if phrase not in said:
            failures.append(
                f"stale-media: the timeline writer never said {phrase!r} on "
                f"stderr. A null in a JSON file nobody opened is not a report, "
                f"and the reason it matters is that the demo.mp4 in the folder "
                f"is somebody else's."
            )
    # Review frames are extracted off `media`, so an ungated run would have
    # photographed the *planted* recording and handed a reviewer a sheet of
    # frames from a different video under this take's beat names.
    frames_dir = out_dir / "frames"
    extracted = (
        sorted(p.name for p in frames_dir.glob("*.png")) if frames_dir.is_dir() else []
    )
    if extracted:
        failures.append(
            f"stale-media: {extracted!r} were extracted from a demo.mp4 this "
            f"take did not write — every one of them is a frame of the "
            f"previous run"
        )
    marker = out_dir / FAILURE_MARKER
    if not marker.is_file():
        failures.append(f"stale-media: no {FAILURE_MARKER}")
    elif "is a *previous* run's" not in marker.read_text():
        failures.append(
            f"stale-media: {FAILURE_MARKER} does not say the demo.mp4 beside "
            f"it belongs to an earlier run: "
            f"{' '.join(marker.read_text().split())[:200]!r}"
        )
    if not failures:
        print(
            f"smoke: stale-media a take that encoded nothing reports "
            f"duration: null beside a {planted_duration:.1f}s file it did not "
            f"write, extracts no frames from it, and says so on stderr and in "
            f"{FAILURE_MARKER}"
        )
    return failures


def run_marker_cleared(out_root: Path, base_url: str) -> list[str]:
    """A take that succeeds into a folder a failed one left behind.

    The other half of #46. A marker that outlives the run it describes is the
    same lie inverted, and a `failure/` from two takes ago is worse than that:
    it is a plaintext dump of a page, which may hold exactly the value the new
    take was rewritten to hide.
    """
    from demo_recording import Recorder
    from demo_recording.failure import FAILURE_MARKER

    out_dir = fresh_take_dir(out_root, "marker-cleared")
    marker = out_dir / FAILURE_MARKER
    marker.write_text(f"# stale marker\n\n{STALE_MARK}\n")
    dump = out_dir / "failure"
    dump.mkdir()
    (dump / "failure.json").write_text(json.dumps({"stale": STALE_MARK}) + "\n")
    (dump / "screen.txt").write_text(f"a previous take's page text: {STALE_MARK}\n")

    failures: list[str] = []
    try:
        with Recorder(out_dir, base_url=base_url, speech=False) as rec:
            rec.goto("/")
            rec.caption(CRASH_CAPTION)
    except BaseException as exc:  # noqa: BLE001 - a raising take is a failure
        return [f"marker-cleared: the take raised {type(exc).__name__}: {exc}"]

    if not (out_dir / "demo.mp4").is_file():
        return ["marker-cleared: the take wrote no demo.mp4, so it did not succeed"]
    if marker.is_file():
        failures.append(
            f"marker-cleared: {FAILURE_MARKER} survived a take that wrote a "
            f"fresh demo.mp4. It says this folder is not the output of a "
            f"successful take, beside one that is — and a marker that is "
            f"sometimes wrong is a marker nobody reads."
        )
    left = (
        [
            p.name
            for p in sorted(dump.glob("*"))
            if p.is_file() and STALE_MARK in p.read_text(errors="replace")
        ]
        if dump.is_dir()
        else []
    )
    if left:
        failures.append(
            f"marker-cleared: a previous take's failure dump {left!r} is still "
            f"here after a clean take. It is a plaintext account of a page, "
            f"and this is the same hazard a stale evidence/ file is."
        )
    if not failures:
        print(
            f"smoke: marker-cleared a successful take removed the "
            f"{FAILURE_MARKER} and the failure/ dump a previous run left"
        )
    return failures


def run_failure(out_root: Path) -> list[str]:
    """Every take about what a *failed* take leaves behind."""
    failures: list[str] = []
    with fixture_server() as base_url:
        failures += run_crash_web(out_root, base_url)
        failures += run_crash_interrupt(out_root, base_url)
        failures += run_crash_between(out_root, base_url)
        failures += run_stale_media(out_root, base_url)
        failures += run_marker_cleared(out_root, base_url)
    failures += run_crash_terminal(out_root)
    return failures
