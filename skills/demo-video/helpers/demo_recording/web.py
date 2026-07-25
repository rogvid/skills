"""Recorder — records a web app by driving a Playwright page.

The original demo-video recorder, unchanged in behavior: overlays a visible
cursor, burns narrator captions into the frame (via _DemoBase), and adds
web storyboard verbs (goto/click/type_into/spotlight/…) plus the decorative
on-screen "terminal card" for showing off-browser actions during a web demo.

Note: `Recorder.terminal()` is a *prop inside a web demo* — a styled card
that fakes a command to make an off-browser action visible. To record an
actual CLI or TUI, use `TerminalRecorder` instead (see terminal.py).

    from demo_recording import Recorder

    with Recorder(Path(__file__).parent, base_url="http://localhost:3000") as rec:
        rec.goto("/")
        rec.caption("The dashboard shows every open order.")
        rec.pause(2)
        rec.shot("01-dashboard")          # -> images/01-dashboard.png
        rec.click("text=Orders")
    # exiting converts the recording into demo.mp4
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from .core import _beat_verb, _DemoBase, _env

# Pastel gradient behind the window — matches the terminal recorder's
# background so web and terminal demos share one look.
_WEB_BG = "linear-gradient(135deg, #f6d5f0 0%, #d7e3fb 52%, #cdeede 100%)"

# The window frame drawn behind the recording: gradient background + a dark
# rounded window with a title bar and traffic-light buttons. Screenshotted
# once per run; the app video is composited into its body by ffmpeg.
_FRAME_HTML = """<!doctype html><meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; }
  body { background: __BG__; }
  #win { position: fixed; left: __WINX__px; top: __WINY__px;
    width: __WINW__px; height: __WINH__px; border-radius: 14px;
    overflow: hidden; background: #181825;
    box-shadow: 0 34px 90px rgba(20,16,40,.40), 0 8px 22px rgba(20,16,40,.28); }
  #bar { height: 36px; display: flex; align-items: center; gap: 8px;
    padding: 0 14px; background: #232334;
    font: 13px/1 ui-monospace, monospace; color: #9399b2; }
  .dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
  #ttl { flex: 1; text-align: center; letter-spacing: .02em; }
</style>
<div id="win">
  <div id="bar">
    <span class="dot" style="background:#ff5f57"></span>
    <span class="dot" style="background:#febc2e"></span>
    <span class="dot" style="background:#28c840"></span>
    <span id="ttl">__TITLE__</span>
    <span style="width:44px"></span>
  </div>
</div>
"""

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


class Recorder(_DemoBase):
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
    """

    def __init__(
        self,
        out_dir=None,
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
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=terminal_prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model,
        )
        self.base_url = (
            base_url or _env("BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        # The recording is composited into a window and scaled down (~0.8),
        # so captions are rendered larger to stay readable in the final mp4.
        self._caption_font_px = 34

    def _frame_geometry(self) -> dict:
        """Where the window and the app video sit in the final frame.
        The app keeps the recording's aspect ratio; a pad leaves the window's
        rounded corners visible around it."""
        W, H = self._size["width"], self._size["height"]
        pad, bar = 14, 36
        appw = int(W * 0.80) & ~1                 # even width
        apph = int(round(appw * H / W)) & ~1      # keep recording aspect
        winw, winh = appw + 2 * pad, apph + 2 * pad + bar
        winx, winy = (W - winw) // 2, (H - winh) // 2
        return {
            "appw": appw, "apph": apph, "winw": winw, "winh": winh,
            "winx": winx, "winy": winy,
            "appx": winx + pad, "appy": winy + bar + pad,
        }

    def _init_context(self, context) -> None:
        context.add_init_script(_CURSOR_JS.replace("__ACCENT__", self._accent))
        context.add_init_script(
            _TERMINAL_JS.replace("__TERM_TITLE__", self._terminal_title)
            .replace("__TERM_PROMPT__", self._terminal_prompt)
        )
        context.add_init_script(_SPOTLIGHT_JS.replace("__ACCENT__", self._accent))

    def _start(self) -> None:
        # Render the window+background frame once (on a throwaway page, so the
        # app page stays clean for goto). ffmpeg composites the recording into
        # it in _postprocess.
        self._geom = self._frame_geometry()
        g = self._geom
        # Browser-like window title: the app's host (e.g. "localhost:3000").
        title = urlparse(self.base_url).netloc or "app"
        html = (
            _FRAME_HTML.replace("__BG__", _WEB_BG)
            .replace("__WINX__", str(g["winx"])).replace("__WINY__", str(g["winy"]))
            .replace("__WINW__", str(g["winw"])).replace("__WINH__", str(g["winh"]))
            .replace("__TITLE__", title)
        )
        self._frame_png = self.out_dir / ".frame.png"
        p = self._context.new_page()
        p.set_content(html)
        p.wait_for_timeout(150)
        p.screenshot(path=str(self._frame_png))
        p.close()

    def _postprocess(self, mp4: Path) -> None:
        # Composite the recorded video into the window body on the background.
        g = self._geom
        tmp = mp4.with_suffix(".comp.mp4")
        filt = (
            f"[0:v]scale={g['appw']}:{g['apph']}[app];"
            f"[1:v][app]overlay={g['appx']}:{g['appy']}[v]"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(mp4), "-i", str(self._frame_png),
             "-filter_complex", filt, "-map", "[v]", "-map", "0:a?",
             "-c:a", "copy", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-r", "25", "-movflags", "+faststart", str(tmp)],
            check=True,
        )
        tmp.replace(mp4)
        self._frame_png.unlink(missing_ok=True)

    # -- storyboard verbs ---------------------------------------------------

    @_beat_verb("goto")
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

    @_beat_verb("terminal")
    def terminal(self, command: str) -> None:
        """Type a command in an on-screen terminal card, then perform the
        real action it describes right after this returns."""
        self.page.evaluate("cmd => window.__demoTerminal(cmd)", command)

    @_beat_verb("terminal_output")
    def terminal_output(self, text: str) -> None:
        """Reveal real command output inside the terminal card, line by
        line — run the command first, pass its actual (trimmed) output."""
        self.page.evaluate("t => window.__demoTerminalOutput(t)", text)

    @_beat_verb("terminal_close")
    def terminal_close(self, stamp: str | None = None) -> None:
        """Stamp a closing line ('✓ delivered' by default, "" for none)
        on the terminal card and fade it out."""
        if stamp != "":
            self.page.evaluate("s => window.__demoTerminalDone(s)", stamp)
            self.pause(1.2)
        self.page.evaluate("() => window.__demoTerminalHide()")
        self.pause(0.5)

    @_beat_verb("spotlight")
    def spotlight(self, selector: str | None = None) -> None:
        """Highlight one element while the caption talks about it;
        spotlight() with no argument clears it."""
        self.page.evaluate("() => window.__demoSpotlightClear()")
        if selector:
            self.page.locator(selector).first.evaluate(
                "el => window.__demoSpotlight(el)"
            )
        self.pause(0.3)

    @_beat_verb("move_to")
    def move_to(self, selector: str) -> None:
        """Glide the cursor onto an element (smooth, watchable motion)."""
        box = self.page.locator(selector).first.bounding_box()
        if box is None:
            raise RuntimeError(f"no visible element for {selector!r}")
        self.page.mouse.move(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30
        )

    @_beat_verb("click")
    def click(self, selector: str) -> None:
        self.move_to(selector)
        self.pause(0.4)
        self.page.locator(selector).first.click()

    @_beat_verb("click_fast")
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

    @_beat_verb("type_into")
    def type_into(self, selector: str, text: str, delay_ms: int = 40) -> None:
        """Click a field and type into it visibly, key by key — for form
        demos (checkout, login, search). For anything the verbs don't
        cover, `self.page` is the live Playwright page."""
        self.click(selector)
        self.page.keyboard.type(text, delay=delay_ms)

    @_beat_verb("scroll_to")
    def scroll_to(self, selector: str) -> None:
        self.page.locator(selector).first.evaluate(
            "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
        )
        self.pause(1.2)

    @_beat_verb("wait_for")
    def wait_for(self, selector: str, timeout_s: float = 60) -> None:
        """Wait for something the app does on its own (a job, a run)."""
        self.page.locator(selector).first.wait_for(timeout=timeout_s * 1000)
