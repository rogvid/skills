#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.49"]
# ///
"""End-to-end smoke test for the demo-video recorders.

This is the main entry point that uses the modular smoke test package.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add the smoke package to path
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.smoke.constants import (
    EXPENSIVE_ARMS,
    CLOCK_PROBE_ARMS,
    CLOCK_SAFE_ARMS,
    SMOKE_LOCK,
    KEEP_OUT_ROOTS,
    REAP_MIN_AGE_S,
    LOCK_CHILD_TIMEOUT_S,
)
from tests.smoke.utils import (
    scrub_env,
    fresh_take_dir,
    open_output,
    reap_previous_out_roots,
    out_roots_to_reap,
    check_clock_before_recording,
    SmokeFailure,
    only_one_suite,
)
from smoke.runs import (
    run_web,
    run_terminal,
    run_segments,
    run_spotlight,
    run_terminal_opening,
    run_content,
    run_overlay,
    run_coverage,
    run_web_problems,
    run_terminal_problems,
    run_strict_web,
    run_strict_terminal,
    run_wrapper,
    run_stills_only,
    run_evidence,
    run_narration,
    run_terminal_race,
    run_determinism,
    run_failure,
)


def selects(only: str | None, arms: tuple[str, ...]) -> bool:
    """Whether the chosen flag runs a phase the arms in `arms` reach."""
    if only is None:
        return True
    if only == "--cheap":
        return any(arm not in EXPENSIVE_ARMS for arm in arms)
    return only in arms


def run_phases(only: str | None, out_root: Path) -> list[str]:
    """Every phase the chosen flag selects, in order."""
    failures: list[str] = []
    
    if selects(only, ("--lock-only",)):
        from smoke.checks.lock import check_lock_refusal
        failures += check_lock_refusal(out_root)
    
    if selects(only, ("--web-only",)):
        failures += run_web(out_root)
    
    if selects(only, ("--terminal-only",)):
        failures += run_terminal(out_root)
    
    if selects(only, ("--segments-only",)):
        failures += run_segments(out_root)
    
    if selects(only, ("--web-only", "--polish-only")):
        failures += run_spotlight(out_root)
    
    if selects(only, ("--terminal-only", "--polish-only")):
        failures += run_terminal_opening(out_root)
    
    if selects(only, ("--terminal-only", "--content-only")):
        failures += run_content(out_root)
    
    if selects(only, ("--web-only", "--content-only", "--overlay-only")):
        failures += run_overlay(out_root)
    
    if selects(only, ("--web-only", "--coverage-only")):
        failures += run_coverage(out_root)
    
    if selects(only, ("--web-only", "--issues-only")):
        failures += run_web_problems(out_root)
    
    if selects(only, ("--web-only", "--strict-only")):
        failures += run_strict_web(out_root)
    
    if selects(only, ("--web-only", "--wrapper-only")):
        failures += run_wrapper(out_root)
    
    if selects(only, ("--web-only", "--stills-only")):
        failures += run_stills_only(out_root)
    
    if selects(only, ("--web-only", "--evidence-only")):
        failures += run_evidence(out_root)
    
    if selects(only, ("--web-only", "--narration-only")):
        failures += run_narration(out_root)
    
    if selects(only, ("--terminal-only", "--issues-only")):
        failures += run_terminal_problems(out_root)
    
    if selects(only, ("--terminal-only",)):
        failures += run_terminal_race(out_root)
    
    if selects(only, ("--terminal-only", "--strict-only")):
        failures += run_strict_terminal(out_root)
    
    if selects(only, ("--determinism-only",)):
        failures += run_determinism(out_root)
    
    if selects(only, ("--failure-only",)):
        failures += run_failure(out_root)
    
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the demo-video recorders against tests/fixture.",
    )
    parser.add_argument("--web-only", action="store_true", help="record only the web takes")
    parser.add_argument("--terminal-only", action="store_true", help="record only the terminal takes")
    parser.add_argument("--determinism-only", action="store_true", help="record only the three determinism takes")
    parser.add_argument("--segments-only", action="store_true", help="record only the two-segment take and its stitch (issue #7)")
    parser.add_argument("--evidence-only", action="store_true", help="record only the per-beat evidence take (issue #9)")
    parser.add_argument("--narration-only", action="store_true", help="record only the speech take, from a seeded cache (issue #157)")
    parser.add_argument("--failure-only", action="store_true", help="record only the takes that do not finish (issues #11/#20/#24/#46)")
    parser.add_argument("--polish-only", action="store_true", help="record only the two takes that grade how a recording looks (issues #110 and #111)")
    parser.add_argument("--content-only", action="store_true", help="record only the pair that grades whether the recorder notices a recording showing nothing (issue #97)")
    parser.add_argument("--overlay-only", action="store_true", help="record only the pair that grades clearing a light interlude and reporting one left up (issues #162 and #163)")
    parser.add_argument("--coverage-only", action="store_true", help="record only the take that grades acceptance-criterion coverage (issue #12)")
    parser.add_argument("--strict-only", action="store_true", help="record only the two short takes that strict=True must refuse (issue #3)")
    parser.add_argument("--wrapper-only", action="store_true", help="record only the wrapper pair (issue #358)")
    parser.add_argument("--stills-only", action="store_true", help="record only the stills-only run (issue #372)")
    parser.add_argument("--issues-only", action="store_true", help="record only the broken-page and failing-command takes (issue #197)")
    parser.add_argument("--lock-only", action="store_true", help="record nothing: grade what a run the machine lock refuses leaves behind (issue #105)")
    parser.add_argument("--cheap", action="store_true", help="record every phase that any arm other than --web-only, --content-only and --terminal-only reaches (issue #61)")
    parser.add_argument("--allow-concurrent", action="store_true", help="run even when another suite holds the machine lock")
    parser.add_argument("--allow-stepping-clock", action="store_true", help="record the timing arms even when the pre-run probe finds the host's wall clock stepping (issue #370)")
    parser.add_argument("--out-dir", type=Path, help="where recordings land (default: a fresh temp dir)")
    parser.add_argument("--keep", action="store_true", help="keep the output directory even when everything passes")
    
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
    
    from smoke.constants import HELPERS_DIR
    if not HELPERS_DIR.is_dir():
        print(f"smoke: helpers not found at {HELPERS_DIR}", file=sys.stderr)
        return 1
    
    import shutil
    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        print(
            "smoke: ffmpeg and ffprobe must be on PATH — the recorders shell "
            "out to both.",
            file=sys.stderr,
        )
        return 1
    
    scrub_env()
    
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
        import shutil
        shutil.rmtree(out_root, ignore_errors=True)
    elif out_root is not None:
        print(f"smoke: recordings kept in {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())