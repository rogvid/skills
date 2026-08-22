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

import re
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from .chrome import chrome_geometry, chrome_html
from .content import OPENING_HOLD_LIMIT_S, content_rect, opening_gap
from .core import (
    INTERLUDE_CSS_WEB,
    WEB_WINDOW_BODY,
    _beat_verb,
    _DemoBase,
    _env,
    _env_flag,
)
from .target import guard_target

# Pastel gradient behind the window — matches the terminal recorder's
# background so web and terminal demos share one look.
_WEB_BG = "linear-gradient(135deg, #f6d5f0 0%, #d7e3fb 52%, #cdeede 100%)"

# The window frame drawn behind the recording: gradient background + a dark
# rounded window with a title bar and traffic-light buttons. Screenshotted
# once per run; the app video is composited into its body by ffmpeg.
#
# `__WINBG__` is `core.WEB_WINDOW_BODY`, and it is a shared constant rather
# than a literal because the interlude card is painted to match this colour in
# the encoded frame (issue #291) — see `core.WEB_CARD_BODY`, which is this value
# compensated for the extra encoder the card goes through (#301). Paint this
# from a literal and the two drift apart on the next edit, with nothing left
# tying the card's compensation to the thing it compensates for.
_FRAME_HTML = """<!doctype html><meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; }
  body { background: __BG__; }
  #win { position: fixed; left: __WINX__px; top: __WINY__px;
    width: __WINW__px; height: __WINH__px; border-radius: 14px;
    overflow: hidden; background: __WINBG__;
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
#
# **The dot follows pointer *motion*, not every `mousemove` — issue #186.**
#
# Chromium dispatches one `mousemove` of its own per document, at the widget's
# initial pointer position — `(0, 0)` on a fresh page — when it recomputes
# hover state after the first layout. Nothing about it says "synthetic": it is
# `isTrusted`, it carries a `pointerover`, a `mouseover` and a `pointermove`
# beside it exactly as a real move does, and it belongs to no storyboard beat.
# Measured on the fixture page here, it is *created* at `timeStamp` 9 ms and
# *delivered* at ~89 ms, against a `DOMContentLoaded` at ~20 ms — and `attach`
# below subscribes at `DOMContentLoaded`, because it needs `document.body`.
# Which of the two wins is load-dependent, so whether an 18 px dot is burned
# into the top-left corner of a take's opening stills is a coin flip: eleven of
# twelve takes under 14-way CPU load had it, one did not. That is what makes a
# `deterministic=True` take's stills fail to reproduce (#185, #188), and it is
# the whole of it — two stills that disagree differ in 69 of 921 600 pixels,
# all of them inside x 0-8, y 0-8.
#
# What tells that event apart from a real one is not its trust, its type or
# its timing: it is that it reports **a position the pointer was already at**.
# So the overlay remembers the position it has been told about — seeded with
# `(0, 0)`, where a fresh page's pointer sits and where that event lands — and
# drops a `mousemove` that repeats it. Nothing is drawn until the pointer is
# somewhere it has not been, so the dot stays where the stylesheet parks it,
# off screen, until the storyboard moves the pointer for the first time. That
# is the one thing here that does not depend on when an event was delivered:
# both orderings of the load-time event and a storyboard's first move end with
# the dot at the position the storyboard asked for.
#
# **Positions rather than `movementX`/`movementY`, and this is issue #202.**
# The delta the browser reports for the *first* mouse event in a page is a
# build detail, because there is no previous event to measure it against:
#
#   | Chromium | park at (60, 640) as the page's first mouse event |
#   |---|---|
#   | 136 (playwright 1.52) | `movementX/Y` 60, 640 — measured from the origin |
#   | 147 (playwright 1.59) | `movementX/Y` **0, 0** — measured from itself |
#   | 151 (playwright 1.61) | 60, 640 — and a settle event precedes it |
#
# A guard reading `movementX === 0 && movementY === 0` therefore threw the
# storyboard's own park away on 147 — indistinguishable there from the
# load-time event — while staying green on 151, which is how it passed CI and
# `tests/smoke` on one machine and failed on another. Reading positions costs
# nothing on any of the three and does not ask the engine for a delta at all,
# so an engine that implements no `movementX` behaves like every other.
#
# What it cannot do, and cannot be made to do: draw the dot for a pointer verb
# that lands on exactly `(0, 0)`. The pointer *starts* there, so "the pointer
# was moved to the origin" and "the pointer has not moved" are the same state
# and no rule reading events can separate them. A storyboard that wants the
# cursor at the very corner of the viewport has to pass through somewhere else.
#
# **The dot is built at `document_start` and inserted at `DOMContentLoaded`,
# and that split is issue #203.** All of the above is a rule about events, and
# a rule about events is worth nothing while nothing is listening. `attach`
# needs `document.body`, so it can only run at `DOMContentLoaded` — and a
# `mousemove` dispatched before that used to be delivered to no handler at
# all. Nothing replaces it: the pointer is where it was asked to be, the
# browser has no reason to say so again, and the dot stays at the stylesheet's
# off-screen park for the rest of the document. Reachable only by combining
# two `rec.page` calls, neither of which `SKILL.md` or `reference/` documents —
# what they document is the escape hatch itself, `rec.page`:
#
#     rec.page.goto(url, wait_until="commit")   # Recorder.goto waits for load
#     rec.page.mouse.move(60, 640)
#
# Measured against `tests/fixture` with the position rule above already in
# place, 12 takes per build, counting only the takes where a probe confirmed
# the move was delivered while `document.readyState` was still `'loading'`:
# the dot was placed in **0 of 17** such takes before this split and **13 of
# 13** after, on Chromium 136, 147 and 149. Chromium 151 never reached the
# window in 24 takes — its `DOMContentLoaded` lands at 11-17 ms and
# Playwright's move at 39-68 ms — so it is untested rather than passing.
#
# So the listeners are registered while the script itself is evaluated, which
# for a Playwright init script is `document_start`, and the element they write
# to is created there too. **A detached element can be styled**: the inline
# `left`/`top` a `mousemove` writes is still on the div when `attach` puts it
# in the document, so the dot appears at `DOMContentLoaded` already standing
# where the pointer went. Nothing is drawn any earlier than it used to be —
# the stylesheet and the insertion are both still at `DOMContentLoaded`, and
# an untouched pointer still leaves the parked-off-screen dot #186 is about.
#
# What is deliberately *not* covered: a move dispatched before the navigation.
# That one lands in the previous document, which had its own overlay and its
# own dot, and no rule in the new document can recover it. Nor is the move
# Chromium drops on the floor — in the same 48 takes the document received no
# `mousemove` at all in 3 of 12 on 136, 4 of 12 on 147, 2 of 12 on 149 and 7
# of 12 on 151, identically before and after this change, and a dot cannot be
# placed for an event that never arrives. That is issue #230.
#
# What this does not do: place the dot after a navigation. A document that
# replaces the one the dot lived in gets a fresh, parked dot, and Chromium
# sends its hover-recompute move only for the *first* document — measured, two
# further navigations with the pointer inside the viewport produced no
# `mousemove` at all, over four seconds. So the cursor is already absent
# between a `goto()` and the next pointer verb today, and this changes nothing
# about that.
_CURSOR_JS = """
(() => {
  const dot = document.createElement('div');
  dot.id = '__demo_cursor';
  let atX = 0, atY = 0;
  window.addEventListener('mousemove', (e) => {
    if (e.clientX === atX && e.clientY === atY) return;
    atX = e.clientX;
    atY = e.clientY;
    dot.style.left = e.clientX + 'px';
    dot.style.top = e.clientY + 'px';
  }, true);
  window.addEventListener('mousedown', () => dot.classList.add('__down'), true);
  window.addEventListener('mouseup', () => dot.classList.remove('__down'), true);
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
    document.body.appendChild(dot);
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

# How long `press()` holds the frame after the key goes down (issue #130).
#
# A key press is instantaneous in a way typing is not: the list refilters, the
# dialog closes, the focus ring jumps, and it is over inside one frame. A verb
# that returned the moment Playwright did would put the change and the *next*
# verb's action in the same frame of video, which is the jump cut `type_into`'s
# per-character delay exists to avoid — the whole reason the storyboard is not
# just driving Playwright.
#
# 0.5 s is a floor with a reason rather than a round number: SKILL.md's
# "Pacing and perception" puts a saccade at ~200 ms and says a change needs a
# fixation after it to be recognised rather than merely noticed. It is
# deliberately *below* the 1.5 s emphasis floor, because a press is a beat in
# the middle of an interaction and not the emphasis itself — a storyboard that
# wants the result dwelt on says `hold()` after it, as it does after a click.
PRESS_HOLD_S = 0.5

# How long `clear()` leaves the selection highlight up before deleting it.
#
# The highlight is the only thing on screen that explains where the text went.
# Without the pause the field goes from a value to nothing between two frames
# with no cursor, no keystroke and no selection visible — exactly the "jump
# cut" reading issue #130 filed against `page.keyboard.press("Backspace")`.
CLEAR_SELECT_HOLD_S = 0.4

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
        ticket: str | None = None,
        allow_private: bool | None = None,
        wrapper: bool | None = None,
    ) -> None:
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=terminal_prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model, strict=strict,
            deterministic=deterministic, clock=clock,
            timezone_id=timezone_id, locale=locale, evidence=evidence,
            criteria=criteria, ticket=ticket, allow_private=allow_private,
        )
        self.base_url = (
            base_url or _env("BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        # The base checked `DEMO_VIDEO_BASE_URL`; this checks what this take
        # actually resolved, which is the explicit argument when there is one.
        # Still before a browser exists — `__enter__` is what launches one.
        guard_target(
            self.base_url,
            self._allow_private,
            source="this take's base_url",
        )
        # Opt-in wrapper path (issue #358, design record #355): the take
        # records a recorder-owned wrapper page — window chrome, a caption
        # band below the app rect — with the app in an iframe at true pixel
        # size, and the exit-time composite does not run. Transitional: #361
        # makes it the only path and removes the flag.
        if wrapper is None:
            wrapper = _env_flag("WRAPPER")
        self._wrapper = bool(wrapper)
        # The app iframe's Frame, once `_start` has mounted it (wrapper only).
        self._app_frame: object | None = None
        # Where the wrapper take last commanded the pointer, in wrapper-page
        # coordinates. Seeded at the origin, where a fresh page's pointer
        # actually sits; `_glide` is the only writer.
        self._cursor_at: tuple[float, float] = (0.0, 0.0)
        if not self._wrapper:
            # The recording is composited into a window and scaled down
            # (~0.8), so captions are rendered larger to stay readable in the
            # final mp4. A wrapper take is recorded at true pixel size and
            # keeps the base 26px — the terminal recorder's effective size —
            # because there is no scale to compensate for.
            self._caption_font_px = 34
        # And the same composite is why the interlude card is not the default
        # one: the terminal palette is the colour of a *terminal*, and inside
        # this window frame a full-bleed field of it reads as one — the whole
        # of issue #291. The web card is the window's own body colour instead,
        # as it lands in demo.mp4. See core.INTERLUDE_CSS_WEB.
        self._interlude_css = INTERLUDE_CSS_WEB
        # What spotlight() is currently pointing at, which is what a beat's
        # evidence is scoped to. Held here rather than read back out of the
        # page: `window.__spotEl` is an element handle, not a selector, and the
        # selector is the thing worth writing down.
        self._spotlit: str | None = None
        # Set by the retained `framenavigated` listener. Nothing reads it;
        # see `_note_navigation` for why the listener is kept anyway.
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

    @property
    def app(self):
        """The app's document — where the verbs point.

        On a wrapper take this is the app iframe's Playwright `Frame`; the
        wrapper document around it is the recorder's own chrome, so
        `rec.app.locator(...)` is the escape hatch that reaches the app the
        way the verbs do. `rec.page` stays the wrapper `Page` — the whole
        browser surface, chrome included — so nothing an escape hatch could
        reach before is out of reach now.

        Off the wrapper path it is the page's main frame, so a storyboard
        written against `rec.app` records identically on both paths.
        """
        if self._wrapper:
            if self._app_frame is None:
                raise RuntimeError(
                    "this wrapper take has no app frame yet — rec.app exists "
                    "once the recorder has entered (`with Recorder(...) as "
                    "rec:`), which is what mounts the iframe"
                )
            return self._app_frame
        return self.page.main_frame

    def _target(self):
        """What locator-driving verbs run against: the app frame on a wrapper
        take, the page otherwise. `Frame` and `Page` share the whole surface
        used here (locator/evaluate/url/title), so one call site serves both.
        """
        return self._app_frame if self._wrapper else self.page

    def _init_context(self, context) -> None:
        # The wrapper take's cursor lives in the wrapper document (see
        # chrome.py) and is driven explicitly by the recorder, so the
        # event-following dot is not injected there: context init scripts run
        # in every frame, and the app iframe would otherwise draw a second
        # dot on top of the chrome's.
        if not self._wrapper:
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

    def _watch_extra(self, page) -> None:
        """What a *document* being replaced means to a web take.

        **This used to be a `_watch_page` override, and that is the bug #147
        is about.** `_DemoBase._watch_page` already existed under that name —
        the subscription for `console`, `pageerror`, `requestfailed` and
        `response`, every problem this recorder exists to write down and what
        `strict=True` refuses a take over. Declaring it here shadowed all four
        for web takes only: no error, no warning, `timeline.json` well-formed
        and empty of issues. The base now seals `_watch_page` and calls this,
        so the same mistake is a `TypeError` while the module imports.

        Neither callback below calls into Playwright. Page events are
        delivered on the same thread that is blocked inside a Playwright call,
        so calling back into the API from one of them is a way to deadlock a
        take — `_note_document_replaced` writes an issue and reads `page.url`,
        which is the last URL the connection already told this process about
        and costs no round trip.
        """
        # **Kept deliberately when the masking went** — #142's carve-out.
        # Written for the paint gate, which is gone; nothing reads the flag.
        #
        # `frameattached` went with the rest: it existed because a frame that
        # attached after the parent's checkpoint had never been verified, which
        # is a statement about a mask and about nothing else.
        page.on("framenavigated", self._note_navigation)
        # The caption bar is a DOM element, so a document replacing the one it
        # lives in takes it off the screen (#134). This is the signal for that
        # and `framenavigated` is not: Playwright fires `framenavigated` for
        # same-document history navigation too, so an SPA route change would
        # clear a caption that is still on screen — the same lie in the other
        # direction. `domcontentloaded` is fired once per new document, and
        # only for the main frame, so an iframe loading does not touch it.
        #
        # That last sentence was read off `playwright-core` and is now
        # measured: `NAVIGATIONS` in `tests/unit` holds the page-event stream
        # a real Chromium delivers for `goto`, a link click, `go_back`, a form
        # submit, `location.href`, a meta refresh, a reload, two same-document
        # SPA route changes and an iframe load, identical on Chromium 136, 147
        # and 151, and the suite replays each one through this subscription
        # (issue #179).
        #
        # On a **wrapper** take (#358) that main-frame-only property is what
        # ends the #134 class: the caption lives in the wrapper document,
        # `goto()` navigates the app *iframe*, and the wrapper document is
        # never replaced — so this never fires mid-take, no `caption_lost`
        # issue is recorded, and both are the truth rather than a suppression:
        # the line really is still on screen after the app navigates, and the
        # beats that keep reporting it are right.
        page.on("domcontentloaded", self._note_document_replaced)

    def _start(self) -> None:
        if self._wrapper:
            self._start_wrapper()
            return
        # Render the window+background frame once (on a throwaway page, so the
        # app page stays clean for goto). ffmpeg composites the recording into
        # it in _postprocess.
        self._geom = self._frame_geometry()
        g = self._geom
        # Browser-like window title: the app's host (e.g. "localhost:3000").
        title = urlparse(self.base_url).netloc or "app"
        html = (
            _FRAME_HTML.replace("__BG__", _WEB_BG)
            .replace("__WINBG__", WEB_WINDOW_BODY)
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

    def _start_wrapper(self) -> None:
        """Build the wrapper page on the recorded page itself (issue #358).

        The chrome is the recording, not a still ffmpeg composites later: the
        recorded page carries the window, the caption band and the cursor
        overlay, and the app loads into an iframe sized to the app rect at
        true pixel size. `self._geom` keeps `_frame_geometry`'s key names, so
        `_content_rect` and every other geometry consumer reads one shape.
        """
        self._geom = chrome_geometry(self._size["width"], self._size["height"])
        title = urlparse(self.base_url).netloc or "app"
        self.page.set_content(
            chrome_html(
                self._geom,
                title=title,
                window_body=WEB_WINDOW_BODY,
                accent=self._accent,
                caption_font_px=self._caption_font_px,
            )
        )
        # Mounted here rather than shipped in the chrome document because the
        # iframe is the *web* medium's content — #362 mounts xterm.js in the
        # same slot. Size comes from the slot's CSS (chrome.py), which is the
        # app rect exactly.
        self.page.evaluate(
            "() => {"
            " const frame = document.createElement('iframe');"
            " frame.id = '__chrome_app';"
            " frame.name = '__chrome_app';"
            " frame.src = 'about:blank';"
            " document.getElementById('__chrome_slot').appendChild(frame);"
            " }"
        )
        handle = self.page.wait_for_selector(
            "#__chrome_app", state="attached", timeout=10_000
        )
        frame = handle.content_frame()
        if frame is None:
            raise RuntimeError(
                "the wrapper page mounted the app iframe but Playwright "
                "returned no frame for it — the take cannot drive the app"
            )
        self._app_frame = frame

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
        if self._wrapper:
            # The recorded page already is the framed picture — one encoder,
            # no composite, no opening-hold overlay (the wrapper's opening is
            # #360's). `_opening_held` stays None: this path never claims to
            # cover a gap, which is the same honest answer the terminal
            # recorder gives.
            return
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
        """The ARIA tree, the URL and the title, as one document.

        Read off `_target()`: on a wrapper take the page is the recorder's
        own chrome and the crash happened in the app, so the app frame is
        what a failure dump has to show.
        """
        target = self._target()
        aria, aria_format = self._aria(target.locator("body"))
        head = [f"url: {target.url}"]
        try:
            head.append(f"title: {target.title()}")
        except Exception:  # noqa: BLE001 - a dying page still has a URL
            head.append("title: (unreadable)")
        head.append(f"aria_format: {aria_format}")
        return "\n".join([*head, "", aria or "(no accessibility snapshot)"])


    def _note_navigation(self, frame) -> None:
        """A frame navigated. Nothing reads this, and that is deliberate.

        The flag used to mean "the next checkpoint must re-inject and re-verify
        the mask". There is no mask, so nothing consumes it. The *listener* is
        what #142 keeps, and it fires for any frame and for same-document
        history navigation as well, which is why it is not what invalidates the
        caption — see `_note_document_replaced`.

        Deliberately does nothing else — see `_watch_page` for why touching
        Playwright from an event callback is not safe here.
        """
        self._navigated = True

    def _note_document_replaced(self, page) -> None:
        """A new document is in the main frame, so the caption bar is gone.

        `_CAPTION_JS` builds `#__demo_caption` inside the document, and a full
        page load destroys it. `self._caption` — which every beat that does not
        carry its own caption is stamped with — is a Python attribute and
        survives, so without this a mid-take `goto()` leaves every later beat
        reporting a line that is not on screen, in a `timeline.json` this skill
        says to commit (issue #134).

        Clearing it here rather than in `goto()` covers a link click,
        `go_back()`, a form submit, `location.href` and a meta refresh too:
        they all replace the document and none of them goes through `goto`.
        Measured, not assumed — see `_watch_extra` and `NAVIGATIONS` in
        `tests/unit`.

        **The line does not go quietly (issue #180).** Clearing alone leaves
        the beat log honest and mute: a storyboard that captions, navigates
        and then holds records an empty caption column and nothing that says
        why, which is true and is almost certainly not what its author meant.
        So the drop is recorded as a `caption_lost` issue naming the line and
        the document that replaced it, and `timeline.md`'s Issues section
        carries it. Deliberately **not** in `STRICT_KINDS`: this is the
        storyboard's mistake, not the app saying it is broken, and strict mode
        is a verdict on the app.
        """
        lost, self._caption = self._caption, ""
        if not lost:
            # Every take opens with a document load, and a storyboard that
            # navigates before it says anything does it again. An issue per
            # load with no caption up would be noise nobody reads.
            return
        try:
            url = page.url
        except Exception:  # noqa: BLE001 - a page dying still lost the caption
            url = "(unknown)"
        self._note_issue(
            "caption_lost",
            f"a new document at {url} replaced the one holding the caption "
            f"{lost!r}, so the line left the screen — every beat after this "
            f"reports no caption until the storyboard sets one again",
            lost_caption=lost,
            url=url,
        )

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
        """One pass: the ARIA snapshot, the URL, and the spotlight target.

        Captured from `_target()`: on a wrapper take (#358) the page's own
        body is the recorder's chrome and one opaque iframe node, so evidence
        read there would describe the recorder instead of the app.
        """
        doc = self._target()
        aria, aria_format = self._aria(doc.locator("body"))
        payload: dict = {
            "scope": self._spotlit,
            "url": doc.url,
            "title": doc.title(),
            "aria_format": aria_format,
            "aria": aria,
            "scope_aria": None,
            "html": None,
        }
        if self._spotlit:
            target = doc.locator(self._spotlit).first
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
        # On a wrapper take the *iframe* navigates; the wrapper document —
        # which holds the caption, the cursor and the chrome — never does,
        # so a mid-take goto cannot take the caption off the screen (see
        # `_watch_extra`).
        target = self._target()
        # Asset fetches hang occasionally on a busy dev box — a reload
        # recovers, so retry rather than dying mid-recording.
        for attempt in range(3):
            try:
                target.goto(url, timeout=45_000)
                break
            except Exception as exc:
                # An app that refuses framing is not a flake: Chromium
                # cancels the iframe navigation over X-Frame-Options or CSP
                # frame-ancestors with exactly this error, and what a retry
                # would buy is the artifact-lie this slice must not ship — a
                # silently blank window recorded as a demo. Refuse instead,
                # naming the header (issue #358).
                if self._wrapper and "ERR_BLOCKED_BY_RESPONSE" in str(exc):
                    raise RuntimeError(self._frame_refusal(url)) from exc
                if attempt == 2:
                    raise
        try:
            target.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # apps that poll never go network-idle; the page is up

    def _frame_refusal(self, url: str) -> str:
        """Why this app cannot be recorded through the wrapper's iframe.

        Chromium's `ERR_BLOCKED_BY_RESPONSE` says a response header blocked
        the frame but not which, so the recorder asks once more —
        `context.request` reuses the browser's own network stack — and reads
        the header out of the answer. Named, because "the iframe stayed
        blank" is not something a storyboard author can act on and the header
        is.
        """
        header = None
        try:
            answer = self._context.request.get(url)
            xfo = answer.headers.get("x-frame-options")
            if xfo:
                header = f"X-Frame-Options: {xfo}"
            else:
                csp = answer.headers.get("content-security-policy", "")
                found = re.search(r"frame-ancestors[^;]*", csp)
                if found:
                    header = f"Content-Security-Policy: {found.group(0).strip()}"
        except Exception:  # noqa: BLE001 - the refusal stands without a name
            pass
        named = header or (
            "a frame-blocking response header (the follow-up request could "
            "not read which)"
        )
        return (
            f"this app refuses to be framed: {url} answered with {named}, so "
            f"Chromium blocked the wrapper take's iframe. Recording on would "
            f"produce a silently blank window presented as a demo, so the "
            f"take refuses instead. Record without wrapper=True, or serve "
            f"the demo target without that header."
        )

    @_beat_verb("terminal")
    def terminal(self, command: str) -> None:
        """Type a command in an on-screen terminal card, then perform the
        real action it describes right after this returns.

        The card is raised in the app's document (`_target()`), so on a
        wrapper take it appears over the app inside the window — the same
        place it lands on a composite take — rather than over the chrome.
        """
        self._target().evaluate("cmd => window.__demoTerminal(cmd)", command)

    @_beat_verb("terminal_output")
    def terminal_output(self, text: str) -> None:
        """Reveal real command output inside the terminal card, line by
        line — run the command first, pass its actual (trimmed) output."""
        self._target().evaluate("t => window.__demoTerminalOutput(t)", text)

    @_beat_verb("terminal_close")
    def terminal_close(self, stamp: str | None = None) -> None:
        """Stamp a closing line ('✓ delivered' by default, "" for none)
        on the terminal card and fade it out."""
        if stamp != "":
            self._target().evaluate("s => window.__demoTerminalDone(s)", stamp)
            self.pause(1.2)
        self._target().evaluate("() => window.__demoTerminalHide()")
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
        #
        # Both calls run in the app's document (`_target()`): the spotlight
        # functions are context init scripts, which Playwright evaluates in
        # every frame, so they exist in the wrapper take's iframe too — and
        # the element being lit lives there.
        self._target().evaluate("() => window.__demoSpotlightClear()")
        if selector:
            self._target().locator(selector).first.evaluate(
                "el => window.__demoSpotlight(el)"
            )
        # Set after the highlight actually landed, so a selector that matched
        # nothing (and raised above) never becomes the scope of a beat's
        # evidence — a scope naming an element that is not there would put
        # `"html": null` in the file with no explanation.
        self._spotlit = selector or None
        self.pause(0.3)

    def _glide(self, x: float, y: float, steps: int) -> None:
        """Move the pointer to page coordinates `(x, y)`, dot included.

        The legacy path is one Playwright call: the injected dot follows the
        `mousemove` events. On a wrapper take the dot lives in the wrapper
        document, and no wrapper listener can hear a move whose target is
        inside the iframe — the browser delivers it to the iframe's document
        — so the recorder drives the dot itself, one explicit update per
        pointer step. The dot is exactly where the pointer was commanded to
        be, by construction, which is also what makes the #186/#202 class
        (a dot placed by an event the storyboard never sent) unreachable
        here: nothing listens, so nothing synthetic can move it.

        Coordinates are wrapper-page coordinates either way — Playwright's
        `bounding_box()` answers relative to the main frame's viewport even
        for elements inside an iframe, so the app-rect offset is already in
        every box the verbs read.
        """
        if not self._wrapper:
            self.page.mouse.move(x, y, steps=steps)
            return
        sx, sy = self._cursor_at
        for i in range(1, steps + 1):
            xi = sx + (x - sx) * i / steps
            yi = sy + (y - sy) * i / steps
            self.page.mouse.move(xi, yi)
            self.page.evaluate(
                "([x, y]) => window.__demoChromeCursor(x, y)", [xi, yi]
            )
        self._cursor_at = (x, y)

    def _cursor_pressed(self, down: bool) -> None:
        """Squeeze (or release) the wrapper document's cursor dot."""
        if not self._wrapper:
            return
        fn = "__demoChromeCursorDown" if down else "__demoChromeCursorUp"
        self.page.evaluate(f"() => window.{fn}()")

    @_beat_verb("move_to")
    def move_to(self, selector: str) -> None:
        """Glide the cursor onto an element (smooth, watchable motion)."""
        box = self._target().locator(selector).first.bounding_box()
        if box is None:
            raise RuntimeError(f"no visible element for {selector!r}")
        self._glide(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30
        )

    @_beat_verb("click")
    def click(self, selector: str) -> None:
        self.move_to(selector)
        self.pause(0.4)
        self._cursor_pressed(True)
        try:
            self._target().locator(selector).first.click()
        finally:
            self._cursor_pressed(False)

    @_beat_verb("click_fast")
    def click_fast(self, selector: str) -> None:
        """Coordinate click without Playwright's stability wait — for
        elements that re-render continuously (polling UIs re-mount
        popovers, restarting entrance animations, so locator.click()'s
        actionability check can stall for minutes)."""
        deadline = time.monotonic() + 10
        box = None
        while box is None:
            box = self._target().locator(selector).first.bounding_box()
            if box is None:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"no visible element for {selector!r}")
                time.sleep(0.1)
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self._glide(x, y, steps=15)
        self.pause(0.3)
        self._cursor_pressed(True)
        try:
            self.page.mouse.click(x, y)
        finally:
            self._cursor_pressed(False)

    @_beat_verb("type_into")
    def type_into(self, selector: str, text: str, delay_ms: int = 40) -> None:
        """Click a field and type into it visibly, key by key — for form
        demos (checkout, login, search). For anything the verbs don't
        cover, `self.page` is the live Playwright page.

        **Types at the caret; it does not empty the field first.** A second
        term typed into a box that already holds one appends to it. `clear()`
        is the verb for emptying it, and it is a separate beat on purpose —
        see its docstring.

        Type example values. Nothing here hides what it types — see "What this
        records, and what it does not defend against" in SKILL.md.
        """
        self.click(selector)
        self.page.keyboard.type(text, delay=delay_ms)

    @_beat_verb("clear")
    def clear(self, selector: str) -> None:
        """Empty a field, visibly — click it, select what is in it, delete.

        The counterpart to `type_into`, which appends (issue #130). A search
        demo empties the box between terms as a matter of course, and before
        this verb existed the only way to do it was `rec.page.keyboard`, which
        records no beat at all: `timeline.json` showed the click and then the
        next caption, and the two keystrokes that actually emptied the field
        happened in the gap between them.

        **A verb rather than an argument on `type_into`.** Emptying a field is
        something the viewer watches happen, so it is a thing with its own
        beat, its own frame and its own evidence file; folding it into
        `type_into` would give one beat that did two visible things and named
        only the second. And the case that settles it takes no text at all —
        the demo that clears the search box to show the unfiltered list
        restored has no `type_into` call for the argument to hang on.

        **Selects and deletes rather than animating one backspace per
        character.** The selection highlight is a frame a viewer can read, it
        costs the same whether the field holds four characters or forty, and it
        is what a person actually does. The delete is a real `Backspace`, so an
        app listening on `keydown` sees what a keyboard would send —
        `fill("")` sends no key events at all.
        """
        self.click(selector)
        self._target().locator(selector).first.select_text()
        self.pause(CLEAR_SELECT_HOLD_S)
        self.page.keyboard.press("Backspace")
        self.pause(0.3)

    @_beat_verb("press", lambda args, kwargs: args[0] if args else kwargs.get("key"))
    def press(self, key: str, hold_s: float = PRESS_HOLD_S) -> None:
        """Press one named key wherever the focus already is — `"Enter"` to
        submit, `"Escape"` to dismiss, `"Tab"` to move on, `"Control+A"`.

        Playwright's key names (`Enter`, `Escape`, `Tab`, `ArrowDown`,
        `Control+A`, `Shift+Tab`); an unknown one raises rather than typing its
        letters. One key per call, so each press is its own beat with its own
        frame — the beat records the key by name, which is the whole of what
        `rec.page.keyboard.press` could not do (issue #130).

        **Cursor-free and selector-free, deliberately.** The keys a form demo
        needs are about the thing that already has focus: `Tab` is a demo *of*
        the focus order and clicking a target first would destroy it, and
        `Escape` dismisses whatever is up rather than acting on an element.
        `type_into()` and `clear()` leave the caret in the field they drove, so
        a press straight after either one lands where the viewer is looking.

        Holds `hold_s` afterwards so the effect is on screen long enough to
        read — see PRESS_HOLD_S. Shorten it when touring several fields with
        `Tab`; lengthen it, or say `hold()`, when the press is the point.
        """
        self.page.keyboard.press(key)
        self.pause(hold_s)

    @_beat_verb("scroll_to")
    def scroll_to(self, selector: str) -> None:
        self._target().locator(selector).first.evaluate(
            "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
        )
        self.pause(1.2)

    @_beat_verb("wait_for")
    def wait_for(self, selector: str, timeout_s: float = 60) -> None:
        """Wait for something the app does on its own (a job, a run)."""
        self._target().locator(selector).first.wait_for(timeout=timeout_s * 1000)

    @contextmanager
    def act(self, label: str) -> Iterator[None]:
        """Stamp one beat around raw `rec.page` work, named by `label`.

            with rec.act("apply the machinery filter"):
                rec.page.select_option("#type-filter", "machinery")

        `rec.page` is the escape hatch, and anything done through it bare is
        invisible: no beat, so no frame is aimed at it, no evidence file is
        written, and the blind review cannot see it happened (issue #344). The
        failure that motivated this was exactly that shape — a storyboard
        drove a filter with `rec.page.select_option(...)`, the server log
        proved the request fired, and the take's beat log had nothing: the
        reviewer correctly reported the filtering was never exercised, while
        the caption claimed it. `clear()`'s docstring records the same class
        of hole for `rec.page.keyboard`; this is the wrapper that closes it
        for whatever the verbs don't cover.

        The block gets what a verb gets: a span in the beat log (verb `act`,
        the label as its target), a mid-point review frame, and an evidence
        file. The label is required and must name what the block does —
        an empty or blank one is refused before any beat opens, because a
        nameless beat is the invisibility this verb exists to end.

        **An exception inside the block behaves as it does in a failing
        verb:** the beat still closes with its `t_end` stamped, the error's
        type and message are recorded on it verbatim, and the exception
        propagates — so the take's failure path (the `failure/` dump, the
        marker) runs exactly as if a verb had raised. A beat-stamping verb
        called inside the block folds into this beat, like the verbs a
        composite verb is built from.
        """
        if not label or not label.strip():
            raise ValueError(
                "act() needs a non-empty label naming what the block does — "
                "the label is the only thing that puts this work in the "
                "timeline (issue #344)"
            )
        with self._beat("act", selector=label):
            yield
