"""Composite a take into demo.mp4, the stills, and a one-image contact sheet.

Input is the `take.json` the recorder writes: screencast frames stamped with
wall-clock time, the edit list mapping them onto the video's clock, and every
overlay event in video time. Each output frame is a pure function of its
time, so identical consecutive frames (every hold) are drawn once.
"""

from __future__ import annotations

import bisect
import json
import math
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .clock import SourceMap

FPS = 30
SPOT_IN_S, SPOT_OUT_S = 0.7, 0.6
FADE_S = 0.18
CARD_FADE_S = 0.3
CURSOR_LINGER_S = 2.0
RIPPLE_S = 0.6
PRESS_S = 0.26
NAV_FADE_S = 0.3
SCRIM = (12, 12, 22)
SCRIM_ALPHA = 0.36
# Text smaller than this, in pixels of a 1080p video, is hard to read; a
# spotlight on it pushes in until it reaches this size.
READABLE_PX = 17
# A smaller push-in helps legibility too little to be worth the lost context.
MIN_ZOOM = 1.25


def smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ease(x: float) -> float:
    """Minimum-jerk easing: how a hand starts and stops a movement."""
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


def lerp(a: list[float], b: list[float], p: float) -> list[float]:
    return [u + (v - u) * p for u, v in zip(a, b, strict=True)]


def fade(t: float, start: float, end: float, ramp: float) -> float:
    """1 inside [start, end], ramping over `ramp` at both ends."""
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / ramp, (end - t) / ramp) if ramp > 0 else 1.0


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


class Take:
    def __init__(self, path: Path) -> None:
        self.dir = path.parent
        m = self.m = json.loads(path.read_text())
        g = m["geometry"]
        self.W, self.H = g["size"]
        self.cx, self.cy, self.cw, self.ch = g["content"]
        self.unit = g["unit"]
        self.duration = m["duration"]
        self.accent = hex_rgb(m["accent"])
        self.base = Image.open(self.dir / m["assets"]["window"]).convert("RGB")
        self.body = self.base.getpixel((self.cx + self.cw // 2, self.cy + self.ch // 2))
        self.frames = m["frames"]
        self.times = [f[0] for f in self.frames]
        self.source = SourceMap([tuple(p) for p in m["pieces"]])
        self.cursor = Image.open(self.dir / m["assets"]["cursor"]).convert("RGBA")
        self.hotspot = m["assets"]["hotspot"]
        self.corners = self._corners()
        self.spots = m["spots"]
        self.navs = m.get("navs", [])
        self.captions = m["captions"]
        self.caption_y = g["caption_y"]
        self.activity = self._cursor_activity()

    # -- geometry --------------------------------------------------------------

    def _corners(self) -> list:
        """The window's rounded bottom corners, restored over the content."""
        r = round(self.m["geometry"]["radius"])
        mask = Image.new("L", (2 * r, 2 * r), 255)
        ImageDraw.Draw(mask).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=0)
        left = mask.crop((0, r, r, 2 * r))
        right = mask.crop((r, r, 2 * r, 2 * r))
        bottom = self.cy + self.ch - r
        out = []
        for x, m in ((self.cx, left), (self.cx + self.cw - r, right)):
            out.append(((x, bottom), self.base.crop((x, bottom, x + r, bottom + r)), m))
        return out

    def spot_at(self, spot: dict, t: float) -> tuple[list[float], list[float]]:
        """The spotlit element's (rect, context) at `t`. The recorder
        re-measures after each step; between two measurements it moves."""
        track = spot["track"]
        i = bisect.bisect_right([k[0] for k in track], t) - 1
        if i < 0:
            return track[0][1], track[0][2]
        if i + 1 >= len(track):
            return track[i][1], track[i][2]
        (t0, r0, c0), (t1, r1, c1) = track[i], track[i + 1]
        p = smooth((t - t0) / max(t1 - t0, 1e-6))
        return lerp(r0, r1, p), lerp(c0, c1, p)

    def _spot_camera(self, spot: dict, rect: list[float], context: list[float]) -> tuple:
        """Push in only as far as the element's text needs to be readable -
        not at all when it already is - and keep its context, the row or card
        around it, in view so headings are not cropped."""
        x, y, w, h = rect
        _, _, kw, kh = context
        text = spot.get("text") or READABLE_PX * self.unit
        need = {True: 1.6, False: 1.0}.get(spot.get("zoom"), READABLE_PX * self.unit / text)
        if need < MIN_ZOOM:
            return (1.0, self.cw / 2, self.ch / 2)
        zoom = min(
            need,
            0.6 * self.cw / max(w, 1),
            0.6 * self.ch / max(h, 1),
            0.92 * self.cw / max(kw, 1),
            0.92 * self.ch / max(kh, 1),
            1.6,
        )
        if zoom < MIN_ZOOM:
            return (1.0, self.cw / 2, self.ch / 2)
        half_w, half_h = self.cw / (2 * zoom), self.ch / (2 * zoom)
        cx, cy = x + w / 2, y + h / 2
        # Slide toward the context until it fits, then clamp to the page.
        kx, ky, _, _ = context
        cx = min(max(cx, kx + kw - half_w), kx + half_w) if kw <= 2 * half_w else cx
        cy = min(max(cy, ky + kh - half_h), ky + half_h) if kh <= 2 * half_h else cy
        cx = min(max(cx, half_w), self.cw - half_w)
        cy = min(max(cy, half_h), self.ch - half_h)
        return (zoom, cx, cy)

    def camera(self, t: float, settled: bool = False) -> tuple[float, float, float]:
        weights = []
        for s in self.spots:
            if settled:
                w = 1.0 if s["start"] <= t < s["end"] else 0.0
            else:
                w = smooth((t - s["start"]) / SPOT_IN_S) * (1 - smooth((t - s["end"]) / SPOT_OUT_S))
            if w > 0:
                weights.append((w, self._spot_camera(s, *self.spot_at(s, t))))
        total = sum(w for w, _ in weights)
        if total <= 0:
            return (1.0, self.cw / 2, self.ch / 2)
        # Two spotlights crossing hand over directly, without zooming out between.
        if total > 1:
            weights = [(w / total, c) for w, c in weights]
        cams = [(1 - min(total, 1.0), (1.0, self.cw / 2, self.ch / 2)), *weights]
        z, x, y = (sum(w * c[k] for w, c in cams) for k in range(3))
        # A blend of two in-bounds views can still reach past an edge.
        half_w, half_h = self.cw / (2 * z), self.ch / (2 * z)
        x = min(max(x, half_w), self.cw - half_w)
        y = min(max(y, half_h), self.ch - half_h)
        return (round(z, 4), round(x, 1), round(y, 1))

    def to_view(self, cam, x: float, y: float) -> tuple[float, float]:
        z, cx, cy = cam
        return ((x - cx) * z + self.cw / 2, (y - cy) * z + self.ch / 2)

    def _cursor_activity(self) -> list[tuple[float, float]]:
        spans = [(g["t0"], g["t1"] + CURSOR_LINGER_S) for g in self.m["glides"]]
        spans += [(c[0], c[0] + CURSOR_LINGER_S) for c in self.m["clicks"]]
        spans.sort()
        merged: list[list[float]] = []
        for a, b in spans:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return [(a, b) for a, b in merged]

    # -- assets ----------------------------------------------------------------

    @cache  # noqa: B019 - one Take per process
    def overlay(self, name: str) -> Image.Image:
        return Image.open(self.dir / name).convert("RGBA")

    @lru_cache(maxsize=64)  # noqa: B019 - one Take per process
    def faded(self, name: str, alpha: float) -> Image.Image:
        image = self.overlay(name) if name != "cursor" else self.cursor
        if alpha >= 1:
            return image
        out = image.copy()
        out.putalpha(image.getchannel("A").point(lambda v: round(v * alpha)))
        return out

    @lru_cache(maxsize=16)  # noqa: B019 - one Take per process
    def pointer(self, alpha: float, scale: float) -> Image.Image:
        image = self.faded("cursor", alpha)
        if scale >= 1:
            return image
        size = (round(image.width * scale), round(image.height * scale))
        return image.resize(size, Image.Resampling.LANCZOS)

    @lru_cache(maxsize=4)  # noqa: B019 - one Take per process
    def frame(self, index: int) -> Image.Image:
        return Image.open(self.dir / "frames" / self.frames[index][1]).convert("RGB")

    @lru_cache(maxsize=4)  # noqa: B019 - one Take per process
    def at_rest(self, index: int) -> Image.Image:
        image = self.frame(index)
        if image.size == (2 * self.cw, 2 * self.ch):
            return image.reduce(2)  # a snapshot: a plain 2x2 average is exact
        if image.size != (self.cw, self.ch):
            image = image.resize((self.cw, self.ch), Image.Resampling.BICUBIC)
        return image

    # -- one frame ---------------------------------------------------------------

    def ops(self, t: float, settled: bool = False) -> tuple:
        """Everything that decides the frame at video time `t`, as plain data.

        `settled` is for stills: everything on screen at `t` is shown fully
        arrived - captions and rings faded in, the zoom pushed in - and
        clicks leave no ripple. The recorder's clock rises between any two
        events, so what started by `t` and ends after it is on screen."""

        def shown(item: dict, ramp: float, tail: float = 0.0) -> float:
            start, end = item["start"], item["end"]
            if settled:
                return 1.0 if start <= t < end else 0.0
            return round(fade(t, start, end + tail, ramp), 2) if start <= t <= end + tail else 0.0

        real = self.source(t)
        index = bisect.bisect_right(self.times, real) - 1
        blend = None
        for nav in self.navs:
            # Keep the old page up while the new one loads, then crossfade.
            if nav["start"] <= t < nav["ready"] + NAV_FADE_S:
                old = bisect.bisect_right(self.times, nav["real"]) - 1
                if t < nav["ready"]:
                    index = old
                elif old >= 0 and old != index:
                    blend = (old, round(smooth((t - nav["ready"]) / NAV_FADE_S), 2))
        cam = self.camera(t, settled)
        spots = tuple(
            (tuple(round(v, 1) for v in self.spot_at(s, t)[0]), s["ring"], a)
            for s in self.spots
            if (a := shown(s, 0.3, SPOT_OUT_S)) > 0
        )
        ripples = tuple(
            (c[1], c[2], round((t - c[0]) / RIPPLE_S, 2))
            for c in self.m["clicks"]
            if 0 <= t - c[0] <= RIPPLE_S and not settled
        )
        cursor = None
        pos = self._cursor_at(t)
        if pos:
            alpha = 0.0
            for a, b in self.activity:
                if a <= t <= b + 0.3:
                    alpha = max(alpha, min(1.0, (t - a) / 0.15, (b + 0.3 - t) / 0.3))
            if alpha > 0:
                press = 1.0
                for c in self.m["clicks"]:
                    if 0 <= t - c[0] <= PRESS_S and not settled:
                        press = 1 - 0.2 * math.sin(math.pi * (t - c[0]) / PRESS_S)
                cursor = (round(pos[0], 1), round(pos[1], 1), round(alpha, 2), round(press, 2))
        cards = tuple((c["png"], a) for c in self.m["cards"] if (a := shown(c, CARD_FADE_S)) > 0)
        caps = tuple((c["png"], a) for c in self.captions if (a := shown(c, FADE_S)) > 0)
        badges = tuple(("ff", f["png"], a) for f in self.m["ff"] if (a := shown(f, 0.2)) > 0)
        badges += tuple(("key", k["png"], a) for k in self.m["keys"] if (a := shown(k, 0.15)) > 0)
        return (index, blend, cam, spots, ripples, cursor, cards, caps, badges)

    def _cursor_at(self, t: float) -> tuple[float, float] | None:
        last = None
        for g in self.m["glides"]:
            if g["t0"] > t:
                break
            last = g
        if last is None:
            return None
        if t >= last["t1"]:
            return tuple(last["to"])  # type: ignore[return-value]
        # A hand moves in a slight arc, bowing upward, fast in the middle.
        p = ease((t - last["t0"]) / max(last["t1"] - last["t0"], 1e-6))
        (x0, y0), (x1, y1) = last["from"], last["to"]
        dx, dy = x1 - x0, y1 - y0
        nx, ny = -dy, dx
        if ny > 0 or (ny == 0 and nx < 0):
            nx, ny = -nx, -ny
        reach = math.hypot(dx, dy)
        bow = min(0.12, 90 * self.unit / max(reach, 1)) * math.sin(math.pi * p)
        return (x0 + dx * p + nx * bow, y0 + dy * p + ny * bow)

    def draw(self, ops: tuple) -> Image.Image:
        index, blend, cam, spots, ripples, cursor, cards, caps, badges = ops
        out = self.base.copy()
        if index < 0:
            content = Image.new("RGB", (self.cw, self.ch), self.body)
        else:
            z, cx, cy = cam
            if z > 1.0:
                # Zoom from the captured pixels, which may be denser than the view.
                source = self.frame(index)
                if blend:
                    source = Image.blend(self.frame(blend[0]), source, blend[1])
                k = source.width / self.cw
                hw, hh = self.cw / (2 * z), self.ch / (2 * z)
                content = source.resize(
                    (self.cw, self.ch),
                    Image.Resampling.BICUBIC,
                    box=(
                        k * max(0, cx - hw),
                        k * max(0, cy - hh),
                        k * min(self.cw, cx + hw),
                        k * min(self.ch, cy + hh),
                    ),
                )
            else:
                content = self.at_rest(index)
                content = (
                    Image.blend(self.at_rest(blend[0]), content, blend[1])
                    if blend
                    else content.copy()
                )
        u = self.unit
        radius = round(10 * u)
        stroke = max(2, round(3 * u))
        for rect, ring, alpha in spots:
            x, y, w, h = rect
            pad = 8 * u * cam[0]
            x0, y0 = self.to_view(cam, x, y)
            x1, y1 = self.to_view(cam, x + w, y + h)
            box = (round(x0 - pad), round(y0 - pad), round(x1 + pad), round(y1 + pad))
            # Dim everything, then put the spotlit box back at full brightness.
            lit = content.crop(box)
            a = SCRIM_ALPHA * alpha
            content = content.point([round(v * (1 - a) + c * a) for c in SCRIM for v in range(256)])
            hole = Image.new("L", lit.size, 0)
            ImageDraw.Draw(hole).rounded_rectangle(
                (0, 0, lit.width - 1, lit.height - 1), radius, fill=255
            )
            content.paste(lit, box[:2], hole)
            if ring:
                line = Image.new("L", lit.size, 0)
                ImageDraw.Draw(line).rounded_rectangle(
                    (0, 0, lit.width - 1, lit.height - 1),
                    radius,
                    outline=round(255 * alpha),
                    width=stroke,
                )
                content.paste(self.accent, box, line)
        for x, y, p in ripples:
            # A soft disc that swells and fades, edged by a crisp ring.
            vx, vy = self.to_view(cam, x, y)
            grow = 1 - (1 - min(p, 1.0)) ** 3
            r = round((10 + 34 * grow) * u)
            mask = Image.new("L", (2 * r + 1, 2 * r + 1), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, 2 * r, 2 * r), fill=round(90 * (1 - p)))
            draw.ellipse(
                (0, 0, 2 * r, 2 * r), outline=round(255 * (1 - p) ** 1.5), width=stroke + 1
            )
            content.paste(
                self.accent,
                (round(vx) - r, round(vy) - r, round(vx) + r + 1, round(vy) + r + 1),
                mask,
            )
        if cursor:
            x, y, alpha, press = cursor
            vx, vy = self.to_view(cam, x, y)
            if 0 <= vx <= self.cw and 0 <= vy <= self.ch:
                image = self.pointer(alpha, press)
                hx, hy = self.hotspot[0] * press, self.hotspot[1] * press
                content.paste(image, (round(vx - hx), round(vy - hy)), image)
        for png, alpha in cards:
            image = self.faded(png, alpha)
            content.paste(image, (0, 0), image)
        margin = round(self.ch * 0.045)
        for kind, png, alpha in badges:
            image = self.faded(png, alpha)
            edge = round(18 * u)
            if kind == "ff":
                content.paste(image, (self.cw - image.width - edge, edge), image)
            else:
                content.paste(
                    image, (self.cw - image.width - edge, self.ch - image.height - margin), image
                )
        out.paste(content, (self.cx, self.cy))
        for position, patch, mask in self.corners:
            out.paste(patch, position, mask)
        for png, alpha in caps:
            image = self.faded(png, alpha)
            xy = ((self.W - image.width) // 2, self.caption_y - image.height // 2)
            out.paste(image, xy, image)
        return out

    def at(self, t: float, settled: bool = False) -> Image.Image:
        return self.draw(self.ops(t, settled))

    # -- outputs -------------------------------------------------------------------

    def video(self, path: Path) -> None:
        count = max(1, math.ceil(self.duration * FPS))
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{self.W}x{self.H}",
            "-r",
            str(FPS),
            "-i",
            "-",
        ]
        audio = self.m["audio"]
        for clip in audio:
            cmd += ["-i", clip["path"]]
        # Threaded colour conversion: single-threaded, it is slower than x264.
        chains = ["[0:v]scale=threads=8:out_color_matrix=bt709:out_range=tv,format=yuv420p[v]"]
        maps = ["-map", "[v]"]
        if audio:
            chains += [
                f"[{i + 1}:a]adelay={round(c['t'] * 1000)}:all=1[a{i}]" for i, c in enumerate(audio)
            ]
            mix = "".join(f"[a{i}]" for i in range(len(audio)))
            chains.append(f"{mix}amix=inputs={len(audio)}:normalize=0:duration=longest,apad[aout]")
            maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
        cmd += [
            "-filter_threads",
            "8",
            "-filter_complex",
            ";".join(chains),
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "superfast",
            "-crf",
            "20",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-t",
            f"{count / FPS:.3f}",
            "-movflags",
            "+faststart",
            str(path),
        ]
        # Runs of identical frames are drawn once. Frames are drawn a few ahead
        # in threads (Pillow releases the GIL) while ffmpeg takes the last.
        runs: list[list] = []
        for i in range(count):
            ops = self.ops(i / FPS)
            if runs and runs[-1][0] == ops:
                runs[-1][1] += 1
            else:
                runs.append([ops, 1])
        encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                ahead: deque = deque()
                pending = iter(runs)
                for ops, n in pending:
                    ahead.append((pool.submit(self.draw, ops), n))
                    if len(ahead) >= 8:
                        break
                while ahead:
                    future, n = ahead.popleft()
                    data = future.result().tobytes()
                    for ops, m in pending:
                        ahead.append((pool.submit(self.draw, ops), m))
                        break
                    for _ in range(n):
                        encoder.stdin.write(data)
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise SystemExit("demo-video: ffmpeg failed to encode the video")

    def moments(self) -> list[tuple[float, str]]:
        """One settled frame per caption, card and still, for review."""
        points = [(max(c["start"], c["end"] - FADE_S - 0.1), c["text"]) for c in self.captions]
        points += [((c["start"] + c["end"]) / 2, "[card] " + c["text"]) for c in self.m["cards"]]
        points += [(s["t"], "[still] " + s["name"]) for s in self.m["shots"]]
        points.sort()
        kept: list[tuple[float, str]] = []
        for t, label in points:
            if kept and t - kept[-1][0] < 0.3:
                kept[-1] = (kept[-1][0], kept[-1][1] + " / " + label)
            else:
                kept.append((max(0.0, t), label))
        return kept or [(self.duration / 2, "")]

    def tiles(self) -> list[tuple[float, str, Image.Image]]:
        """The review moments as full frames. A moment that looks the same as
        the one before it (a still taken during a caption) shares its tile."""
        out: list[tuple[float, str, Image.Image]] = []
        last = None
        for t, label in self.moments():
            image = self.at(t, settled=True)
            thumb = image.resize((96, 54), Image.Resampling.BOX).convert("L")
            if last is not None and _same(last, thumb):
                t0, label0, image0 = out[-1]
                out[-1] = (t0, f"{label0} / {label}", image0)
                continue
            out.append((t, label, image))
            last = thumb
        return out

    def sheet(self, path: Path) -> None:
        tiles = self.tiles()
        # Long demos get smaller tiles, so the sheet costs fewer image tokens.
        cols, tile_w = (5, 384) if len(tiles) > 12 else (4, 480) if len(tiles) > 6 else (3, 480)
        tile_h = round(tile_w * self.H / self.W)
        label_h = 50
        rows = math.ceil(len(tiles) / cols)
        sheet = Image.new(
            "RGB",
            (cols * tile_w + (cols + 1) * 8, rows * (tile_h + label_h) + (rows + 1) * 8),
            (245, 245, 248),
        )
        font = ImageFont.load_default(size=15)
        draw = ImageDraw.Draw(sheet)
        for i, (t, label, image) in enumerate(tiles):
            x = 8 + (i % cols) * (tile_w + 8)
            y = 8 + (i // cols) * (tile_h + label_h + 8)
            sheet.paste(image.resize((tile_w, tile_h), Image.Resampling.LANCZOS), (x, y))
            text = f"{i + 1}. {t:5.1f}s  {label}"
            lines = _wrap(draw, text, font, tile_w - 4)[:2]
            for j, line in enumerate(lines):
                draw.text((x + 2, y + tile_h + 4 + j * 19), line, fill=(30, 30, 40), font=font)
        sheet.save(path)

    def timeline(self, path: Path) -> None:
        lines = [f"# {self.duration:.1f}s", "", "| time | step |", "|---|---|"]
        for t, label in self.m["steps"]:
            lines.append(f"| {t:6.1f} | {label.replace('|', '/')} |")
        path.write_text("\n".join(lines) + "\n")


def _same(a: Image.Image, b: Image.Image) -> bool:
    """Two thumbnails a viewer would call the same frame."""
    diff = ImageChops.difference(a, b)
    return (
        sum(diff.point(lambda v: 255 if v > 24 else 0).getdata()) / 255 < 0.01 * a.width * a.height
    )


def _wrap(draw, text: str, font, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    if len(lines) > 2:
        lines[1] = lines[1][: max(0, len(lines[1]) - 1)] + "…"
    return lines


def main(argv: list[str]) -> int:
    manifest = Path(argv[1])
    started = time.time()
    take = Take(manifest)
    m = take.m
    out = Path(m["out"])
    images = out / "images"
    images.mkdir(parents=True, exist_ok=True)
    names = {s["name"] for s in m["shots"]}
    for stale in images.glob("*.png"):
        if stale.stem not in names:
            stale.unlink()
    # Default PNG compression: `optimize` is 5x slower for 5% smaller files.
    with ThreadPoolExecutor(max_workers=4) as pool:
        saves = [
            pool.submit(take.at(shot["t"], settled=True).save, images / f"{shot['name']}.png")
            for shot in m["shots"]
        ]
        for save in saves:
            save.result()
    take.sheet(out / "sheet.png")
    take.timeline(out / "timeline.md")
    (out / "failure.png").unlink(missing_ok=True)
    if not m["draft"]:
        take.video(out / "demo.mp4")
    rendered = time.time() - started

    what = "draft (no video)" if m["draft"] else f"demo.mp4 {take.duration:.1f}s {take.W}x{take.H}"
    print(f"demo-video: {what}  (take {m['take_s']:.0f}s, render {rendered:.0f}s)")
    print(f"  review: {out / 'sheet.png'} - one frame per caption; steps in timeline.md")
    if m["shots"]:
        print(f"  stills: {len(m['shots'])} in {images}")
    for f in m["ff"]:
        real = f["speed"] * (f["end"] - f["start"])
        print(
            f"  fast-forward at {f['start']:.1f}s: {real:.0f}s of waiting shown in {f['end'] - f['start']:.1f}s"
        )
    small = [
        s["text"]
        for s in take.spots
        if s.get("zoom") is None
        and take._spot_camera(s, *take.spot_at(s, s["start"] + SPOT_IN_S))[0] > 1
    ]
    if len(small) * 2 > len(take.spots):
        # Zooming at every step reads as restless; bigger text in the app is better.
        px = sorted(small)[len(small) // 2] / take.unit
        print(
            f"  note: {len(small)} of {len(take.spots)} spotlights zoom, their text is {px:.0f}px "
            f"(readable: {READABLE_PX}px); show it bigger in the app itself if it can"
        )
    if take.duration > 90:
        print(f"  note: {take.duration:.0f}s is long for a demo; 30-90s holds attention")
    problems = m["problems"]
    if problems:
        print(f"  warn: {len(problems)} problem(s) on the page, first: {problems[0][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
