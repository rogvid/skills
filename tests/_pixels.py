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


def to_video_rect(rect: Rect, geom: dict, frame_size: tuple[int, int]) -> Rect:
    """A page-space rect, mapped to where it lands in the composited mp4.

    The web recorder scales the page into a window (~0.8) and overlays it on a
    background, so a rect read off the live page is not where those pixels are
    in demo.mp4. Derived from the recorder's own geometry rather than a
    hardcoded factor, so a change to the window carries this with it.
    """
    width, height = frame_size
    sx, sy = geom["appw"] / width, geom["apph"] / height
    x, y, w, h = rect
    return (
        int(geom["appx"] + x * sx),
        int(geom["appy"] + y * sy),
        max(2, int(w * sx)),
        max(2, int(h * sy)),
    )


def caption_band(frame_size: tuple[int, int]) -> Rect:
    """The strip of a full still that holds the burned-in caption bar.

    Covers both recorders: the web caption sits 44 px off the page bottom and
    the terminal's 88 px, and both boxes are around 70 px tall.
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

# And where the window's body is read: a band below the app rect, inset from
# the left and right so the window's rounded corners and its drop shadow stay
# out of the mean. Below rather than above because the title bar up there is a
# different colour again and carries text and three coloured dots; this band is
# flat window body and nothing else.
#
# **Nothing the card does can paint here** — the pad is part of the frame still
# ffmpeg composites the app video *onto*, a different layer entirely. That is
# what makes the reading worth grading against the card: the two bands are the
# two encoder paths of #301, one each, and the claim is that they agree.
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


def frame_band(app: Rect, win: Rect) -> Rect | None:
    """The band of the window's body this reads the frame's colour out of.

    Between the bottom of the app rect and the bottom of the window — the pad
    the recorder leaves so the window's rounded corners stay visible around the
    video. `None` when there is no pad to read.

    Graded against the card by `check_criterion_card`'s second claim, and
    printed beside it on a healthy run.
    """
    ax, ay, aw, ah = app
    _, wy, _, wh = win
    top, bottom = ay + ah, wy + wh
    if bottom - top < 6:
        return None
    fx, fw = FRAME_BAND
    # Inset from the pad's own edges: the outermost row blends into the drop
    # shadow, and the innermost into the video above it.
    return (ax + int(aw * fx), top + 2, max(8, int(aw * fw)), bottom - top - 4)


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
