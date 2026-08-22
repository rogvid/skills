"""Review frames: one PNG per beat, deduplicated, pulled out of the finished mp4.

Nobody reviewing a demo through this skill can watch a video, so every review
is a review of frames. They are aligned to beats rather than to a clock — a
clock misses a short beat entirely and photographs a long static one twice.
A beat whose picture repeats the last kept frame's is dropped and named on
the sheet rather than reprinted (see the dedupe section below).

`beat_frames(out_dir)` regenerates the whole sheet from demo.mp4 and
timeline.json without re-recording.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

from .content import media_duration
from .markdown import _fmt_t, _md_cell
from .timeline import capture_clock_correction, timeline_paths

# -- beat-aligned review frames ----------------------------------------------
#
# Nobody driving this skill can watch a video, so every review of a demo is a
# review of frames pulled out of it. Sampling those uniformly in time
# (`ffmpeg -vf fps=1/3`) misses a short beat entirely and photographs a long
# static one twice, so the frames come off the beat log instead: one per beat,
# at the beat's **midpoint**. `t_start` is the wrong instant to photograph —
# for a `caption` beat it is 0% into the bar's fade-in, and for any other verb
# it is before the verb has done anything. The midpoint is inside the beat by
# construction, which is what `t_end` is on the record for.
#
# **These frames carry no caption, and that is deliberate.** The obvious next
# step is to print each frame under the line that was on screen when its beat
# ran, and it is not sound: the beat log and the video are on different clocks
# (issue #18), so a frame taken at a beat's timestamp can show the neighbouring
# line — and it would arrive labelled with the log's, which is worse than no
# label at all. An earlier version of this file tried to recover the mapping by
# finding caption transitions in the video. Review found it mislabelling frames
# on ordinary storyboards, three ways that are not fixable by tuning:
#
#   * two captions of the same length ("Step 1 of 3." -> "Step 2 of 3.") change
#     only glyph pixels — under 0.25 mean luma in the caption band, which is
#     no signal at all, so whatever else repainted in the window wins;
#   * an app that keeps repainting under the bar supplies a stronger edge than
#     the caption does, at a time of its own choosing;
#   * a mid-take `goto()` destroys the caption bar with the document. The beat
#     log no longer keeps the dead line (#134), but it clears from the *next*
#     beat, so the bar leaves the screen a beat before the log says so and
#     there is still nothing in the picture to measure the moment against.
#
# All three are the same mistake — guessing which pixel change was the caption.
# The sound fix is for the recorder to *state* the mapping rather than have it
# inferred, by rendering the beat index into the frame where extraction can
# read it back. That changes every recording's pixels, so it was raised as its
# own change — issue #60, closed as not planned for exactly that reason. So
# these frames are handed over bare, which is what the uniform sampling they
# replace did too; they are simply aimed better.
#
# `frames.md` therefore prints no caption, no verb and no selector. It is the
# sheet handed to a **context-free** reviewer who is asked what story the
# pictures tell; a `click('#refresh')` in the margin answers the question for
# them.
#
# **The midpoint is a beat-log instant, and the seek is a video one.** Those
# are two different clocks: the log is `time.monotonic()`, the video is stamped
# with the host's wall clock, and a host that steps that clock parts them by
# the size of the step. So every cut below is the midpoint **plus the steps the
# beat's own capture recorded before it**, read out of the timeline's
# `capture_clock` by `capture_clock_correction` — measured at up to 1.50 s of
# error uncorrected on the WSL2 box of #247, which at 25 fps is ~37 frames of a
# sheet that *is* the demo as far as a reviewer is concerned (issue #229).
#
# When the record cannot supply that number — no field, or a sampler that says
# it could not watch — the cut falls back to the bare midpoint, and the
# manifest and the sheet say so in as many words. Zero is the only number
# available there, but it is a fallback and not a correction, and a sheet that
# let the two look alike would be claiming an accuracy nobody measured.
#
# **And a beat can have no frame to be cut at all.** A backward step of Δ does
# not slide the video, it deletes a Δ-wide window of wall time from the file
# (issue #256, and the note over `capture_clock_correction`), so a midpoint
# inside that window is of a moment `demo.mp4` does not contain. `Placed.lost`
# is how the correction says so, and this is the one case where the sheet's
# timestamp is *not* where the beat is: the frame is cut at the last instant
# before the gap, and both manifest and sheet name the beat as one whose own
# wall time is missing. The alternative — cutting at the midpoint plus the
# steps, as everything here did until #256 — puts the frame up to a whole step
# early, in content that predates the step, and it was found by eye:
# `seg-run1`'s `beat-05.png` was cut at 4.58 s and shows the previous caption.
FRAMES_DIRNAME = "frames"
FRAMES_SCHEMA = 2

# The sheet is read by agents, not played back, and image tokens are what
# killed the first field run (#343): a 122 s demo produced 80 native-res
# frames — ~98k image tokens — and three reviewer agents died on session
# limits before one review finished. 44% of those frames were a picture
# already shown. Two mechanical fixes, no judgement in either: `_extract`
# scales every frame to at most 1024 px wide (never up), and a frame whose
# picture is within DEDUPE_RMSE of the **last kept** frame's is dropped —
# named in the manifest's `deduped` list and on the sheet, never silently.
# The threshold is mechanical on purpose: a hand-picked subset can launder a
# finding out of a review; a threshold cannot. The first and last frame of a
# sheet are always kept, and a comparison that fails keeps its frame — a
# broken comparator must fatten the sheet, never thin it.
DEDUPE_RMSE = 3.0

# Scene-change detection, the fallback for what the storyboard did not script.
# A beat that holds the frame for seconds can still contain a transition
# nobody wrote down — an app finishing a load, a toast appearing, a redirect —
# and beat alignment is blind to those by construction. Only for beats long
# enough that one could hide in them.
#
# The threshold is low because ffmpeg scores a whole frame and only part of one
# of these is the app: the recorder's own chrome is a fifth to a third of the
# picture and never moves. Measured over the reference takes — a page's first
# paint 0.041, a caption appearing 0.022-0.025, a table filtering to one row
# 0.013, an idle hold 0.007 and under. Scoring the app's own rect instead would
# make one threshold mean the same thing in both media; that was issue #57, and
# it is closed as not planned, so this threshold is the answer and not a
# placeholder for one.
SCENE_MIN_SPAN_S = 3.0
SCENE_THRESHOLD = 0.02
SCENE_MAX_EXTRA = 3

# Keep the last frame inside the file: an -ss exactly at the duration decodes
# nothing.
_FRAME_EDGE_S = 0.05


def frames_paths(out_dir: Path | str) -> tuple[Path, Path, Path]:
    """(dir, json, md) for a take's beat frames."""
    frames_dir = Path(out_dir) / FRAMES_DIRNAME
    return frames_dir, frames_dir / "frames.json", frames_dir / "frames.md"


def scene_times(
    mp4: Path,
    start: float,
    end: float,
    threshold: float = SCENE_THRESHOLD,
    limit: int = SCENE_MAX_EXTRA,
) -> list[float]:
    """Video times between `start` and `end` where the picture changes hard.

    The fallback for what the storyboard did not script. Returns at most
    `limit` times, in order, and an empty list for a stretch of video that
    holds still.
    """
    if end - start <= 0:
        return []
    # `metadata=print:file=-` rather than the filter's default: the default
    # writes through ffmpeg's logger at INFO level, which `-v error` throws
    # away — a silent way for this whole function to always return nothing.
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{end - start:.3f}",
            "-i",
            str(mp4),
            "-vf",
            f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    times = [
        start + float(match) for match in re.findall(r"pts_time:([0-9.]+)", proc.stdout)
    ]
    # The first decoded frame of a seek has nothing before it to be compared
    # with, and ffmpeg scores it 1.0. That is the seek, not a scene change.
    return sorted(t for t in times if t > start + 0.08)[:limit]


def _extract(mp4: Path, at: float, path: Path) -> bool:
    """One frame of `mp4` at `at` seconds, written to `path`.

    Scaled to at most 1024 px wide — `min(1024,iw)` so a smaller video is
    never upscaled — because these frames are read by agents, in image
    tokens, and 1024 was verified legible on the field app of #343:
    burned-in captions, toast text, table digits, dropdown labels. Every
    frame of one sheet comes out of one mp4 through this one filter, so the
    kept frames stay mutually comparable.
    """
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
            str(path),
        ],
        capture_output=True,
    )
    return proc.returncode == 0 and path.is_file()


def _frame_mse(kept: Path, candidate: Path) -> float | None:
    """Mean squared error between two extracted frames, or None.

    ffmpeg's `psnr` filter, because ffmpeg is already the hard dependency
    that wrote both files — a Python imaging library would be a new import
    for every storyboard that imports these helpers. Parsed from `mse_avg`
    rather than from the psnr number itself: identical frames report an
    `inf` psnr, and `inf` is a value to special-case where an mse of `0.0`
    is just a number under the threshold. `metadata=print:file=-` for the
    reason `scene_times` gives: the filter's default logging goes through
    ffmpeg's logger at INFO level, which `-v error` throws away.

    None means the comparison itself failed. The caller must keep the frame
    then — a broken comparator must fatten the sheet, never thin it.
    """
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(kept),
            "-i",
            str(candidate),
            "-filter_complex",
            "psnr,metadata=print:file=-",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    match = re.search(r"lavfi\.psnr\.mse_avg=([0-9.]+)", proc.stdout)
    return float(match.group(1)) if match else None


def beat_frames(out_dir: Path | str, doc: dict | None = None) -> dict:
    """Write a review frame per beat, deduplicated, and an index to read them.

    A frame whose picture is within DEDUPE_RMSE of the last kept frame's is
    taken off the sheet and off disk, and recorded in the manifest's
    `deduped` list — file, beat, kind, t, the kept file it matched and the
    measured rmse — with a named line on the sheet. The first and last frame
    are always kept, and a frame the comparator could not measure is kept
    with a warning.

    Reads the timeline the take just wrote (or `doc`), extracts
    `frames/beat-NN.png` at each beat's midpoint **on the video's clock** — the
    midpoint plus that beat's own capture's recorded wall-clock steps, or the
    bare midpoint with the reason stated when the record cannot say, or the
    last instant before the gap for a beat a backward step deleted from the
    file (see the section header) — and writes `frames/frames.md` for a
    reviewer and `frames/frames.json` for a tool. Neither says anything
    about what is *in* a frame — see the section header.

    Returns the manifest. Safe to re-run: it is a pure function of the mp4 and
    the timeline, so a demo whose frames were deleted can get them back without
    re-recording, and a re-run takes the previous run's frames back off disk
    first rather than leaving stale ones in a directory somebody is about to
    hand to a reviewer.

    **Refuses to run for a segment take, and only for that.** A single
    segment's timeline numbers its beats from zero and describes a
    `<segment>.seg.mp4`, so two of them would write `beat-00.png` over each
    other and the sheet would name a file `stitch()` deletes. A *stitched*
    demo is a different thing: `stitch()` merges the parts into one timeline
    whose beats are renumbered and offset onto the joined video's clock, and
    that is a whole demo — it gets frames like any other, written by `stitch()`
    itself, and it is the case that needs a review sheet most, since a demo
    long enough to record in parts is a demo nobody wants to scrub by hand.
    """
    out_dir = Path(out_dir)
    if doc is None:
        doc = json.loads(timeline_paths(out_dir)[0].read_text())
    mp4 = out_dir / str(doc.get("media") or "demo.mp4")
    frames_dir, json_path, md_path = frames_paths(out_dir)
    beats = doc.get("beats") or []
    manifest: dict = {
        "schema": FRAMES_SCHEMA,
        "generated_by": "demo-video",
        "media": mp4.name,
        "duration": doc.get("duration"),
        "recorder": doc.get("recorder"),
        "frames": [],
        # The frames dropped because their picture repeats the last kept
        # frame's. Named, never counted: file, beat, kind, t, which kept file
        # they matched and the measured rmse, so no beat leaves the sheet
        # without a record a reader can check.
        "deduped": [],
        # Filled in below, once there is a sheet for it to describe: whether
        # these frames were cut on the video's clock or on the beat log's, and
        # why not when they were not. Null on a manifest that wrote no frames.
        "clock_correction": None,
        "skipped": None,
    }
    if doc.get("segment"):
        manifest["skipped"] = (
            f"{doc['segment']} is one segment of a demo, not a demo; its beats "
            f"are numbered from zero and its media is a .seg.mp4 that stitch() "
            f"deletes. stitch() writes the frames, off the merged timeline"
        )
        return manifest
    if not beats:
        manifest["skipped"] = "the take recorded no beats"
        return manifest
    if not mp4.is_file():
        manifest["skipped"] = f"there is no {mp4.name} to extract frames from"
        return manifest

    duration = doc.get("duration")
    if not isinstance(duration, (int, float)):
        try:
            duration = media_duration(mp4)
        except (subprocess.CalledProcessError, ValueError, OSError):
            duration = float(beats[-1].get("t_end") or 0.0)
    last = max(0.0, float(duration) - _FRAME_EDGE_S)

    place, clock = capture_clock_correction(doc)
    manifest["clock_correction"] = clock

    planned: list[dict] = []
    # Beats long enough for the unscripted-transition search whose span in the
    # video turned out to be empty. See where it is appended.
    skipped_scenes: list[int] = []
    for beat in beats:
        t_start, t_end = beat.get("t_start"), beat.get("t_end")
        if not isinstance(t_start, (int, float)):
            continue
        if not isinstance(t_end, (int, float)) or t_end < t_start:
            t_end = t_start
        # Onto the video's clock before anything is clamped: the correction is
        # what puts the beat where the frames are, and clamping first would
        # aim at the end of a file the beat does not reach.
        #
        # Every instant is placed **by the steps before that instant** —
        # `place(beat, t)`, not one number per beat. A step landing inside a
        # beat's own first half moved this frame and did not move the beat's
        # start, and half of a take's wall time is inside some beat's first
        # half, so a per-beat number leaves roughly one step in two applied to
        # the wrong instants.
        logged = (float(t_start) + float(t_end)) / 2
        placed = place(beat, logged)
        middle = min(max(placed.at, 0.0), last)
        index = int(beat.get("index", len(planned)))
        entry = {
            "file": f"beat-{index:02d}.png",
            "kind": "beat",
            "beat": index,
            "t": round(middle, 3),
        }
        # **Only when there is one**, like narration's `clamped`: a key on
        # every frame is a key nobody reads, and `0.0` beside a frame that is
        # exactly where its beat is would be a hole nobody found.
        #
        # Rounded *before* the test, exactly as `mix_plan` does it and for the
        # same reason: a midpoint 0.2 ms short of where the video resumes is
        # inside a hole by less than this record can write down, and
        # `"no_video": 0.0` beside it says "there is no frame of this beat"
        # about a frame that is where its beat is. Testing the raw float was
        # this file's own version of the bug the rounding exists to stop.
        if round(placed.lost, 3):
            entry["no_video"] = round(placed.lost, 3)
        planned.append(entry)
        # Only for beats long enough to hide an unscripted transition. Beat
        # alignment sees what the storyboard wrote down; a redirect, a toast or
        # a load finishing inside a long hold is invisible to it.
        if float(t_end) - float(t_start) < SCENE_MIN_SPAN_S:
            continue
        # The same slide, for the same reason: this window is a search through
        # the video, so it has to be the beat's span *in the video*. Left on
        # the log's clock it would scan a stretch the beat had already left —
        # and each edge is corrected at its own instant, because a step inside
        # the beat moves its end and not its start.
        lo = min(max(place(beat, float(t_start)).at, 0.0), last)
        hi = min(max(place(beat, float(t_end)).at, 0.0), last)
        # Placing each edge at its own instant can leave no window at all: a
        # beat that begins and ends inside one backward step's hole has none of
        # its wall time in the file, so both edges clamp to the same instant,
        # and a beat clamped past the end of the video collapses the same way.
        # There is genuinely nothing to search, and `scene_times` answers an
        # empty window with an empty list — so the only wrong move is to let the
        # sheet quietly carry fewer frames. Recorded here, printed in frames.md,
        # and named by beat. A beat the step lands *inside* keeps the part of
        # its span the file still has, which is `lo` up to the hole's edge.
        if hi <= lo:
            skipped_scenes.append(index)
            continue
        for n, cut in enumerate(scene_times(mp4, lo, hi), 1):
            planned.append(
                {
                    "file": f"beat-{index:02d}-scene-{n}.png",
                    "kind": "scene",
                    "beat": index,
                    "t": round(cut, 3),
                }
            )

    # Take the previous run's sheet off disk before writing this one. A demo
    # whose storyboard lost beats would otherwise leave frames nobody planned
    # sitting in the directory SKILL.md tells you to hand over. Bounded to the
    # names this function writes — never the directory.
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*frames_dir.glob("beat-*.png"), json_path, md_path]:
        try:
            # missing_ok: the two manifests do not exist on a first run, and a
            # warning about failing to delete them would be on every take.
            stale.unlink(missing_ok=True)
        except OSError:  # noqa: PERF203 - a leftover is worth reporting, not fatal
            print(
                f"demo-video: WARNING — could not remove the stale {stale.name}",
                file=sys.stderr,
            )

    written: list[dict] = []
    for record in planned:
        if _extract(mp4, float(record["t"]), frames_dir / str(record["file"])):
            written.append(record)
        else:
            print(
                f"demo-video: WARNING — could not extract a frame at "
                f"{record['t']}s for beat {record['beat']}",
                file=sys.stderr,
            )

    # Drop the frames that repeat a picture already kept, in sheet order and
    # against the **last kept** frame — never against a fixed neighbour, or a
    # slow fade would survive as a chain of pairwise near-duplicates. Scene
    # frames participate exactly like beat frames: a "transition" that left
    # the picture where it was is the same non-information either way. See
    # the note over DEDUPE_RMSE for why the threshold is mechanical.
    kept: list[dict] = []
    deduped: list[dict] = []
    for n, record in enumerate(written):
        # The sheet's anchors: where the demo started and where it ended stay
        # visible even when nothing on screen ever moved.
        if n == 0 or n == len(written) - 1:
            kept.append(record)
            continue
        mse = _frame_mse(
            frames_dir / str(kept[-1]["file"]), frames_dir / str(record["file"])
        )
        if mse is None:
            print(
                f"demo-video: WARNING — could not compare {record['file']} "
                f"with {kept[-1]['file']}; keeping the frame. A broken "
                f"comparator must fatten the sheet, never thin it.",
                file=sys.stderr,
            )
            kept.append(record)
            continue
        if mse >= DEDUPE_RMSE * DEDUPE_RMSE:
            kept.append(record)
            continue
        png = frames_dir / str(record["file"])
        try:
            png.unlink()
        except OSError:
            # A picture on disk that the manifest disowned is worse than a
            # duplicate: it is a frame nobody indexed in a directory the
            # skill says to hand over whole. Keep it listed instead.
            print(
                f"demo-video: WARNING — could not remove the duplicate "
                f"{record['file']}, so it stays on the sheet",
                file=sys.stderr,
            )
            kept.append(record)
            continue
        deduped.append(
            {
                "file": record["file"],
                "beat": record["beat"],
                "kind": record["kind"],
                "t": record["t"],
                "matches": kept[-1]["file"],
                "rmse": round(math.sqrt(mse), 2),
            }
        )
    manifest["frames"] = kept
    manifest["deduped"] = deduped
    manifest["scene_search_skipped"] = skipped_scenes
    # How far the video is *known* to have slid under the beat log, as a floor
    # rather than a correction: a beat that ends after the video does is wall
    # time that never reached the file (issue #18). Measured against the last
    # beat's **corrected** end, because a recorded wall-clock step already
    # explains that much of the gap and is already applied above — reporting it
    # here too would tell a reviewer their frames may be stale by the very
    # amount they were just moved by.
    tail = beats[-1]
    tail_end = float(tail.get("t_end") or 0.0)
    over = place(tail, tail_end).at - float(duration)
    manifest["capture_loss_at_least"] = round(max(0.0, over), 3)
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_frames_md(manifest))
    return manifest


def write_beat_frames(out_dir: Path | str, doc: dict, where: str) -> dict | None:
    """`beat_frames`, without letting a review sheet cost a recording.

    Everything it does is ffmpeg re-reading an mp4 that is already on disk, so
    a failure loses the sheet and nothing else — and raising out of a take's
    `__exit__`, or out of `stitch()` after the concat, would take the video,
    the stills and the beat log down with it. `where` names the caller in the
    warning, because "could not extract beat frames" during a stitch and during
    a take are different things to go looking at.
    """
    try:
        manifest = beat_frames(out_dir, doc)
    except Exception as exc:  # noqa: BLE001 - a review sheet is not a recording
        print(
            f"demo-video: WARNING — {where} could not extract beat frames: "
            f"{exc}. The video, the stills and the timeline are unaffected; "
            f"`beat_frames(out_dir)` re-runs it.",
            file=sys.stderr,
        )
        return None
    if manifest["skipped"]:
        # Say which, rather than announcing a directory that was never
        # created — a segment take reaches this on every run.
        print(
            f"demo-video: no review frames — {manifest['skipped']}",
            file=sys.stderr,
        )
        return manifest
    dropped = len(manifest.get("deduped") or [])
    print(
        f"wrote {frames_paths(out_dir)[0]} ({len(manifest['frames'])} review frames"
        + (f", {dropped} dropped as repeats and named in frames.md" if dropped else "")
        + ")"
    )
    return manifest


def _clock_md(clock: object, holed: bool = False) -> list[str]:
    """What the sheet says about the clock its frames were cut on.

    Three sentences for three states, and the reason all three are printed
    rather than only the interesting one: a reviewer cannot tell a frame cut
    with the host's steps applied from one cut without them by looking at it.
    Saying nothing on the fallback would leave the sheet reading exactly like
    a corrected one — which is the confidently-wrong artifact this whole field
    exists to avoid, and it is why "the clock was watched and held still" is
    also stated out loud instead of being inferred from silence.

    `holed` is whether any frame on this sheet is of a beat the clock deleted
    from the file, and it is a parameter rather than something the paragraph
    below leaves to `_no_video_md` to correct afterwards: the stepped sentence
    says flatly that every frame is its midpoint plus the steps before it, and
    for those frames that is false. A reader who stops at the first paragraph
    — which is what a headline paragraph is for — would carry away the wrong
    rule and never reach the correction.
    """
    if not isinstance(clock, dict):
        return []
    if not clock.get("applied"):
        return [
            f"**These frames were cut on the beat log, uncorrected**: "
            f"{clock.get('note')}. The video is on the host's wall clock and "
            f"the beat log is not, so if that clock stepped during this take "
            f"every frame after the step is of a moment that much later in the "
            f"demo — and nothing here knows by how much.",
            "",
        ]
    # On the **count**, never on the total. Two steps that cancel — a +0.9 s
    # pulse and the -0.9 s that undoes it, which is the shape of the host this
    # work exists for — total zero and still move every frame cut between
    # them. Branching on the total would print "did not step" over a sheet
    # whose frames had moved by nearly a second.
    if not clock.get("steps"):
        return [
            "The host's wall clock was watched for the length of this take and "
            "did not step, so each frame is at its beat's midpoint.",
            "",
        ]
    return [
        f"**The host's wall clock stepped {clock.get('steps')} time(s) while "
        f"this was recorded** ({clock.get('total') or 0.0:+.2f}s in total), and "
        f"the video is on that clock. "
        + (
            "Each frame below was therefore cut at "
            if not holed
            else "Except for the frames named in the next paragraph, whose "
            "beats are not in the file at all, each frame below was cut at "
        )
        + "its beat's midpoint **plus the steps its own capture recorded "
        "before that instant**, not at the midpoint itself — the timestamps "
        "in the table are where the frames came out of the video, and the "
        "total above is the correction for none of them individually. "
        "`timeline.json`'s `capture_clock` has the steps.",
        "",
    ]


def _no_video_md(frames: list[dict]) -> list[str]:
    """The frames whose beat the host's clock deleted from the file (#256).

    Named, never counted, and never silent: the sheet's whole contract is that
    a frame is the moment its heading says it is, and for these it is not —
    there is no such moment in `demo.mp4` to be. A backward step of Δ deletes
    a Δ-wide window of wall time outright rather than sliding the video, so a
    beat inside that window was never encoded. The frame is the last one before
    the gap, which is as close as the file goes.

    Saying nothing here is the failure this exists to stop, and it is not
    hypothetical: it is what shipped. `seg-run1`'s `beat-05.png` was cut a
    whole step early, into content that predates the step, and arrived on a
    sheet that presented it as the beat's midpoint — a frame of the previous
    caption, confidently numbered for the beat after it.
    """
    holed = [f for f in frames if f.get("no_video")]
    if not holed:
        return []
    named = ", ".join(f"`{_md_cell(f.get('file'))}`" for f in holed)
    return [
        f"**{named} {'is' if len(holed) == 1 else 'are'} not at the beat "
        f"{'it is' if len(holed) == 1 else 'they are'} named for: the host's "
        f"wall clock stepped backwards over that moment, and a backward step "
        f"takes its own width of wall time *out of the file* rather than "
        f"moving it.** There is no frame of "
        f"{'that beat' if len(holed) == 1 else 'those beats'} in this "
        f"recording. What is printed is the last frame before the gap — the "
        f"video resumes "
        + ", ".join(
            f"{float(f['no_video']) * 1000:.0f} ms after `{_md_cell(f.get('file'))}`'s "
            f"own moment"
            for f in holed
        )
        + ". Read "
        + ("it" if len(holed) == 1 else "them")
        + " as the moment the demo reached before the clock moved, not as the "
        "beat. `timeline.json`'s `capture_clock` has the steps.",
        "",
    ]


def render_frames_md(manifest: dict) -> str:
    """The review sheet: the frames, in order, and nothing else.

    Pure function of the manifest, so it can be re-rendered without the video.

    **What it deliberately does not carry**: the caption each frame ran under,
    the verb, and the selector. The first is a claim the recorder cannot check
    (see the section header); the second and third are the storyboard, and this
    is the document handed to a reviewer who is asked what story the pictures
    tell on their own. `click('#refresh')` printed beside a frame answers that
    question for them, and the `fps=1/3` handoff this replaces did not leak it.
    """
    frames = manifest.get("frames") or []
    head = [f"`{manifest.get('media') or 'demo.mp4'}`"]
    if manifest.get("duration") is not None:
        head.append(f"{float(manifest['duration']):.1f}s")
    head.append(f"{len(frames)} frames")
    out = [
        "# Review frames",
        "",
        " · ".join(head),
        "",
        "One frame per beat of the demo — per thing the storyboard did — rather "
        "than one every N seconds, so nothing the demo does is missed. A beat "
        "whose picture repeats an earlier frame's is named below instead of "
        "reprinted. Read them in order. Written by the "
        "demo-video recorder whenever it encodes an mp4 — which now includes a "
        "take that crashed, whose recording stops where the storyboard gave up "
        "(see `failure/`); re-record rather than editing it.",
        "",
        "**They are not captioned, on purpose.** The recorder knows which line "
        "was on screen during each *beat*, but the beat log and the video run "
        "on different clocks — see "
        "[#18](https://github.com/rogvid/skills/issues/18) — so a caption "
        "printed under a frame can belong to the frame next to it. A frame with "
        "a confident wrong caption is worse than a frame with none. "
        "[#60](https://github.com/rogvid/skills/issues/60) is how the pairing "
        "gets earned back.",
        "",
    ]
    if manifest.get("skipped"):
        return "\n".join(out + [f"No frames were written: {manifest['skipped']}.", ""])
    holed = _no_video_md(frames)
    out += _clock_md(manifest.get("clock_correction"), bool(holed))
    out += holed
    swallowed = manifest.get("scene_search_skipped") or []
    if swallowed:
        # Named, not counted: the reader's question is which beat is thinner
        # than it looks, and "one beat" does not answer it.
        beats = ", ".join(f"`beat-{int(i):02d}.png`" for i in swallowed)
        out += [
            f"{beats} covers a beat long enough for the recorder to look "
            f"inside it for a change the storyboard did not script — and the "
            f"host's wall clock stepped further during that beat than the beat "
            f"is long, so none of its wall time is in the video and **no extra "
            f"frames were looked for**. The sheet is that much thinner than it "
            f"would be on a steady host; nothing is missing from the beat's "
            f"own frame above.",
            "",
        ]
    # One line per dropped frame, named like everything else this sheet
    # withholds — `scene_search_skipped` above set the rule. The reader's
    # question is which beat is not pictured and where its picture is, and a
    # count answers neither.
    for drop in manifest.get("deduped") or []:
        out += [
            f"`{_md_cell(drop.get('file'))}` is not on this sheet: its "
            f"picture is `{_md_cell(drop.get('matches'))}`'s "
            f"(RMSE {drop.get('rmse')} < {DEDUPE_RMSE}).",
            "",
        ]
    loss = manifest.get("capture_loss_at_least") or 0.0
    if loss > 0.05:
        out += [
            f"This take lost at least {loss * 1000:.0f} ms of wall time to the "
            f"capture (its last beat ends after the video does), so a frame may "
            f"sit that much later in the demo than the beat it was aimed at.",
            "",
        ]
    out += [
        "| frame | at |",
        "|---|---:|",
    ]
    for frame in frames:
        out.append(f"| `{_md_cell(frame.get('file'))}` | {_fmt_t(frame.get('t'))} |")
    out.append("")
    for frame in frames:
        name = str(frame.get("file"))
        title = f"{name.removesuffix('.png')} — {_fmt_t(frame.get('t'))}s"
        if frame.get("kind") == "scene":
            title += " (an extra frame: the picture changed here)"
        # Beside the picture as well as above the table: a reviewer scrolling
        # the frames reads the headings and never the preamble, and this is the
        # one heading whose timestamp is not where its beat is.
        if frame.get("no_video"):
            title += " (no video of this beat — the last frame before the gap)"
        out += [f"## {title}", "", f"![{name}]({name})", ""]
    return "\n".join(out).rstrip() + "\n"
