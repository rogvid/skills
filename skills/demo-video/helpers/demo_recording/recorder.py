"""The recorders. A storyboard drives one inside a `with` block:

    with Recorder(HERE, base_url="http://localhost:3000") as rec:
        rec.goto("/")
        rec.caption("Every open order, newest first.")
        rec.click("role=button[name='New order']")

The take runs as fast as the app allows. Holds, cursor glides and title cards
are inserted into the video afterwards, and long waits on the app become a
short fast-forward, so a take of a one-minute demo takes about as long as the
app needs to do the work.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import inspect_page, narration
from .capture import Screencast
from .clock import FF_REAL_MAX_S, Clock, ff_duration
from .overlays import Overlays, geometry

SKILL_DIR = Path(__file__).resolve().parents[2]
RENDERER = SKILL_DIR / "scripts" / "demo-render"
# Spoken clips, keyed by text and voice, shared by every demo on the machine.
TTS_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "demo-video" / "tts"

SPOT_MIN_S = 1.8
LEGACY = {
    "segment",
    "strict",
    "deterministic",
    "evidence",
    "criteria",
    "ticket",
    "preview",
    "caption_overlay",
    "window_scale",
    "allow_private",
    "stills_only",
    "preset",
    "clock",
    "timezone_id",
    "locale",
    "intro",
    "outro",
    "terminal_title",
    "terminal_prompt",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get("DEMO_VIDEO_" + name)
    return value if value not in (None, "") else default


def _pair(text: str | None, default: tuple[int, int]) -> tuple[int, int]:
    if not text:
        return default
    w, h = text.lower().split("x")
    return int(w), int(h)


def _script_dir() -> Path:
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    return Path(path).resolve().parent if path else Path.cwd()


class _Take:
    """What every medium shares: the clock, captions, cards, stills, and the
    hand-off to the renderer."""

    theme = "light"
    default_viewport = (1440, 810)

    def __init__(
        self,
        out_dir: str | Path | None = None,
        *,
        title: str | None = None,
        size: tuple[int, int] | None = None,
        viewport: tuple[int, int] | None = None,
        pace: float | None = None,
        speech: bool | None = None,
        voice: str | None = None,
        accent: str | None = None,
        **legacy: object,
    ) -> None:
        self.out = Path(out_dir) if out_dir else _script_dir()
        self.title = title or legacy.pop("window_title", None)  # type: ignore[assignment]
        ignored = sorted(k for k in legacy if k in LEGACY)
        unknown = sorted(k for k in legacy if k not in LEGACY)
        if unknown:
            raise TypeError(f"unexpected argument(s): {', '.join(unknown)}")
        if ignored:
            print(f"demo-video: ignoring removed option(s): {', '.join(ignored)}", file=sys.stderr)
        self.size = size or _pair(_env("SIZE"), (1920, 1080))
        self.viewport = viewport or _pair(_env("VIEWPORT"), self.default_viewport)
        self.pace = pace if pace is not None else float(_env("PACE", "1.0") or 1.0)
        self.draft = _env("DRAFT") not in (None, "0")
        self.accent = accent or _env("ACCENT", "#6366f1")
        self._api_key = os.environ.get("ELEVENLABS_API_KEY")
        self.speech = bool(self._api_key) if speech is None else speech
        if self.speech and not self._api_key:
            raise RuntimeError("speech=True needs ELEVENLABS_API_KEY")
        if self.draft:
            self.speech = False
        self.voice = voice or _env("VOICE", narration.DEFAULT_VOICE)
        self.geom = geometry(self.size, self.viewport)
        self.take_dir = self.out / ".take"

        self.clock: Clock | None = None
        self._step = "starting"
        self._steps: list[tuple[float, str]] = []
        self._captions: list[dict] = []
        self._caption: dict | None = None
        self._cards: list[dict] = []
        self._spots: list[dict] = []
        self._spot: dict | None = None
        self._glides: list[dict] = []
        self._clicks: list[float | list] = []
        self._keys: list[dict] = []
        self._ff: list[dict] = []
        self._audio: list[dict] = []
        self._shots: list[dict] = []
        self._problems: list[str] = []
        self._cursor = [self.geom["content"][2] / 2, self.geom["content"][3] * 0.6]
        self._started = time.time()

    # -- lifecycle ------------------------------------------------------------

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        shutil.rmtree(self.take_dir, ignore_errors=True)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        _, _, cw, ch = self.geom["content"]
        vw, vh = self.viewport
        self.context = self.browser.new_context(
            viewport={"width": vw, "height": vh},
            device_scale_factor=self.geom["scale"],
            **self._context_options(),
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(10_000)
        self.page.on("pageerror", lambda e: self._problems.append(f"page error: {e}"))
        self.page.on(
            "console",
            lambda m: m.type == "error" and self._problems.append(f"console error: {m.text}"),
        )
        self.page.on(
            "requestfailed",
            lambda r: self._problems.append(f"request failed: {r.method} {r.url} ({r.failure})"),
        )
        self.screencast = Screencast(self.context, self.page, self.take_dir / "frames", cw, ch)
        self.clock = Clock()
        with self._off_clock():
            self._start()
        return self

    def __exit__(self, kind, error, tb) -> bool:
        if kind is None:
            try:
                self._finish()
            finally:
                self._close()
            return False
        if kind is KeyboardInterrupt:
            self._close()
            return False
        self._report_failure(error)
        self._close()
        if _env("TRACEBACK"):
            return False
        raise SystemExit(1)

    def _close(self) -> None:
        for step in (self._stop, self.browser.close, self._pw.stop):
            try:
                step()
            except Exception:  # noqa: BLE001 - teardown
                pass

    # -- media hooks ----------------------------------------------------------

    def _context_options(self) -> dict:
        return {}

    def _start(self) -> None:
        raise NotImplementedError

    def _stop(self) -> None:
        self.screencast.stop()

    def _tick(self) -> None:
        """Called while real time passes. The terminal pumps its PTY here."""

    def _failure_detail(self) -> str:
        return ""

    # -- time -----------------------------------------------------------------

    def _now(self) -> float:
        assert self.clock is not None
        return self.clock.now()

    def _real(self, seconds: float) -> None:
        """Let `seconds` of wall-clock time pass, recorded at normal speed."""
        end = time.time() + seconds
        while True:
            self._tick()
            remaining = end - time.time()
            if remaining <= 0:
                return
            self.page.wait_for_timeout(min(40.0, remaining * 1000))

    def _settle(self, quiet: float = 0.35, cap: float = 2.5) -> None:
        """Wait until the screen has stopped changing for `quiet` seconds, so
        a debounced search or a transition lands before the next step. The
        still tail shows nothing new, so all but a beat of it is cut."""
        start = time.time()
        while True:
            self._real(0.04)
            last = max(self.screencast.last_arrival, start)
            now = time.time()
            if now - last >= quiet or now - start >= cap:
                break
        tail = max(self.screencast.last_arrival, start) + 0.12
        if time.time() > tail:
            assert self.clock is not None
            self.clock.retime(tail, 0.0)

    def _hold(self, seconds: float) -> None:
        assert self.clock is not None
        self.clock.insert(seconds)

    @contextmanager
    def _app_time(self):
        """Time spent waiting on the app. Short waits play at normal speed;
        long ones become a fast-forward with a badge."""
        assert self.clock is not None
        start = time.time()
        yield
        real = time.time() - start
        if real > FF_REAL_MAX_S:
            a, b = self.clock.retime(start, ff_duration(real))
            if b > a:
                self._ff.append({"start": a, "end": b, "speed": real / (b - a)})

    @contextmanager
    def _off_clock(self):
        """Recorder work that must not show up in the video at all."""
        assert self.clock is not None
        start = time.time()
        yield
        self.clock.retime(start, 0.0)

    def _mark(self, label: str) -> None:
        self._step = label
        self._steps.append((self._now(), label))

    def _reading(self, text: str) -> float:
        return max(1.4, 0.6 + 0.3 * len(text.split())) * self.pace

    def _voice(self, text: str) -> float:
        """Speak `text` from now, when narration is on. Returns its length."""
        if not self.speech:
            return 0.0
        with self._off_clock():
            path = narration.clip(
                text, TTS_CACHE, self._api_key or "", self.voice, narration.DEFAULT_MODEL
            )
            length = narration.duration(path)
        self._audio.append({"t": self._now(), "path": str(path)})
        return length + 0.35

    # -- verbs every medium has -------------------------------------------------

    def caption(self, text: str) -> None:
        """Show `text` as the narrator line. `""` clears it. Each line stays up
        at least as long as it takes to read (or to speak)."""
        self._settle_caption()
        self._mark(f"caption {text!r}" if text else "caption cleared")
        if self._caption:
            self._caption["end"] = self._now()
            self._caption = None
        if text:
            need = max(self._reading(text), self._voice(text))
            self._caption = {"text": text, "start": self._now(), "need": need}
            self._captions.append(self._caption)

    def _settle_caption(self) -> None:
        if self._caption:
            short = self._caption["start"] + self._caption["need"] - self._now()
            if short > 0:
                self._hold(short)

    def hold(self, min_s: float = 1.0) -> None:
        """Hold the frame until the caption has been read (or spoken), and at
        least `min_s`."""
        self._mark("hold")
        remaining = 0.0
        if self._caption:
            remaining = self._caption["start"] + self._caption["need"] - self._now()
        self._hold(max(min_s * self.pace, remaining))

    def pause(self, seconds: float) -> None:
        """Hold the frame for `seconds` (scaled by pace)."""
        self._mark(f"pause {seconds}")
        self._hold(seconds * self.pace)

    def interlude(self, text: str) -> None:
        """A full-window title card, held long enough to read, then taken down."""
        self._mark(f"interlude {text!r}")
        if not text:
            return
        self._settle_caption()
        if self._caption:
            self._caption["end"] = self._now()
            self._caption = None
        start = self._now()
        need = max(self._reading(text) + 0.5, self._voice(text), 2.2 * self.pace)
        self._hold(need)
        self._cards.append({"text": text, "start": start, "end": self._now()})

    def shot(self, name: str) -> None:
        """Save the current frame as `images/<name>.png`."""
        self._mark(f"shot {name}")
        self._shots.append({"t": self._now(), "name": name})

    @contextmanager
    def act(self, label: str):
        """Wrap raw work on `rec.page` that waits on the app, so a long wait
        becomes a fast-forward instead of dead air."""
        self._mark(f"act {label!r}")
        with self._app_time():
            yield

    # -- finishing ----------------------------------------------------------------

    def _finish(self) -> None:
        assert self.clock is not None
        self._step = "finishing"
        self._settle_caption()
        if self._spot:
            self._end_spot()
        if self._caption:
            self._caption["end"] = self._now()
        self._hold(0.6)
        duration = self.clock.finish()
        self._stop()
        with self._off_clock():
            assets = self._render_assets()
        manifest = {
            "out": str(self.out),
            "draft": self.draft,
            "geometry": self.geom,
            "theme": self.theme,
            "accent": self.accent,
            "duration": duration,
            "take_s": round(time.time() - self._started, 1),
            "frames": sorted(self.screencast.frames),
            "pieces": self.clock.pieces,
            "captions": [
                {
                    "start": c["start"],
                    "end": c["end"],
                    "png": assets["captions"][c["text"]],
                    "text": c["text"],
                }
                for c in self._captions
                if c["end"] - c["start"] > 0.05
            ],
            "cards": [dict(c, png=assets["cards"][c["text"]]) for c in self._cards],
            "spots": self._spots,
            "glides": self._glides,
            "clicks": self._clicks,
            "keys": [dict(k, png=assets["badges"][k["text"]]) for k in self._keys],
            "ff": [dict(f, png=assets["badges"][f["text"]]) for f in self._ff],
            "audio": self._audio,
            "shots": self._shots,
            "steps": self._steps,
            "problems": self._problems,
            "assets": {
                "window": assets["window"],
                "cursor": assets["cursor"],
                "hotspot": assets["hotspot"],
            },
        }
        path = self.take_dir / "take.json"
        path.write_text(json.dumps(manifest))
        self.browser.close()
        result = subprocess.run(["uv", "run", "-q", "--script", str(RENDERER), str(path)])
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        if not _env("KEEP_TAKE"):
            shutil.rmtree(self.take_dir, ignore_errors=True)

    def _render_assets(self) -> dict:
        overlays = Overlays(
            self.browser, self.take_dir / "overlays", self.geom, self.theme, self.accent
        )
        for f in self._ff:
            f["text"] = f"⏩ {f['speed']:.0f}×"
        cursor, hotspot = overlays.cursor()
        assets = {
            "window": overlays.window(self.title or self._default_title()),
            "cursor": cursor,
            "hotspot": hotspot,
            "captions": {c["text"]: overlays.caption(c["text"]) for c in self._captions},
            "cards": {c["text"]: overlays.card(c["text"]) for c in self._cards},
            "badges": {b["text"]: overlays.badge(b["text"]) for b in self._keys + self._ff},
        }
        overlays.close()
        return {
            k: (
                {t: "overlays/" + p for t, p in v.items()}
                if isinstance(v, dict)
                else ("overlays/" + v if isinstance(v, str) else v)
            )
            for k, v in assets.items()
        }

    def _default_title(self) -> str:
        return "demo"

    def _report_failure(self, error: BaseException | None) -> None:
        lines = str(error).strip().splitlines() or [type(error).__name__]
        message = " ".join(line.strip() for line in lines[:2])
        print(f"demo-video: FAILED at {self._step}: {message[:300]}", file=sys.stderr)
        shot = self.out / "failure.png"
        try:
            self.page.screenshot(path=str(shot))
            print(f"  screen: {shot}", file=sys.stderr)
        except Exception:  # noqa: BLE001 - the page is gone
            pass
        detail = self._failure_detail()
        if detail:
            print(detail, file=sys.stderr)
        for problem in self._problems[:3]:
            print(f"  {problem[:200]}", file=sys.stderr)
        shutil.rmtree(self.take_dir, ignore_errors=True)


class Recorder(_Take):
    """Records a web app, driven through Playwright."""

    def __init__(
        self,
        out_dir: str | Path | None = None,
        base_url: str | None = None,
        *,
        browser_context: dict | None = None,
        **options,
    ) -> None:
        super().__init__(out_dir, **options)
        self.base_url = (base_url or _env("BASE_URL", "http://localhost:8000") or "").rstrip("/")
        self._browser_context = browser_context or {}
        self._capturing = False

    def _context_options(self) -> dict:
        return self._browser_context

    def _start(self) -> None:
        pass  # capture starts once the first page has loaded

    def _default_title(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.base_url).netloc or "app"

    def _failure_detail(self) -> str:
        try:
            url = self.page.url
        except Exception:  # noqa: BLE001
            url = "?"
        return f"  url: {url}\n  what the page offers:\n{inspect_page.describe(self.page)}"

    def _locate(self, target):
        return self.page.locator(target).first if isinstance(target, str) else target

    def _box(self, target) -> dict:
        """The element's box in content pixels, once it is visible."""
        locator = self._locate(target)
        with self._app_time():
            locator.wait_for(state="visible")
            locator.scroll_into_view_if_needed()
            box = locator.bounding_box()
        if not box:
            raise RuntimeError(f"{target!r} has no box on screen")
        s = self.geom["scale"]
        return {"x": box["x"] * s, "y": box["y"] * s, "w": box["width"] * s, "h": box["height"] * s}

    # -- verbs ------------------------------------------------------------------

    def goto(self, path: str = "") -> None:
        """Open `path` (relative to base_url) and wait for it to load."""
        self._mark(f"goto {path!r}")
        url = path if "://" in path else self.base_url + "/" + path.lstrip("/")
        first = not self._capturing
        with self._off_clock() if first else self._app_time():
            self.page.goto(url, wait_until="load")
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:  # noqa: BLE001 - a page that polls never goes idle
                pass
            if first:
                self.screencast.start()
                self._capturing = True
                self.page.wait_for_timeout(150)
        if not first:
            self._settle()

    def move_to(self, target) -> None:
        """Glide the cursor onto an element."""
        self._mark(f"move_to {target!r}")
        self._glide_to(self._box(target))
        self._real(0.15)

    def _glide_to(self, box: dict) -> None:
        x, y = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
        (x0, y0) = self._cursor
        distance = math.hypot(x - x0, y - y0)
        seconds = min(0.95, max(0.45, 0.35 + distance / 2200)) * self.pace
        start = self._now()
        self._hold(seconds)
        self._glides.append({"t0": start, "t1": self._now(), "from": [x0, y0], "to": [x, y]})
        self._cursor = [x, y]
        s = self.geom["scale"]
        self.page.mouse.move(x / s, y / s)

    def click(self, target) -> None:
        """Glide to an element and click it."""
        self._mark(f"click {target!r}")
        self._glide_to(self._box(target))
        self._real(0.1)
        self._clicks.append([self._now(), *self._cursor])
        with self._app_time():
            self._locate(target).click()
        self._settle()

    def type_into(self, target, text: str) -> None:
        """Click a field and type `text` into it, key by key."""
        self.click(target)
        self._mark(f"type_into {target!r} {text!r}")
        assert self.clock is not None
        start = time.time()
        self.page.keyboard.type(text, delay=15)
        self.clock.retime(start, min(3.0, max(0.3, len(text) * 0.06)) * self.pace)
        self._settle(quiet=0.45)

    def clear(self, target) -> None:
        """Empty a field."""
        self._mark(f"clear {target!r}")
        self._locate(target).fill("")
        self._settle()

    def press(self, key: str) -> None:
        """Press a named key, like "Enter" or "Control+K", with a key badge."""
        self._mark(f"press {key!r}")
        label = {"Enter": "⏎ Enter", "Escape": "Esc", "Tab": "⇥ Tab"}.get(key, key)
        self._keys.append(
            {"start": self._now(), "end": self._now() + 1.1 * self.pace, "text": label}
        )
        self.page.keyboard.press(key)
        self._settle()

    def scroll_to(self, target) -> None:
        """Scroll an element smoothly into the middle of the view."""
        self._mark(f"scroll_to {target!r}")
        locator = self._locate(target)
        with self._app_time():
            locator.wait_for(state="attached")
        locator.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
        self._settle()

    def wait_for(self, target, timeout_s: float = 60, state: str = "visible") -> None:
        """Wait for something the app does on its own. A long wait becomes a
        fast-forward in the video."""
        self._mark(f"wait_for {target!r}")
        with self._app_time():
            self._locate(target).wait_for(state=state, timeout=timeout_s * 1000)
        self._settle()

    def wait_until(self, condition, timeout_s: float = 60) -> None:
        """Wait until a JavaScript expression (str) or a Python callable is
        true. Use this instead of pausing in a loop."""
        self._mark("wait_until")
        with self._app_time():
            if isinstance(condition, str):
                self.page.wait_for_function(condition, timeout=timeout_s * 1000)
            else:
                deadline = time.time() + timeout_s
                while not condition():
                    if time.time() > deadline:
                        raise TimeoutError(f"wait_until: not true after {timeout_s}s")
                    self.page.wait_for_timeout(250)
        self._settle()

    def spotlight(self, target=None, ring: bool = True) -> None:
        """Push the camera in on an element and ring it. `spotlight()` ends it.
        `ring=False` zooms without the ring."""
        self._mark(f"spotlight {target!r}" if target is not None else "spotlight cleared")
        if self._spot:
            self._end_spot()
        if target is not None:
            box = self._box(target)
            self._spot = {
                "start": self._now(),
                "rect": [box["x"], box["y"], box["w"], box["h"]],
                "ring": ring,
            }
            self._spots.append(self._spot)

    def _end_spot(self) -> None:
        assert self._spot is not None
        short = self._spot["start"] + SPOT_MIN_S * self.pace - self._now()
        if short > 0:
            self._hold(short)
        self._spot["end"] = self._now()
        self._spot = None

    def inspect(self) -> None:
        """Print what the current page offers to point at, with selectors.
        For writing a storyboard; leaves no trace in the video."""
        with self._off_clock():
            print(f"demo-video: inspect {self.page.url}\n{inspect_page.describe(self.page)}")
