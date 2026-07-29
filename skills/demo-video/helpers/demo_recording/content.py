"""Did the recording show anything?

Every other field in a timeline is a statement about what the storyboard *did*,
and all of them can be exactly right while the recording shows nothing: a title
card left up, a modal that never closed, an app that stopped painting. So the
recorder also measures the picture, over the region the app occupies in the
encoded frame, and writes down what it found.

The measurements shell out to ffmpeg and ffprobe and come back with numbers.
No image library, no browser, no extra dependency — which is what lets the
floors and the warning conditions be graded directly.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
from pathlib import Path


def media_duration(path: Path) -> float:
    """Duration of any media file in seconds, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


# -- did the recording show anything? (issue #97) ----------------------------
#
# Everything above this line describes what the storyboard **did**. The beat
# log, the evidence documents, the exit codes, the stills and the captions are
# all statements about the program and about the verbs that drove it, and every
# one of them can be completely correct while the recording shows nothing at
# all.
#
# That is not hypothetical. Take 1 of this repo's own reference demo had a
# title card covering the terminal for 24.3 s of a 60.2 s video — 40% of the
# recording, with the real CLI running underneath it, invisible. `timeline.json`
# had all 17 terminal beats in order with correct exit codes; `evidence/*.json`
# held the full command output, because the xterm.js buffer was right and
# merely covered; the stills, the captions and the stderr summary all read like
# a healthy take. A reviewing agent handed the criteria plus `evidence/` and
# `timeline.md` certified the CLI criterion as demonstrated. Only `frames/`
# disagreed — 17 consecutive identical PNGs — and only because somebody looked
# at the pictures.
#
# So the recorder measures the picture too, and writes the answer where the
# text tier is read: `content` in the timeline envelope, plus a line on stderr.
# Two independent arms, because the failure above defeats one of them:
#
#   score       median luma standard deviation over the content rect. Catches
#               a recording that never rises above blank — a black take, a page
#               that never painted, a mask that covered everything.
#   static_for  the longest run of consecutive sampled frames that do not
#               change, in seconds. Catches a recording that is *covered* or
#               frozen, which the score cannot: the #91 card is dark with a
#               line of white text on it and scores ~12, comfortably "content".
#
# **Three things about the rect, and each one was a defect somewhere.**
#
# 1. It is the region the *app* occupies, not the frame. A fifth to a third of
#    every frame is the recorder's own chrome — a pastel gradient at ~230 luma
#    framing a window at ~35 — and it never changes. Scored whole-frame, a
#    blank recording measured 61.8 against a healthy one's 60.2: the metric ran
#    backwards, and the chrome is why (issue #17). The recorder knows its own
#    geometry, so it hands over the rect rather than guessing at one.
# 2. The caption band is cut off the bottom (`CONTENT_CAPTION_TRIM`). The
#    caption bar is burned into the recording and it is the recorder's own
#    drawing, not the app's — leaving it in lets a caption supply the contrast
#    for a blank app on the score arm, and lets a caption *change* count as the
#    picture changing on the static arm. Either one turns a broken take green.
# 3. It is sampled from the encoded mp4, after compositing, which is the file a
#    reviewer actually watches. Measuring the raw webm would grade something
#    nobody is handed.
#
# **Warn, never refuse.** A demo legitimately holding one frame through a long
# narrated beat is ordinary, and a heuristic that fails takes is worse than a
# heuristic that misses one — the same argument that scoped the terminal
# verifier to registered values only (issue #5). Nothing here raises, nothing
# here deletes an artifact, and a check that cannot run says so in `content`
# rather than being silently absent.
#
# **What this deliberately does not do** is judge whether the demo shows the
# *right* thing. That is issue #12's job, and a human's. This answers exactly
# one question: did the recording capture anything at all.

# Frames sampled per second of video. Two, not one: `static_for` is quantised
# to this step, so at 1 fps the shortest reportable run is a full second and
# the number a reviewer reads is coarser than the thing it describes. Past ~4
# the decode starts to cost more than the check is worth on a 60 s take.
CONTENT_SAMPLE_FPS = 2

# Every frame is reduced to this before any arithmetic — one ffmpeg pass, no
# image library, no extra dependency. Small on purpose: it is a blur, and a
# blur is what makes "did this change" robust against encoder noise. It is also
# why the static arm cannot see a single character change (~0.02 mean absolute
# luma at this size, far under CONTENT_STATIC_DIFF) and does not try to; a
# blinking cursor is not the demo showing something.
_CONTENT_W, _CONTENT_H = 160, 90

# How much of the content rect's height is dropped off the bottom before
# scoring. Sized for the caption bar plus its shadow at either recorder's
# geometry — the web caption's top edge sits at 84.2% of the app rect's height
# and the terminal's at 85.7%, with a 24 px shadow above each — and it is the
# same 0.8 keep that tests/smoke has used for its own content floor since #17.
#
# **This is why the static arm needs the beat log, and the reasoning is worth
# keeping.** Excluding the caption bar is not optional: the bar is the
# recorder's own drawing, it renders *over* an interlude card as readily as
# over the app, and leaving it in would let a caption change count as the
# picture changing — which defeats the detector on exactly the occlusion it
# exists for. But the exclusion has a cost, and it is not a small one: the two
# things this skill hands an author for keeping a still screen alive — swapping
# captions, and narration pacing — are both invisible here **by construction**.
# A perfectly healthy demo that tours a rendered screen with three captions
# holds the measured region still for 20-22 s, which is indistinguishable from
# a card covering the terminal for 23 s.
#
# So a held stretch on its own says nothing about whether anything is wrong,
# and `CONTENT_ACTING_VERBS` below is what turns it into a signal. Two stated
# limits survive that, both narrower:
#
#   * whatever happens in the bottom fifth of the app is not measured at all;
#     on a terminal that is the last rows before the screen starts scrolling.
#   * a demo that genuinely holds still *through* an acting verb warns, and is
#     right to be looked at even though nothing is broken.
CONTENT_CAPTION_TRIM = 0.2

# Median luma standard deviation under which the content rect is "blank".
#
# Measured over the trimmed rect, on every take tests/smoke records plus this
# repo's reference demo:
#
#   blank                            0.2 - 1.1   (a real recording with the app
#                                                 rect painted flat scores 0.21)
#   healthy, sparsest terminal       2.0         (one failing command, nothing
#                                                 else on screen)
#   healthy, ordinary terminal       4.6 - 14.3
#   healthy, web                    16.0 - 36.1
#
# One floor for both media rather than two, and it sits at 1.0 — 2x under the
# sparsest healthy take in the suite and roughly 5x over a blank one. The
# asymmetry is deliberate and it is not a compromise: this arm has a partner.
# A page that never painted does not change either, so the static arm below
# catches the blank case a second time, and a floor set high enough to catch
# every blank take on its own would warn about honest, nearly-empty terminal
# demos — which costs the warning its credibility everywhere.
#
# tests/smoke keeps its own, higher, per-medium floors as a *gate*. This is the
# floor shipped to somebody else's app, where a false alarm is the expensive
# failure.
CONTENT_BLANK_FLOOR = 1.0

# When two consecutive samples count as "the same picture": fewer than
# CONTENT_MOVED_PIXELS of the 14 400 reduced pixels moved by more than
# CONTENT_PIXEL_DELTA luma levels.
#
# **A mean absolute difference does not work here, and that was measured, not
# assumed.** libx264 re-quantises a held frame at every I-frame, and on the
# occluded reference take that redrew the card's glyph edges hard enough to
# move the mean by 0.43 — while the *smallest real change* in the healthy take
# of the same storyboard moved it by 0.71. A 1.6x gap is not a threshold, it is
# a coin toss, and setting it either way loses the detector or floods it.
#
# Counting pixels separates the two cleanly, because the two phenomena have
# different shapes: re-quantisation is a fraction of a level smeared over the
# whole rect, while a command running or a page repainting moves a *region* by
# tens of levels. Measured over the same two takes, per consecutive pair:
#
#   covered (a card over the whole terminal)   0 pixels, every pair of 46
#   healthy terminal, real changes             2, 13, 20, 27, 31, ... 1256
#   healthy web, real changes                 10, 13, 14, 16, 17, ... 991
#
# So the bar sits at 4: it never fires on the covered take (which reported
# 0.43 mean and would have defeated any mean-based bar) and it is 2.5x under
# the smallest change either healthy take makes. The 2-pixel terminal pair is
# the tail of a transition whose leading edge already registered 1256 pixels
# half a second earlier — missing it costs nothing.
CONTENT_PIXEL_DELTA = 12
CONTENT_MOVED_PIXELS = 4

# How long the content rect may hold still before it is worth looking at, *and*
# an acting verb ran inside that stretch. `static_for` is reported always,
# whatever it is; this and CONTENT_ACTING_VERBS together decide whether stderr
# and `warnings` mention it.
#
# Measured, on the longest stretch a take holds one frame:
#
#   reference demo, web part                       4.5 s   healthy
#   reference demo, terminal part                  5.0 s   healthy
#   tests/smoke's content-shown take               6.0 s   healthy
#   tests/smoke's terminal take                   10.0 s   healthy
#   a terminal demo touring a screen, 2 captions  16.5 s   healthy
#   a web demo touring a screen, 3 captions       20.0 s   healthy
#   a terminal demo touring a screen, 3 captions  22.0 s   healthy
#   reference demo take 1, card over the terminal 23.0 s   the defect
#   tests/smoke's content-covered take            30.5 s   the defect
#
# **Read that table before touching this constant.** There is no value of it
# that separates the last two rows from the three above them: a healthy demo
# narrated over a rendered screen and a demo nobody can see produce the same
# number. That is not a tuning problem, it is what excluding the caption band
# costs (see CONTENT_CAPTION_TRIM), and it is why duration alone never warns.
#
# What this constant does is set how long a stretch has to be before it is worth
# reporting at all. 15 s is comfortably over every healthy take's ordinary holds
# and under the shortest occlusion measured.
CONTENT_STATIC_WARN_S = 15.0

# The storyboard verbs that **act on the app**. A held picture spanning one of
# these is worth a human's attention; a held picture spanning only the others is
# a narrated hold — which is exactly what this skill tells authors to write:
#
#     "during unavoidable waits, tour what's on screen or swap the caption"
#
# This is the whole difference between a detector and a timer. Without it the
# static arm fires on ordinary demos on both media — measured at 16.5-22.0 s on
# three healthy takes, against 23.0 s for the defect it exists to catch — and
# the sentence it prints blames an occlusion that did not happen. An artifact
# confidently attributing something to the wrong cause is the precise failure
# issue #97 exists to remove, so the detector must not commit it.
#
# The split is by *what the verb does to the picture*, not by how long it takes:
#
#   acting    it changed the app, the page or the terminal screen, so something
#             should have moved in the measured region and nothing did.
#   passive   it narrated, waited, held, or photographed. A still picture is the
#             expected outcome there, not a symptom.
#
# `wait_for*` are passive on purpose: a wait that returns immediately because
# its condition already held changes nothing, and cannot be told apart here from
# one that really waited. Guessing would put the false positive straight back.
#
# tests/smoke asserts this covers **every** verb the recorders define, so a verb
# added later cannot quietly default into either bucket.
CONTENT_ACTING_VERBS = frozenset(
    {
        "click",
        "click_fast",
        "goto",
        "key",
        "move_to",
        "run",
        "scroll_to",
        "send",
        "spotlight",
        "terminal",
        "terminal_close",
        "terminal_output",
        "type_into",
    }
)
CONTENT_PASSIVE_VERBS = frozenset(
    {
        "bridge",
        "caption",
        "hold",
        "interlude",
        "pause",
        "shot",
        "wait_for",
        "wait_for_prompt",
        "wait_for_text",
    }
)

# How many of the beats a held stretch spans are named in the report. Enough to
# see what was going on, few enough that `timeline.json` stays a file somebody
# opens.
CONTENT_STATIC_BEATS_MAX = 8


# -- the blank opening (issue #119) ------------------------------------------
#
# Chromium's screencast starts with the page, and the page is `about:blank`
# until the storyboard's first `goto()` returns. `about:blank` paints white, so
# every web take opened on a flat white app rect — measured at ~400 ms on the
# reference demo, and reported by a human watching it, not by anything here.
#
# `_t0` cannot simply be moved later to skip it: the comment on it in
# `__enter__` is load-bearing, and says why. Frame zero of the recording is the
# page's creation, so pinning `_t0` anywhere else shifts every beat timestamp
# and every narration offset earlier than the frame it describes.
#
# **So the gap is covered, not cut.** The web recorder finds the first frame
# that differs from the one the take opened on, and composites *that* frame
# over the app rect for the seconds before it. Content at every later time
# stays exactly where it was: the video's duration is unchanged, the audio is
# untouched, and not one timestamp moves — which is the whole reason this shape
# was chosen over trimming, whose uniform `t -= trim` would have to be threaded
# through `frames/` extraction, `stitch()`'s merged offsets and the capture-loss
# offset in issue #18.
#
# **What it costs, and why the artifact has to say so.** Those first frames show
# the app before it painted. That is a picture the recording did not capture,
# and a recorder that fabricates one silently is doing the thing this whole
# package refuses to do everywhere else. So `content.opening` carries `held` —
# how many seconds were covered — and the summary line says it out loud.
#
# **The number that grades it is measured from the other side.** `held` is what
# the recorder believes it did; `gap` is measured afterwards, off the encoded
# mp4, by the same sampling the picture check uses. On a web take that worked,
# `gap` is 0.0 *because* the hold landed — so a hold that silently did nothing
# shows up as a non-zero `gap` on the file somebody watches, and warns. The two
# numbers come from different passes over different files on purpose.
#
# Neither number is invented for recorders that do not do this: `held` is null
# for them (the terminal recorder frames itself in the page and `_postprocess`
# is a no-op there), and only a recorder that holds can warn about a gap it
# failed to cover.

# How long an opening gap may be before the recorder refuses to cover it. Past
# this the opening is not a screencast artefact, it is an app that takes a long
# time to paint — which is information about the app, and covering seconds of it
# would be inventing a demo rather than repairing one. Over the limit nothing is
# held, `note` says why, and the measured `gap` then warns on its own.
OPENING_HOLD_LIMIT_S = 1.5

# How far in to look for the first change, and how finely. 20 fps because the
# thing being measured is ~400 ms long: at the picture check's own 2 fps the
# answer would be 0.0 or 0.5 with nothing in between.
OPENING_SEARCH_S = 3.0
OPENING_SAMPLE_FPS = 20

# A measured gap under this is one or two frames of encoder settling, not an
# opening somebody would notice. Three samples at OPENING_SAMPLE_FPS.
OPENING_WARN_S = 0.15


def content_rect(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """An app rect with the recorder's own caption band cut off the bottom.

    Both recorders' `_content_rect` funnel through this, so "what the check
    measures" is one definition rather than two that drift.
    """
    x, y, w, h = rect
    return (
        max(0, int(x)),
        max(0, int(y)),
        max(2, int(w)),
        max(2, int(h * (1.0 - CONTENT_CAPTION_TRIM))),
    )


def _content_frames(
    mp4: Path,
    rect: tuple[int, int, int, int],
    sample_fps: int,
    limit_s: float | None = None,
) -> list[bytes]:
    """`mp4`'s content rect, sampled and reduced to grayscale frames.

    `limit_s` stops after that many seconds of video — the opening check looks
    at the first few seconds and decoding a whole 60 s take to answer a question
    about its first 400 ms is waste. None reads the file to the end.
    """
    x, y, w, h = rect
    chain = (
        f"fps={sample_fps},crop={w}:{h}:{x}:{y},"
        f"scale={_CONTENT_W}:{_CONTENT_H},format=gray"
    )
    window = [] if limit_s is None else ["-t", f"{limit_s:.3f}"]
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), *window, "-vf", chain,
         "-an", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg could not sample {mp4.name}: "
            f"{proc.stderr.decode(errors='replace').strip()[:300]}"
        )
    size = _CONTENT_W * _CONTENT_H
    raw = proc.stdout
    return [raw[i : i + size] for i in range(0, len(raw) - size + 1, size)]


def _luma_stddev(frame: bytes) -> float:
    """How much picture is in one reduced frame. A flat frame scores 0."""
    n = len(frame)
    mean = sum(frame) / n
    return (sum((b - mean) ** 2 for b in frame) / n) ** 0.5


def _moved_pixels(a: bytes, b: bytes) -> int:
    """How many reduced pixels moved by more than `CONTENT_PIXEL_DELTA`.

    The question a mean cannot answer: *did part of the picture change*, as
    opposed to *did the whole thing shift by a fraction of a level*. See the
    constants above for the measurement that made the difference matter.
    """
    return sum(
        1 for x, y in zip(a, b, strict=True) if abs(x - y) > CONTENT_PIXEL_DELTA
    )


def opening_gap(
    mp4: Path | str,
    rect: tuple[int, int, int, int] | None,
    *,
    fps: int = OPENING_SAMPLE_FPS,
    search_s: float = OPENING_SEARCH_S,
    floor: float = CONTENT_BLANK_FLOOR,
) -> tuple[float | None, str | None]:
    """How long this recording opens on a featureless picture nothing changes.

    Returns `(seconds, note)`. `seconds` is 0.0 when the take opens on a
    picture, which is the healthy answer and the common one; `None` when
    nothing could be measured, and then `note` says why. See the section header
    for what the web recorder does with it.

    **Two conditions, and the second is what stops this firing on a static
    app.** The opening frame has to be *featureless* — under the same blank
    floor the picture check uses — and only then is the wait for it to change
    meaningful. A demo that opens on a rendered page holding still for two
    seconds is an ordinary demo; without the floor it would read identically to
    a page that never painted, and every such take would report a two-second
    opening gap that is not there.

    Calibrated off the take's **own** first frame rather than against an
    absolute white, so it does not assume anything about what a blank page
    looks like: an app on a dark background whose recorder opens black is the
    same phenomenon and measures the same way.

    Never raises, for the reason `content_report` does not: this runs inside
    the encode path, and a measurement must never be able to cost somebody a
    recording.
    """
    try:
        if rect is None:
            return None, (
                "this recorder does not know where the app sits in the frame"
            )
        mp4 = Path(mp4)
        if not mp4.is_file():
            return None, f"there is no {mp4.name} to measure"
        frames = _content_frames(mp4, rect, fps, limit_s=search_s)
        if len(frames) < 2:
            return None, (
                f"only {len(frames)} frame(s) could be sampled from {mp4.name} "
                f"at {fps} fps, which is too few to say anything"
            )
        if _luma_stddev(frames[0]) >= floor:
            return 0.0, None
        for i in range(1, len(frames)):
            if _moved_pixels(frames[0], frames[i]) >= CONTENT_MOVED_PIXELS:
                return round(i / fps, 3), None
        return round((len(frames) - 1) / fps, 3), (
            f"the picture had still not changed {search_s:.1f}s in, which is as "
            f"far as this looks — so the opening is at least that long, and may "
            f"be the whole take"
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return None, f"{type(exc).__name__}: {exc}"


def opening_report(
    gap: float | None,
    note: str | None,
    held: float | None,
    *,
    limit: float = OPENING_HOLD_LIMIT_S,
) -> dict:
    """`content.opening`: what the take opened on, and what was done about it.

    `held` is null for a recorder that does not cover its opening — see the
    section header for why the two numbers come from different passes over
    different files.
    """
    return {"gap": gap, "held": held, "limit": limit, "note": note}


def opening_warning(opening: dict | None) -> str | None:
    """The one thing worth saying out loud about an opening, or None.

    Only a recorder that *holds* can warn, and that is the point rather than a
    convenience: a non-zero gap on a recorder that covers its opening means the
    cover did not land, which is a defect. The same number on a recorder that
    never claimed to cover anything is just a description, and warning about it
    would fire on every take of that medium — the exact way a warning stops
    being read.
    """
    if not isinstance(opening, dict):
        return None
    gap, held = opening.get("gap"), opening.get("held")
    if held is None or not isinstance(gap, (int, float)):
        return None
    if gap < OPENING_WARN_S:
        return None
    note = opening.get("note")
    return (
        f"this take opens on {gap:.2f}s of featureless picture that does not "
        f"change — the app had not painted when the recording started, and the "
        f"opening hold did not cover it" + (f" ({note})" if note else "")
    )


def _beats_within(beats: list[dict], start: float, end: float) -> list[dict]:
    """The beats that **began** inside [start, end], classified.

    Began, not overlapped and not midpoint-inside, and the difference is the
    whole correctness of this. A held stretch begins at the first sample after
    something changed — and the thing that changed is very often the verb
    immediately before it. Measured on a healthy fixture: `run("seq 1 4")`
    spanning 2.32-2.85 s, its output landing at 2.50 s, and the stretch
    therefore starting at 2.50 s. By midpoint (2.585 s) that `run` is "inside a
    stretch where nothing changed" — while in fact it is the thing that *ended*
    the previous stretch and started this one. The warning that produced was
    exactly the false positive this correlation exists to remove.

    So a beat qualifies only if it started at or after the stretch did. The
    error this trades for is a miss: a long acting verb that begins before the
    stretch and runs silently through it is not counted. That is the direction
    to be wrong in — quieter than the truth, never louder — and it is also the
    direction the beat/video clock skew (issue #18) pushes an edge case.
    """
    found = []
    for beat in beats or []:
        t_start = beat.get("t_start")
        if not isinstance(t_start, (int, float)):
            continue
        if not start <= float(t_start) <= end:
            continue
        verb = str(beat.get("verb") or "")
        found.append(
            {
                "index": beat.get("index"),
                "verb": verb,
                "acting": verb in CONTENT_ACTING_VERBS,
            }
        )
    return found


def content_report(
    mp4: Path | str,
    rect: tuple[int, int, int, int] | None,
    beats: list[dict] | None = None,
    *,
    floor: float = CONTENT_BLANK_FLOOR,
    sample_fps: int = CONTENT_SAMPLE_FPS,
    static_limit: float = CONTENT_STATIC_WARN_S,
) -> dict:
    """Does this recording show anything? See the section header.

    A function of the mp4, the rect and the beat log, so it can be re-run on a
    demo somebody already has without re-recording:

        doc = json.loads((d / "timeline.json").read_text())
        content_report(d / "demo.mp4", tuple(doc["content"]["rect"]), doc["beats"])

    `rect` is the app's region in *video* pixels, already trimmed by
    `content_rect`; pass None and the report says, in the document itself, that
    nothing was measured and why.

    **`beats` is what makes the held-picture arm a detector rather than a
    timer**, and leaving it out is a supported, conservative choice rather than
    an optimisation: without it `static_for` is still measured and reported, and
    it never warns, because there is no way to tell a demo narrating over a
    rendered screen from a demo nobody can see. See CONTENT_ACTING_VERBS.

    Never raises — the whole body is guarded, not just the ffmpeg call. This
    runs inside `__exit__` before the timeline, the evidence and the review
    frames are written, so an exception escaping here would cost a take every
    artifact that section promises can never be lost.
    """
    try:
        return _content_report(
            mp4, rect, beats, floor=floor, sample_fps=sample_fps,
            static_limit=static_limit,
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return {
            "measured": False,
            "note": (
                f"the picture check itself failed ({type(exc).__name__}: "
                f"{exc}), so nothing is claimed about these frames"
            ),
            "rect": list(rect) if rect else None,
            "sample_fps": sample_fps,
            "frames": 0,
            "score": None,
            "floor": floor,
            "static_for": None,
            "static_from": None,
            "static_beats": None,
            "static_limit": static_limit,
            # Supplied by the recorder in `_measure_content` (issue #119), not
            # measured here: half of it is what the encode *did*, which no
            # amount of looking at the finished file can recover. Present and
            # null rather than absent, so the shape of `content` is the same
            # whoever built it.
            "opening": None,
            "warnings": [],
        }


def _content_report(
    mp4: Path | str,
    rect: tuple[int, int, int, int] | None,
    beats: list[dict] | None,
    *,
    floor: float,
    sample_fps: int,
    static_limit: float,
) -> dict:
    """`content_report` without the guard. Call that, not this."""
    mp4 = Path(mp4)
    report: dict = {
        "measured": False,
        "note": None,
        "rect": list(rect) if rect else None,
        "sample_fps": sample_fps,
        "frames": 0,
        "score": None,
        "floor": floor,
        "static_for": None,
        "static_from": None,
        # The beats the held stretch spans, and whether each acted on the app.
        # Null when no beat log was supplied — which is *not* the same as an
        # empty list, and the difference decides whether the arm may warn.
        "static_beats": None,
        "static_limit": static_limit,
        "opening": None,  # the recorder fills this in — see the guard above
        "warnings": [],
    }
    if rect is None:
        report["note"] = (
            "this recorder does not know where the app sits in the frame, so "
            "nothing about the picture was measured — see content_report()"
        )
        return report
    if not mp4.is_file():
        report["note"] = f"there is no {mp4.name} to measure"
        return report
    try:
        frames = _content_frames(mp4, rect, sample_fps)
    except Exception as exc:  # noqa: BLE001 - a measurement is not a recording
        report["note"] = f"{type(exc).__name__}: {exc}"
        return report
    if len(frames) < 2:
        report["note"] = (
            f"only {len(frames)} frame(s) could be sampled from {mp4.name} at "
            f"{sample_fps} fps, which is too few to say anything"
        )
        report["frames"] = len(frames)
        return report

    report["measured"] = True
    report["frames"] = len(frames)
    # Median, not mean and not min: one blank opening frame must not condemn a
    # take (every web take opens on a page that has not painted yet), and one
    # good frame must not excuse a blank one.
    score = statistics.median(_luma_stddev(f) for f in frames)
    report["score"] = round(score, 2)

    # The longest run of consecutive samples that do not change, measured in
    # gaps rather than frames: two identical samples 0.5 s apart is 0.5 s of
    # held picture, not 1.0 s.
    step = 1.0 / sample_fps
    best_gaps = best_start = run_gaps = run_start = 0
    for i in range(1, len(frames)):
        if _moved_pixels(frames[i - 1], frames[i]) < CONTENT_MOVED_PIXELS:
            run_gaps += 1
        else:
            run_gaps, run_start = 0, i
        if run_gaps > best_gaps:
            best_gaps, best_start = run_gaps, run_start
    held = best_gaps * step
    began, ended = best_start * step, (best_start + best_gaps) * step
    report["static_for"] = round(held, 2)
    report["static_from"] = round(began, 2)

    # What the storyboard was doing while the picture stood still. Verb and
    # index only — never the selector: a selector can hold a value somebody
    # registered as a secret, and this string goes to stderr before the take's
    # scrubbing has run. The index is enough; the beat is in the same file.
    spanned = None if beats is None else _beats_within(beats, began, ended)
    acting = [b for b in (spanned or []) if b["acting"]]
    if spanned is not None:
        report["static_beats"] = spanned[:CONTENT_STATIC_BEATS_MAX]

    warnings: list[str] = []
    if score < floor:
        warnings.append(
            f"there is no picture where the app should be: the content rect "
            f"scores {score:.2f} luma stddev (median of {len(frames)} sampled "
            f"frames over {tuple(rect)}), under the {floor} blank floor. These "
            f"frames are featureless — a page that never painted, a take "
            f"recorded black, or a rect that is not where the app ended up."
        )
    # Both conditions, and the second is the one that stops this being a timer.
    # A long held stretch on its own is *ordinary*: a demo touring a rendered
    # screen with three captions holds it for 20-22 s, which is what the defect
    # this exists for also measures. Only a stretch that swallowed a verb which
    # acted on the app is worth a human's time.
    if held >= static_limit and acting:
        named = ", ".join(f"beat {b['index']} `{b['verb']}`" for b in acting[:4])
        more = f" (+{len(acting) - 4} more)" if len(acting) > 4 else ""
        warnings.append(
            f"the content rect held one picture for {held:.1f}s "
            f"({began:.1f}s-{ended:.1f}s) while {len(acting)} verb(s) that act "
            f"on the app ran inside it: {named}{more}. Nothing changed in the "
            f"measured region while they ran. **What was measured**: the app "
            f"rect {tuple(rect)}, which excludes the recorder's own caption bar "
            f"— so a caption change is invisible here by design and is not what "
            f"this reports. An overlay left up, a modal that never closed and an "
            f"app that stopped painting all look like this; so does a demo that "
            f"genuinely holds still through these verbs. The frames cannot tell "
            f"those apart — open {mp4.name} at {began:.1f}s and look."
        )
    report["warnings"] = warnings
    return report


def merge_content(records: list[dict]) -> dict:
    """The content report for a demo stitched out of several segments.

    `records` are the merged timeline's per-segment records, each with its own
    `content` (the report that segment wrote when it encoded its `.seg.mp4`).
    Nothing is re-measured: a stitched demo can join a web part and a terminal
    part, and there is no single rect for the join. So the merged answer is the
    **worst** of the parts on each arm, and every warning is kept, attributed
    to the segment it came from.

    Under-reports rather than over-reports, in two known ways, both preferred
    to a confident guess: a held stretch spanning a cut is reported as the
    longer of its two halves rather than their sum, and a segment that could
    not be measured at all lowers nothing.
    """
    parts = [
        (record.get("segment"), record.get("content"))
        for record in records
        if isinstance(record.get("content"), dict)
    ]
    measured = [content for _, content in parts if content.get("measured")]
    return {
        "measured": bool(measured),
        "note": (
            None
            if measured
            else "no segment of this demo reported a measured picture — see "
            "each segment's own `content` under `segments`"
        ),
        "rect": None,  # per segment; a merged demo may mix two geometries
        "sample_fps": _common([c.get("sample_fps") for c in measured]),
        "frames": sum(int(c.get("frames") or 0) for c in measured),
        "score": min(
            (c["score"] for c in measured if c.get("score") is not None),
            default=None,
        ),
        "floor": _common([c.get("floor") for c in measured]),
        "static_for": max(
            (c["static_for"] for c in measured if c.get("static_for") is not None),
            default=None,
        ),
        # Both deliberately null: the worst run belongs to one segment's own
        # clock and to that segment's own beat numbering, and restating either
        # against the merged video would be a confidently wrong timestamp and a
        # confidently wrong beat index. The segment's own record has both.
        "static_from": None,
        "static_beats": None,
        "static_limit": _common([c.get("static_limit") for c in measured]),
        # The **first** segment's, not the worst and not a merge, because only
        # segment one's opening is the joined video's opening; every other
        # segment's frame zero lands in the middle of the demo, where a blank
        # frame is a cut and not this phenomenon at all. Null when there are no
        # segments to ask (issue #119).
        "opening": (parts[0][1].get("opening") if parts else None),
        "warnings": [
            f"segment {name!r}: {warning}"
            for name, content in parts
            for warning in (content.get("warnings") or [])
        ],
    }


def print_content_summary(content: dict | None, media: str) -> None:
    """Say what the picture check found, on stderr, unasked.

    The whole point of issue #97 is that nobody was going to open the video, so
    this is printed on every take rather than only when something is wrong: a
    reviewer who has never seen the healthy line has no baseline for the
    unhealthy one.
    """
    if not isinstance(content, dict):
        return
    if not content.get("measured"):
        print(
            f"demo-video: the picture in {media} was not measured — "
            f"{content.get('note')}",
            file=sys.stderr,
        )
        return
    for warning in content.get("warnings") or []:
        print(f"demo-video: WARNING — {media}: {warning}", file=sys.stderr)
    if content.get("warnings"):
        return
    held = content.get("static_for")
    limit = content.get("static_limit")
    # A long held stretch that did *not* warn is worth one clause rather than
    # silence: it is the ordinary shape of a narrated demo, and a reader who
    # only ever sees the number when something is wrong will read it as wrong.
    why = ""
    if isinstance(held, (int, float)) and isinstance(limit, (int, float)):
        if held >= limit:
            why = (
                " — over the "
                f"{limit}s limit, but every beat inside it was narration, a "
                "hold or a wait, which is what a still screen is supposed to "
                "look like"
            )
    # Said on every healthy take that held one, unasked, for the same reason
    # the rest of this line is: the frames somebody watches at the start of
    # this demo are not frames the recording captured, and a recorder that
    # repairs its own output quietly is one nobody can audit (issue #119).
    opening = content.get("opening")
    opened = ""
    if isinstance(opening, dict):
        held_open = opening.get("held")
        if isinstance(held_open, (int, float)) and held_open > 0:
            opened = (
                f"; the first {held_open:.2f}s is a hold — the app had not "
                f"painted yet, so its first painted frame covers the gap"
            )
    print(
        f"{media} shows a picture (content {content.get('score')} over the "
        f"app rect, longest still stretch {held}s{why}{opened})"
    )


def _common(values: list, mixed: object = None) -> object:
    """The value every segment agrees on, or `mixed` when they do not."""
    if not values:
        return mixed
    first = values[0]
    return first if all(v == first for v in values[1:]) else mixed
