"""The caption: a pill composited over the finished frame.

The caption used to be drawn *in* the recorded page — a floating pill over
the app rect's bottom edge (#403), or a band reserved below it (#358). Both
are page pixels, and the camera (camera.py) scales the composited frame, so
a push-in over an element near the top of the app cropped the caption out
of the take entirely: measured on the ticket-queue empty-state demo, where
the line "Now the queue says why it is empty." was off screen for the whole
spotlight that it was explaining.

So the pill is post-production, the camera's shape: the browser renders it
(it is the same CSS the page used, so the typography is unchanged), the
recorder logs each line as an interval on the timeline, and the video pass
lays the pill over the frame **after** the zoom, at the bottom of the
frame, where nothing the camera does can reach it.

Two things are deliberately given up, and both are stated rather than
hidden:

  * **The pill no longer blurs what is behind it.** `backdrop-filter`
    needs a backdrop, and a PNG rendered on transparency has none. The
    fill stays the same translucent dark.
  * **The line is no longer in the recorded page's DOM**, so the evidence
    file's caption is read from the pill document the compositor draws
    from rather than from the frame's own document. It is still a browser
    -rendered element carrying that text, and it is the exact image the
    viewer sees - but it is one document removed from the frame, which is
    a step back from #134's rule. Reading the composited pill out of the
    frames closes that gap; this repository's `tests/pixel` (not shipped
    with the installed skill) is where that reading belongs.

The crossfade is the DOM one's, reproduced: at a line change both pills are
up for `CAPTION_FADE_S`, the old fading out while the new fades in. So an
interval's pill is drawn from `t_start` until `t_end + CAPTION_FADE_S`.
"""

from __future__ import annotations

from pathlib import Path

# The crossfade, matching the `transition: opacity .3s ease` the stacked
# caption layers in chrome.py used.
CAPTION_FADE_S = 0.3

# How far the pill PNG's bottom edge sits above the frame's, in output-frame
# pixels. The pill is placed against the *frame*, not the window: it is a
# subtitle now, and the window may be pushed in under it. The PNG carries
# `chrome.CAPTION_PILL_PAD_PX` of shadow room below the pill itself, so a
# viewer measures that much more than this number.
CAPTION_FRAME_INSET_PX = 18


def png_dimensions(path: Path) -> tuple[int, int]:
    """A PNG's pixel size, read off its IHDR chunk.

    Sixteen bytes of header rather than an ffprobe process: this is asked
    once per caption line, on the take's own clock, and the pill is a file
    this package wrote moments earlier.
    """
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG — the caption pill was not written")
    return (
        int.from_bytes(header[16:20], "big"),
        int.from_bytes(header[20:24], "big"),
    )


def caption_filter(
    events: list[dict],
    *,
    base: str,
    first_input: int,
    out_label: str = "v",
) -> tuple[list[str], str] | None:
    """The overlay chain that lays this take's caption pills on the video.

    `events` is the timeline's `captions` list — `{"t_start", "t_end",
    "png"}`, times in seconds on the video's clock and `png` the pill the
    browser rendered for that line. `base` is the label of the video the
    pills go over, `first_input` the index the caller's first pill input
    will have in the ffmpeg command (the take's video is 0), and
    `out_label` the label the last overlay writes.

    Returns `(inputs, chain)` — the ffmpeg input arguments to splice in
    ahead of `-filter_complex`, in order, and the filter chain — or None
    for a take with no caption, where the caller encodes exactly as it did
    before the pill existed.

    Each pill rides an input of its own, **bounded to its own interval**:
    `-loop 1` with `-t` for the length it is up and `-itsoffset` for when
    it starts, so its frames carry the take's own timestamps and `overlay`
    pairs each with the frame it belongs over. The bound is not a detail —
    an unbounded `-loop 1` input never ends, and six of them on a 26 s take
    ran the encode past 1.4 GB of output and were killed for memory before
    the file was closed. `eof_action=pass:repeatlast=0` is the other half:
    without it `overlay` would hold a finished pill's last frame on screen
    for the rest of the take.

    The position is computed by ffmpeg from the two streams' sizes
    (`W`/`w`), so a pill that wrapped to two lines needs no measurement
    here.
    """
    ordered = sorted(events, key=lambda e: e["t_start"])
    for event in ordered:
        if event["t_end"] <= event["t_start"]:
            raise ValueError(
                f"caption event ends at {event['t_end']} at or before it "
                f"starts ({event['t_start']}) — a line with no length is "
                f"not on screen"
            )
    if not ordered:
        return None
    inputs: list[str] = []
    parts: list[str] = []
    label = base
    for index, event in enumerate(ordered):
        up = event["t_end"] + CAPTION_FADE_S - event["t_start"]
        inputs += [
            "-loop",
            "1",
            "-t",
            f"{up:.3f}",
            "-itsoffset",
            f"{event['t_start']:.3f}",
            "-i",
            str(Path(event["png"])),
        ]
        stream = first_input + index
        pill = f"cap{index}"
        # The fade out starts at t_end, so the line holds its full interval
        # and then crossfades with the next one, which fades in from the
        # same instant — the stacked layers' behaviour in chrome.py.
        parts.append(
            f"[{stream}:v]format=rgba,"
            f"fade=t=in:st={event['t_start']:.3f}:d={CAPTION_FADE_S}:alpha=1,"
            f"fade=t=out:st={event['t_end']:.3f}:d={CAPTION_FADE_S}:alpha=1"
            f"[{pill}]"
        )
        nxt = out_label if index == len(ordered) - 1 else f"capped{index}"
        parts.append(
            f"[{label}][{pill}]overlay=x=(W-w)/2:y=H-h-{CAPTION_FRAME_INSET_PX}"
            f":eof_action=pass:repeatlast=0"
            f":enable='between(t,{event['t_start']:.3f},"
            f"{event['t_end'] + CAPTION_FADE_S:.3f})'[{nxt}]"
        )
        label = nxt
    return inputs, ";".join(parts)
