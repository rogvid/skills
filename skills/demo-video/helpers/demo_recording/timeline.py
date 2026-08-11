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
import math
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .failure import FAILURE_DIR, FAILURE_MARKER
from .markdown import _fmt_t, _md_cell

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
#   capture_clock dict?  — the clock `media` is on, which is **not** the clock
#                          `beats` are on. Chromium stamps every screencast
#                          frame with the host's *wall* clock; the beat log is
#                          `time.monotonic()`. So the recorder samples the
#                          difference for the take's whole life and writes down
#                          every step it saw: `measured` (bool — see below),
#                          `note` (why not, when it is false), `steps` (each
#                          `t`, seconds into the take, and `delta`, seconds
#                          the wall clock jumped), `total`, `sample_interval`
#                          and `min_step` (the sampler's own settings; the
#                          smallest jump it calls a step), and `max_gap` /
#                          `max_gap_limit` (the widest interval the sampler
#                          actually left between two readings, and the bound
#                          over which it refuses to answer).
#                          **Read `measured` first.** When it is false,
#                          `steps` is empty and `total` is null on purpose:
#                          the sampler was away long enough that it cannot say
#                          when — or whether — the clock moved, and a consumer
#                          correcting a beat with a number nobody watched is
#                          the failure this field grew a flag to prevent
#                          (issue #247). An empty `steps` with `measured` true
#                          means the clock held still, which is a different
#                          answer again from the field being absent.
#                          **An instant the log puts at `t` sits at
#                          `t + (the steps before `t`)` in the video** —
#                          measured against the encode over six takes and 38
#                          caption transitions, residual under 101 ms where
#                          the uncorrected log was out by up to 1.50 s.
#                          reference/limits.md has the measurement. Note the
#                          rule is indexed by the **instant being converted**,
#                          not by the beat it came from: converting a beat's
#                          midpoint sums the steps before the midpoint, and a
#                          step inside that beat's first half belongs to it.
#                          Reading `t_start` for every instant of a beat leaves
#                          such a step out entirely, and the measurement above
#                          cannot see that — caption transitions sit at beat
#                          *starts*, the one instant where the two agree.
#                          **A backward step also leaves a hole, and the rule
#                          above is wrong inside it** (issue #256). A step of
#                          −Δ at `T` does not slide the video: it *deletes*
#                          the monotonic window `(T, T+Δ)` from the file,
#                          because the encoder stamps frames with the wall
#                          clock and will not write a stamp it has already
#                          written. Measured one video frame wide — `video
#                          31.560 → 31.600 shows mono 31.644 → 32.644`. An
#                          instant inside that window has **no video at all**,
#                          and `t + (the steps before t)` lands it up to a
#                          whole step early, in content that predates the
#                          step. The rule that holds everywhere is that the
#                          video's clock is the *high-water mark* of the wall
#                          clock: an instant sits at the greatest of `t + (the
#                          steps before t)` and every `T + (the steps before
#                          T)` for a step at `T ≤ t`. Outside a hole the two
#                          agree exactly and this is the same arithmetic;
#                          inside one it clamps to the last instant the file
#                          has. `capture_clock_correction` below answers both
#                          — where the instant sits, and how many seconds of
#                          the correction the hole swallowed — and the
#                          recorder's own consumers say which they got.
#                          On a merged demo (`stitch`) every part's steps are
#                          here, moved onto the stitched clock by that part's
#                          `offset`, and each step also carries the `segment`
#                          it was measured in. **That `segment` is the
#                          attribution to trust**, not the timestamp: a step is
#                          sampled for as long as the capture runs, which is
#                          longer than the video it produced, so a step's `t`
#                          can fall past the next part's `boundaries` entry.
#                          The correction for an instant is the steps of *its
#                          own* segment up to that instant — never `total`, and
#                          never an earlier part's, whose loss is already in
#                          the offsets. `capture_clock_correction` below is
#                          this rule, and is what the recorder's own consumers
#                          read it through. `boundaries` (merged demos only) is
#                          where each capture starts on the stitched clock.
#                          **Null** on a merged demo any of whose parts carried
#                          no usable record: a partial answer here would say a
#                          part nobody measured held still.
#   segments      list?   — merged demos only (`stitch`): one record per part,
#                          in order, each `segment`, `media`, `duration`
#                          (ffprobe), `offset` (where it starts in `media`),
#                          `beats`, `recorder`, `determinism`, `content`,
#                          `narration` and that part's own `capture_clock`,
#                          the last two on its own clock.
#                          Absent from a timeline a single take wrote.
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
#   narration     dict?  — **null** on a take that mixed no speech into
#                          `media` — narration off, no lines, or no mp4
#                          encoded. Otherwise, where each spoken line's audio
#                          was actually put: `lines`, one record per clip in
#                          the order they were mixed, each `t` (the beat-log
#                          instant the line appeared, `time.monotonic()`) and
#                          `at` (where that instant is in `media`, which is
#                          what the mix used as its `adelay`); plus
#                          `clock_correction`, the same `applied` / `total` /
#                          `steps` / `note` state `capture_clock_correction`
#                          returns. The audio rides the *video's* clock
#                          because it is inside the video, so `at` is `t`
#                          corrected the same way a review frame's seek is
#                          (issue #226) — and the state is here so a reader
#                          can tell a mix that was corrected from one that
#                          fell back to the raw offset because nobody watched
#                          the clock. A line also carries `clamped` — **only
#                          when it has one** — being the seconds of correction
#                          that could not be applied because the result fell
#                          before its own capture's first frame: `adelay`
#                          cannot express a negative delay, so `at` is the
#                          start of that line's *own capture* (0.0 on a take
#                          recorded in one piece, that part's `offset` on a
#                          stitched demo — **not** 0.0 there), and that line
#                          alone is *not* `t` plus the steps before it.
#                          **No record this recorder emits produces a
#                          `clamped` line any more** (issue #256): an instant
#                          is never placed earlier than the step that moved
#                          it, and the sampler starts at frame zero, so `at`
#                          cannot come out negative. The field and its floor
#                          stay for a record from somewhere else, because
#                          `adelay` refuses a negative delay and that costs a
#                          take its whole audio track rather than one clip.
#                          A line carries `no_video` — again **only when it
#                          has one** — when the instant it was spoken at falls
#                          inside a hole a backward step deleted from the file
#                          (issue #256): its `at` is the last moment before
#                          that gap and `no_video` is how many seconds later
#                          the video resumes. There is no moment in `media`
#                          for such a line to be at, and the rule above is
#                          false for it in the other direction.
#                          On a merged demo every
#                          part's lines are here, moved onto the stitched clock
#                          by that part's `offset` and each naming its own
#                          `segment`; `clock_correction.applied` is true only
#                          if every part that narrated corrected its own mix,
#                          and `parts` / `parts_uncorrected` (merged demos
#                          only) say how many of them that verdict is about,
#                          so a demo where one part of three could not correct
#                          is not reported as a demo where none could.
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
#   overlaps      list?  — merged demos only (`stitch`), and **empty on a
#                          healthy merge**, which is the merge saying it
#                          looked. One record per adjacent pair of beats where
#                          the later one starts before the earlier one ended:
#                          `beat` / `previous_beat` (their `index` in this
#                          file), `segment` / `previous_segment`, `seam` (is
#                          the later beat the first of its part — read off the
#                          parts' beat counts, not off the two segment names,
#                          which nothing stops being equal), `overlap`
#                          (seconds, on the clock the table above is on),
#                          `video_overlap` (the same difference with both
#                          instants put on the *video's* clock by the rule
#                          `capture_clock` documents; **null** when no
#                          correction was possible, which is not zero) and
#                          `no_video` / `previous_no_video`, the `lost` of
#                          each endpoint's `Placed`: non-zero when a backward
#                          step deleted that instant from the file, in which
#                          case it has **no frame at all** and the pair being
#                          "in order" says nothing about it. Only reported
#                          past `MERGE_OVERLAP_SLACK_S` (5 ms), which is the
#                          bar `tests/smoke` grades a merged log against.
#                          A merged timestamp is its part's own
#                          `time.monotonic()` plus that part's `offset`, and
#                          the offset is the part's real ffprobe duration — a
#                          wall clock. A part whose host clock stepped
#                          backwards has a video shorter than its own beat log
#                          by the size of the step, so its last beats run past
#                          where the next part begins (issue #263). Nothing is
#                          moved to fix it: `video_overlap` at or below zero
#                          says the frames are in order and only this column
#                          runs backwards. Absent from a timeline a single take
#                          wrote.
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
#                      exception's `type` and its `message` **verbatim**, on a
#                      verb that raised — `wait_for_text()` puts a thousand
#                      characters of terminal screen in there and nothing
#                      filters it, which is a reason not to point the recorder
#                      at anything real (#138). Absent-on-success rather than
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
# **Evidence is plain text, and nothing in it is hidden.** This recorder does
# not defend against a value reaching the screen (see SKILL.md), so a string
# the app renders is in here verbatim, in a form that greps. That is the same
# exposure the recording already has — it is worth saying because pixels feel
# private and a JSON file does not, and it is why `evidence/` is gitignored
# rather than committed.
#
# The documents are built in memory while the page is alive and written in
# `__exit__`, which is what keeps the capture off the page's critical path.
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
#   (nonzero_exit), `lost_caption`/`url` (caption_lost)
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
    "caption_lost",     # a page load took the caption bar off the screen
)

# What `strict=True` refuses to pass: the app saying, in its own voice, that it
# is broken. `console_warning`, `request_failed`, `http_error` and
# `caption_lost` are recorded but not fatal on their own — a warning is not a
# failure, a request the storyboard never depended on is the recorder's
# business to report rather than to veto, and a caption dropped by a
# navigation is the storyboard's mistake and not the app's.
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


# -- reading `capture_clock` back ---------------------------------------------
#
# `beats` are `time.monotonic()`; `media` is on the host's *wall* clock. So an
# instant the log puts at `t` sits at `t + (the steps its own capture recorded
# before it)` in the video — the rule the envelope documentation above states,
# measured over six takes and 38 caption transitions: uncorrected the video was
# up to 1.50 s from the log by 13.5 s in, corrected all 38 landed within 101 ms
# (issue #229, reference/limits.md).
#
# **It is indexed by the instant, not by the beat**, and the difference is a
# whole step. The envelope's "up to its `t_start`" is that rule applied to a
# beat's *start*; a consumer converting the beat's **midpoint** — which is what
# a review frame is cut at — has to sum the steps before the *midpoint*, or a
# step landing in the beat's own first half is left out and that frame does not
# move at all. That is not a corner case: **46.9 %, 48.0 % and 48.8 % of each
# take's `duration`** lies inside some beat's first half over this repo's three
# committed demos, so roughly one recorded step in two falls there. (Of the
# beats' own spans it is 50.0 % by construction, which is why the denominator
# is stated.) It was missed the first time
# because #250 validated the rule against *caption transitions*, which sit at
# beat starts — the one instant at which the two readings cannot differ.
#
# **The record can give three different answers, and the third is the one that
# is easy to lose:**
#
#   * `measured: true` with steps — correct by them, per capture.
#   * `measured: true` with none — the clock *was watched* and held still. The
#     correction is zero because somebody looked.
#   * `measured: false`, or no record at all — **nobody knows.** `steps` is an
#     empty list here too (issue #247), so a consumer reading only `steps`
#     cannot tell this case from the one above it. Zero is still the number
#     applied, because there is no other number available — but it is not a
#     correction, and an artifact built on it has to say so. A sheet that
#     implies a correction nobody could compute is exactly the confidently
#     wrong attribution this field grew a `measured` flag to prevent.
#
# `state` below is what an artifact prints so its reader can tell the three
# apart, and it is deliberately part of the return value rather than something
# a caller re-derives.
#
# **And there is a fourth thing an *instant* can be, which no state describes:
# inside a hole, with no video at all** (issue #256). That is a property of the
# instant and not of the record — the same well-measured record answers it for
# one beat and not for the next — so it rides on the answer instead, as
# `Placed.lost`. A −Δ step deletes the monotonic window `(T, T+Δ)` from the
# file, and until #256 every consumer here returned a shift for every `t > T`,
# so an instant inside that window was corrected up to a whole step early, into
# content that predates the step. Measured in the shipped path: `seg-run1`'s
# `beat-05` had its midpoint at 5.633 s, inside the hole (5.151, 6.202); its
# frame was cut at video 4.58 s and **shows the previous caption**.
#
# The arithmetic is `_placed` below, and it is the wall clock's *high-water
# mark* rather than a running sum with a special case bolted on. Two properties
# of writing it that way are worth stating, because both are what make it safe
# to apply everywhere:
#
#   * **on a host that never steps it is the identity**, and on a host that
#     steps it is the old sum digit for digit everywhere outside a hole.
#     Nothing about an ordinary take changes — which is also why nothing about
#     an ordinary take can grade it, and why every case for it is synthetic.
#   * **it composes.** Overlapping holes — a second step landing inside the
#     first one's window — fall out of the maximum with no rule of their own,
#     which a per-step special case would have had to get right by hand.
#
# What it deliberately does **not** do is second-guess the size of the step:
# the hole is Δ wide because the record says the step was Δ. Three of six
# stepping takes in #255 showed the video moving by less than the recorded
# amount, and that is issue #259 — a question about whether the record
# describes the world, which no arithmetic here can answer.


class Placed(NamedTuple):
    """Where a beat-log instant is in the video, and whether it is there at all.

    `at` is the instant in `media`, already clamped to the last instant the
    file has if this one falls inside a hole. `lost` is how many seconds of
    the correction that clamp swallowed: **zero for an instant with video**,
    and for one without, the distance from here to where the file starts
    again — which is also how far too early the uncorrected rule would have
    put it. A consumer that publishes `at` without saying `lost` is back to
    presenting a beat with no video as a frame at its midpoint.
    """

    at: float
    lost: float


def _placed(steps: list[tuple[float, float]], t: float) -> Placed:
    """`t` on the video's clock, given one capture's steps. See above.

    The video's clock is the high-water mark of the host's wall clock, because
    the encoder will not write a frame stamp it has already written: the file
    stalls for the width of a backward step instead of rewinding.
    """
    running = 0.0
    # The furthest the file had got before any step at or before `t` — the
    # edge a hole clamps to. `-inf` rather than 0.0 so that a capture with no
    # steps is the identity rather than a floor at its own start.
    edge = -math.inf
    for at, delta in sorted(steps):
        if at > t:
            break
        edge = max(edge, at + running)
        running += delta
    shifted = t + running
    # `max`, so an instant with video returns `shifted` *itself* and `lost` is
    # exactly 0.0 rather than a rounding of it.
    reached = max(shifted, edge)
    return Placed(reached, reached - shifted)


def _usable_steps(doc: dict, record: dict) -> list[dict] | None:
    """`record`'s steps, or None if this record cannot honestly correct a beat.

    Refuses rather than corrects by part of a record. A step missing its `t`
    or its `delta` would silently drop out of every sum, and a merged record
    whose steps have lost the `segment` they were measured in matches no beat
    at all — both leave the arithmetic looking applied while it corrects
    nothing, which is worse than declining out loud.
    """
    listed = record.get("steps")
    if not isinstance(listed, list):
        return None
    # Which captures a step is allowed to name, read off the document rather
    # than assumed: the segments of a merged demo, and *no segment at all* on a
    # take recorded in one piece, whose beats carry none either. Both
    # directions matter — a merged step with no `segment` and a single take's
    # step that has one both match no beat, so they would correct nothing while
    # the sheet reported a correction.
    #
    # **Stated limit, and pre-existing**: this is inexact for one document
    # shape it never sees — a single *segment*'s own timeline, whose beats do
    # carry a segment while its steps do not, so `{None}` accepts every step
    # and `correct` then matches no beat. Nothing reaches it: `beat_frames`
    # returns `skipped` for a document with a `segment` before it asks for a
    # correction at all, and `stitch()` re-derives the merged record from the
    # parts rather than reading one part's. Written down so the next reader
    # does not have to re-derive that.
    named = {s.get("segment") for s in doc.get("segments") or [] if isinstance(s, dict)}
    allowed = named or {None}
    steps = []
    for step in listed:
        if not isinstance(step, dict):
            return None
        at, delta = step.get("t"), step.get("delta")
        for value in (at, delta):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
        if step.get("segment") not in allowed:
            return None
        steps.append(step)
    return steps


def _no_correction(beat: dict, t: float) -> Placed:
    """The placement for a record that cannot supply one. `t`, and stated.

    `lost` is 0.0 rather than null, and that is not a claim that this instant
    has video: a record nobody could read says nothing about holes either.
    `state.applied` is what carries "nothing here knows", and every consumer
    prints it — a second null to mean the same thing would be a second thing
    to forget.
    """
    return Placed(float(t), 0.0)


def capture_clock_correction(
    doc: dict,
) -> tuple[Callable[[dict, float], Placed], dict]:
    """(place, state) — where each instant of `doc` is in the video.

    `place(beat, t)` puts the beat-log instant `t`, taken from `beat`, at the
    same moment in `media`, using the steps of that beat's **own capture** up
    to **`t` itself** — never the running total and never an earlier part's,
    whose loss is already in the merged offsets (see `_merge_capture_clock`).
    On a take recorded in one piece neither the steps nor the beats name a
    segment, and the same rule is then the whole list.

    **`t` and not the beat**, because a caller converting a beat's midpoint and
    one converting its start are asking different questions whenever a step
    landed between the two — see the note above this function.

    It returns a `Placed`, not a number of seconds, because an instant a
    backward step deleted from the file has no honest number: `at` is then the
    last instant the file has and `lost` says how much of the correction that
    clamp swallowed. A caller that reads `at` alone is publishing a frame at a
    moment the video does not contain (issue #256).

    `state` is what the artifact says about the correction — `applied`,
    `total`, `steps` (how many the record carries) and `note` (why not, when
    `applied` is false). It exists so a document cannot show a corrected
    timestamp without being able to say whether a correction was possible.
    """
    record = doc.get("capture_clock")
    if not isinstance(record, dict):
        return _no_correction, {
            "applied": False,
            "total": None,
            "steps": 0,
            "note": (
                "this timeline carries no capture_clock, so nothing here knows "
                "whether the host's wall clock moved under the beat log"
            ),
        }
    if record.get("measured") is not True:
        return _no_correction, {
            "applied": False,
            "total": None,
            "steps": 0,
            "note": record.get("note")
            or (
                "the take's wall clock was not measured, so nothing here knows "
                "whether it moved under the beat log"
            ),
        }
    steps = _usable_steps(doc, record)
    if steps is None:
        return _no_correction, {
            "applied": False,
            "total": None,
            "steps": 0,
            "note": (
                "this timeline's capture_clock says it was measured, but its "
                "steps are not in the shape this reader can attribute to a "
                "beat — correcting by part of a record would look applied "
                "while correcting nothing"
            ),
        }

    def place(beat: dict, t: float) -> Placed:
        return _placed(
            [
                (float(step["t"]), float(step["delta"]))
                for step in steps
                if step.get("segment") == beat.get("segment")
            ],
            float(t),
        )

    return place, {
        "applied": True,
        # Totalled from the steps that were **used**, not copied out of the
        # record's own `total`. The two can disagree — `tests/smoke` has an
        # injection for exactly that — and this number's job is to describe
        # the correction that was applied, not to repeat a claim about it.
        "total": round(sum(float(step["delta"]) for step in steps), 4),
        "steps": len(steps),
        "note": None,
    }


def capture_clock_shift(record: object) -> tuple[Callable[[float], Placed], dict]:
    """(place, state) for a capture that is still the only one there is.

    `capture_clock_correction` above reads a finished timeline, where a step is
    attributed to the segment it was measured in and a beat is matched against
    it. A take mixing its **own** audio has no such question to answer: one
    capture is running, every step in the record is that capture's, and the
    steps do not name a segment until `stitch()` gives them one. So the rule
    collapses to "how far had the wall clock stepped by `t`", and it is read
    through the same function rather than re-derived — the two must not be able
    to drift apart, because `frames/` and the audio track of the same demo have
    to describe the same video.

    `place(t)` puts the beat-log instant `t` in the video, as a `Placed`;
    `state` is the same three-state record `capture_clock_correction` returns,
    and the caller is expected to put it in an artifact rather than swallow it.
    """
    correct, state = capture_clock_correction({"capture_clock": record})

    def place(t: float) -> Placed:
        # The empty beat is the point: a single capture's steps carry no
        # segment and neither does this, so every step in the record is this
        # instant's to be corrected by.
        return correct({}, t)

    return place, state


def _capture_clock_md(state: dict) -> list[str]:
    """What `timeline.md` says about the clock its own timestamps are on.

    Silent on the ordinary take — a measured clock that held still is what the
    reader already assumes, and a line on every timeline is a line nobody
    reads. It speaks in the two cases where the assumption is wrong: the clock
    stepped, or nobody watched it.
    """
    if not state.get("applied"):
        return [
            f"**The clock this take's video is on was not measured.** "
            f"{state.get('note')}. The times below are `time.monotonic()` and "
            f"the recording is on the host's wall clock, so if the two parted "
            f"company while this was recording, nothing in this file can say "
            f"by how much.",
            "",
        ]
    # On the **count**, never on the total: two steps that cancel total zero
    # and still part the two clocks for everything recorded between them.
    if not state.get("steps"):
        return []
    return [
        f"**The host's wall clock stepped {state.get('steps')} time(s) while "
        f"this was recorded** ({state.get('total') or 0.0:+.2f}s in total). The "
        f"times below are `time.monotonic()`; the recording is on that wall "
        f"clock, so an instant this table puts at `t` sits at `t` plus the "
        f"steps its own capture recorded before `t` — not at `t`, and not at "
        f"`t` plus the total above, which is the correction for no single row. "
        f"`timeline.json`'s `capture_clock` carries every step and the capture "
        f"it was measured in; `frames/frames.md` says whether the review "
        f"frames were cut with it applied.",
        "",
    ]


def _overlaps_md(overlaps: object) -> list[str]:
    """What `timeline.md` says when its own beat table runs backwards (#263).

    Silent on every take that has none, and on every take recorded in one
    piece, which carries no such field at all. It speaks where a reader would
    otherwise scroll past a row starting before the row above it ended and
    conclude the log is corrupt — or, worse, not notice.

    `stitch()` publishes the list; this only renders it. The sentence a reader
    needs is the second one: whether the frames are in order even though the
    column is not — and, when an endpoint sits in a hole a backward step
    deleted, that "in order" is **not** the same as "the frames are fine",
    because one of the two beats has no frame at all (issue #256).

    The count in the header is of the rows this actually prints, not of the
    list handed in: a hand-edited `timeline.json` can carry an entry this
    cannot render, and a header that counted those would disagree with the
    bullets under it in the one document whose job is to be read.
    """
    listed = overlaps if isinstance(overlaps, list) else []
    rows = [entry for entry in listed if isinstance(entry, dict)]
    if not rows:
        return []
    out = [
        f"**This stitched beat log is not monotonic**: "
        f"{len(rows)} beat(s) below start before the beat before them "
        f"ended. Nothing was moved to hide it — a merged timestamp is the "
        f"part's own `time.monotonic()` log plus that part's `offset`, and "
        f"the offset is the part's real ffprobe **duration**, which is on the "
        f"wall clock the encoder stamped. A part whose host clock stepped "
        f"backwards has a video shorter than its own beat log by the size of "
        f"the step, so its last beats run past where the next part begins "
        f"(issue #263). `timeline.json`'s `overlaps` carries the same list.",
        "",
    ]
    for overlap in rows:
        where = "at the seam" if overlap.get("seam") else "inside one segment"
        video = overlap.get("video_overlap")
        # Which of the two endpoints, if either, the step deleted from the
        # file. Named by beat, because "one of these has no frame" is not
        # something a reader can act on.
        deleted = [
            (f"beat {_md_cell(overlap.get(beat))}", float(overlap.get(key) or 0.0))
            for beat, key in (
                ("previous_beat", "previous_no_video"),
                ("beat", "no_video"),
            )
            if isinstance(overlap.get(key), (int, float))
            and not isinstance(overlap.get(key), bool)
            and overlap.get(key)
        ]
        if not isinstance(video, (int, float)) or isinstance(video, bool):
            verdict = (
                "nothing here can say whether the video puts them in order: "
                "this demo carries no `capture_clock` a reader could correct "
                "them with"
            )
        elif video <= 0 and deleted:
            # In order, and still not fine: `at` for a deleted instant is the
            # last moment the file has, not where that instant is. Saying only
            # the first half is the #256 defect in a new artifact.
            verdict = (
                f"corrected by each capture's own steps they are "
                f"{abs(float(video)):.3f}s apart and **in order** — but the "
                f"file has no frame for "
                + ", ".join(
                    f"{name} at all, the video resuming {gap * 1000:.0f} ms later"
                    for name, gap in deleted
                )
                + " (issue #256), so this is not a demo whose frames are all "
                "there"
            )
        elif video <= 0:
            verdict = (
                f"corrected by each capture's own steps they are "
                f"{abs(float(video)):.3f}s apart and **in order** — the frames "
                f"are fine and it is the log's column that runs backwards"
            )
        else:
            verdict = (
                f"corrected by each capture's own steps they **still** overlap "
                f"by {float(video):.3f}s, which the recorded steps do not "
                f"explain"
            )
        out.append(
            f"- beat {_md_cell(overlap.get('previous_beat'))} → "
            f"{_md_cell(overlap.get('beat'))} "
            f"(`{_md_cell(overlap.get('previous_segment'))}` → "
            f"`{_md_cell(overlap.get('segment'))}`, {where}) overlap by "
            f"**{float(overlap.get('overlap') or 0.0):.3f}s**; {verdict}."
        )
    out.append("")
    return out


def _narration_md(narration: object) -> list[str]:
    """What `timeline.md` says about where the spoken lines ended up.

    Same shape of statement as `_capture_clock_md`, and silent for the same
    reason on the same take: a watched clock that held still put every line
    exactly where the log says, and a line on every timeline is a line nobody
    reads. It speaks in the two cases where that is not what happened — the
    clock stepped and the mix followed it, or nobody watched and the mix could
    only use the raw offset. The second is the one that matters here: the audio
    is *audible* evidence, and a listener who hears the voice drift away from
    the caption has no other way to find out that nothing knew by how much.

    Two qualifications are printed rather than left to be inferred, because
    both make the headline sentence false for *some* of the lines and a reader
    correcting by hand would be corrected twice:

      * a line whose correction hit the zero floor (`clamped`) did not move by
        the steps before it — it moved by as much of them as the start of the
        file left room for. Unreachable from a record this recorder writes
        since #256, and kept for one that came from elsewhere;
      * a line the clock stepped *over* (`no_video`) was spoken during wall
        time the file does not contain, so its clip sits at the last moment
        before the gap and not where the steps put it (issue #256);
      * on a stitched demo where only some narrating parts could correct, the
        refusal is stated as **k of m segments** rather than as the whole demo.
    """
    if not isinstance(narration, dict):
        return []
    lines = narration.get("lines") or []
    # `clock` rather than `state`, which is what `_capture_clock_md` above
    # calls its own: two identical guard lines in one file are two lines a
    # fault injection cannot tell apart, and the harness refuses an anchor
    # that matches twice rather than proving the wrong one.
    clock = narration.get("clock_correction")
    if not lines or not isinstance(clock, dict):
        return []
    if not clock.get("applied"):
        # A merged record knows how much of the demo it is talking about; a
        # single take's is the whole of it. Saying "the 3 spoken lines were
        # mixed uncorrected" over a demo where two of them were is pessimistic
        # rather than dangerous, but it is still not what happened.
        refused, parts = clock.get("parts_uncorrected"), clock.get("parts")
        whose = (
            f"the lines of {refused} of this demo's {parts} narrated segment(s)"
            if refused and parts
            else f"the {len(lines)} spoken line(s)"
        )
        return [
            f"**{whose[0].upper()}{whose[1:]} were mixed at their beat-log "
            f"offsets, uncorrected**: {clock.get('note')}. The audio sits "
            f"inside the video and therefore on the video's clock, so if the "
            f"host's wall clock stepped while this was recording the voice is "
            f"that far from the caption it belongs to — and nothing here knows "
            f"whether it did.",
            "",
        ]
    # On the count, never the total — two steps that cancel move every line
    # mixed between them. Same argument as `_capture_clock_md`.
    if not clock.get("steps"):
        return []
    # ...and the lines the floor caught, which the sentence below is otherwise
    # untrue for. Reachable only here: an uncorrected mix shifts nothing, so
    # nothing it produces can go negative.
    clamped = [line for line in lines if line.get("clamped")]
    # **"the start of its own capture", never "0.0".** A single take's capture
    # starts at the top of the file and the two read the same; a stitched
    # part's starts at that part's `offset`, and a clamped line of part two has
    # an `at` of 7.5 rather than of zero. Saying 0.0 there is a published
    # artifact stating a second the clip is not at, on exactly the host this
    # correction exists for.
    tail = (
        f" **{len(clamped)} of them could not be moved the whole way**: the "
        f"steps before that line were larger than the line's own offset into "
        f"its capture, so the wall time it occupied is not in the video at all "
        f"and `adelay` cannot express a negative delay. Those clips start where "
        f"their own capture does — the top of the file on a take recorded in "
        f"one piece, that part's `offset` on a stitched demo — and `clamped` is "
        f"how many seconds of the correction that boundary swallowed."
        if clamped
        else ""
    )
    # ...and the lines that were spoken over wall time the file does not have.
    # A different sentence from `clamped` and never folded into it: that one is
    # a line the *start of the file* caught, this one is a line the host's
    # clock deleted the moment of. Both make the headline sentence false, for
    # different reasons a listener would chase differently.
    holed = [line for line in lines if line.get("no_video")]
    tail += (
        f" **{len(holed)} of them {'was' if len(holed) == 1 else 'were'} spoken "
        f"over wall time that is not in the video at all**: a backward step "
        f"takes its own width out of the file rather than moving it, so there "
        f"is no moment in `media` for "
        f"{'that line' if len(holed) == 1 else 'those lines'} to be at. "
        f"{'Its' if len(holed) == 1 else 'Their'} clip starts at the last "
        f"moment before the gap, and `no_video` is how many seconds later the "
        f"video resumes (issue #256)."
        if holed
        else ""
    )
    return [
        f"**The {len(lines)} spoken line(s) were mixed where the host's "
        f"stepped clock puts them in the video**, not at the beat-log offsets "
        f"in the table below: each line's `at` in `timeline.json`'s "
        f"`narration` is its `t` plus the steps its own capture recorded "
        f"before that instant. Without it the voice would trail the caption "
        f"by the size of the step for the rest of the take (issue #226).{tail}",
        "",
    ]


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
    # Directly above the beat table, because it is a statement about the
    # numbers in it: a reader who has scrolled past the table has already read
    # the timestamps as the video's, which is the misreading this says out
    # loud. The recorder warns about the same thing on stderr, minutes and
    # several thousand lines before anybody opens this file (issue #229).
    out += _capture_clock_md(capture_clock_correction(doc)[1])
    # Directly under it, because it is the same statement about a different
    # artifact: the row's timestamp is on the beat log, and so was the audio
    # until the mix corrected it. Read off `narration` rather than recomputed
    # from `capture_clock` — what belongs here is what the mix *did*, and a
    # paragraph derived from the record would keep claiming a correction if
    # the mix ever stopped applying one.
    out += _narration_md(doc.get("narration"))
    # Last before the table, because it is the sharpest statement about it: a
    # reader who meets a row starting before the row above it ended without
    # this paragraph concludes the log is corrupt, and one who does not meet it
    # at all reads a number that is not where that beat is (issue #263).
    out += _overlaps_md(doc.get("overlaps"))
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
            f"requests, non-zero exit codes, and captions a page load took "
            f"off the screen, each attributed to the beat it fired during. A "
            f"demo can look perfect and still be a recording of a broken app.",
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
