"""The camera: a post-production push-in over each spotlighted element.

The zoom this replaces was live DOM — `<body>` scaled 1.06 around the
element's centre while the spotlight was up — and it gave the viewer
nothing: the element sat at the transform's origin, so it did not move,
and 6% of a 60 px chip is invisible. What a viewer actually saw was the
surrounding layout shifting and clipping under the window chrome, which
reads as jitter, not intent. A camera move has to scale the *composited*
frame — window chrome included — and the DOM cannot reach past the page
into the frame around it. That is the limit where editing stops being
Playwright's job.

So the camera is post-production, Screen Studio's shape: capture raw,
edit afterwards. `spotlight()` logs each interval as geometry on the
timeline (the `camera` key in timeline.json, in output-frame pixels);
and `_convert` renders the filter this module builds — an eased push-in
to `CAMERA_ZOOM` over each event, centred on the element, by `zoompan`.

**The push is rendered from 1x footage, and that is a measured limit,
not an oversight.** A 1.3x push on a 1280 px take shows a 984 px crop
upscaled, so the move is softer than the static footage around it —
for the half second of the ease, which is how every screen-recorder
push-in looks. True supersampling was tried and measured out: capture
at `device_scale_factor=2` produces a 2x canvas with the same 1x
detail in its top-left corner — Playwright's record_video pipeline
captures the page surface at CSS resolution and the device scale adds
no detail to the video. The two honest ways past that are a 2x-CSS
viewport (doubles every CSS coordinate; responsive apps reflow, which
changes what the demo shows) or a self-owned CDP screencast capture
(machinery of its own). Neither is this module's job today.

The take itself stays honest: nothing on screen moves that the app did
not do. The move is added where motion lives — the encode — from
geometry the recorder measured while the page was alive, and the
timeline publishes that geometry so a move can be re-rendered or
audited without the take.

`zoompan` needs one courtesy: it re-stamps output frames at its `fps`
rather than following the input's timestamps, and a screencast's webm
is variable-rate — so `fps` normalizes the stream by PTS first, and
only then does `zoompan`'s sequential re-stamp become an identity
mapping. Without that order a gap in the screencast compresses the
take and the narration mix drifts off its captions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# How far the camera pushes in over a spotlighted element. 1.3 is the
# smallest move that reads as a decision rather than a tremor: the DOM
# zoom this replaces was 1.06 and measured as nothing (frames either
# side of a spotlight differ mostly by the outline, not the zoom).
CAMERA_ZOOM = 1.3

# How long the push-in and the pull-back each take, in seconds. Long
# enough to read as one motion at 25 fps (12-13 frames), short next to
# the shortest caption hold.
CAMERA_EASE_S = 0.5


def video_dimensions(path: Path) -> tuple[int, int]:
    """The pixel size of a recorded file, off ffprobe."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    width, height = out.split(",")
    return int(width), int(height)


def _smoothstep(expr: str) -> str:
    """The ease: smoothstep of a progress expression already shaped so
    that it rises 0→1 over the push, holds at 1, and falls 1→0 over the
    pull — `min` of the time from both ends, clamped to 0..1."""
    u = f"clip({expr},0,1)"
    return f"{u}*{u}*(3-2*{u})"


def camera_filter(
    events: list[dict],
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    fps: int = 25,
) -> str | None:
    """The video filter chain that renders this take's camera moves.

    `events` is the timeline's `camera` list: `{"t_start", "t_end",
    "rect": [x, y, w, h]}`, times in seconds and the rect in
    **output-frame** pixels — the coordinates a reader maps onto
    demo.mp4. Rects are scaled up to source pixels here, once, at the
    only place that knows both sizes. Returns None for a take with no
    events, and the caller encodes exactly as it did before the camera
    existed.

    The chain is `fps` (PTS-normalize, see the module note) then one
    `zoompan` carrying every event: `z` is 1 plus the sum of each
    event's eased push — events do not overlap, so at most one term is
    non-zero — and `x`/`y` are the same weights times each event's
    clamped centred offset. A weight of 0 contributes a literal 0, so
    between events the camera sits at z=1, x=0, y=0: the identity. The
    offsets read `zoom`, zoompan's own per-frame value for this frame's
    z, so the pan and the push stay one motion.
    """
    if not events:
        return None
    ordered = sorted(events, key=lambda e: e["t_start"])
    for i in range(len(ordered) - 1):
        earlier, later = ordered[i], ordered[i + 1]
        if later["t_start"] < earlier["t_end"]:
            raise ValueError(
                "camera events overlap — one spotlight cannot still be "
                f"open at [{later['t_start']}, {later['t_end']}] when "
                f"[{earlier['t_start']}, {earlier['t_end']}] is still "
                "running; the push-in weights would sum past CAMERA_ZOOM"
            )
    for event in ordered:
        x, y, w, h = event["rect"]
        if w <= 0 or h <= 0:
            raise ValueError(
                f"camera event [{event['t_start']}, {event['t_end']}] has a "
                f"degenerate rect {event['rect']} — nothing to centre on"
            )
        if event["t_end"] <= event["t_start"]:
            raise ValueError(
                f"camera event ends at {event['t_end']} at or before it "
                f"starts ({event['t_start']})"
            )
    scale_x = src_w / out_w
    scale_y = src_h / out_h
    push = f"{CAMERA_ZOOM - 1:.2f}"
    zooms: list[str] = []
    xs: list[str] = []
    ys: list[str] = []
    for event in ordered:
        ease = (
            f"min((time-{event['t_start']:.3f})/{CAMERA_EASE_S},"
            f"({event['t_end']:.3f}-time)/{CAMERA_EASE_S})"
        )
        weight = _smoothstep(ease)
        cx = (event["rect"][0] + event["rect"][2] / 2) * scale_x
        cy = (event["rect"][1] + event["rect"][3] / 2) * scale_y
        zooms.append(weight)
        xs.append(f"{weight}*clip({cx:.1f}-iw/(2*zoom),0,iw-iw/zoom)")
        ys.append(f"{weight}*clip({cy:.1f}-ih/(2*zoom),0,ih-ih/zoom)")
    z = f"1+{push}*({'+'.join(zooms)})"
    x = "+".join(xs)
    y = "+".join(ys)
    return (
        f"fps={fps},"
        f"zoompan=z='{z}':x='{x}':y='{y}'"
        f":d=1:s={out_w}x{out_h}:fps={fps}"
    )
