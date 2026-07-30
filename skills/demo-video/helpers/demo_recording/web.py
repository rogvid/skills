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
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .content import OPENING_HOLD_LIMIT_S, content_rect, opening_gap
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

# How long the spotlight's enter and exit take. One constant, used as the
# element's `transition` and as the shape of the timer that backs the exit up,
# so the two cannot drift apart.
SPOTLIGHT_TRANSITION = "all .25s ease"

# Grace on top of the element's *computed* transition time before the exit
# gives up waiting for `transitionend` and restores the style anyway. Covers a
# compositor that delivers the event a frame or two late; too small and the
# last sliver of the fade is cut off, too large and a property that never
# transitioned at all stalls the verb.
SPOTLIGHT_EXIT_SLACK_MS = 120

# Spotlight: a highlight ring + slight scale on one element, pointing the
# viewer at the evidence a caption is talking about (reason lines, chips).
#
# **The exit is animated by the same transition the entrance used**, and the
# order below is the whole of issue #111. Restoring `__spotPrev` in one
# `setAttribute` is what guarantees the element is handed back exactly as it
# was found — including an inline style the app itself set — but it also
# removes `transition` in the *same frame* as it removes `transform` and
# `outline`, so there is nothing left to animate the exit with. The spotlight
# eased in over 250 ms and snapped out in one frame, and the asymmetry is what
# read as broken.
#
# So the spotlight's own properties are reverted individually, while the
# transition is still on the element, and the wholesale restore waits for
# `transitionend`. Two details that are not decoration:
#
#   * `transitionend` does not fire when nothing actually changed, so a timer
#     backs it up. Its length comes from the element's own *computed*
#     transition time rather than from a constant, which is what keeps
#     `deterministic=True` cheap: the motion rule flattens transitions to 1 ms
#     with `!important`, so a deterministic take's exit is over in a
#     millisecond and the fallback never runs. A hardcoded 400 ms would have
#     charged every deterministic take — `tests/smoke` included — nearly half a
#     second per clear for a transition that had already finished.
#   * the ring fades by animating its *colour* to alpha 0 rather than by
#     clearing the `outline` shorthand. `outline-style` is not an animatable
#     property, so clearing it makes the ring vanish in one frame while the
#     scale eases — half a snap, which is the bug wearing a smaller hat.
#     `background` and `transform` are cleared outright, because removing an
#     inline declaration transitions to the value underneath it and that value
#     is the one the element is supposed to return to.
_SPOTLIGHT_JS = """
window.__demoSpotlightMs = (el) => {
  // What the browser says this element's transition costs, not what this file
  // asked for. The determinism rule overrides it with `!important`.
  let cs;
  try { cs = getComputedStyle(el); } catch (e) { return 0; }
  const worst = (value) => (value || '').split(',').reduce((max, part) => {
    const text = part.trim();
    const n = parseFloat(text);
    if (!isFinite(n)) return max;
    return Math.max(max, /ms$/.test(text) ? n : n * 1000);
  }, 0);
  return worst(cs.transitionDuration) + worst(cs.transitionDelay);
};
window.__demoSpotlight = async (el) => {
  // Awaited: a second spotlight on the *same* element would otherwise read
  // `__spotPrev` off a style attribute the pending exit has not finished
  // reverting, and then the exit's restore would wipe the new highlight.
  await window.__demoSpotlightClear();
  window.__spotEl = el;
  // `getAttribute`, not `getAttribute(...) || ''` — an element that had no
  // style attribute at all must get none back, or "returned exactly as found"
  // is one `style=""` short of true.
  window.__spotPrev = el.getAttribute('style');
  el.style.transition = '__TRANSITION__';
  el.style.outline = '3px solid rgba(__ACCENT__,.85)';
  el.style.outlineOffset = '3px';
  el.style.borderRadius = '6px';
  el.style.background = 'rgba(__ACCENT__,.10)';
  el.style.transform = 'scale(1.02)';
};
window.__demoSpotlightClear = () => {
  const el = window.__spotEl;
  if (!el) return Promise.resolve(false);
  const prev = window.__spotPrev;
  window.__spotEl = null;
  window.__spotPrev = null;
  el.style.outlineColor = 'rgba(__ACCENT__,0)';
  el.style.background = '';
  el.style.transform = '';
  const restore = () => {
    if (prev === null || prev === undefined) el.removeAttribute('style');
    else el.setAttribute('style', prev);
  };
  const ms = window.__demoSpotlightMs(el);
  if (!(ms > 0)) { restore(); return Promise.resolve(true); }
  return new Promise((resolve) => {
    let done = false;
    // Hoisted, so `finish` can unsubscribe it.
    function onEnd(event) { if (event.target === el) finish(); }
    const finish = () => {
      if (done) return;
      done = true;
      el.removeEventListener('transitionend', onEnd);
      restore();
      resolve(true);
    };
    // This element's own transition only. A descendant's bubbles up here too,
    // and one that finishes early would restore the style mid-fade.
    el.addEventListener('transitionend', onEnd);
    setTimeout(finish, ms + __SLACK_MS__);
  });
};
"""



# The spotlight target's markup, cleaned, from a *clone* — nothing here may
# touch the live page, which is being recorded.
#
# Two things come out that `outerHTML` would otherwise put in a file nobody
# expects to hold them, and neither reason is about secrets:
#
#   * `<script>` and `<style>` text, and `srcdoc` — source code and whole
#     embedded documents, none of it on screen;
#   * the recorder's own furniture — the caption bar, the cursor — which is
#     chrome, not app.
#
# The mask-elision arm went with #142. What is left is a statement about what
# belongs in a text dump of an element, which is a separate concern and
# survives on its own terms — graded directly by tests/smoke's evidence take
# since #150, which injects an element holding a script and a srcdoc.
_EVIDENCE_HTML_JS = r"""(el) => {
  // Value-bearing attributes. Every one of these can hold a string the page
  // never rendered — a `data-token`, a `data-cfg` holding a whole JSON config,
  // an `href` carrying a session id — and none is structure. Stripped from
  // every element: an attribute that renders nowhere was in no frame, no
  // still, no caption and no narration clip, so serializing it would make
  // evidence the only place it exists. `id`, `class`, `role` and `style` stay,
  // because they are what makes the markup worth reading.
  const VALUED = ['value', 'title', 'alt', 'placeholder', 'aria-label',
                  'href', 'src', 'srcdoc', 'content', 'action', 'poster'];
  const clone = el.cloneNode(true);
  const drop = (root, sel) => {
    let hits = [];
    try { hits = root.querySelectorAll(sel); } catch (e) { return; }
    for (const hit of hits) hit.remove();
  };
  drop(clone, 'script,style,template,noscript,link,meta');
  // The recorder's own overlays are chrome, not the app.
  drop(clone, '[id^="__demo"],[id^="__term"]');
  const strip = (node) => {
    for (const a of VALUED) {
      try { node.removeAttribute(a); } catch (e) { /* exotic attr */ }
    }
    // Every data-* attribute, whatever it is called. A whitelist would only
    // ever be a list of the ones somebody happened to think of.
    let names = [];
    try { names = Array.prototype.slice.call(node.attributes || [])
      .map((a) => a.name); } catch (e) { names = []; }
    for (const name of names) {
      if (name.slice(0, 5) === 'data-') {
        try { node.removeAttribute(name); } catch (e) { /* ignore */ }
      }
    }
  };
  let all = [];
  try { all = [clone].concat(Array.prototype.slice.call(
    clone.querySelectorAll('*'))); } catch (e) { all = [clone]; }
  for (const node of all) strip(node);
  return clone.outerHTML;
}"""



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
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=terminal_prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model, strict=strict,
            deterministic=deterministic, clock=clock,
            timezone_id=timezone_id, locale=locale, evidence=evidence,
            criteria=criteria,
        )
        self.base_url = (
            base_url or _env("BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        # The recording is composited into a window and scaled down (~0.8),
        # so captions are rendered larger to stay readable in the final mp4.
        self._caption_font_px = 34
        # What spotlight() is currently pointing at, which is what a beat's
        # evidence is scoped to. Held here rather than read back out of the
        # page: `window.__spotEl` is an element handle, not a selector, and the
        # selector is the thing worth writing down.
        self._spotlit: str | None = None
        # Set by the retained `framenavigated` listener. Nothing reads it yet;
        # see `_note_navigation` and #134.
        self._navigated = False

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

    def _content_rect(self) -> tuple[int, int, int, int] | None:
        """Where the page lands inside the composited frame (issue #97).

        `_postprocess` scales the raw recording to `appw x apph` and overlays
        it at `appx, appy` on the window-and-background still, so this is the
        app's region of the *encoded* file — which is the only frame anybody
        watches. Everything outside it is the recorder's own chrome, and that
        chrome is exactly what made a whole-frame score rank a blank recording
        above a healthy one (issue #17).
        """
        geom = getattr(self, "_geom", None)
        if not geom:
            return None
        return content_rect(
            (geom["appx"], geom["appy"], geom["appw"], geom["apph"])
        )

    def _init_context(self, context) -> None:
        context.add_init_script(_CURSOR_JS.replace("__ACCENT__", self._accent))
        context.add_init_script(
            _TERMINAL_JS.replace("__TERM_TITLE__", self._terminal_title)
            .replace("__TERM_PROMPT__", self._terminal_prompt)
        )
        context.add_init_script(
            _SPOTLIGHT_JS.replace("__ACCENT__", self._accent)
            .replace("__TRANSITION__", SPOTLIGHT_TRANSITION)
            .replace("__SLACK_MS__", str(SPOTLIGHT_EXIT_SLACK_MS))
        )

    def _start(self) -> None:
        # **Kept deliberately when the masking went** — #142's carve-out.
        # This listener was written for the paint gate, and the gate is gone;
        # but it is also the recorder's *only* reaction to a document being
        # replaced. A link click, go_back(), a form submit, location.href and
        # a meta refresh all land here and nowhere else, and #134 — a mid-take
        # goto() leaving `self._caption` stale, so every later beat logs a
        # caption that is not on screen, into files this skill says to commit —
        # cannot be fixed without knowing that a navigation happened.
        #
        # `frameattached` went with the rest: it existed because a frame that
        # attached after the parent's checkpoint had never been verified, which
        # is a statement about a mask and about nothing else.
        #
        # The callback only sets a flag. Playwright delivers page events on the
        # same thread that is blocked in a Playwright call, so calling back
        # into the API from here is a way to deadlock a take.
        self.page.on("framenavigated", self._note_navigation)
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

    def _opening_hold(self, mp4: Path) -> Path | None:
        """Cover this take's blank opening with the app's first painted frame.

        Returns the still to composite over the app rect, or None when there is
        nothing to cover. See "the blank opening" in `core` for why the gap is
        covered rather than trimmed, and what it costs.

        Measured on `mp4` **before** compositing, where the whole frame is the
        app page and the window chrome does not exist yet — so there is no rect
        to get wrong, and none of the chrome that made a whole-frame metric run
        backwards in issue #17 is in the picture.
        """
        self._opening_held = 0.0
        gap, note = opening_gap(
            mp4, (0, 0, self._size["width"], self._size["height"])
        )
        if gap is None or gap <= 0:
            return None
        if gap > OPENING_HOLD_LIMIT_S:
            # Deliberately nothing. `_measure_content` then measures the same
            # gap on the encoded file and warns, which is the honest outcome:
            # an app that takes this long to paint is showing the viewer
            # something true about itself.
            print(
                f"demo-video: this take opened on {gap:.2f}s with nothing "
                f"painted, over the {OPENING_HOLD_LIMIT_S}s the recorder will "
                f"cover, so the opening is left as recorded"
                + (f" ({note})" if note else ""),
                file=sys.stderr,
            )
            return None
        still = self.out_dir / ".hold.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{gap:.3f}",
             "-i", str(mp4), "-frames:v", "1", str(still)],
            check=True,
        )
        self._opening_held = gap
        return still

    def _postprocess(self, mp4: Path) -> None:
        # Composite the recorded video into the window body on the background.
        g = self._geom
        hold = self._opening_hold(mp4)
        tmp = mp4.with_suffix(".comp.mp4")
        inputs = ["-i", str(mp4), "-i", str(self._frame_png)]
        filt = (
            f"[0:v]scale={g['appw']}:{g['apph']}[app];"
            f"[1:v][app]overlay={g['appx']}:{g['appy']}"
        )
        if hold is None:
            filt += "[v]"
        else:
            # A second overlay of the same size at the same place, switched off
            # the moment the app painted. Content at every t >= held keeps the
            # timestamp it already had: the video's duration does not change,
            # the audio is copied untouched, and nothing that reads a beat time
            # has to know this happened.
            inputs += ["-i", str(hold)]
            filt += (
                f"[base];[2:v]scale={g['appw']}:{g['apph']}[held];"
                f"[base][held]overlay={g['appx']}:{g['appy']}"
                f":enable='lt(t,{self._opening_held:.3f})'[v]"
            )
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", *inputs,
                 "-filter_complex", filt, "-map", "[v]", "-map", "0:a?",
                 "-c:a", "copy", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-crf", "20", "-r", "25", "-movflags", "+faststart", str(tmp)],
                check=True,
            )
            tmp.replace(mp4)
        finally:
            # In a finally because `.hold.png` is a frame of the *app*, not of
            # the recorder's chrome: if ffmpeg raises, leaving it on disk leaves
            # a full-size picture of whatever the app was showing sitting beside
            # the demo.
            self._frame_png.unlink(missing_ok=True)
            if hold is not None:
                hold.unlink(missing_ok=True)


    def _failure_screen(self) -> str | None:
        """The page's accessibility tree, for `failure/screen.txt` (issue #11).

        The DOM the issue asks for, in the form the rest of this package
        already publishes it: `aria_snapshot` is semantic, an order of
        magnitude smaller than the markup, and — unlike `document.body
        .outerHTML` — carries neither inline `<script>` text nor `srcdoc`
        documents that were never on screen. The URL and title go with it,
        because "which page was it even on" is the first question a crash
        raises and neither is recoverable from a frame.

        Captured independently of `evidence=…`. Per-beat evidence answers "what
        did the page look like at the end of beat 7"; this answers "what did it
        look like when it died", which is a different moment — the failing verb
        ran after that capture — and it has to be there when evidence is
        switched off, because a crash is when it is wanted most.
        """
        return self._failure_page_text()

    def _failure_page_text(self) -> str:
        """The ARIA tree, the URL and the title, as one document."""
        aria, aria_format = self._aria(self.page.locator("body"))
        head = [f"url: {self.page.url}"]
        try:
            head.append(f"title: {self.page.title()}")
        except Exception:  # noqa: BLE001 - a dying page still has a URL
            head.append("title: (unreadable)")
        head.append(f"aria_format: {aria_format}")
        return "\n".join([*head, "", aria or "(no accessibility snapshot)"])


    def _note_navigation(self, frame) -> None:
        """A frame navigated. Nothing reads this yet, and that is deliberate.

        The flag used to mean "the next checkpoint must re-inject and re-verify
        the mask". There is no mask, so nothing consumes it. The *listener* is
        what #142 keeps: it is the only way this recorder learns that a
        document was replaced, and #134 needs precisely that. Keeping the hook
        and dropping its consumer is a smaller thing to get wrong than
        re-deriving the hook later.

        Deliberately does nothing else — see `_start` for why touching
        Playwright from an event callback is not safe here.
        """
        self._navigated = True

    # -- evidence (issue #9) ------------------------------------------------


    def _aria(self, locator) -> tuple[str | None, str]:
        """(snapshot, format) for one locator's accessibility tree.

        Playwright's `aria_snapshot` arrived in 1.49 and `page.accessibility`
        — the API issue #9 was written against — has since been removed, so
        there is exactly one way to do this and no second, untested branch
        pretending otherwise. An older Playwright gets a null snapshot and a
        format that says why, rather than a fallback nobody here can exercise.
        """
        if not hasattr(locator, "aria_snapshot"):
            return None, "unavailable: this Playwright predates 1.49"
        return locator.aria_snapshot(), "aria-yaml"

    def _capture_page(self) -> dict:
        """One pass: the ARIA snapshot, the URL, and the spotlight target."""
        aria, aria_format = self._aria(self.page.locator("body"))
        payload: dict = {
            "scope": self._spotlit,
            "url": self.page.url,
            "title": self.page.title(),
            "aria_format": aria_format,
            "aria": aria,
            "scope_aria": None,
            "html": None,
        }
        if self._spotlit:
            target = self.page.locator(self._spotlit).first
            payload["scope_aria"] = self._aria(target)[0]
            payload["html"] = target.evaluate(_EVIDENCE_HTML_JS)
        return payload

    def _evidence_payload(self) -> dict:
        """What was on screen at the end of this beat, as text.

        The ARIA snapshot is the primary artifact and the page's is always
        taken: it is what lets a reviewer say what was on screen without
        decoding a frame. `outerHTML` is the spotlight target's only — never
        the page's — because the markup of a whole document is an order of
        magnitude larger than its ARIA tree, and carries inline script text and
        `srcdoc` documents that were never on screen at all. Stripping those,
        and the value-bearing attributes, is `_EVIDENCE_HTML_JS`'s remaining
        job and has nothing to do with masking.

        **One round trip now.** It used to be three — a harvest on each side of
        the snapshot, retried until they agreed — because the mask had to be
        built out of text the snapshot had actually seen, and a page repainting
        between the two reads produced a mask with a hole in it. With no mask
        there is nothing to reconcile, so a beat can no longer come back as
        `{"omitted": …}` because the page would not hold still.
        """
        return self._capture_page()

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
        spotlight() with no argument clears it.

        **The verb waits out the exit transition.** Clearing a spotlight now
        animates (issue #111), and a verb that returned mid-fade would hand the
        next beat a half-restored element: this beat's evidence records the
        spotlight target's `outerHTML` *including its style attribute*, which
        would then be a value that depends on when the compositor happened to
        fire — not a thing a storyboard can be written against. So when this
        returns, the previous element's inline style is byte-identical to what
        the spotlight found.

        What it costs is bounded and self-calibrating rather than a flat
        charge: the wait is the element's *computed* transition time, so a
        clear takes ~250 ms longer than it used to on an ordinary take and ~1 ms
        longer under `deterministic=True`, where the motion rule flattens
        transitions. Measured end to end, including the verb's own `pause(0.3)`:
        0.55 s against 0.31 s before, and 0.33 s deterministic. A storyboard
        that moves a highlight from one element to the next pays it once — the
        old element's exit runs, then the new one's entrance — and what it buys
        is that the two are never on screen half-lit at the same time.
        """
        # `evaluate` resolves the promise the clear returns, so this line does
        # not come back until the exit transition has run to its end and the
        # style attribute has been put back. That is the whole of the paragraph
        # above, and it is one word: `evaluate`.
        self.page.evaluate("() => window.__demoSpotlightClear()")
        if selector:
            self.page.locator(selector).first.evaluate(
                "el => window.__demoSpotlight(el)"
            )
        # Set after the highlight actually landed, so a selector that matched
        # nothing (and raised above) never becomes the scope of a beat's
        # evidence — a scope naming an element that is not there would put
        # `"html": null` in the file with no explanation.
        self._spotlit = selector or None
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
        deadline = time.monotonic() + 10
        box = None
        while box is None:
            box = self.page.locator(selector).first.bounding_box()
            if box is None:
                if time.monotonic() > deadline:
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
        cover, `self.page` is the live Playwright page.

        Type example values. Nothing here hides what it types — see "What this
        records, and what it does not defend against" in SKILL.md.
        """
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
