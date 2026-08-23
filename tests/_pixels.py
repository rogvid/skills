"""The pixel primitives `tests/smoke` grades recordings with.

Lifted out of `tests/smoke` (#324, #349) so the pixel loop can read frames
with the same primitives the smoke suite grades with — two loops, one
toolkit. Everything here is a mechanism: ffmpeg subprocess calls and pure
Python arithmetic, no image library, no extra dependency.

A plain module, imported and never run — deliberately not a PEP 723 script.
The thresholds these readings are compared against are each suite's own
policy and stay with the suite that owns them.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

# x, y, width, height in source-frame pixels.
Rect = tuple[int, int, int, int]

# The luma readings reduce frames to 160x90 8-bit grayscale via ffmpeg and do
# the arithmetic in pure Python.
_GRAY_W, _GRAY_H = 160, 90


def gray_frames(
    path: Path,
    rect: Rect | None = None,
    sample_fps: int | None = None,
    start: float | None = None,
    duration: float | None = None,
) -> list[bytes]:
    """Decode an mp4 or png into 160x90 grayscale frames.

    `rect` crops a region of the source frame *before* scaling. Passing the
    region the app actually occupies is the whole point: the recorder's chrome
    is high-contrast and static, so a whole-frame score is dominated by it and
    cannot tell a blank app from a working one.

    `start`/`duration` cut a window out of the video first. Both are input
    options, so the seek is accurate and the returned frames start at the
    first one at or after `start` — with `sample_fps` set, frame *i* is at
    `start + i / sample_fps`, give or take that one frame.
    """
    chain = []
    if sample_fps:
        chain.append(f"fps={sample_fps}")
    if rect is not None:
        x, y, w, h = rect
        chain.append(f"crop={w}:{h}:{x}:{y}")
    chain += [f"scale={_GRAY_W}:{_GRAY_H}", "format=gray"]
    window: list[str] = []
    if start is not None:
        window += ["-ss", f"{start:.3f}"]
    if duration is not None:
        window += ["-t", f"{duration:.3f}"]
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            *window,
            "-i",
            str(path),
            "-vf",
            ",".join(chain),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg could not decode {path}: "
            f"{proc.stderr.decode(errors='replace').strip()[:300]}"
        )
    size = _GRAY_W * _GRAY_H
    raw = proc.stdout
    return [raw[i : i + size] for i in range(0, len(raw) - size + 1, size)]


def contrast(frame: bytes) -> float:
    """Luma standard deviation. Anything visible scores tens; a flat frame 0."""
    n = len(frame)
    mean = sum(frame) / n
    return math.sqrt(sum((b - mean) ** 2 for b in frame) / n)


def frame_difference(a: bytes, b: bytes) -> float:
    """Mean absolute luma difference between two reduced frames."""
    return sum(abs(x - y) for x, y in zip(a, b, strict=False)) / len(a)


def to_video_rect(rect: Rect, geom: dict) -> Rect:
    """An app-document rect, mapped to where it lands in the recorded frame.

    The app records inside the wrapper's content slot at true pixel size
    (#358, cutover #361), so the mapping is the slot's offset and no scale —
    the deleted composite's ~0.8 factor went with it. Derived from the
    recorder's own geometry rather than hardcoded, so a chrome change
    carries this with it. Rects already in wrapper-page coordinates (a
    Playwright `bounding_box()`, which answers in main-frame coordinates
    even for iframe elements) need no mapping at all.
    """
    x, y, w, h = rect
    return (
        int(geom["appx"] + x),
        int(geom["appy"] + y),
        max(2, int(w)),
        max(2, int(h)),
    )


def caption_band(frame_size: tuple[int, int]) -> Rect:
    """The strip of a full still that holds the caption.

    Covers both recorders: the web caption's reserved band sits ~54-150 px
    off the frame bottom at the default viewport (chrome_geometry), and the
    terminal's in-page bar 88 px off it, ~70 px tall.
    """
    width, height = frame_size
    return (0, max(0, height - 160), width, 140)


# Where in the app rect the strip is read: a band across the top, inset from
# every edge. Above the centred text on purpose — glyphs move the mean by ~5
# levels and by however many words the clause has, which is a reading of the
# sentence and not of the card. Inset from the left and right because the
# composite's edges blend the app into the window frame, and from the top for
# the same reason: the outermost rows of the app video are a chroma blend into
# the window's pad, ~2 px wide once the page is scaled into the window.
CARD_STRIP = (0.10, 0.06, 0.80, 0.12)  # x, y, w, h as fractions of the app rect

# And where the window's body is read: a band of bare window body, inset
# from the left and right so the window's rounded corners and its drop
# shadow stay out of the mean. On a wrapper take that is the window's
# *bottom pad*, below the caption band (each suite's `wrapper_pad_band`
# builds the rect from these fractions): the title bar is a different
# colour again and carries text and three coloured dots, and the strip
# directly below the app rect is the caption band, which carries a bubble
# whenever a line is up.
#
# **Nothing the card does can paint here** — the card layer covers the app
# rect exactly (chrome.py). That is what makes the reading worth grading
# against the card: same encoder, two layers, and the claim is that the one
# declared colour arrives as one (#360; the two-encoder pair this replaced
# is #301's history).
FRAME_BAND = (0.15, 0.70)  # x offset and width, as fractions of the app rect


def strip_rgb(mp4: Path, at: float, rect: Rect) -> tuple[float, float, float] | None:
    """Mean R, G and B over `rect` of the frame at `at` seconds.

    Colour, not luma: the state this has to be told apart from is a card that
    never painted, over a **white** page, and white and warm paper are 8 levels
    apart in red and 31 in blue. A grayscale reading throws away the channel
    that carries the answer.
    """
    x, y, w, h = rect
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(mp4),
            "-vf",
            f"crop={w}:{h}:{x}:{y}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    raw = proc.stdout
    if proc.returncode != 0 or len(raw) < 3:
        return None
    channels = tuple(sum(raw[i::3]) / len(raw[i::3]) for i in range(3))
    return channels  # type: ignore[return-value]


def card_strip(app: Rect) -> Rect:
    """The band of the app rect this reads the card's colour out of."""
    x, y, w, h = app
    fx, fy, fw, fh = CARD_STRIP
    return (
        x + int(w * fx),
        y + int(h * fy),
        max(8, int(w * fw)),
        max(8, int(h * fh)),
    )


def off_card(rgb: tuple[float, float, float], card: tuple[int, int, int]) -> float:
    """How far a reading is from a card's colour, worst channel."""
    return max(abs(value - want) for value, want in zip(rgb, card, strict=True))


def channels_apart(
    one: tuple[float, float, float], other: tuple[float, float, float]
) -> float:
    """How far two *readings* sit apart, worst channel.

    Separate from `off_card` because both sides are measured here rather than
    declared: this is the card against the window body, two encodings compared
    with each other and neither of them a constant.
    """
    return max(abs(a - b) for a, b in zip(one, other, strict=True))


def psnr_db(a: Path, b: Path) -> float | None:
    """ffmpeg's PSNR between two images, in dB. Infinity becomes `math.inf`."""
    done = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(a),
            "-i",
            str(b),
            "-lavfi",
            "psnr",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    found = re.search(r"average:([0-9.]+|inf)", done.stderr)
    if not found:
        return None
    return math.inf if found.group(1) == "inf" else float(found.group(1))
