"""Joining segment recordings into one demo, losslessly.

`stitch()` concatenates the parts and merges their beat logs, moving each
segment's beats by the real duration of the parts before it. It refuses before
it encodes anything if the parts cannot honestly be joined — `concat -c copy`
accepts a frame-rate mismatch, a resolution mismatch and a silent part, exits
0, and the damage is invisible afterwards.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .content import _common, media_duration, merge_content, print_content_summary
from .coverage import _merged_coverage, _merged_ticket_fields, _ticket_field
from .frames import write_beat_frames
from .timeline import (
    MAX_ISSUES,
    TIMELINE_SCHEMA,
    capture_clock_correction,
    timeline_paths,
    write_timeline,
)


def _shift(value: object, offset: float) -> float | None:
    """A timestamp moved `offset` seconds later, or None if there wasn't one."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(float(value) + offset, 3)


def _merge_determinism(records: list[dict]) -> dict:
    """The determinism record of a merged demo, key by key.

    A value every segment agrees on is that value; anything they disagree on
    becomes null, because there is no honest single answer and the per-segment
    records are right there in `segments`. Silently taking the first segment's
    would say a demo was recorded on a frozen clock when half of it was not.
    """
    order: list[str] = []
    for record in records:
        for key in record or {}:
            if key not in order:
                order.append(key)
    return {
        key: _common([(record or {}).get(key) for record in records]) for key in order
    }


def _merge_capture_clock(docs: list[dict], records: list[dict]) -> dict | None:
    """Every part's wall-clock steps, moved onto the stitched video's clock.

    Chromium stamps each screencast frame with the host's *wall* clock while
    the beat log is `time.monotonic()`, so a host that steps its clock parts
    the two by the size of the step (issues #18, #215). Each take records its
    own steps as `capture_clock`; those files are removed by the merge, so
    without this a reader of a stitched `demo.mp4` has a beat log on one clock,
    a video on another, and nothing to reconcile them with (issue #225).

    Two things make the merged record usable, and both are about **which steps
    apply to which beats**:

    * every step carries the `segment` it was measured in, and that is the
      attribution to trust. A step is sampled for as long as the capture runs,
      which is longer than the video it produced — losing wall time is the
      whole phenomenon — so a step's merged `t` can legitimately fall past the
      next part's `offset`, and a reader keying on time alone would hand it to
      the wrong capture.
    * `boundaries` records where each capture starts on the stitched clock.

    The correction for one beat is therefore the steps of **its own** segment
    up to its own `t_start`, never the running total: each capture's first
    frame restarts its clock, and `_merged_timeline` already lays the parts out
    by their measured durations, so a step in an earlier part is *already* in
    the later parts' offsets. Adding it again would over-correct by a whole
    step.

    Returns **null** unless every part carries a well-formed record. A merge
    that quietly treated a missing one as "the clock held still" would state,
    in an artifact somebody corrects timestamps with, that a part nobody
    measured was measured — and `total` would be short by whatever it stepped.

    **A part whose own record says `measured: false` is exactly that case**,
    and it is the one that looks harmless: its `steps` is a well-formed empty
    list, so a merge that only checked the shape would fold "nobody watched
    this part" into a stitched record indistinguishable from "this part's
    clock held still" (issue #247).
    """
    steps: list[dict] = []
    for doc, record in zip(docs, records, strict=True):
        clock = doc.get("capture_clock")
        if not isinstance(clock, dict) or clock.get("measured") is not True:
            return None
        listed = clock.get("steps")
        if not isinstance(listed, list):
            return None
        for step in listed:
            if not isinstance(step, dict):
                return None
            at = _shift(step.get("t"), record["offset"])
            delta = step.get("delta")
            unusable = (
                at is None
                or not isinstance(delta, (int, float))
                or isinstance(delta, bool)
            )
            if unusable:
                return None
            steps.append(
                {**step, "t": at, "delta": float(delta), "segment": record["segment"]}
            )
    clocks = [doc.get("capture_clock") or {} for doc in docs]
    gaps = [c.get("max_gap") for c in clocks]
    return {
        # True by construction: every part was checked above, and a merge is
        # refused outright when any of them was not measured.
        "measured": True,
        "note": None,
        "steps": steps,
        # The sum across the whole recording session, which is **not** the
        # correction for any single beat — see above. It is here because a
        # non-zero total is what tells a reader to look at `steps` at all.
        "total": round(sum(step["delta"] for step in steps), 4),
        "sample_interval": _common([c.get("sample_interval") for c in clocks]),
        "min_step": _common([c.get("min_step") for c in clocks]),
        # The worst coverage any part managed, not an average: a stitched
        # record is only as believable as its shakiest capture.
        "max_gap": max(
            (
                g
                for g in gaps
                if isinstance(g, (int, float)) and not isinstance(g, bool)
            ),
            default=None,
        ),
        "max_gap_limit": _common([c.get("max_gap_limit") for c in clocks]),
        "boundaries": [record["offset"] for record in records],
    }


def _merge_narration(docs: list[dict], records: list[dict]) -> dict | None:
    """Every part's spoken lines, moved onto the stitched video's clock.

    Each part mixed its own audio into its own `.seg.mp4` at its own capture's
    corrected offsets (issue #226), and `concat -c copy` lays those tracks
    end to end at the parts' measured durations — so a line's place in the
    joined video is its place in its part plus that part's `offset`, the same
    arithmetic the beats get. `segment` is carried per line for the same reason
    a step carries one: it is the attribution to trust when a reader asks which
    capture's clock a number is on.

    Returns **null** when no part narrated, which is what a single take that
    narrated nothing says too. A part that narrated nothing is simply absent
    from `lines` — it contributed no audio, so its clock has nothing to say
    about this field, and folding its state in would let a silent segment
    refuse a correction two narrated ones really applied.
    """
    lines: list[dict] = []
    refused: list[str] = []
    note: str | None = None
    steps = 0
    total = 0.0
    narrating = 0
    for doc, record in zip(docs, records, strict=True):
        narration = doc.get("narration")
        if not isinstance(narration, dict):
            continue
        narrating += 1
        for line in narration.get("lines") or []:
            lines.append(
                {
                    **line,
                    "t": _shift(line.get("t"), record["offset"]),
                    "at": _shift(line.get("at"), record["offset"]),
                    "segment": record["segment"],
                }
            )
        state = narration.get("clock_correction")
        state = state if isinstance(state, dict) else {}
        if state.get("applied"):
            steps += int(state.get("steps") or 0)
            total += float(state.get("total") or 0.0)
        else:
            refused.append(str(record["segment"]))
            note = note or state.get("note")
    if not narrating:
        return None
    applied = not refused
    return {
        "lines": lines,
        "clock_correction": {
            # False the moment **any** narrating part could not correct its own
            # mix: the demo a listener plays is one file, and one part's voice
            # drifting off its captions is not made right by the others.
            "applied": applied,
            "total": round(total, 4) if applied else None,
            "steps": steps if applied else 0,
            # ...but *how much* of the demo that is, said rather than left to
            # the reader. The flag above is all-or-nothing on purpose; without
            # these two `timeline.md` prints "the 3 spoken lines were mixed
            # uncorrected" over a demo where two of them were corrected, which
            # is pessimistic and still not what happened. Absent from a single
            # take's record, which has no parts to count.
            "parts": narrating,
            "parts_uncorrected": len(refused),
            "note": None
            if applied
            else (
                f"{', '.join(refused)} mixed its narration at the beat-log "
                f"offsets, uncorrected" + (f" — {note}" if note else "")
            ),
        },
    }


# How far a segment's recorded `duration` may sit from what its .seg.mp4
# measures now. The recorder probed the same file with the same tool moments
# after writing it, so anything past this is not rounding — it is a log paired
# with a *different* recording of that segment (see _segment_timeline).
SEGMENT_STALE_S = 0.25


def _segment_timeline(out_dir: Path, segment: str, media: Path, probed: float) -> dict:
    """One segment's timeline document, checked against the media beside it.

    Refuses rather than guesses. A segment timeline that is missing, written
    to a different schema, or describing a different recording is not
    something a merge can quietly work around: the result would be a demo-wide
    timeline whose beats belong to a video nobody has, which is exactly the
    failure #7 exists to remove.

    The check that does the work here is the **duration** one. The `media`
    name is derived from the same segment string as the path this was loaded
    from, so those two can only disagree if somebody hand-edited the file —
    whereas re-recording one segment and merging it against the previous
    take's log is an ordinary Tuesday, produces a name that matches perfectly,
    and is precisely the stale pairing that would date-stamp the wrong beats
    onto this demo.
    """
    json_path, _ = timeline_paths(out_dir, segment)
    if not json_path.is_file():
        raise FileNotFoundError(
            f"{json_path} — segment {segment!r} has an mp4 but no beat log, so "
            f"its beats cannot be merged into the demo's timeline. Re-record "
            f"the segment (a clean take always writes one); note that a "
            f"previous stitch() deletes the segment logs unless it was passed "
            f"keep_parts=True."
        )
    doc = json.loads(json_path.read_text())
    if doc.get("schema") != TIMELINE_SCHEMA:
        raise ValueError(
            f"{json_path} is schema {doc.get('schema')!r}, but this package "
            f"writes and merges schema {TIMELINE_SCHEMA!r} — re-record the "
            f"segment rather than merging a document this code does not know "
            f"the shape of"
        )
    if doc.get("mode") == "stills":
        raise ValueError(
            f"{json_path} is a stills-only run, not a segment (issue #372): "
            f"it recorded no video, so there is nothing of it to join onto "
            f"this demo. Re-record segment {segment!r} without stills_only."
        )
    if doc.get("media") != media.name:
        raise ValueError(
            f"{json_path} describes {doc.get('media')!r}, not {media.name!r} — "
            f"it is a leftover from a different take, and merging it would "
            f"stamp somebody else's beats onto this demo"
        )
    logged = doc.get("duration")
    if (
        isinstance(logged, (int, float))
        and abs(float(logged) - probed) > SEGMENT_STALE_S
    ):
        raise ValueError(
            f"{json_path} was written for a {float(logged):.2f}s recording, but "
            f"{media.name} is {probed:.2f}s — the log and the video are from "
            f"different takes of segment {segment!r}. Re-record the segment, or "
            f"delete the stale log: merging them would put this demo's beats at "
            f"timestamps belonging to a video that no longer exists."
        )
    return doc


# What every part must agree on before `concat -c copy` may join them. All of
# these are silent failures rather than loud ones, which is why they are
# checked here instead of being left to ffmpeg:
#
#   frame rate  a mismatch is accepted, ffmpeg exits 0, and the joined video
#               runs at one part's rate — measured putting a beat 1.92 s from
#               its frame, which is the merge's whole subject matter;
#   geometry    accepted silently, and the output keeps the first part's
#               dimensions, so the second is stretched or cropped. Reachable
#               through the very demo the merged envelope's "mixed" recorder
#               value exists for: a web segment and a terminal one;
#   audio       a silent part followed by a narrated one makes concat drop the
#               narration *entirely*. The recorders give every segment a track
#               (silence when there are no lines) for this reason, so a part
#               without one did not come from here.
#
# None of it is reachable through the shipped recorders, which pin -r 25, one
# viewport and an audio track per segment. Nothing enforced that at the join.
_STREAM_FIELDS = ("codec", "width", "height", "frame rate", "audio track")


def _stream_shape(path: Path) -> tuple:
    """(codec, width, height, r_frame_rate, has audio) for one part."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    video = tuple(out.stdout.strip().split(","))
    audio = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return (*video, bool(audio.stdout.strip()))


def _check_stream_shapes(parts: list[Path]) -> None:
    """Refuse to concat parts that differ in anything concat cannot fix."""
    shapes = [_stream_shape(p) for p in parts]
    for shape, part in zip(shapes[1:], parts[1:], strict=True):
        if shape == shapes[0]:
            continue
        differing = ", ".join(
            f"{name} {a!r} vs {b!r}"
            for name, a, b in zip(_STREAM_FIELDS, shapes[0], shape, strict=False)
            if a != b
        )
        raise ValueError(
            f"{part.name} does not match {parts[0].name}: {differing}. "
            f"`concat -c copy` joins these without complaint and the result is "
            f"wrong in a way nothing downstream can see — a frame-rate mismatch "
            f"moves every beat of the later segments away from its frame, a "
            f"geometry mismatch keeps the first part's dimensions, and a part "
            f"with no audio track makes concat drop every later part's "
            f"narration. Re-record the segments with the same recorder settings."
        )


# How far a merged beat may start before the previous one ended without being
# called an overlap. **This is `tests/smoke`'s `BEAT_ORDER_SLACK_S`, and the two
# have to stay equal**: that is the bar the suite grades a stitched log's
# monotonicity against, so a tighter number here prints "this stitched beat log
# is not monotonic" over a take the suite calls healthy, and a wider one stays
# quiet about a log the suite fails. Measured at 0.4 ms and 0.6 ms seams either
# side of it. `MergeOverlap.test_the_slack_here_is_the_slack_the_suite_grades`
# in tests/unit is what keeps them equal; a check that cries wolf is a check
# that gets ignored, and then it protects nothing.
MERGE_OVERLAP_SLACK_S = 0.005


def _merge_overlaps(doc: dict) -> list[dict]:
    """Where a stitched beat log runs backwards, and what the video's clock says.

    **The merge lays the parts out on two different clocks and the seam is where
    they meet** (issue #263). Each part's beats keep their own
    `time.monotonic()` timestamps; the offset that moves them is the part's real
    **ffprobe duration**, which is on the wall clock the encoder stamped. Those
    agree until a part's host clock steps backwards — a step of −Δ deletes Δ of
    wall time from that part's video without taking a millisecond out of its
    beat log, so the part's log outruns its own file and the next part's first
    beat is offset to a moment the previous part's last beat has not reached
    yet. Reproduced at −1.4684 s: `beat 21 t_end 37.451`, `beat 22 t_start
    37.441` — a 10 ms overlap out of a 1.4684 s step, 0.7% of it, and the only
    measurement of the size there is. Do not derive an expected overlap from Δ;
    one point fixes no relationship.

    **Reported, not clamped, and that is the decision here.** Moving the beats
    to make the numbers rise would put them at instants neither the log nor the
    video has: the merged timestamp of a beat is exactly its own log's plus its
    own part's offset, and every consumer that corrects a beat by its own
    capture's steps (see `_merge_capture_clock`) depends on that identity. A
    clamp would buy a monotonic column by making the column mean nothing. So the
    overlap is published instead, with the one thing a reader actually needs:

    `video_overlap` is the same difference **after** putting both instants on
    the video's clock by the documented rule — each corrected by the steps of
    its own capture. Zero or below means the two frames really are in order and
    only the log's column runs backwards, which is the mechanism above and is
    not a defect in the file a reviewer scrubs. Above zero means the recorded
    steps do not account for it and something else moved the beats. **Null**
    when no correction was possible at all, which is not the same answer as
    zero and must not read like one.

    `no_video` and `previous_no_video` carry the other half of each `Placed`,
    and they are not decoration: an endpoint inside a hole has **no frame at
    all**, and `at` for it is the last instant the file has rather than where
    that instant is. Publishing `video_overlap` alone would let a reader be
    told the two beats are in order — which is true — beside a claim that the
    frames are fine, which is false for a beat the step deleted. That is
    exactly the defect `Placed.lost` exists to prevent (issue #256), and a
    conservative direction does not make a false sentence acceptable.

    Every adjacent pair is compared, not only the pairs at a seam, because
    "this stitched log is monotonic" is a claim about the whole list — `seam`
    says which kind each one is, since only the seams are this merge's
    arithmetic. **`seam` is read off the parts' beat counts, not off the two
    beats' `segment` strings**: nothing stops `stitch()` being handed one
    segment name twice (`tests/smoke` treats "merged segment one twice" as a
    real failure mode), and a genuine seam reported as "inside one segment"
    sends the reader to the wrong file.

    Empty on a healthy merge: the list is the merge saying it looked. The bar
    is `MERGE_OVERLAP_SLACK_S`, which is the suite's own.
    """
    place, state = capture_clock_correction(doc)
    beats = doc.get("beats") or []
    # Where each part's first beat lands in the merged list, by running total
    # of the parts' own beat counts. Independent of what the parts are called.
    seams: set[int] = set()
    at = 0
    for record in doc.get("segments") or []:
        at += int((record or {}).get("beats") or 0)
        seams.add(at)
    found: list[dict] = []
    for before, after in zip(beats, beats[1:], strict=False):
        ends = _shift(before.get("t_end"), 0.0)
        starts = _shift(after.get("t_start"), 0.0)
        if ends is None or starts is None:
            continue
        overlap = round(ends - starts, 3)
        if overlap <= MERGE_OVERLAP_SLACK_S:
            continue
        placed_before = place(before, ends) if state.get("applied") else None
        placed_after = place(after, starts) if state.get("applied") else None
        found.append(
            {
                "beat": after.get("index"),
                "previous_beat": before.get("index"),
                "segment": after.get("segment"),
                "previous_segment": before.get("segment"),
                "seam": after.get("index") in seams,
                "overlap": overlap,
                "video_overlap": round(placed_before.at - placed_after.at, 3)
                if placed_before is not None and placed_after is not None
                else None,
                "previous_no_video": round(placed_before.lost, 3)
                if placed_before is not None
                else None,
                "no_video": round(placed_after.lost, 3)
                if placed_after is not None
                else None,
            }
        )
    return found


def _merged_timeline(
    segments: list[str],
    parts: list[Path],
    docs: list[dict],
    durations: list[float],
    demo: Path,
) -> dict:
    """One timeline for a stitched demo, built from its segments'.

    Each segment's beats are offset by the **real duration of the segments
    before it**, read off the encoded `.seg.mp4` with ffprobe rather than
    summed from the storyboard's nominal pacing. The encoder's answer is the
    only one that matches the file a reviewer scrubs: Chromium's screencast
    drops wall time during idle stretches (issue #18), so a segment's video is
    routinely shorter than the time its beats say it took. Nominal timing would
    put every beat of every later segment progressively past its frame.

    The consequence worth knowing: a stall *inside* a segment still skews that
    segment's own late beats against its own video, and the merge inherits it —
    but it cannot leak across a boundary, because the next segment's offset is
    measured, not accumulated from beats.
    """
    beats: list[dict] = []
    issues: list[dict] = []
    records: list[dict] = []
    offset = 0.0
    issue_count = 0
    strict = True
    for segment, part, doc, probed in zip(
        segments, parts, docs, durations, strict=True
    ):
        duration = round(probed, 3)
        base = len(beats)
        for beat in doc.get("beats") or []:
            merged = dict(beat)
            # `index` is documented as the position in *this* file, and
            # timeline.md's table, every "beat N" message and any positional
            # consumer read it that way — so it is renumbered. What that would
            # destroy, `segment_index` keeps: the pair (segment, segment_index)
            # names the same beat before and after the merge. See issue #22.
            merged["segment_index"] = beat.get("segment_index", beat.get("index"))
            merged["index"] = len(beats)
            merged["t_start"] = _shift(beat.get("t_start"), offset)
            merged["t_end"] = _shift(beat.get("t_end"), offset)
            # A wrapper segment's hold-clear instant is a video offset like
            # the two above, and the merged sheet's opening-hold note reads
            # it (frames.py) — left unshifted it would name part one's
            # frames as under part two's hold.
            if "opening_hold_until" in merged:
                merged["opening_hold_until"] = _shift(
                    beat.get("opening_hold_until"), offset
                )
            beats.append(merged)
        for issue in doc.get("issues") or []:
            moved = dict(issue)
            moved["t"] = _shift(issue.get("t"), offset)
            # `beat` indexes the segment's own beat list; re-point it at the
            # merged one, or an issue arrives attributed to whatever beat of
            # segment one happens to sit at that index.
            if isinstance(issue.get("beat"), int) and not isinstance(
                issue.get("beat"), bool
            ):
                moved["beat"] = base + int(issue["beat"])
            issues.append(moved)
        issue_count += int(doc.get("issue_count") or 0)
        strict = strict and bool(doc.get("strict"))
        records.append(
            {
                "segment": segment,
                "media": part.name,
                "duration": duration,
                "offset": round(offset, 3),
                "beats": len(doc.get("beats") or []),
                # This part's own ticket, absent when it named none — so a
                # merged demo whose parts disagree can be read back to the
                # segment that said each thing, rather than only to the list of
                # what was said (issue #275).
                **_ticket_field(doc.get("ticket")),
                "recorder": doc.get("recorder"),
                "determinism": doc.get("determinism"),
                # Carried through rather than recomputed: the segment measured
                # its own `.seg.mp4` against its own rect, and a stitched demo
                # may join two media with two different geometries. See
                # `merge_content`.
                "content": doc.get("content"),
                # This part's own record, on its own clock, untouched. The
                # merged one above is null the moment any part is missing
                # theirs, and the parts that *were* measured should not go
                # with it — see `_merge_capture_clock`.
                "capture_clock": doc.get("capture_clock"),
                # Likewise: where this part put its own spoken lines, on its
                # own clock. The merged field above is the same lines moved
                # onto the joined video's.
                "narration": doc.get("narration"),
            }
        )
        offset = round(offset + duration, 3)
    total = None
    if demo.exists():
        try:
            total = round(media_duration(demo), 3)
        except (subprocess.CalledProcessError, ValueError, OSError):
            total = None  # a timeline without it still beats none
    doc = {
        "schema": TIMELINE_SCHEMA,
        "generated_by": "demo-video",
        "recorder": _common([r["recorder"] for r in records], "mixed"),
        "segment": None,  # this document is the whole demo, not a part of one
        # The ticket the parts were recorded against, when they agree on one.
        # When they do not, `ticket_conflicts` names every one of them and
        # `ticket` is absent — named rather than resolved, the treatment
        # `coverage.conflicts` already gives a disagreement about wording
        # (issue #275).
        **_merged_ticket_fields(docs),
        "media": demo.name,
        "duration": total,
        "determinism": _merge_determinism([r["determinism"] for r in records]),
        "content": merge_content(records),
        # The clock demo.mp4 is on, which is not the clock the beats above are
        # on. Merged the way the beats are — by the parts' measured durations —
        # and attributed per capture, because a step in an earlier part must
        # not be applied to a later part's beats (issue #225).
        "capture_clock": _merge_capture_clock(docs, records),
        # Where the spoken lines are in the joined video, and whether every
        # part that spoke could put them on that video's clock (issue #226).
        "narration": _merge_narration(docs, records),
        # Recomputed over the *merged* beat list, not unioned from the
        # segments' own reports: `index` is renumbered by the merge, and a
        # report assembled from per-segment ones would point a reviewer at beat
        # numbers that do not exist in the file they are reading.
        "coverage": _merged_coverage(docs, beats),
        "segments": records,
        "beats": beats,
        "strict": strict,
        # Same cap as a single take's, for the same reason: timeline.json has
        # to stay a file somebody can open. `issue_count` is the honest total.
        "issues": issues[:MAX_ISSUES],
        "issue_count": issue_count,
    }
    # Last, and off the assembled document rather than off the loop above: the
    # answer needs the merged `capture_clock` this function has only just
    # finished building, and a reader asking "is this log monotonic" is asking
    # about the list as it shipped.
    doc["overlaps"] = _merge_overlaps(doc)
    return doc


def _stills_only_segment(out_dir: Path, segment: str) -> bool:
    """Whether this segment's own beat log says it recorded pictures, no video.

    Read off the segment's timeline rather than off the environment: the log is
    what the run actually wrote, and `DEMO_VIDEO_STILLS_ONLY` is only what it
    was asked for. A segment whose log is missing or unreadable is **not**
    stills-only — it falls through to the ordinary checks, which have proper
    words for every way that can be wrong.
    """
    json_path = out_dir / f"{segment}.seg.timeline.json"
    if not json_path.is_file():
        return False
    try:
        return json.loads(json_path.read_text()).get("mode") == "stills"
    except (OSError, ValueError):
        return False


def stitch(out_dir: Path, segments: list[str], keep_parts: bool = False) -> None:
    """Concatenate segment recordings into demo.mp4 and merge their beat logs.

    Each segment records its own <segment>.seg.mp4 and, beside it,
    <segment>.seg.timeline.json with timestamps relative to that segment's own
    start. This writes one demo.mp4 and one timeline.json / timeline.md next to
    it, with every beat moved onto the stitched video's clock — see
    `_merged_timeline` for how the offsets are derived and why they come from
    ffprobe rather than from the storyboard.

    Refuses before it encodes anything: every part must exist, be probeable,
    carry a beat log of this schema written for *this* recording of it, and
    agree with the other parts on everything `concat -c copy` cannot fix.

    keep_parts=True leaves the .seg.mp4 files on disk so a single segment
    can be re-recorded and re-stitched without redoing the expensive ones
    (segments are untracked; only demo.mp4 is committed). The per-segment
    timelines follow their media exactly: kept when the .seg.mp4 is kept —
    a re-stitch needs them — and deleted with it otherwise. Leaving them
    behind would leave a timeline naming a file that no longer exists, and
    the next stitch could not tell that stale log from a fresh one (#21).
    """
    out_dir = Path(out_dir)
    parts = [out_dir / f"{s}.seg.mp4" for s in segments]
    # A stills-only run of a segmented storyboard is not a broken stitch — it
    # is a run that correctly recorded no video, in every segment, on purpose
    # (#372). There is nothing to concatenate and the stills are the artifact,
    # so this returns rather than refusing.
    #
    # That distinction is the whole of #405's second half. `demo-rehearse`
    # runs stills-only, so before this a *segmented* storyboard could not
    # rehearse at all: the gate that decides whether a take is worth recording
    # died on `FileNotFoundError: part1.seg.mp4` — a message about a missing
    # file, for a file nothing was supposed to write.
    #
    # A **mix** stays an error, and is left to the per-segment check below,
    # which words it properly: some segments having video and others not is a
    # take somebody half re-recorded, and joining them would publish a demo
    # missing the middle.
    stills = [_stills_only_segment(out_dir, name) for name in segments]
    if stills and all(stills):
        print(
            f"stitch: every segment of this run is stills-only, so there is no "
            f"video to join — {len(segments)} segment(s) wrote their pictures "
            f"and nothing else. No demo.mp4 was written.",
            file=sys.stderr,
        )
        return
    for p in parts:
        if not p.exists():
            raise FileNotFoundError(p)
    # Everything the merge needs is read and checked *before* a frame is
    # encoded — the durations included, not just the beat logs. Failing here
    # costs nothing; failing after the concat leaves a fresh demo.mp4 with no
    # timeline beside it, which is the one state a reader cannot tell from a
    # demo that never had beats. That is reachable without anyone's help: a
    # truncated .seg.mp4 makes concat exit 0 and ffprobe raise afterwards.
    durations = [media_duration(p) for p in parts]
    _check_stream_shapes(parts)
    docs = [
        _segment_timeline(out_dir, s, p, d)
        for s, p, d in zip(segments, parts, durations, strict=True)
    ]
    listing = out_dir / ".concat.txt"
    demo = out_dir / "demo.mp4"
    try:
        listing.write_text(
            "".join(
                # concat-demuxer quoting: a literal ' inside single quotes
                # is written as '\'' (paths like ".../Rógvi's Mac/..." occur).
                "file '{}'\n".format(str(p.resolve()).replace("'", "'\\''"))
                for p in parts
            )
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(demo),
            ],
            check=True,
        )
    finally:
        # Even when ffmpeg failed: a stray .concat.txt in a demo folder is
        # untracked litter that outlives the run that made it.
        listing.unlink(missing_ok=True)
    merged = _merged_timeline(segments, parts, docs, durations, demo)
    json_path, _ = write_timeline(out_dir, merged)
    print(f"wrote {demo} and {json_path.name} from {len(segments)} segments")
    # Again here, and that is not duplication. The segment that recorded a
    # covered stretch said so when it was recorded, minutes and several
    # thousand lines of output ago; `demo.mp4` is the file somebody watches and
    # this timeline is the file somebody commits, so the verdict has to arrive
    # with them (issue #97).
    print_content_summary(merged.get("content"), demo.name)
    # The review sheet, from the merged log rather than from any part's. A
    # single segment's timeline cannot produce one — its beats start at zero
    # and name a `.seg.mp4` this function is about to delete — but the merged
    # document is a whole demo, and a demo long enough to record in parts is
    # the one nobody wants to review by scrubbing. Written here rather than in
    # each segment's `__exit__` for the same reason: this is the first moment
    # a whole demo exists. Re-stitching rewrites it, clearing the last one's
    # frames first.
    write_beat_frames(out_dir, merged, "stitch()")
    if not keep_parts:
        # missing_ok throughout, and the media and its log in one pass: a
        # segment named twice, or a part something else already removed, must
        # not abort this loop half-done and leave the orphans of #21 behind.
        for s, p in zip(segments, parts, strict=True):
            p.unlink(missing_ok=True)
            for path in timeline_paths(out_dir, s):
                path.unlink(missing_ok=True)
