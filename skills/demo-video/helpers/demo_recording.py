# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Record self-explanatory browser demos of a web app.

Shared machinery for the demo-video skill: drives headless Chromium via
Playwright, overlays a visible cursor, burns narrator captions into the
frame, records video, and converts to mp4 with ffmpeg on exit — so each
demo's record.py stays a short, readable storyboard.

Usage:

    from demo_recording import Recorder

    with Recorder(Path(__file__).parent, base_url="http://localhost:3000") as rec:
        rec.goto("/")
        rec.caption("The dashboard shows every open order.")
        rec.pause(2)
        rec.shot("01-dashboard")          # -> images/01-dashboard.png
        rec.click("text=Orders")
    # exiting converts the recording into demo.mp4

Long real-world waits (background jobs, agent turns) are recorded as
segments: Recorder(out_dir, segment="part1") writes part1.seg.mp4, and
stitch(out_dir, ["part1", "part2"]) losslessly concatenates them into
demo.mp4. Bridge the skipped time with rec.interlude("…minutes later…").

Storyboards import this module from the demo-video skill directory and
run as single-file uv scripts (PEP 723 inline metadata declaring the
playwright dependency) — no project environment needed, only `uv` and
`ffmpeg` on PATH, plus a one-time
`uv run --with playwright playwright install chromium`.

Configuration: every Recorder parameter falls back to a DEMO_VIDEO_*
environment variable, so projects can set defaults in .env and keep
storyboards clean. Explicit parameters always win over env vars.

    DEMO_VIDEO_OUT_DIR          default out_dir (where demo files land)
    DEMO_VIDEO_BASE_URL         default base_url
    DEMO_VIDEO_ACCENT_RGB       cursor/spotlight color, e.g. "235,110,20"
    DEMO_VIDEO_TERMINAL_TITLE   on-screen terminal card title
    DEMO_VIDEO_TERMINAL_PROMPT  on-screen terminal card prompt
    DEMO_VIDEO_VIEWPORT         recording size, e.g. "1280x720"
    DEMO_VIDEO_SPEECH           "1"/"true" force narration on, "0"/"false" off
    DEMO_VIDEO_VOICE_ID         ElevenLabs voice
    DEMO_VIDEO_SPEECH_MODEL     ElevenLabs model
    ELEVENLABS_API_KEY          enables narration when set
    DEMO_VIDEO_SKILL_DIR        read by storyboards (not this module) to
                                locate the skill folder
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import TracebackType

from playwright.sync_api import Page, sync_playwright

# A visible stand-in for the mouse: headless recordings have no OS cursor,
# so inject a dot that follows pointer events (and squeezes on click).
_CURSOR_JS = """
(() => {
  const attach = () => {
    if (document.getElementById('__demo_cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #__demo_cursor { position: fixed; top: -40px; left: -40px; width: 18px;
        height: 18px; border-radius: 50%; background: rgba(__ACCENT__,.45);
        border: 2px solid rgba(__ACCENT__,.95); pointer-events: none;
        z-index: 2147483647; transform: translate(-50%,-50%);
        transition: width .1s, height .1s; }
      #__demo_cursor.__down { width: 12px; height: 12px; }
    `;
    document.head.appendChild(style);
    const dot = document.createElement('div');
    dot.id = '__demo_cursor';
    document.body.appendChild(dot);
    window.addEventListener('mousemove', (e) => {
      dot.style.left = e.clientX + 'px';
      dot.style.top = e.clientY + 'px';
    }, true);
    window.addEventListener('mousedown', () => dot.classList.add('__down'), true);
    window.addEventListener('mouseup', () => dot.classList.remove('__down'), true);
  };
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', attach);
  else attach();
})();
"""

# Terminal card: a small terminal-styled window that "types" a command on
# screen, so events the demo triggers from outside the browser (a file
# dropped into a folder, an API call) are demonstrated, not asserted. The
# script performs the real action at the moment the card finishes typing.
_TERMINAL_JS = """
window.__demoTerminal = async (cmd) => {
  let el = document.getElementById('__demo_term');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_term';
    el.style.cssText = `
      position: fixed; top: 84px; left: 50%; transform: translateX(-50%);
      width: min(680px, 86%); border-radius: 10px; overflow: hidden;
      background: #1c1a17; box-shadow: 0 14px 44px rgba(0,0,0,.45);
      z-index: 2147483645; opacity: 0; transition: opacity .35s ease;
      font: 15px/1.6 ui-monospace, monospace;
    `;
    el.innerHTML = `
      <div style="display:flex;gap:6px;padding:9px 12px;background:#2a2723">
        <span style="width:11px;height:11px;border-radius:50%;background:#e0604f"></span>
        <span style="width:11px;height:11px;border-radius:50%;background:#d9a13f"></span>
        <span style="width:11px;height:11px;border-radius:50%;background:#6aa15f"></span>
        <span style="color:#8d8779;font-size:12px;margin-left:8px">__TERM_TITLE__</span>
      </div>
      <pre id="__demo_term_body" style="margin:0;padding:14px 16px;color:#e8e4da;white-space:pre-wrap"></pre>
    `;
    document.body.appendChild(el);
  }
  requestAnimationFrame(() => { el.style.opacity = '1'; });
  const body = document.getElementById('__demo_term_body');
  const prompt = '__TERM_PROMPT__';
  body.textContent = prompt;
  await new Promise(r => setTimeout(r, 600));
  for (const ch of cmd) {
    body.textContent += ch;
    await new Promise(r => setTimeout(r, 42));
  }
  await new Promise(r => setTimeout(r, 350));
};
window.__demoTerminalDone = (stamp) => {
  const body = document.getElementById('__demo_term_body');
  if (body) body.textContent += '\\n' + (stamp || '✓ delivered');
};
window.__demoTerminalOutput = async (text) => {
  const body = document.getElementById('__demo_term_body');
  if (!body) return;
  const out = document.createElement('span');
  out.style.cssText = 'display:block;margin-top:8px;color:#c9c2b2;font-size:13px;';
  body.appendChild(out);
  for (const line of text.split('\\n')) {
    out.textContent += line + '\\n';
    await new Promise(r => setTimeout(r, 90));
  }
};
window.__demoTerminalHide = () => {
  const el = document.getElementById('__demo_term');
  if (el) { el.style.opacity = '0'; setTimeout(() => el.remove(), 400); }
};
"""

# Spotlight: a highlight ring + slight scale on one element, pointing the
# viewer at the evidence a caption is talking about (reason lines, chips).
_SPOTLIGHT_JS = """
window.__demoSpotlight = (el) => {
  window.__demoSpotlightClear();
  window.__spotEl = el;
  window.__spotPrev = el.getAttribute('style') || '';
  el.style.transition = 'all .25s ease';
  el.style.outline = '3px solid rgba(__ACCENT__,.85)';
  el.style.outlineOffset = '3px';
  el.style.borderRadius = '6px';
  el.style.background = 'rgba(__ACCENT__,.10)';
  el.style.transform = 'scale(1.02)';
};
window.__demoSpotlightClear = () => {
  if (window.__spotEl) {
    window.__spotEl.setAttribute('style', window.__spotPrev);
    window.__spotEl = null;
  }
};
"""

# Interlude: a full-screen title card for jumps over real-world time the
# recording skips (minutes of background work between two segments).
_INTERLUDE_JS = """
window.__demoInterlude = (text) => {
  let el = document.getElementById('__demo_interlude');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_interlude';
    el.style.cssText = `
      position: fixed; inset: 0; display: flex; align-items: center;
      justify-content: center; background: #1c1a17; color: #f7f4ee;
      font: 500 30px/1.5 system-ui, sans-serif; text-align: center;
      padding: 0 12%; z-index: 2147483647; opacity: 0;
      transition: opacity .45s ease; pointer-events: none;
    `;
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""

# Caption bar: a narrator line burned into the recording (and stills), so
# the video explains itself to someone watching with no other context.
_CAPTION_JS = """
window.__demoCaption = (text) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    el.style.cssText = `
      position: fixed; left: 50%; bottom: 30px; transform: translateX(-50%);
      max-width: 78%; padding: 11px 20px; border-radius: 9px;
      background: rgba(24,22,18,.86); color: #f7f4ee; text-align: center;
      font: 500 21px/1.35 system-ui, sans-serif; letter-spacing: .01em;
      pointer-events: none; z-index: 2147483646; opacity: 0;
      transition: opacity .3s ease; box-shadow: 0 4px 18px rgba(0,0,0,.25);
    `;
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""


def _env(name: str, default: str | None = None) -> str | None:
    """A DEMO_VIDEO_-prefixed environment variable, or the default."""
    value = os.environ.get(f"DEMO_VIDEO_{name}", "").strip()
    return value or default


def _env_flag(name: str) -> bool | None:
    """Tri-state env flag: True/False when set, None when absent."""
    value = _env(name)
    if value is None:
        return None
    return value.lower() in ("1", "true", "yes", "on")


def media_duration(path: Path) -> float:
    """Duration of any media file in seconds, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def tts_clip(
    text: str,
    cache_dir: Path,
    voice_id: str,
    model_id: str,
    api_key: str,
) -> Path:
    """Synthesize one narration line with ElevenLabs, cached by content.

    The cache key includes voice and model, so switching either re-generates.
    Cached clips make retakes free — the API is only hit for new lines.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()[:20]
    clip = cache_dir / f"{key}.mp3"
    if clip.exists():
        return clip
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": model_id}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    # Free-tier keys get 429 "system_busy" under load, and any network can
    # blip mid-recording — retry with backoff rather than losing a take.
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                partial = clip.with_suffix(".part")
                partial.write_bytes(resp.read())
                partial.rename(clip)  # atomic: no truncated clip is cached
            return clip
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(
                f"ElevenLabs TTS failed ({e.code}): {detail}"
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e
    raise AssertionError("unreachable")


class Recorder:
    """Playwright page wrapper that records video and captures guide stills.

    A plain Recorder produces demo.mp4 on exit. When the demo spans a long
    real-world wait (a background job, a slow run), record segments
    instead: Recorder(out_dir, segment="part1") writes part1.seg.mp4, and
    stitch(out_dir, ["part1", "part2"]) concatenates them into demo.mp4.
    Bridge the time jump with rec.interlude("…a few minutes later…") at the
    start of the next segment.

    accent_rgb themes the cursor dot and spotlight ring; terminal_title and
    terminal_prompt brand the on-screen terminal card for the story being
    told (e.g. "upstream system" / "upstream:~$ ").

    Speech: when the ELEVENLABS_API_KEY environment variable is set (or
    speech=True is passed), every caption and interlude line is also
    narrated out loud — synthesized via ElevenLabs, cached in .tts/, and
    mixed onto demo.mp4 at the moment the line appeared on screen. Pacing
    self-adjusts: a new line waits for the previous one to finish speaking,
    so storyboard pauses are minimums, never cut-offs.
    """

    def __init__(
        self,
        out_dir: Path | str | None = None,
        base_url: str | None = None,
        segment: str | None = None,
        accent_rgb: tuple[int, int, int] | None = None,
        terminal_title: str | None = None,
        terminal_prompt: str | None = None,
        viewport: tuple[int, int] | None = None,
        speech: bool | None = None,
        voice_id: str | None = None,
        speech_model: str | None = None,
    ) -> None:
        # Every setting resolves explicit parameter > DEMO_VIDEO_* env var
        # > built-in default (see module docstring for the variable names).
        out_dir = out_dir or _env("OUT_DIR")
        if out_dir is None:
            raise RuntimeError(
                "no output directory: pass out_dir or set DEMO_VIDEO_OUT_DIR"
            )
        self.out_dir = Path(out_dir)
        self.base_url = (
            base_url or _env("BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.segment = segment
        self.images_dir = self.out_dir / "images"
        self._video_dir = self.out_dir / ".video"
        if accent_rgb is None:
            raw = _env("ACCENT_RGB", "235,110,20")
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise RuntimeError(
                    f"DEMO_VIDEO_ACCENT_RGB must be 'R,G,B', got {raw!r}"
                )
            accent_rgb = tuple(int(p) for p in parts)  # type: ignore[assignment]
        self._accent = ",".join(str(c) for c in accent_rgb)
        self._terminal_title = terminal_title or _env("TERMINAL_TITLE", "terminal")
        self._terminal_prompt = terminal_prompt or _env("TERMINAL_PROMPT", "$ ")
        if viewport is None:
            raw = _env("VIEWPORT", "1280x720")
            w, sep, h = raw.lower().partition("x")
            if not (sep and w.strip().isdigit() and h.strip().isdigit()):
                raise RuntimeError(
                    f"DEMO_VIDEO_VIEWPORT must be 'WIDTHxHEIGHT', got {raw!r}"
                )
            viewport = (int(w), int(h))
        self._size = {"width": viewport[0], "height": viewport[1]}
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if speech is None:
            speech = _env_flag("SPEECH")
        if speech is True and not api_key:
            raise RuntimeError(
                "speech is forced on but ELEVENLABS_API_KEY is not set"
            )
        self._speech = bool(api_key) if speech is None else speech
        self._api_key = api_key
        # Default voice "Sarah" is premade — works on free-tier keys.
        self._voice_id = voice_id or _env("VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
        self._speech_model = speech_model or _env(
            "SPEECH_MODEL", "eleven_multilingual_v2"
        )
        self._tts_dir = self.out_dir / ".tts"
        self._lines: list[tuple[float, Path]] = []  # (video offset s, clip)
        self._line_end = 0.0  # wall-clock time the current line stops speaking
        self._t0 = 0.0  # wall-clock time video capture started
        self.page: Page = None  # type: ignore[assignment]

    def __enter__(self) -> "Recorder":
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._video_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
            self._context = self._browser.new_context(
                viewport=self._size,
                record_video_dir=str(self._video_dir),
                record_video_size=self._size,
            )
            self._context.add_init_script(
                _CURSOR_JS.replace("__ACCENT__", self._accent)
            )
            self._context.add_init_script(_CAPTION_JS)
            self._context.add_init_script(
                _TERMINAL_JS.replace("__TERM_TITLE__", self._terminal_title)
                .replace("__TERM_PROMPT__", self._terminal_prompt)
            )
            self._context.add_init_script(
                _SPOTLIGHT_JS.replace("__ACCENT__", self._accent)
            )
            self._context.add_init_script(_INTERLUDE_JS)
            self.page = self._context.new_page()
        except Exception:
            # __exit__ never runs when __enter__ raises — don't leak the
            # Playwright driver (typical cause: chromium not installed).
            self._pw.stop()
            raise
        self._t0 = time.time()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self._finish_line(tail=0.5)  # don't end mid-sentence
        video = self.page.video
        self._context.close()
        webm = Path(video.path()) if video else None
        self._browser.close()
        self._pw.stop()
        if exc_type is None and webm and webm.exists():
            self._convert(webm)
        for leftover in self._video_dir.glob("*"):
            leftover.unlink()
        self._video_dir.rmdir()

    # -- storyboard verbs ---------------------------------------------------

    def goto(self, path: str = "") -> None:
        url = path if path.startswith("http") else self.base_url + path
        # Asset fetches hang occasionally on a busy dev box — a reload
        # recovers, so retry rather than dying mid-recording.
        for attempt in range(3):
            try:
                self.page.goto(url, timeout=45_000)
                break
            except Exception:
                if attempt == 2:
                    raise
        try:
            self.page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # apps that poll never go network-idle; the page is up

    def pause(self, seconds: float) -> None:
        """Hold the frame so viewers can read what is on screen."""
        time.sleep(seconds)

    def caption(self, text: str) -> None:
        """Show a narrator line at the bottom of the frame ("" hides it).

        Captions die on full page loads but survive SPA client-side
        navigation — clear with caption("") before any navigating click
        and set a fresh line after, so no line ever straddles two views.
        With speech enabled the line is also spoken; the previous line
        always finishes before this one starts.
        """
        clip = self._prepare_line(text)
        self.page.evaluate("t => window.__demoCaption(t)", text)
        self._start_line(clip)
        self.pause(0.3)

    def terminal(self, command: str) -> None:
        """Type a command in an on-screen terminal card, then perform the
        real action it describes right after this returns."""
        self.page.evaluate("cmd => window.__demoTerminal(cmd)", command)

    def terminal_output(self, text: str) -> None:
        """Reveal real command output inside the terminal card, line by
        line — run the command first, pass its actual (trimmed) output."""
        self.page.evaluate("t => window.__demoTerminalOutput(t)", text)

    def terminal_close(self, stamp: str | None = None) -> None:
        """Stamp a closing line ('✓ delivered' by default, "" for none)
        on the terminal card and fade it out."""
        if stamp != "":
            self.page.evaluate("s => window.__demoTerminalDone(s)", stamp)
            self.pause(1.2)
        self.page.evaluate("() => window.__demoTerminalHide()")
        self.pause(0.5)

    def interlude(self, text: str, hold: float = 2.8) -> None:
        """Full-screen title card over the page — use at the start of a
        segment to mark real-world time the recording skips; "" fades out.
        With speech enabled the card's line is spoken too."""
        clip = self._prepare_line(text)
        self.page.evaluate("t => window.__demoInterlude(t)", text)
        self._start_line(clip)
        self.pause(hold if text else 0.6)

    # -- speech (ElevenLabs narration) --------------------------------------

    def _prepare_line(self, text: str) -> Path | None:
        """Synthesize (or fetch cached) audio for a narration line, and wait
        out the previous line — never speak two lines at once, never show a
        caption while the voice is still on the previous one."""
        clip = None
        if self._speech and text:
            clip = tts_clip(
                text, self._tts_dir, self._voice_id, self._speech_model,
                self._api_key,
            )
        self._finish_line()
        return clip

    def _start_line(self, clip: Path | None) -> None:
        """Log the line as starting now, at the current video offset."""
        if clip is not None:
            now = time.time()
            self._lines.append((now - self._t0, clip))
            self._line_end = now + media_duration(clip)

    def _finish_line(self, tail: float = 0.0) -> None:
        remaining = self._line_end - time.time()
        if remaining > 0:
            time.sleep(remaining + tail)

    def spotlight(self, selector: str | None = None) -> None:
        """Highlight one element while the caption talks about it;
        spotlight() with no argument clears it."""
        self.page.evaluate("() => window.__demoSpotlightClear()")
        if selector:
            self.page.locator(selector).first.evaluate(
                "el => window.__demoSpotlight(el)"
            )
        self.pause(0.3)

    def shot(self, name: str) -> Path:
        """Still for the written guide -> images/<name>.png."""
        path = self.images_dir / f"{name}.png"
        self.page.screenshot(path=str(path))
        return path

    def move_to(self, selector: str) -> None:
        """Glide the cursor onto an element (smooth, watchable motion)."""
        box = self.page.locator(selector).first.bounding_box()
        if box is None:
            raise RuntimeError(f"no visible element for {selector!r}")
        self.page.mouse.move(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30
        )

    def click(self, selector: str) -> None:
        self.move_to(selector)
        self.pause(0.4)
        self.page.locator(selector).first.click()

    def click_fast(self, selector: str) -> None:
        """Coordinate click without Playwright's stability wait — for
        elements that re-render continuously (polling UIs re-mount
        popovers, restarting entrance animations, so locator.click()'s
        actionability check can stall for minutes)."""
        deadline = time.time() + 10
        box = None
        while box is None:
            box = self.page.locator(selector).first.bounding_box()
            if box is None:
                if time.time() > deadline:
                    raise RuntimeError(f"no visible element for {selector!r}")
                time.sleep(0.1)
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.mouse.move(x, y, steps=15)
        self.pause(0.3)
        self.page.mouse.click(x, y)

    def type_into(self, selector: str, text: str, delay_ms: int = 40) -> None:
        """Click a field and type into it visibly, key by key — for form
        demos (checkout, login, search). For anything the verbs don't
        cover, `self.page` is the live Playwright page."""
        self.click(selector)
        self.page.keyboard.type(text, delay=delay_ms)

    def scroll_to(self, selector: str) -> None:
        self.page.locator(selector).first.evaluate(
            "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
        )
        self.pause(1.2)

    def wait_for(self, selector: str, timeout_s: float = 60) -> None:
        """Wait for something the app does on its own (a job, a run)."""
        self.page.locator(selector).first.wait_for(timeout=timeout_s * 1000)

    # -- media conversion ---------------------------------------------------

    def _convert(self, webm: Path) -> None:
        name = f"{self.segment}.seg.mp4" if self.segment else "demo.mp4"
        mp4 = self.out_dir / name
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm)]
        if self._speech:
            # Mix each narration clip in at the moment its line appeared.
            # Segments always get an aac track (silence if no lines) so
            # stitch()'s lossless concat sees uniform streams.
            if self._lines:
                for _, clip in self._lines:
                    cmd += ["-i", str(clip)]
                delayed = ";".join(
                    f"[{i + 1}:a]adelay={int(off * 1000)}:all=1[a{i}]"
                    for i, (off, _) in enumerate(self._lines)
                )
                inputs = "".join(f"[a{i}]" for i in range(len(self._lines)))
                # aformat pins the layout: mixed mono TTS clips would
                # otherwise yield a mono track that -c copy concat can't
                # join with the stereo silence of a line-less segment.
                filt = (
                    f"{delayed};{inputs}amix=inputs={len(self._lines)}"
                    ":normalize=0,"
                    "aformat=sample_rates=44100:channel_layouts=stereo,"
                    "apad[aud]"
                )
            else:
                cmd += ["-f", "lavfi", "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=44100"]
                filt = "[1:a]apad[aud]"
            cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[aud]",
                    "-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-r", "25", "-movflags", "+faststart", str(mp4)]
        subprocess.run(cmd, check=True)
        spoken = f", {len(self._lines)} spoken lines" if self._speech else ""
        print(f"wrote {mp4} ({mp4.stat().st_size // 1024} kB{spoken})")


def stitch(out_dir: Path, segments: list[str], keep_parts: bool = False) -> None:
    """Concatenate segment recordings into demo.mp4.

    keep_parts=True leaves the .seg.mp4 files on disk so a single segment
    can be re-recorded and re-stitched without redoing the expensive ones
    (segments are untracked; only demo.mp4 is committed).
    """
    out_dir = Path(out_dir)
    parts = [out_dir / f"{s}.seg.mp4" for s in segments]
    for p in parts:
        if not p.exists():
            raise FileNotFoundError(p)
    listing = out_dir / ".concat.txt"
    listing.write_text(
        "".join(
            # concat-demuxer quoting: a literal ' inside single quotes
            # is written as '\'' (paths like ".../Rógvi's Mac/..." occur).
            "file '{}'\n".format(str(p.resolve()).replace("'", "'\\''"))
            for p in parts
        )
    )
    demo = out_dir / "demo.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(demo)],
        check=True,
    )
    listing.unlink()
    if not keep_parts:
        for p in parts:
            p.unlink()
