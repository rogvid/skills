"""The beat log: its schema, its two renderings, and what bounds them.

This is a published contract, not a private convenience — beat-aligned frame
extraction, per-beat evidence capture and acceptance-criterion coverage all
read it. Treat it as append-only: adding a key to a beat or to the envelope is
fine, renaming or repurposing one is not.

Nothing here drives a browser. `render_timeline_md` and `write_timeline` are
functions of a document, which is what makes the document's guarantees
checkable without recording anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from .failure import FAILURE_DIR, FAILURE_MARKER

# -- beat timeline -----------------------------------------------------------
#
# Every storyboard verb the recorder runs is logged as a *beat*: what was
# done, when, and what caption was on screen while it happened. On clean exit
# the log lands next to the media as timeline.json (machine-readable) and
# timeline.md (human-readable, with the stills embedded).
#
# This is a published contract, not a private convenience — beat-aligned frame
# extraction, per-beat evidence capture and acceptance-criterion coverage all
# read it. Treat it as append-only: adding a key to a beat or to the envelope
# is fine, renaming or repurposing one is not (bump TIMELINE_SCHEMA if you
# ever must).
#
# Envelope
#   schema        int    — TIMELINE_SCHEMA, bumped on any breaking change
#   generated_by  str    — always "demo-video"
#   recorder      str    — "Recorder" | "TerminalRecorder" (which medium), or
#                          "mixed" on a merged demo whose segments differ
#   segment       str?   — the segment name, or null for a whole demo
#   media         str    — the mp4 this timeline describes, e.g. "demo.mp4"
#   duration      float? — that mp4's real duration (ffprobe), null if absent
#   determinism   dict   — the conditions the take was recorded under:
#                          `deterministic` (was the clock frozen and motion
#                          flattened), `clock` (the frozen instant, null when
#                          the page's clock ran), `timezone_id`, `locale`.
#                          On a merged demo each value is the one every segment
#                          agrees on, or null where they disagree — the
#                          per-segment truth is in `segments`.
#   segments      list?   — merged demos only (`stitch`): one record per part,
#                          in order, each `segment`, `media`, `duration`
#                          (ffprobe), `offset` (where it starts in `media`),
#                          `beats`, `recorder`, `determinism`. Absent from a
#                          timeline a single take wrote.
#   content       dict?  — what the *picture* turned out to be, measured off
#                          the encoded mp4 over the region the app occupies:
#                          `measured` (bool), `note` (why not, when it is
#                          false), `rect`, `sample_fps`, `frames`, `score`
#                          (median luma stddev), `floor`, `static_for` (the
#                          longest stretch in seconds where nothing in the rect
#                          changed), `static_from`, `static_limit`, `opening`
#                          (see below) and `warnings` (empty on a healthy take).
#                          **Null** on a take that encoded no mp4. This is the
#                          only field in this document that describes the frames
#                          rather than the storyboard — see "did the recording
#                          show anything?" for why it had to exist.
#   content.opening
#                 dict?  — what the take opened on, and what the encode did
#                          about it: `gap` (seconds of featureless, unchanging
#                          picture at the start, measured off this mp4; 0.0
#                          when it opens on a picture, null when it could not
#                          be measured), `held` (seconds the recorder covered
#                          with the app's first painted frame, **null** for a
#                          recorder that does not do this), `limit` and `note`.
#                          On a merged demo this is the *first* segment's — the
#                          only one whose frame zero is the demo's. A non-zero
#                          `held` means the frames at the start of the video
#                          are not frames the recording captured; see "the
#                          blank opening".
#   coverage      dict?  — **null** unless the take was recorded against a
#                          ticket (`Recorder(criteria={...})`). What the
#                          storyboard *claimed*, never what it proved:
#                          `criteria` (the declared {id: text}), `claimed`
#                          ({id: [beats that tagged it]} — every declared id is
#                          a key, with an empty list where nothing did),
#                          `unclaimed` (the ids no beat tagged, the one
#                          machine-checkable finding here), `tagged_beats`,
#                          `untagged_beats`, and `conflicts` on a merged demo
#                          whose segments used different text for one id.
#                          On a stitched demo it is recomputed over the merged
#                          beats, so its indices match this file. See
#                          "acceptance criteria and coverage".
#   beats         list   — the beats, in the order they ran
#   strict        bool   — whether strict mode was on for this take (on a
#                          merged demo: only if it was on for every segment)
#   issues        list   — the problems the take recorded (see "take issues")
#   issue_count   int    — how many were seen; > len(issues) only if capped
#   failure       dict?  — **absent** from a take that exited cleanly, which is
#                          what makes its presence mean something. On an
#                          abnormal exit: `type` and `message` of what came out
#                          of the `with`, `beat` (index of the beat whose verb
#                          raised, or null when the failure happened between
#                          beats) and that beat's `verb`. See "failure
#                          artifacts" below.
#
# Beat
#   index     int    — position in `beats`, 0-based. Renumbered by `stitch`, so
#                      it is always the beat's position *in this file*.
#   t_start   float  — seconds from the start of `media` to the verb starting
#   t_end     float  — seconds from the start of `media` to the verb returning
#   caption   str    — the caption text on screen during the beat (the new
#                      text for a `caption` beat, the line shown for an
#                      `interlude` beat); "" when no caption is up
#   verb      str    — the storyboard verb: "caption", "click", "run", ...
#   selector  str?   — what the verb acted on, as a string: a CSS selector for
#                      the web verbs, the command / keys / pattern for the
#                      terminal ones, the path for `goto`. Null when the verb
#                      has no target (`pause`, `hold`, a cleared `spotlight`).
#   still     str?   — for `shot` beats, the still's path relative to the
#                      timeline file ("images/01-dashboard.png"); else null
#   segment   str?   — the segment this beat was recorded in, or null
#   segment_index
#             int    — the beat's position within its own segment. Equal to
#                      `index` in a take's own timeline, and *unchanged* by a
#                      merge — so `(segment, segment_index)` names a beat the
#                      same way before and after `stitch`, which `index` alone
#                      cannot (see issue #22).
#   ac        list?  — **absent** on a beat that claims no acceptance
#                      criterion, which is most of them. Present, as a list of
#                      declared criterion ids, on a `caption` or `shot` given
#                      `ac=`. A claim by the storyboard's author and nothing
#                      more — see `coverage` above.
#   evidence  str?   — path, relative to the timeline file, of this beat's
#                      evidence file ("evidence/beat-04.json"); null when
#                      evidence capture is off. See "per-beat evidence" below
#   exit_code int?   — TerminalRecorder `run` beats only: the shell's status
#                      for that command, or null if it could not be read
#   error     dict?  — **absent** on a verb that returned. Present, with the
#                      exception's `type` and its scrubbed `message`, on a verb
#                      that raised. Absent-on-success rather than
#                      `error: null`-on-success on purpose: a consumer asking
#                      "did this beat do what it says" wants the answer to be
#                      structurally missing when there is nothing to say, and
#                      a take recorded before this key existed then reads the
#                      same way as one that succeeded. See issue #24.
#
# Only the verb a storyboard calls becomes a beat. The verbs recorders build
# out of other verbs (`click` glides with `move_to`, `type_into` clicks first)
# record one beat spanning the whole call, not one per internal step.
TIMELINE_SCHEMA = 1

# -- per-beat evidence -------------------------------------------------------
#
# A reviewing agent handed only frames has to infer the DOM from pixels. The
# recorder is *driving* the page — it has the real thing — so at the end of
# every beat it also writes down what was on screen, in text, next to the
# frame the beat's timestamps point at.
#
# What is captured, per medium:
#
#   Recorder          the page's ARIA snapshot (Playwright's `aria_snapshot`,
#                     a compact YAML tree of roles and accessible names) —
#                     semantic, an order of magnitude smaller than the markup,
#                     and stable across restyling. Plus `url` and `title`. When
#                     a spotlight is up, the same snapshot *scoped to the
#                     spotlight target* and that element's `outerHTML`.
#   TerminalRecorder  the rendered screen, ANSI already stripped by xterm.js
#                     (`_screen()`), scrollback included.
#
# **`outerHTML` is only ever the spotlight target's, never the page's**, and
# that is a safety decision as much as a size one. `document.body.outerHTML`
# on the smoke fixture is 24 kB against 2.3 kB of ARIA, and it carries two
# things ARIA does not: the text of every inline `<script>`, and `srcdoc`
# attributes — i.e. source code and whole embedded documents that nobody put
# on screen. The clone that is serialized drops both (see web.py).
#
# **Evidence is plain text, and that makes it the leak path with the fewest
# natural defences.** Every other artifact this package writes is pixels, and
# `redact()` is a *pixel* control: it covers where a value renders and leaves
# the value in the DOM, which is exactly what is being dumped here. So:
#
#   * every string written is masked against the registered secrets *and*
#     against the rendered text of everything `redact()` is covering, harvested
#     from the page at capture time (see `Recorder._redacted_rendered_text`);
#   * nothing reaches the disk until the take has exited cleanly and the mask
#     has been verified — the documents are built in memory and written
#     alongside timeline.json, so a take that dies on a SecretLeak leaves no
#     evidence file to delete;
#   * a document that still holds a forbidden literal when it is serialized
#     raises SecretLeak and kills the take rather than being written.
#
# Naming, and issue #22. A beat's `index` is its position in *its own take*, so
# two segments of one demo both start at 0. Evidence therefore does two things
# that make renumbering a non-event: a segment's files carry the segment in
# their name (`evidence/part1.seg.beat-03.json`, mirroring how
# `<segment>.seg.timeline.json` is named), and the path is written *onto the
# beat* as `evidence` rather than derived from `index` by whoever reads the
# log. A merge that renumbers beats (issue #7) has only to carry that string
# across; nothing has to be renamed, and every evidence file names its own
# `segment` and `index` internally.
EVIDENCE_SCHEMA = 1
EVIDENCE_DIR = "evidence"

# Per-field character budgets. A TUI's scrollback is 5000 lines and a real
# app's ARIA tree is unbounded, so an uncapped evidence directory is bigger
# than the mp4 it describes. Truncation is *marked*, never silent: a reviewer
# reading a cut-off tree has to be able to tell it was cut off, and the file
# says so twice — inline where the text stops, and in `truncated`.
EVIDENCE_MAX_ARIA = 12_000
EVIDENCE_MAX_HTML = 8_000
EVIDENCE_MAX_SCREEN = 12_000
EVIDENCE_LIMITS = {
    "aria": EVIDENCE_MAX_ARIA,
    "scope_aria": EVIDENCE_MAX_ARIA,
    "html": EVIDENCE_MAX_HTML,
    "screen": EVIDENCE_MAX_SCREEN,
}
EVIDENCE_TRUNCATED = "\n…[demo-video: truncated here, {n} more characters]"

# Print a warning past this much evidence in one take. Not a cap — the
# per-field budgets are the cap — but a large accessibility tree times a long
# storyboard is a real cost (issue #49) and it should not arrive silently.
EVIDENCE_DIR_WARN_BYTES = 2_000_000


def evidence_name(index: int, segment: str | None = None) -> str:
    """The file one beat's evidence is written as.

    Mirrors `timeline_paths`: a whole demo writes `beat-04.json`, a segment
    writes `<segment>.seg.beat-04.json`, so two segments of one demo never
    collide and no merge has to rename anything (issue #22).
    """
    stem = f"{segment}.seg." if segment else ""
    return f"{stem}beat-{index:02d}.json"


def _cap_text(text: str, limit: int) -> tuple[str, int]:
    """`text` cut to `limit` characters, with an explicit marker. -> (text, cut)"""
    if len(text) <= limit:
        return text, 0
    cut = len(text) - limit
    return text[:limit] + EVIDENCE_TRUNCATED.format(n=cut), cut


# -- take issues -------------------------------------------------------------
#
# A demo that looks perfect while the app throws on every render passes any
# review that only watches pixels. So the recorders also watch the *app*: the
# browser console, uncaught page exceptions, requests that never completed,
# responses that came back >= 400, and — for TerminalRecorder — the exit status
# of every command `run()` typed. Each becomes an issue on the timeline, and
# each is attributed to the beat that was open when it fired, so a reviewer
# reads "the take broke during `click('#refresh')`" instead of "the take broke".
#
# Issue (part of the envelope's `issues`, same append-only rules as a beat)
#   kind     str   — one of ISSUE_KINDS below
#   t        float — seconds from the start of `media` to *observing* it
#   beat     int?  — index of the beat it is attributed to, or **null** when no
#                    beat can honestly claim it (see below)
#   verb     str?  — that beat's verb, denormalized so the list reads alone
#   caption  str   — the caption on screen at the time, same reason
#   message  str   — one human-readable line
#   plus kind-specific keys: `url`/`line` (console), `url`/`method`
#   (request_failed), `url`/`status` (http_error), `exit_code`/`command`
#   (nonzero_exit)
#
# `t` is when the problem was *observed*, which is not always when it happened:
# Playwright's sync API only delivers page events while it is being called, and
# a command's exit status is only knowable once the prompt comes back. `beat`
# is the attribution to trust; `t` is a hint.
#
# **`beat` is null whenever it cannot be established, and that is a feature.**
# The obvious implementation — blame the most recently started beat — is wrong
# in both directions: it hands an error thrown during a three-second hold to
# whatever beat makes the next Playwright call, quoting a caption that appeared
# after the error did, and it lets a beat that has already closed claim
# something that happened after it. So holds pump events as they wait
# (`_pump_events`), and an event is only attributed to a beat that was open,
# and had been open since events were last known to be flowing
# (`_attributed_beat`). A confidently wrong beat index is worse input for a
# reviewer — or for a conformance gate reading this file — than no answer.
ISSUE_KINDS = (
    "console_error",    # console.error(...) from the page
    "console_warning",  # console.warn(...) from the page
    "page_error",       # an uncaught exception / unhandled rejection
    "request_failed",   # a request that never got a response at all
    "http_error",       # a response with status >= 400
    "nonzero_exit",     # a TerminalRecorder run() whose command failed
)

# What `strict=True` refuses to pass: the app saying, in its own voice, that it
# is broken. `console_warning`, `request_failed` and `http_error` are recorded
# but not fatal on their own — a warning is not a failure, and a request the
# storyboard never depended on is the recorder's business to report, not to
# veto.
#
# In practice that distinction is narrower than it looks, and deliberately so:
# Chromium writes its own "Failed to load resource: …" line to the console for
# every request that fails or comes back >= 400, and that line is a genuine
# console error. So a strict take *does* fail on a 404 — including a favicon
# — because the browser complained about it out loud. Strict means strict; a
# demo of an app that cannot load its own assets is a demo of a broken app.
# Anything less deterministic than that belongs in the log, not in the verdict.
STRICT_KINDS = ("console_error", "page_error", "nonzero_exit")

# A page that throws on every render can throw thousands of times. Record the
# first MAX_ISSUES in full and keep counting the rest — `issue_count` in the
# envelope stays honest, and timeline.json stays a file somebody can open.
# Strict mode counts fatals separately and is *not* capped: a take whose 201st
# problem is its first console error still has to fail.
MAX_ISSUES = 200

# How often a hold gives Playwright a chance to deliver queued page events, and
# how stale that last delivery may be before a beat is no longer allowed to
# claim an event. See `_pump_events` and `_attributed_beat`.
PUMP_INTERVAL_S = 0.1
ATTRIBUTION_SLACK_S = 0.5


class StrictTakeFailed(RuntimeError):
    """A strict take finished, but recorded a problem it refuses to pass.

    Raised out of `__exit__` *after* the mp4, the stills and the timeline have
    been written — a broken take is exactly the one somebody wants to look at,
    so failing it must not also destroy the evidence.
    """


def timeline_paths(out_dir: Path | str, segment: str | None = None) -> tuple[Path, Path]:
    """(json, md) paths for a take's timeline.

    Mirrors how the media is named: a whole demo writes timeline.json next to
    demo.mp4, a segment writes <segment>.seg.timeline.json next to
    <segment>.seg.mp4, so segments of one demo never overwrite each other.
    """
    stem = f"{segment}.seg.timeline" if segment else "timeline"
    out_dir = Path(out_dir)
    return out_dir / f"{stem}.json", out_dir / f"{stem}.md"


def _md_cell(value: object) -> str:
    """A value made safe to drop into a markdown table cell."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def _fmt_t(value: object) -> str:
    # The `cast` is erased at run time, so this is byte-for-byte the behaviour
    # it had inside core.py — including the TypeError `float()` raises on a
    # beat whose timestamp is not a number. What changed is only that the
    # diagnostic is now visible: `[mypy-demo_recording.core]` disables
    # `arg-type` wholesale for one *stated* reason (a ViewportSize TypedDict),
    # and it was silencing this second, unrelated one for free. Moving the
    # function out from under a blanket suppression is how that surfaced.
    return "" if value is None else f"{float(cast('float', value)):.2f}"


def _coverage_md(coverage: object) -> list[str]:
    """The acceptance-criteria section of timeline.md, or nothing (issue #12).

    Every word here is chosen so a reader cannot come away thinking this file
    graded anything. The column is "claimed by", the note says a tag is the
    author's claim, and the only assertive sentence in the section is about
    the criteria nothing claimed — which needs no judgement, because nobody
    asserted them.
    """
    if not isinstance(coverage, dict):
        return []
    criteria = coverage.get("criteria") or {}
    if not criteria:
        return []
    claimed = coverage.get("claimed") or {}
    unclaimed = coverage.get("unclaimed") or []
    out = [
        "## Acceptance criteria",
        "",
        "This take was recorded against a ticket. **The table below is what "
        "the storyboard *claimed*, not what it proved** — an `ac=` tag is a "
        "string its author typed, and whether the frames actually show the "
        "criterion is the reviewer's judgement, not this file's.",
        "",
        "| criterion | claimed by | at | still |",
        "|---|---|---:|---|",
    ]
    for key, text in criteria.items():
        rows = claimed.get(key) or []
        if not rows:
            out.append(
                f"| **{_md_cell(key)}** — {_md_cell(text)} | "
                f"*nothing claims this* | | |"
            )
            continue
        for n, row in enumerate(rows):
            label = (
                f"**{_md_cell(key)}** — {_md_cell(text)}" if n == 0 else ""
            )
            beat = f"beat {row.get('index')}"
            if row.get("segment"):
                beat += f" (`{_md_cell(row['segment'])}`)"
            still = row.get("still")
            out.append(
                f"| {label} | {beat} | {_fmt_t(row.get('t_start'))} | "
                + (f"`{_md_cell(still)}`" if still else "")
                + " |"
            )
    out.append("")
    if unclaimed:
        out += [
            f"**{len(unclaimed)} of {len(criteria)} criteria have no beat "
            f"claiming them: {', '.join(f'`{_md_cell(k)}`' for k in unclaimed)}.** "
            f"Either the demo does not show them, or the storyboard did not say "
            f"where. Both are worth fixing before review.",
            "",
        ]
    else:
        out += [
            f"Every one of the {len(criteria)} criteria has at least one beat "
            f"claiming it. Whether those beats show what they claim is the "
            f"reviewer's call.",
            "",
        ]
    conflicts = coverage.get("conflicts") or []
    if conflicts:
        out += [
            f"**Segments disagree about the wording of "
            f"{', '.join(f'`{_md_cell(k)}`' for k in conflicts)}** — they were "
            f"recorded against different text for the same id, and the first "
            f"segment's wording is the one shown above. Check the segment "
            f"timelines.",
            "",
        ]
    untagged = coverage.get("untagged_beats")
    if isinstance(untagged, int) and untagged:
        out += [
            f"{untagged} beat(s) claim no criterion. That is ordinary — "
            f"navigation, waits and captions that set the scene are not "
            f"demonstrating anything in particular.",
            "",
        ]
    return out


def render_timeline_md(doc: dict) -> str:
    """Render a timeline document as markdown, stills embedded.

    Pure function of the document, so anything that *builds* a document —
    a take on exit, or a stitch that merges several — renders the same way.
    """
    beats = doc.get("beats") or []
    head = [f"`{doc.get('media') or 'demo.mp4'}`"]
    if doc.get("segment"):
        head.append(f"segment `{doc['segment']}`")
    if doc.get("recorder"):
        head.append(str(doc["recorder"]))
    if doc.get("duration") is not None:
        head.append(f"{float(doc['duration']):.1f}s")
    head.append(f"{len(beats)} beats")
    # Where the seams are. A merged demo's beat times are continuous across
    # them, so nothing in the table below says a segment boundary happened —
    # and a reviewer wondering why the scene jumps at 8.4s deserves an answer.
    # It also changes what "do not edit this, regenerate it" means: a merged
    # document comes back from stitch(), not from re-recording.
    segments = doc.get("segments") or []
    out = [
        "# Demo timeline",
        "",
        " · ".join(head),
        "",
        "Written by the demo-video recorder when it stitched the segments "
        "below — do not edit it by hand, re-stitch instead."
        if segments
        else "Written by the demo-video recorder when the take that produced "
        "it *failed* — do not edit it by hand, fix the storyboard and "
        "re-record."
        if doc.get("failure")
        else "Written by the demo-video recorder on every clean exit — do not "
        "edit it by hand, re-record instead.",
        "",
    ]
    # Before the beat table, not after it. A reader who opens this file after a
    # crash is reading it *because* something went wrong, and a timeline that
    # only mentions the failure in a footnote is the artifact-lies problem in
    # miniature — the table above it looks like an ordinary take's.
    failure = doc.get("failure")
    if isinstance(failure, dict):
        where = (
            f"beat {failure['beat']} (`{_md_cell(failure.get('verb'))}`)"
            if failure.get("beat") is not None
            else "between beats — no verb was running, so no beat is blamed"
        )
        out += [
            "## This take did not finish",
            "",
            f"It came out of the `with` block on a "
            f"**{_md_cell(failure.get('type'))}**, at {where}.",
            "",
            f"> {_md_cell(failure.get('message'))}",
            "",
            f"Everything below was still written — a broken take is the one "
            f"somebody wants to look at. `{FAILURE_DIR}/` beside this file has "
            f"the last frame, the console log, the page text and the failing "
            f"beat; `{FAILURE_MARKER}` says the same thing to anyone who only "
            f"opens the folder."
            + (
                ""
                if doc.get("duration") is not None
                else f" **No mp4 was encoded by this take**, so `duration` is "
                f"null; any `{doc.get('media') or 'demo.mp4'}` in this folder "
                f"is a previous run's."
            ),
            "",
        ]
    if segments:
        spans = ", ".join(
            f"`{s.get('segment')}` "
            f"({_fmt_t(s.get('offset'))}–"
            f"{_fmt_t((s.get('offset') or 0) + (s.get('duration') or 0))}s)"
            for s in segments
        )
        out += [
            f"Stitched from {len(segments)} segments, in order: {spans}. Beat "
            f"times below are on the stitched video's clock.",
            "",
        ]
    # Above the beat table, because it is the reason somebody opened this file
    # when the take was recorded against a ticket — and because a reviewer who
    # scrolls past 28 beats first has already formed the impression the
    # coverage report exists to test (issue #12).
    out += _coverage_md(doc.get("coverage"))
    # The exit column only exists when something in this take has one — a web
    # timeline would otherwise carry an empty column on every row. A `run` beat
    # whose status could not be read shows "?" rather than blank, so the
    # degraded case is visible here and not only in the JSON.
    shows_exit = any("exit_code" in b for b in beats)
    if shows_exit:
        out += [
            "| # | start | end | verb | target | exit | caption |",
            "|---:|---:|---:|---|---|---:|---|",
        ]
    else:
        out += [
            "| # | start | end | verb | target | caption |",
            "|---:|---:|---:|---|---|---|",
        ]
    for beat in beats:
        target = beat.get("selector")
        # A beat whose verb raised is marked in the table itself, not only in
        # the JSON. `t_start` and `t_end` are stamped either way, so without
        # this the row is indistinguishable from a row that worked (issue #24).
        error = beat.get("error")
        cells = [
            str(beat.get("index")),
            _fmt_t(beat.get("t_start")),
            _fmt_t(beat.get("t_end")),
            f"`{_md_cell(beat.get('verb'))}`"
            + (
                f" **raised {_md_cell(error.get('type'))}**"
                if isinstance(error, dict)
                else ""
            ),
            f"`{_md_cell(target)}`" if target else "",
        ]
        if shows_exit:
            if "exit_code" not in beat:
                cells.append("")
            elif beat["exit_code"] is None:
                cells.append("?")
            else:
                cells.append(_md_cell(beat["exit_code"]))
        cells.append(_md_cell(beat.get("caption")))
        out.append("| " + " | ".join(cells) + " |")
    issues = doc.get("issues") or []
    if issues:
        total = doc.get("issue_count", len(issues))
        out += [
            "",
            "## Issues",
            "",
            f"{total} recorded while this take ran — console errors, failed "
            f"requests, and non-zero exit codes, each attributed to the beat "
            f"it fired during. A demo can look perfect and still be a "
            f"recording of a broken app.",
            "",
        ]
        # A bullet list rather than a table on purpose: a table row starting
        # `| 0 |` is indistinguishable from a beat row to anything counting
        # the beat table above.
        for issue in issues:
            where = (
                "before the first beat"
                if issue.get("beat") is None
                else f"beat {issue['beat']} (`{_md_cell(issue.get('verb'))}`)"
            )
            out.append(
                f"- **{_md_cell(issue.get('kind'))}** — {where} at "
                f"{_fmt_t(issue.get('t'))}s: {_md_cell(issue.get('message'))}"
            )
        if total > len(issues):
            out.append(f"- …and {total - len(issues)} more, not recorded.")
        out.append("")
    stills = [b for b in beats if b.get("still")]
    if stills:
        out += ["", "## Stills", ""]
        for beat in stills:
            rel = str(beat["still"])
            name = rel.rsplit("/", 1)[-1].removesuffix(".png")
            out += [f"### {name} — {_fmt_t(beat.get('t_start'))}s", ""]
            if beat.get("caption"):
                out += [f"> {beat['caption']}", ""]
            out += [f"![{name}]({rel})", ""]
    return "\n".join(out).rstrip() + "\n"


def write_timeline(out_dir: Path | str, doc: dict) -> tuple[Path, Path]:
    """Write a timeline document as timeline.json + timeline.md."""
    json_path, md_path = timeline_paths(out_dir, doc.get("segment"))
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_timeline_md(doc))
    return json_path, md_path
