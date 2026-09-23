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
from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .clock import SourceMap

FPS = 30
SPOT_IN_S, SPOT_OUT_S = 0.7, 0.6
FADE_S = 0.18
CARD_FADE_S = 0.3
CURSOR_LINGER_S = 2.0
RIPPLE_S = 0.45
SCRIM = (12, 12, 22)
SCRIM_ALPHA = 0.36


def smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


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
        self.spots = [dict(s, cam=self._spot_camera(s["rect"])) for s in m["spots"]]
        self.captions = [dict(c, top=self._caption_on_top(c)) for c in m["captions"]]
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

    def _spot_camera(self, rect: list[float]) -> tuple[float, float, float]:
        x, y, w, h = rect
        zoom = min(0.6 * self.cw / max(w, 1), 0.6 * self.ch / max(h, 1), 1.6)
        if zoom < 1.12:
            return (1.0, self.cw / 2, self.ch / 2)
        half_w, half_h = self.cw / (2 * zoom), self.ch / (2 * zoom)
        cx = min(max(x + w / 2, half_w), self.cw - half_w)
        cy = min(max(y + h / 2, half_h), self.ch - half_h)
        return (zoom, cx, cy)

    def camera(self, t: float) -> tuple[float, float, float]:
        weights = []
        for s in self.spots:
            w = smooth((t - s["start"]) / SPOT_IN_S) * (1 - smooth((t - s["end"]) / SPOT_OUT_S))
            if w > 0:
                weights.append((w, s["cam"]))
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

    def _caption_on_top(self, caption: dict) -> bool:
        """Move a caption to the top when a spotlight sits where it would go."""
        png = self.overlay(caption["png"])
        band = self.ch - png.height - self.ch * 0.08
        for s in self.spots:
            if s["start"] < caption["end"] and s["end"] > caption["start"]:
                x, y, w, h = s["rect"]
                _, y1 = self.to_view(s["cam"], x + w, y + h)
                if y1 > band:
                    return True
        return False

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

    @lru_cache(maxsize=4)  # noqa: B019 - one Take per process
    def frame(self, index: int) -> Image.Image:
        image = Image.open(self.dir / "frames" / self.frames[index][1]).convert("RGB")
        if image.size != (self.cw, self.ch):
            image = image.resize((self.cw, self.ch), Image.Resampling.LANCZOS)
        return image

    # -- one frame ---------------------------------------------------------------

    def ops(self, t: float) -> tuple:
        """Everything that decides the frame at video time `t`, as plain data."""
        real = self.source(t)
        index = bisect.bisect_right(self.times, real) - 1
        cam = self.camera(t)
        spots = tuple(
            (
                tuple(s["rect"]),
                s["ring"],
                round(fade(t, s["start"], s["end"] + SPOT_OUT_S, 0.3), 2),
                cam,
            )
            for s in self.spots
            if s["start"] <= t <= s["end"] + SPOT_OUT_S
        )
        ripples = tuple(
            (c[1], c[2], round((t - c[0]) / RIPPLE_S, 2))
            for c in self.m["clicks"]
            if 0 <= t - c[0] <= RIPPLE_S
        )
        cursor = None
        pos = self._cursor_at(t)
        if pos:
            alpha = 0.0
            for a, b in self.activity:
                if a <= t <= b + 0.3:
                    alpha = max(alpha, min(1.0, (t - a) / 0.15, (b + 0.3 - t) / 0.3))
            if alpha > 0:
                cursor = (round(pos[0], 1), round(pos[1], 1), round(alpha, 2))
        cards = tuple(
            (c["png"], round(fade(t, c["start"], c["end"], CARD_FADE_S), 2))
            for c in self.m["cards"]
            if c["start"] <= t <= c["end"]
        )
        caps = tuple(
            (c["png"], c["top"], round(fade(t, c["start"], c["end"], FADE_S), 2))
            for c in self.captions
            if c["start"] <= t <= c["end"]
        )
        badges = tuple(
            ("ff", f["png"], round(fade(t, f["start"], f["end"], 0.2), 2))
            for f in self.m["ff"]
            if f["start"] <= t <= f["end"]
        )
        badges += tuple(
            ("key", k["png"], round(fade(t, k["start"], k["end"], 0.15), 2))
            for k in self.m["keys"]
            if k["start"] <= t <= k["end"]
        )
        return (index, cam, spots, ripples, cursor, cards, caps, badges)

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
        p = smooth((t - last["t0"]) / max(last["t1"] - last["t0"], 1e-6))
        (x0, y0), (x1, y1) = last["from"], last["to"]
        return (x0 + (x1 - x0) * p, y0 + (y1 - y0) * p)

    def draw(self, ops: tuple) -> Image.Image:
        index, cam, spots, ripples, cursor, cards, caps, badges = ops
        out = self.base.copy()
        if index < 0:
            content = Image.new("RGB", (self.cw, self.ch), self.body)
        else:
            source = self.frame(index)
            z, cx, cy = cam
            if z > 1.0:
                hw, hh = self.cw / (2 * z), self.ch / (2 * z)
                content = source.resize(
                    (self.cw, self.ch),
                    Image.Resampling.BICUBIC,
                    box=(
                        max(0, cx - hw),
                        max(0, cy - hh),
                        min(self.cw, cx + hw),
                        min(self.ch, cy + hh),
                    ),
                )
            else:
                content = source.copy()
        u = self.unit
        radius = round(10 * u)
        stroke = max(2, round(3 * u))
        for rect, ring, alpha, _ in spots:
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
            vx, vy = self.to_view(cam, x, y)
            r = round((8 + 26 * smooth(p)) * u)
            ring_mask = Image.new("L", (2 * r + 1, 2 * r + 1), 0)
            ImageDraw.Draw(ring_mask).ellipse(
                (0, 0, 2 * r, 2 * r), outline=round(200 * (1 - p)), width=stroke
            )
            content.paste(
                self.accent,
                (round(vx) - r, round(vy) - r, round(vx) + r + 1, round(vy) + r + 1),
                ring_mask,
            )
        if cursor:
            x, y, alpha = cursor
            vx, vy = self.to_view(cam, x, y)
            if 0 <= vx <= self.cw and 0 <= vy <= self.ch:
                image = self.faded("cursor", alpha)
                content.paste(
                    image, (round(vx - self.hotspot[0]), round(vy - self.hotspot[1])), image
                )
        for png, alpha in cards:
            image = self.faded(png, alpha)
            content.paste(image, (0, 0), image)
        margin = round(self.ch * 0.045)
        for png, top, alpha in caps:
            image = self.faded(png, alpha)
            x = (self.cw - image.width) // 2
            y = margin if top else self.ch - image.height - margin
            content.paste(image, (x, y), image)
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
        return out

    def at(self, t: float) -> Image.Image:
        return self.draw(self.ops(t))

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
            chains.append(f"{mix}amix=inputs={len(audio)}:normalize=0:duration=longest[aout]")
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
        encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        last_ops, last_bytes = None, b""
        try:
            for i in range(count):
                ops = self.ops(i / FPS)
                if ops != last_ops:
                    last_ops, last_bytes = ops, self.draw(ops).tobytes()
                encoder.stdin.write(last_bytes)
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

    def sheet(self, path: Path) -> None:
        moments = self.moments()
        cols = 4 if len(moments) > 6 else 3
        tile_w = 480
        tile_h = round(tile_w * self.H / self.W)
        label_h = 50
        rows = math.ceil(len(moments) / cols)
        sheet = Image.new(
            "RGB",
            (cols * tile_w + (cols + 1) * 8, rows * (tile_h + label_h) + (rows + 1) * 8),
            (245, 245, 248),
        )
        font = ImageFont.load_default(size=15)
        draw = ImageDraw.Draw(sheet)
        for i, (t, label) in enumerate(moments):
            x = 8 + (i % cols) * (tile_w + 8)
            y = 8 + (i // cols) * (tile_h + label_h + 8)
            sheet.paste(self.at(t).resize((tile_w, tile_h), Image.Resampling.LANCZOS), (x, y))
            text = f"{i + 1}. {t:5.1f}s  {label}"
            lines = _wrap(draw, text, font, tile_w - 4)[:2]
            for j, line in enumerate(lines):
                draw.text((x + 2, y + tile_h + 4 + j * 19), line, fill=(30, 30, 40), font=font)
        sheet.save(path, optimize=True)

    def timeline(self, path: Path) -> None:
        lines = [f"# {self.duration:.1f}s", "", "| time | step |", "|---|---|"]
        for t, label in self.m["steps"]:
            lines.append(f"| {t:6.1f} | {label.replace('|', '/')} |")
        path.write_text("\n".join(lines) + "\n")


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
    for shot in m["shots"]:
        take.at(shot["t"]).save(images / f"{shot['name']}.png", optimize=True)
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
    if take.duration > 90:
        print(f"  note: {take.duration:.0f}s is long for a demo; 30-90s holds attention")
    problems = m["problems"]
    if problems:
        print(f"  warn: {len(problems)} problem(s) on the page, first: {problems[0][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
