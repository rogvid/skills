"""Where a take that did not finish writes itself down.

The constants — paths, schema, message budget — and the half of the dump that is
a function of documents rather than of a live recorder: rendering `failure.md`,
naming the beat that raised, and taking a previous run's dump off disk.

**What is not here is what needs the recorder.** `_failure_doc` reads the
buffered page text, the issue log and the media path off `self`;
`_failure_screen` is the hook a medium overrides to say what its screen holds;
`_write_failure` needs to know whether the encode happened. Those stay in
`core`, and the split is drawn exactly where the state stops: everything below
takes its inputs as arguments and can be checked without a browser (#147).

The docstring used to say the documents "are built in memory and refused whole
if the mask cannot be vouched for". There is no mask (#138); a document is built
and written.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from .markdown import _fmt_t, _md_cell

# -- failure artifacts (issues #11, #20, #24, #32, #46) ----------------------
#
# What a take leaves behind when it does not finish. The rule the whole section
# is built to satisfy: **after an abnormal exit, every artifact present is
# either current, or absent, or explicitly marked stale.** Three things used to
# violate it, and all three lived in `__exit__`:
#
#   * a take that raised converted nothing and wrote nothing, so the one
#     recording anybody wanted to look at was deleted with `.video/` (#32).
#     In CI there is no screen, so that means blind retries.
#   * `_timeline_doc()` probed `demo.mp4` unconditionally, so a take that wrote
#     no mp4 reported the *previous* take's duration beside this take's beats
#     (#20) — and `stitch()` offsets segment timelines by exactly that number.
#   * a failed re-record left the previous run's `demo.mp4` sitting in the
#     folder looking current (#46), which in a review gate produces a confident
#     approval of something that was never recorded.
#
# What is written now, on any abnormal exit the recorder is allowed to keep
# artifacts from:
#
#   demo.mp4              the partial recording, converted from the webm that
#                         was already in hand
#   timeline.json/.md     the beats, with `error` on the one that raised (#24)
#                         and `failure` on the envelope
#   failure/              this section: a self-contained account of the crash
#   demo-video-FAILED.md  the marker (#46), written whether or not anything
#                         else was, and deleted by the next take that succeeds
#
# **Where each piece comes from, and why none of it re-reads the page.**
#
#   * the last frame is extracted from `demo.mp4` with ffmpeg, so it is a frame
#     of the recording rather than a second capture of a page that has since
#     moved on;
#   * the DOM / terminal screen is read **once** (`_failure_screen()`), after
#     `_stop()` has flushed whatever the medium was holding back — so it is the
#     screen the recording ends on — and buffered in memory;
#   * the console log and the failing beat were in memory the whole time.
#
# The build/write split (`_build_failure` / `_write_failure`) survives from
# when a document could be *refused*. What it still carries is the `_convert`
# ordering: building runs before the encode, so the two facts that depend on
# whether an mp4 was written — `media_written_by_this_take` and the last frame
# — are filled in by the writer instead.
FAILURE_DIR = "failure"
FAILURE_SCHEMA = 1

# The marker (#46). Named visibly rather than as the dotfile the issue sketched
# (`.demo-video-failed`): the artifact it exists to contradict is a `demo.mp4`
# somebody is about to watch, and a hidden file next to it is exactly as easy
# to miss as the problem. `ls` shows this one, and so does a file browser.
FAILURE_MARKER = "demo-video-FAILED.md"

# How much of an exception message reaches the marker and the dump. A
# `wait_for_text()` timeout quotes a thousand characters of terminal screen,
# and a Playwright error quotes the selector, a call log and a page snippet;
# past a point that is a file nobody opens rather than a report. The timeline's
# per-beat `error.message` is **not** capped — it is the machine-readable copy
# and something may want to match on it — so nothing is lost by capping here.
FAILURE_MESSAGE_CHARS = 2_000


def failed_beat(beats: Sequence[dict]) -> dict | None:
    """The beat whose verb raised, or None if the failure was between beats.

    Reads `error`, which `_beat` stamps (issue #24), rather than assuming
    the last beat is the culprit — a storyboard can raise in its own code
    between two verbs, and blaming the last beat that *worked* is exactly
    the confidently-wrong attribution `_attributed_beat` refuses to make
    for issues.
    """
    for beat in reversed(list(beats)):
        if "error" in beat:
            return beat
    return None


def failure_summary(
    exc_type: type, exc: BaseException | None, beats: Sequence[dict]
) -> dict:
    """What came out of the `with`, and which beat it came out of.

    Unscrubbed: every consumer (`_timeline_doc`, the dump, the marker)
    masks it on the way to its own file, and each has a different mask.
    """
    beat = failed_beat(beats)
    message = str(exc) if exc is not None else ""
    return {
        "type": exc_type.__name__,
        "message": message[:FAILURE_MESSAGE_CHARS],
        "beat": None if beat is None else beat.get("index"),
        "verb": None if beat is None else beat.get("verb"),
    }


def render_failure_md(doc: dict) -> str:
    """The human half. Pure function of the document above, so it inherits
    its masking rather than re-deriving it."""
    failure = doc.get("failure") or {}
    beat = doc.get("beat") or {}
    where = (
        f"beat {failure.get('beat')} (`{_md_cell(failure.get('verb'))}`"
        + (
            f", target `{_md_cell(beat.get('selector'))}`"
            if beat.get("selector")
            else ""
        )
        + ")"
        if failure.get("beat") is not None
        else "between beats — no verb was running when it happened"
    )
    out = [
        "# This take did not finish",
        "",
        f"`{doc.get('recorder')}` · {doc.get('when')} · "
        f"{doc.get('beats_recorded')} beats recorded",
        "",
        f"**{_md_cell(failure.get('type'))}** at {where}.",
        "",
        f"> {_md_cell(failure.get('message')) or '(no message)'}",
        "",
        "## What is here",
        "",
        "| file | what it is |",
        "|---|---|",
        "| `failure.json` | this, machine-readable: the failing beat in "
        "full, every issue the take recorded, and what was written |",
    ]
    if doc.get("media_written_by_this_take"):
        out.append(
            f"| `last-frame.png` | the final frame of "
            f"`{doc.get('media')}` — what was on screen when it stopped |"
        )
    if doc.get("screen_captured"):
        out.append(
            "| `screen.txt` | the page's accessibility tree (web) or the "
            "rendered terminal buffer, read at the end of the take |"
        )
    out += ["", "## What the app said", ""]
    issues = doc.get("issues") or []
    if not issues:
        out.append(
            "Nothing. No console errors, failed requests or non-zero exits "
            "were recorded, so the app did not announce this."
        )
    else:
        for issue in issues:
            seat = (
                "before the first beat"
                if issue.get("beat") is None
                else f"beat {issue['beat']} (`{_md_cell(issue.get('verb'))}`)"
            )
            out.append(
                f"- **{_md_cell(issue.get('kind'))}** — {seat} at "
                f"{_fmt_t(issue.get('t'))}s: {_md_cell(issue.get('message'))}"
            )
        total = doc.get("issue_count", len(issues))
        if total > len(issues):
            out.append(f"- …and {total - len(issues)} more, not recorded.")
    out += [
        "",
        "## The recording",
        "",
        (
            f"`{doc.get('media')}` beside this folder is **this** take's "
            f"partial recording — the webm the browser had in hand when the "
            f"storyboard gave up, converted rather than discarded."
            if doc.get("media_written_by_this_take")
            else f"**This take encoded no mp4.** Any `{doc.get('media')}` in "
            f"the folder above is a *previous* run's and is not a recording "
            f"of this failure — see `{FAILURE_MARKER}`."
        ),
        "",
    ]
    return "\n".join(out).rstrip() + "\n"


def clear_failure_dir(out_dir: Path) -> list[str]:
    """Take a previous run's `failure/` off disk. Returns what went.

    Same reasoning as `_clear_stale_evidence`, and the same hazard: this
    directory holds a text dump of the page — an ARIA tree or a terminal
    buffer — so a stale one sitting beside a *fresh* take is both a lie
    about which run failed and a file that may hold the very value this
    take was rewritten to hide. Bounded to the names `_write_failure`
    writes, never the directory, so nothing anybody put here is touched.
    """
    directory = out_dir / FAILURE_DIR
    gone: list[str] = []
    if not directory.is_dir():
        return gone
    for name in ("failure.json", "failure.md", "screen.txt", "last-frame.png"):
        path = directory / name
        try:
            if path.is_file():
                path.unlink()
                gone.append(f"{FAILURE_DIR}/{name}")
        except OSError:  # noqa: PERF203 - report what could not be removed
            print(
                f"demo-video: WARNING — could not delete {path}, which is "
                f"a previous take's failure dump and describes a run "
                f"this one is not",
                file=sys.stderr,
            )
    try:
        next(directory.iterdir())
    except StopIteration:
        directory.rmdir()
    except OSError:
        pass
    return gone


def clear_failure_marker(out_dir: Path) -> None:
    """Take a previous run's marker off disk once a take succeeds.

    The other half of #46 and not an optional one: a marker left beside a
    freshly-written demo.mp4 is the same lie inverted, and it is the one
    that makes people stop believing the marker at all.
    """
    marker = out_dir / FAILURE_MARKER
    try:
        if marker.is_file():
            marker.unlink()
            print(
                f"demo-video: this take wrote its own artifacts, so the "
                f"{FAILURE_MARKER} a previous run left here is gone",
                file=sys.stderr,
            )
    except OSError as exc:
        print(
            f"demo-video: WARNING — could not delete {marker} ({exc}). It "
            f"describes a previous run, not this one.",
            file=sys.stderr,
        )
