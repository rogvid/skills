"""Argument handling and phase orchestration, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .checks import (  # noqa: E402
    check_clock_before_recording,
    check_lock_refusal,
)
from .constants import (  # noqa: E402
    EXPENSIVE_ARMS,
    HELPERS_DIR,
)
from .runs import (  # noqa: E402
    run_content,
    run_coverage,
    run_determinism,
    run_evidence,
    run_failure,
    run_narration,
    run_overlay,
    run_segments,
    run_spotlight,
    run_stills_only,
    run_strict_terminal,
    run_strict_web,
    run_terminal,
    run_terminal_opening,
    run_terminal_problems,
    run_terminal_race,
    run_web,
    run_web_problems,
    run_wrapper,
)
from .support import (  # noqa: E402
    SmokeFailure,
    only_one_suite,
    open_output,
    scrub_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the demo-video recorders against tests/fixture.",
    )
    parser.add_argument(
        "--web-only", action="store_true", help="record only the web takes"
    )
    parser.add_argument(
        "--terminal-only",
        action="store_true",
        help="record only the terminal takes",
    )
    parser.add_argument(
        "--determinism-only",
        action="store_true",
        help="record only the three determinism takes",
    )
    parser.add_argument(
        "--segments-only",
        action="store_true",
        help="record only the two-segment take and its stitch (issue #7)",
    )
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        help="record only the per-beat evidence take (issue #9)",
    )
    parser.add_argument(
        "--narration-only",
        action="store_true",
        help="record only the speech take, from a seeded cache (issue #157)",
    )
    parser.add_argument(
        "--failure-only",
        action="store_true",
        help="record only the takes that do not finish (issues #11/#20/#24/#46)",
    )
    parser.add_argument(
        "--polish-only",
        action="store_true",
        help="record only the two takes that grade how a recording looks "
        "(issues #110 and #111)",
    )
    parser.add_argument(
        "--content-only",
        action="store_true",
        help="record only the pair that grades whether the recorder notices a "
        "recording showing nothing (issue #97)",
    )
    parser.add_argument(
        "--overlay-only",
        action="store_true",
        help="record only the pair that grades clearing a light interlude and "
        "reporting one left up (issues #162 and #163)",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="record only the take that grades acceptance-criterion coverage "
        "(issue #12)",
    )
    parser.add_argument(
        "--strict-only",
        action="store_true",
        help="record only the two short takes that strict=True must refuse (issue #3)",
    )
    parser.add_argument(
        "--wrapper-only",
        action="store_true",
        help="record only the wrapper pair: verbs through the app iframe with "
        "the caption in its own band, and the take that must refuse an app "
        "sending X-Frame-Options (issue #358)",
    )
    parser.add_argument(
        "--stills-only",
        action="store_true",
        help="record only the stills-only run: the storyboard's pictures with "
        "no video, no pacing and nothing readable as a take (issue #372)",
    )
    parser.add_argument(
        "--issues-only",
        action="store_true",
        help="record only the broken-page and failing-command takes, which is "
        "what check_issues grades (issue #197)",
    )
    parser.add_argument(
        "--lock-only",
        action="store_true",
        help="record nothing: grade what a run the machine lock refuses "
        "leaves behind, against one that started and failed (issue #105)",
    )
    parser.add_argument(
        "--cheap",
        action="store_true",
        help="record every phase that any arm other than --web-only, "
        "--content-only and --terminal-only reaches — the per-push selection "
        "(issue #61). Derived from the guards in run_phases, not listed: a "
        "phase a new cheap arm reaches is in it automatically.",
    )
    parser.add_argument(
        "--allow-concurrent",
        action="store_true",
        help="run even when another suite holds the machine lock. The timing "
        "bars in this file fail under contention (issue #78), so a run that "
        "needs this flag cannot be read as a verdict.",
    )
    parser.add_argument(
        "--allow-stepping-clock",
        action="store_true",
        help="record the timing arms even when the pre-run probe finds the "
        "host's wall clock stepping (issue #370). Same shape as "
        "--allow-concurrent and the same caveat: a step comes out of "
        "demo.mp4 and not out of the beat log, so a run that needs this "
        "flag cannot be read as a verdict.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="where recordings land (default: a fresh temp dir). The web/ and "
        "terminal/ subdirectories must be absent, empty, or created by a "
        "previous run; each is recreated before its take.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the output directory even when everything passes",
    )
    args = parser.parse_args()

    chosen = [
        flag
        for flag, on in (
            ("--web-only", args.web_only),
            ("--terminal-only", args.terminal_only),
            ("--determinism-only", args.determinism_only),
            ("--segments-only", args.segments_only),
            ("--evidence-only", args.evidence_only),
            ("--narration-only", args.narration_only),
            ("--failure-only", args.failure_only),
            ("--polish-only", args.polish_only),
            ("--content-only", args.content_only),
            ("--overlay-only", args.overlay_only),
            ("--coverage-only", args.coverage_only),
            ("--strict-only", args.strict_only),
            ("--wrapper-only", args.wrapper_only),
            ("--stills-only", args.stills_only),
            ("--issues-only", args.issues_only),
            ("--lock-only", args.lock_only),
            ("--cheap", args.cheap),
        )
        if on
    ]
    if len(chosen) > 1:
        parser.error(f"{' and '.join(chosen)} are mutually exclusive")
    only = chosen[0] if chosen else None

    if not HELPERS_DIR.is_dir():
        print(f"smoke: helpers not found at {HELPERS_DIR}", file=sys.stderr)
        return 1
    sys.path.insert(0, str(HELPERS_DIR))

    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        print(
            "smoke: ffmpeg and ffprobe must be on PATH — the recorders shell "
            "out to both.",
            file=sys.stderr,
        )
        return 1

    scrub_env()

    # Before the machine lock, and that ordering is deliberate: the probe
    # records nothing and touches no shared state, so holding the lock for
    # forty seconds of watching a clock would block a suite that could have
    # run. A refusal here also never reaches `open_output`, so it leaves no
    # directory to send anybody to — the same shape as the lock's own refusal
    # (issue #105), and `main()` already words that case.
    refusal = check_clock_before_recording(only, args.allow_stepping_clock)
    if refusal:
        print("\nsmoke: REFUSED", file=sys.stderr)
        for line in refusal:
            print(f"  - {line}", file=sys.stderr)
        print(
            "\nsmoke: nothing was recorded — this run never started, so "
            "there is no output directory to look in.",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    out_root: Path | None = None
    ephemeral = False
    try:
        with only_one_suite(args.allow_concurrent):
            out_root, ephemeral = open_output(args)
            print(f"smoke: output -> {out_root}")
            failures += run_phases(only, out_root)
    except SmokeFailure as exc:
        failures.append(str(exc))

    if failures:
        print("\nsmoke: FAILED", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        # `out_root is None` is exactly "this run never got past the lock", and
        # that — rather than whether the directory happens to hold anything —
        # is what decides the line. On every other failure the directory is the
        # evidence and saying where it is is the useful thing; on a refusal
        # there is no directory, and telling somebody who has just been told
        # their run did not happen where to find its recordings sends them
        # looking for files that were never written (issue #105).
        if out_root is None:
            print(
                "\nsmoke: nothing was recorded — this run never started, so "
                "there is no output directory to look in.",
                file=sys.stderr,
            )
        else:
            print(f"\nsmoke: recordings left in {out_root}", file=sys.stderr)
        return 1

    print("\nsmoke: PASSED")
    if out_root is not None and ephemeral and not args.keep:
        shutil.rmtree(out_root, ignore_errors=True)
    elif out_root is not None:
        print(f"smoke: recordings kept in {out_root}")
    return 0


def selects(only: str | None, arms: tuple[str, ...]) -> bool:
    """Whether the chosen flag runs a phase the arms in `arms` reach.

    `None` is a whole run and takes everything. `--cheap` takes a phase when
    *any* arm reaching it is not one of `EXPENSIVE_ARMS` — so a phase only the
    long takes reach is skipped, and one that a 26 s arm also reaches is not.
    Every other flag is itself.
    """
    if only is None:
        return True
    if only == "--cheap":
        return any(arm not in EXPENSIVE_ARMS for arm in arms)
    return only in arms


def run_phases(only: str | None, out_root: Path) -> list[str]:
    """Every phase the chosen flag selects, in order."""
    failures: list[str] = []
    # First, and it records nothing: it spawns two child runs of this file and
    # reads what they say about their own output directory (issue #105). Two
    # seconds, before ten minutes of takes, so a full run's own report about
    # where its recordings are is graded before there are any.
    if selects(only, ("--lock-only",)):
        failures += check_lock_refusal(out_root)
    if selects(only, ("--web-only",)):
        failures += run_web(out_root)
    if selects(only, ("--terminal-only",)):
        failures += run_terminal(out_root)
    if selects(only, ("--segments-only",)):
        failures += run_segments(out_root)
    # After the graded takes, never instead of them: these five record
    # nothing worth looking at, and if a recorder is broken the messages
    # above are the ones that say how.
    # How the recording *looks* (issues #110/#111). Reachable from the medium
    # flags as well as from --polish-only, because whoever is changing the
    # spotlight is running --web-only.
    if selects(only, ("--web-only", "--polish-only")):
        failures += run_spotlight(out_root)
    if selects(only, ("--terminal-only", "--polish-only")):
        failures += run_terminal_opening(out_root)
    # Whether the recorder notices a recording that shows nothing (issue #97).
    # Reachable from --terminal-only as well as its own flag: it is a terminal
    # take, and the card it leaves up is the terminal recorder's card.
    if selects(only, ("--terminal-only", "--content-only")):
        failures += run_content(out_root)
    # Clearing a `light` interlude, and noticing one left up (#162/#163). A web
    # take, and reachable from --content-only as well as its own flag: it
    # grades the other half of the same question the pair above does.
    if selects(only, ("--web-only", "--content-only", "--overlay-only")):
        failures += run_overlay(out_root)
    # Acceptance-criterion coverage (issue #12). Reachable from --web-only as
    # well as its own flag: it is a web take, and whoever is changing the
    # recorder's beat record is running --web-only.
    if selects(only, ("--web-only", "--coverage-only")):
        failures += run_coverage(out_root)
    # What the recorder saw behind the pixels (`check_issues`). Reachable from
    # --issues-only as well as from the medium flags, and that split is the
    # point: these two takes record in well under a minute between them, and
    # were reachable only from arms costing 123 s and 186 s. An assertion is
    # only as gradeable as its cheapest arm — `--strict-only` is the worked
    # example, and issue #197 is where this one is written down with numbers.
    if selects(only, ("--web-only", "--issues-only")):
        failures += run_web_problems(out_root)
    # The two takes strict=True must refuse. Reachable on their own as well as
    # from the medium flags, because they are the cheapest graded takes in this
    # file — two short storyboards, no stitch, no second recording to compare
    # against — and the arm that reaches them otherwise costs 186 s. That
    # matters for `tests/smoke-inject`, where an assertion is only as gradeable
    # as its cheapest arm.
    if selects(only, ("--web-only", "--strict-only")):
        failures += run_strict_web(out_root)
    # The wrapper pair (#358). Reachable from --web-only as well as its own
    # flag: it is a web take, and whoever is changing the web recorder is
    # running --web-only. Its own flag is what keeps its assertions gradeable
    # — the arm records in well under a minute against --web-only's 123 s.
    if selects(only, ("--web-only", "--wrapper-only")):
        failures += run_wrapper(out_root)
    # Stills without a video (#372). A web take, so --web-only reaches it; its
    # own flag exists because the arm records in ~2 s and an assertion is only
    # as gradeable as its cheapest arm (#197).
    if selects(only, ("--web-only", "--stills-only")):
        failures += run_stills_only(out_root)
    if selects(only, ("--web-only", "--evidence-only")):
        failures += run_evidence(out_root)
    # Speech end to end (issue #157). A web take, so it is reachable from
    # --web-only as well as its own flag — whoever changes the narration path
    # is running one of the two.
    if selects(only, ("--web-only", "--narration-only")):
        failures += run_narration(out_root)
    if selects(only, ("--terminal-only", "--issues-only")):
        failures += run_terminal_problems(out_root)
    # Not on --issues-only: `run_terminal_race` manufactures its condition with
    # a shell that sleeps before exec'ing, and its assertions are its own —
    # `check_issues` never sees this take.
    if selects(only, ("--terminal-only",)):
        failures += run_terminal_race(out_root)
    if selects(only, ("--terminal-only", "--strict-only")):
        failures += run_strict_terminal(out_root)
    if selects(only, ("--determinism-only",)):
        failures += run_determinism(out_root)
    # What a take that did *not* finish leaves behind. Last, because every
    # phase above records a take that works, and reading "crash-web wrote no
    # demo.mp4" before "web wrote no demo.mp4" would send somebody to the
    # wrong place.
    if selects(only, ("--failure-only",)):
        failures += run_failure(out_root)
    return failures
