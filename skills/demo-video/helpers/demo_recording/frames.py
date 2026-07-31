"""Review frames: one PNG per beat, pulled out of the finished mp4.

Nobody reviewing a demo through this skill can watch a video, so every review
is a review of frames. They are aligned to beats rather than to a clock — a
clock misses a short beat entirely and photographs a long static one twice.

`beat_frames(out_dir)` regenerates the whole sheet from demo.mp4 and
timeline.json without re-recording.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .content import media_duration
from .markdown import _fmt_t, _md_cell
from .timeline import timeline_paths

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
# read it back. That changes every recording's pixels, so it is its own change:
# issue #60. Until then these frames are handed over bare, which is what the
# uniform sampling they replace did too — they are simply aimed better.
#
# `frames.md` therefore prints no caption, no verb and no selector. It is the
# sheet handed to a **context-free** reviewer who is asked what story the
# pictures tell; a `click('#refresh')` in the margin answers the question for
# them.
FRAMES_DIRNAME = "frames"
FRAMES_SCHEMA = 1

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
# 0.013, an idle hold 0.007 and under. Issue #57 proposes scoring the app's own
# rect instead, which would make one threshold mean the same thing in both
# media.
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
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
         "-i", str(mp4),
         "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    times = [
        start + float(match)
        for match in re.findall(r"pts_time:([0-9.]+)", proc.stdout)
    ]
    # The first decoded frame of a seek has nothing before it to be compared
    # with, and ffmpeg scores it 1.0. That is the seek, not a scene change.
    return sorted(t for t in times if t > start + 0.08)[:limit]


def _extract(mp4: Path, at: float, path: Path) -> bool:
    """One frame of `mp4` at `at` seconds, written to `path`."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(mp4),
         "-frames:v", "1", "-update", "1", str(path)],
        capture_output=True,
    )
    return proc.returncode == 0 and path.is_file()


def beat_frames(out_dir: Path | str, doc: dict | None = None) -> dict:
    """Write one review frame per beat, and an index to read them in order.

    Reads the timeline the take just wrote (or `doc`), extracts
    `frames/beat-NN.png` at each beat's midpoint, and writes `frames/frames.md`
    for a reviewer and `frames/frames.json` for a tool. Neither says anything
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

    planned: list[dict] = []
    for beat in beats:
        t_start, t_end = beat.get("t_start"), beat.get("t_end")
        if not isinstance(t_start, (int, float)):
            continue
        if not isinstance(t_end, (int, float)) or t_end < t_start:
            t_end = t_start
        middle = min(max((float(t_start) + float(t_end)) / 2, 0.0), last)
        index = int(beat.get("index", len(planned)))
        planned.append({
            "file": f"beat-{index:02d}.png",
            "kind": "beat",
            "beat": index,
            "t": round(middle, 3),
        })
        # Only for beats long enough to hide an unscripted transition. Beat
        # alignment sees what the storyboard wrote down; a redirect, a toast or
        # a load finishing inside a long hold is invisible to it.
        if float(t_end) - float(t_start) < SCENE_MIN_SPAN_S:
            continue
        window = (min(float(t_start), last), min(float(t_end), last))
        for n, cut in enumerate(scene_times(mp4, *window), 1):
            planned.append({
                "file": f"beat-{index:02d}-scene-{n}.png",
                "kind": "scene",
                "beat": index,
                "t": round(cut, 3),
            })

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
    manifest["frames"] = written
    # How far the video is *known* to have slid under the beat log, as a floor
    # rather than a correction. A beat that ends after the video does can only
    # mean capture loss (issue #18); it is usually zero, and when it is not it
    # is the one number that says how stale a frame's aim may be.
    over = float(beats[-1].get("t_end") or 0.0) - float(duration)
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
    print(
        f"wrote {frames_paths(out_dir)[0]} ({len(manifest['frames'])} review frames)"
    )
    return manifest


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
        "than one every N seconds, so nothing the demo does is missed and a "
        "held frame is photographed once. Read them in order. Written by the "
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
        out += [f"## {title}", "", f"![{name}]({name})", ""]
    return "\n".join(out).rstrip() + "\n"
