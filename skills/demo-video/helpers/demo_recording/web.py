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

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .core import (
    OPENING_HOLD_LIMIT_S,
    SECRET_MASK,
    Secret,
    SecretLeak,
    _beat_verb,
    _DemoBase,
    _env,
    content_rect,
    opening_gap,
)

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


# Redaction: blur the elements a storyboard registered, in the page, for the
# whole take. See Recorder.redact() for why this is not done in post.
#
# THE PROPERTY THIS HAS TO HAVE: the mask never silently misses. Either the
# element is masked, or the take fails. A mask that quietly covers nothing is
# worse than no mask, because the storyboard, the reviewer and the published
# video all read as redacted.
#
# That is why masking is driven from Python through Playwright's selector
# engine rather than from `document.querySelectorAll` alone. The two disagree,
# and the difference is not academic:
#
#   page.locator('#k').count()             -> 1     (open shadow root)
#   document.querySelectorAll('#k').length -> 0
#
# Lit, Stencil, LWC, Shoelace and Ionic all put content behind that boundary,
# and a document-level <style> rule does not cross it either (measured: the
# rule computes to `none` on a shadow element, while an inline style computes
# to `blur(8px)`). Playwright also accepts `text=`, `xpath=`, `>>` and `nth=`,
# which every other verb in this file takes and which querySelectorAll cannot
# parse at all.
#
# So there are three mechanisms, layered:
#
#   1. Python resolves every registered selector through Playwright and marks
#      each element it finds — an inline `filter` at `!important` (which is
#      what reaches inside a shadow root) plus a `data-demo-redact` attribute.
#      It then *verifies*: as many elements masked as Playwright can see, or
#      SecretLeak. This is the layer that cannot silently miss.
#   2. An in-page <style> rule per root, so an element that does not exist yet
#      is masked the instant it is inserted — no JS runs between the node
#      appearing and the next paint, which is the window any "find them and
#      style them" pass leaves open on every re-render. Plain CSS selectors
#      only; the marker attribute covers everything else once seen.
#   3. A MutationObserver per root re-asserting both. Frameworks rewrite the
#      `style` attribute wholesale on re-render (this recorder's own
#      spotlight() does exactly that when it clears) and re-render the head;
#      either wipes one mechanism, and the observer puts it back inside the
#      same microtask, i.e. before the next paint.
#
# Shadow roots are found two ways: walking `.shadowRoot` (open roots only) and
# wrapping `Element.prototype.attachShadow` at document start, which catches
# every root the app opens afterwards including closed ones. A closed root
# created before this script ran is reachable by nothing — not by us and not by
# Playwright — and that case is what the verification exists to turn into a
# failed take rather than a clean-looking leak.
#
# Written as an IIFE expression so the same string works both as a context
# init script (re-applied on every navigation, before the page's own scripts)
# and as a frame.evaluate() on a live document.

# Blur radius, as a floor in px and a multiple of the element's own font size.
# A constant radius is not a safety property: 8 px hides 15 px body text and
# leaves a 52 px hero value plainly readable (measured — the glyph strokes are
# wider than the blur). `em` resolves against each element's computed font, so
# one rule scales itself; `max()` inside `blur()` keeps small text at the floor
# (verified in Chromium: 15 px text -> blur(8px), 48 px text -> blur(25.44px)).
# An ancestor `transform: scale()` needs no special handling — the filter is
# applied in local coordinates and scaled with everything else.
# How much of the element to erase, and how the radius of the optional blur is
# derived. The floor exists for text too small to measure reliably; the ratio
# is applied to *rendered* geometry, never to a computed font-size.
REDACT_BLUR_PX = 8
REDACT_BLUR_REF_PX = 15  # the rendered line height REDACT_BLUR_PX is calibrated for
REDACT_MARK_ATTR = "data-demo-redact"
REDACT_COVER_ATTR = "data-demo-redact-cover"
# Grown by this many CSS px beyond the ink it found, so antialiasing and a
# text-shadow do not peek out from under the edge.
REDACT_COVER_BLEED_PX = 4

# Withholds the first paint of a navigation until the mask is verified.
# An overlay rather than `html{visibility:hidden}`: visibility is inherited, so
# any descendant setting `visibility:visible` switches itself back on through
# it, and a page that strips unknown <style> tags defeats it outright.
_REDACT_GATE_ID = "__demo_redact_gate"

_REDACT_JS = r"""
(() => {
  const PX = __BLURPX__, EM = __BLUREM__, BLEED = __BLEED__;
  const CSS_BLUR = 'blur(max(' + PX + 'px, ' + EM + 'em))';
  const STYLE_ID = '__demo_redact_style';
  const GATE_ID = '__GATE__';
  const MARK = '__MARK__';
  const COVER = '__COVER__';
  const ERASE = __ERASE__;
  const S = window.__demoRedact || (window.__demoRedact = {
    sel: [], roots: [], obs: new WeakMap(), covers: new Map(),
    patched: false, gated: false, ticking: false,
  });
  for (const s of __SELECTORS__) if (!S.sel.includes(s)) S.sel.push(s);
  if (__GATED__) S.gated = true;

  // -- what the element actually paints ------------------------------------
  //
  // Everything below is measured from *rendered geometry*, never from a
  // computed font-size. CSS has unbounded ways to make text bigger than its
  // font-size says — a transformed descendant, `zoom`, an SVG viewBox, a
  // pseudo-element, a nested shadow root — and each one found this way is a
  // hole that has to be closed by hand. A client rect includes transforms and
  // zoom by construction, and is the same quantity whatever produced the ink.
  const deep = (el, out) => {
    out.push(el);
    let kids = [];
    try { kids = el.querySelectorAll('*'); } catch (e) { kids = []; }
    for (const kid of kids) {
      out.push(kid);
      if (kid.shadowRoot) deepRoot(kid.shadowRoot, out);
    }
    if (el.shadowRoot) deepRoot(el.shadowRoot, out);
    return out;
  };
  // Shadow roots at *every* depth, not just the first: a card whose value
  // lives in a child web component is the ordinary composition of "redact a
  // wrapper" and "reach an open shadow root", and one level of recursion
  // misses it entirely.
  const deepRoot = (root, out) => {
    let kids = [];
    try { kids = root.querySelectorAll('*'); } catch (e) { return; }
    for (const kid of kids) {
      out.push(kid);
      if (kid.shadowRoot) deepRoot(kid.shadowRoot, out);
    }
  };

  const union = (a, b) => {
    if (!a) return b;
    if (!b) return a;
    const left = Math.min(a.left, b.left), top = Math.min(a.top, b.top);
    const right = Math.max(a.right, b.right), bottom = Math.max(a.bottom, b.bottom);
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  };

  // The union of everything the element and its subtree lay out, and the
  // tallest single line of text in it. Both come from client rects; the line
  // height is per-line (getClientRects), not the union, so a wrapped
  // paragraph is not mistaken for one enormous glyph.
  const inked = (el) => {
    const nodes = deep(el, []);
    let box = null, line = 0;
    for (const node of nodes) {
      let r;
      try { r = node.getBoundingClientRect(); } catch (e) { continue; }
      if (!r || (!r.width && !r.height)) continue;
      box = union(box, r);
      // A replaced element has no text to measure and its font-size says
      // nothing about the glyphs drawn inside it, so its box stands in.
      const tag = (node.tagName || '').toLowerCase();
      if (tag === 'canvas' || tag === 'img' || tag === 'video' || tag === 'svg'
          || tag === 'object' || tag === 'embed' || tag === 'iframe') {
        line = Math.max(line, Math.min(r.height, 96));
      }
      // A pseudo-element has no node to measure. Its font-size is the one
      // place a computed style is still the best available evidence, and an
      // out-of-flow pseudo is the one shape the cover below can miss — which
      // is why the blur underneath it is sized from this too.
      for (const which of ['::before', '::after']) {
        let ps;
        try { ps = getComputedStyle(node, which); } catch (e) { continue; }
        if (!ps) continue;
        const content = ps.content;
        if (!content || content === 'none' || content === 'normal') continue;
        line = Math.max(line, parseFloat(ps.fontSize) || 0);
      }
      // Real text: every line box it occupies, post-transform.
      for (const child of node.childNodes || []) {
        if (child.nodeType !== 3 || !(child.nodeValue || '').trim()) continue;
        let rects = [];
        try {
          const range = document.createRange();
          range.selectNodeContents(child);
          rects = range.getClientRects();
        } catch (e) { rects = []; }
        for (const r2 of rects) {
          if (!r2.width && !r2.height) continue;
          box = union(box, r2);
          line = Math.max(line, r2.height);
        }
      }
    }
    return { box, line: line || PX };
  };

  const radius = (el) => Math.max(PX, inked(el).line * EM);

  // -- the cover -----------------------------------------------------------
  //
  // An opaque rectangle over what the element paints. A blur is a "how much is
  // enough" question and every answer to it is a heuristic about how the ink
  // was produced; a cover is not. The blur stays underneath as a floor — it is
  // what a stylesheet can do with no JS at all, and it reaches ink the cover's
  // rect can miss (an absolutely positioned pseudo-element), because `filter`
  // applies to everything the element renders.
  const place = (el) => {
    const { box } = inked(el);
    let c = S.covers.get(el);
    if (!box || box.width <= 0 || box.height <= 0) {
      if (c && c.isConnected) c.remove();
      return null;
    }
    if (!c || !c.isConnected) {
      c = document.createElement('div');
      c.setAttribute(COVER, '');
      c.setAttribute('aria-hidden', 'true');
      (document.body || document.documentElement).appendChild(c);
      // The top layer, when the browser has it: `<dialog>.showModal()`, a
      // popover and fullscreen all paint above every z-index there is, and a
      // key inside a modal is an ordinary thing to want redacted.
      if (typeof c.showPopover === 'function') {
        try { c.setAttribute('popover', 'manual'); c.showPopover(); } catch (e) {}
      }
      S.covers.set(el, c);
    }
    const css = 'position:fixed !important;'
      + 'left:' + (box.left - BLEED) + 'px !important;'
      + 'top:' + (box.top - BLEED) + 'px !important;'
      + 'width:' + (box.width + 2 * BLEED) + 'px !important;'
      + 'height:' + (box.height + 2 * BLEED) + 'px !important;'
      + 'margin:0 !important;padding:0 !important;border:0 !important;'
      // A mid grey, not black: the cover is a hard-edged opaque rectangle,
      // and against a light page a near-black one gives the encoder a step
      // it answers with ringing several pixels deep — which reads, to a
      // measurement of sharpness, exactly like text showing through.
      + 'background:#b3ada2 !important;opacity:1 !important;'
      + 'visibility:visible !important;display:block !important;'
      + 'transform:none !important;filter:none !important;clip-path:none !important;'
      + 'z-index:2147483646 !important;pointer-events:none !important;';
    if (c.getAttribute('style') !== css) c.setAttribute('style', css);
    return c;
  };

  const wear = (el) => {
    const want = 'blur(' + radius(el).toFixed(2) + 'px)';
    if (el.style.getPropertyValue('filter') !== want
        || el.style.getPropertyPriority('filter') !== 'important') {
      el.style.setProperty('filter', want, 'important');
    }
    if (el.getAttribute(MARK) === null) el.setAttribute(MARK, '');
    if (ERASE) place(el);
  };

  // -- roots, gate, apply --------------------------------------------------
  const note = (root) => {
    if (!root || S.roots.includes(root)) return;
    S.roots.push(root);
    const obs = new MutationObserver(apply);
    obs.observe(root, {
      childList: true, subtree: true,
      attributes: true, attributeFilter: ['style', 'class', 'id', MARK],
    });
    S.obs.set(root, obs);
  };
  const walk = (root) => {
    let hosts;
    try { hosts = root.querySelectorAll('*'); } catch (e) { return; }
    for (const host of hosts) if (host.shadowRoot) { note(host.shadowRoot); walk(host.shadowRoot); }
  };

  const gate = () => {
    const body = document.body || document.documentElement;
    if (!body) return;
    let el = document.getElementById(GATE_ID);
    if (!S.gated) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('div');
      el.id = GATE_ID;
      el.setAttribute('aria-hidden', 'true');
      body.appendChild(el);
      if (typeof el.showPopover === 'function') {
        try { el.setAttribute('popover', 'manual'); el.showPopover(); } catch (e) {}
      }
    }
    const css = 'position:fixed !important;inset:0 !important;'
      + 'width:100vw !important;height:100vh !important;'
      + 'background:#fff !important;opacity:1 !important;'
      + 'visibility:visible !important;display:block !important;'
      + 'z-index:2147483647 !important;pointer-events:none !important;'
      + 'margin:0 !important;transform:none !important;filter:none !important;';
    if (el.getAttribute('style') !== css) el.setAttribute('style', css);
    if (el.parentNode !== body || body.lastElementChild !== el) body.appendChild(el);
  };

  const each = (fn) => {
    for (const root of S.roots) {
      for (const s of S.sel.concat(['[' + MARK + ']'])) {
        let els;
        try { els = root.querySelectorAll(s); } catch (e) { continue; }
        for (const el of els) fn(el);
      }
    }
  };

  const apply = () => {
    note(document);
    walk(document);
    for (const root of S.roots) {
      const host = root === document ? (document.head || document.documentElement) : root;
      if (!host) continue;
      let style = null;
      for (const child of host.children || []) if (child.id === STYLE_ID) style = child;
      if (!style) {
        style = document.createElement('style');
        style.id = STYLE_ID;
        host.appendChild(style);
      }
      const rules = S.sel.concat(['[' + MARK + ']'])
        .map((s) => s + '{filter:' + CSS_BLUR + ' !important;}')
        .concat(['[' + COVER + ']{filter:none !important;}'])
        .join(' ');
      if (style.textContent !== rules) style.textContent = rules;
    }
    each(wear);
    gate();
    // Layout moves without mutating the DOM — a CSS-animated font-size, a
    // scroll, a resize, a transition. The observer never fires for any of
    // them, so the covers are re-placed every frame for as long as any exist.
    if (ERASE && !S.ticking && S.covers.size) {
      S.ticking = true;
      const tick = () => {
        try { each((el) => place(el)); gate(); } catch (e) {}
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  };

  if (!S.patched && typeof Element !== 'undefined') {
    S.patched = true;
    const real = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function (init) {
      const root = real.call(this, init);
      try { note(root); apply(); } catch (e) { /* never break the app */ }
      return root;
    };
  }

  // -- verification --------------------------------------------------------
  //
  // Independent of the styling that produced the cover: the browser's own hit
  // testing decides what is on top at a point, and it knows about stacking
  // contexts, the top layer and paint order that no property read-back does.
  // What it cannot judge is *extent* — whether the cover is over the right
  // pixels — which is geometry, and which the pixel assertions in tests/smoke
  // grade instead. tests/README.md says so.
  window.__demoRedactMark = (el) => {
    if (!el) return null;
    note(el.getRootNode ? el.getRootNode() : document);
    wear(el);
    apply();
    const { box, line } = inked(el);
    const out = {
      blur: (() => {
        const m = /blur\((\d+(?:\.\d+)?)px\)/.exec(getComputedStyle(el).filter || '');
        return m ? parseFloat(m[1]) : 0;
      })(),
      line: line,
      erase: ERASE,
      covered: !ERASE,
      samples: 0,
      misses: 0,
      hidden: !box || box.width <= 0 || box.height <= 0,
    };
    if (!ERASE || out.hidden) return out;
    const cover = S.covers.get(el);
    if (!cover || !cover.isConnected) return out;
    // pointer-events:none is what keeps a cover from swallowing the clicks a
    // storyboard makes; hit testing honours it, so it is lifted for the
    // duration of the test and put back within the same task — no paint
    // happens in between.
    const covers = [];
    for (const c of S.covers.values()) {
      if (c && c.isConnected) { covers.push(c); c.style.setProperty('pointer-events', 'auto', 'important'); }
    }
    try {
      const r = cover.getBoundingClientRect();
      for (let i = 1; i <= 3; i++) {
        for (let j = 1; j <= 3; j++) {
          const x = r.left + (r.width * i) / 4, y = r.top + (r.height * j) / 4;
          if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) continue;
          out.samples += 1;
          const hit = document.elementFromPoint(x, y);
          const ok = hit && (hit === cover || hit.hasAttribute(COVER)
            || hit.id === GATE_ID);
          if (!ok) out.misses += 1;
        }
      }
    } finally {
      for (const c of covers) c.style.setProperty('pointer-events', 'none', 'important');
    }
    out.covered = out.samples > 0 && out.misses === 0;
    return out;
  };
  window.__demoRedactUngate = () => { S.gated = false; gate(); };
  window.__demoRedactApply = apply;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply);
  }
  apply();
})()
"""

# Is this a selector the *in-page* layer can express? That layer is a
# stylesheet, so the answer is "whatever CSS parses" — and the browser is the
# only honest judge of that. See Recorder.redact() for why anything else is
# refused rather than resolved at checkpoints.
_CSS_ONLY_JS = """(sel) => {
  try { document.createDocumentFragment().querySelector(sel); return true; }
  catch (e) { return false; }
}"""


# -- evidence (issue #9) -----------------------------------------------------
#
# Everything a redacted element *renders*, as text, so the evidence writer can
# mask it. This is the whole reason evidence can inherit redaction:
# `redact("#api-key")` never tells the recorder what `#api-key` says, and a
# dump of the DOM is not covered by a control that paints over pixels.
#
# It runs in the page rather than through Playwright's engine, once per frame
# instead of once per selector per frame, and it finds the same elements the
# mask does two ways:
#
#   * `[data-demo-redact]` — the marker `wear()` stamps on every element the
#     mask has actually reached, including inside open shadow roots;
#   * the registered selectors themselves, re-resolved here, which covers an
#     element that entered the DOM since the last checkpoint. `redact()` only
#     accepts plain CSS, so `querySelectorAll` can parse every one of them.
#
# Shadow roots are walked at every depth, because `textContent` stops at the
# boundary and a value two roots down is the ordinary composition of "redact a
# card" and "the card is a web component" — the same shape the mask's own
# `deep()` exists for.
#
# **Every node in the subtree is harvested on its own, not just the element the
# selector matched**, and that is not thoroughness for its own sake. Redacting
# a *wrapper* is the ordinary call (`redact("#hero-card")` where the value is
# the 44 px child), and the wrapper's `textContent` is the label and the value
# run together — a single string that appears nowhere in an ARIA tree, which
# renders them as separate nodes. Harvesting only the matched element masked
# five of the eight keys on the smoke fixture and left three in the clear.
#
# `::before`/`::after` content is read too, from the computed style, because
# generated content has no node to hold it — and Chromium *does* put it in the
# accessibility tree, so it reaches an evidence file by a route no walk of the
# DOM would find.
# It returns **both halves in one pass**: what the redacted subtrees render,
# and what everything else renders. The second is not a nicety — see
# `_evidence_forbidden`: a harvested string that also appears outside the mask
# is rendered in the clear, so masking it costs the evidence its meaning and
# hides nothing. Computing them apart would let the page move in between and
# make the two disagree about which is which.
_EVIDENCE_HARVEST_JS = r"""(selectors) => {
  const MARK = '__MARK__';
  const COVER = '__COVER__';
  const ATTRS = ['value', 'title', 'alt', 'placeholder', 'aria-label',
                 'content', 'srcdoc', 'data-value'];
  const inside = [];
  const outside = [];
  const add = (bucket, s) => {
    if (typeof s === 'string' && s.trim()) bucket.push(s);
  };
  const roots = [document];
  const findRoots = (root) => {
    let all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of all) {
      if (el.shadowRoot) { roots.push(el.shadowRoot); findRoots(el.shadowRoot); }
    }
  };
  findRoots(document);

  // Everything the mask is covering, found the same two ways the mask itself
  // works: the marker it stamps, and the registered selectors re-resolved.
  const marked = [];
  for (const root of roots) {
    for (const sel of selectors.concat(['[' + MARK + ']'])) {
      let hits = [];
      try { hits = root.querySelectorAll(sel); } catch (e) { continue; }
      for (const hit of hits) if (marked.indexOf(hit) === -1) marked.push(hit);
    }
  }
  // Ancestry in the **flattened** tree, which is the one that renders:
  // `contains()` stops at a shadow boundary, and a light node assigned to a
  // <slot> is painted wherever the slot is, not where the DOM puts it. Walking
  // the DOM instead would call a value slotted into a redacted wrapper
  // "rendered in the clear", exempt it from masking, and publish it.
  const covered = (node) => {
    let n = node;
    while (n) {
      if (marked.indexOf(n) !== -1) return true;
      if (n.assignedSlot) { n = n.assignedSlot; continue; }
      if (n.nodeType === 11) { n = n.host || null; continue; }
      n = n.parentNode;
    }
    return false;
  };

  // Every node a subtree renders through: light descendants, shadow roots at
  // every depth, and — because a shadow root renders its host's light children
  // wherever a <slot> puts them — whatever is assigned to each slot.
  const walk = (node, acc, seen) => {
    if (!node || seen.indexOf(node) !== -1) return acc;
    seen.push(node);
    acc.push(node);
    let kids = [];
    try { kids = node.querySelectorAll ? node.querySelectorAll('*') : []; }
    catch (e) { kids = []; }
    for (const kid of kids) {
      if (seen.indexOf(kid) === -1) { seen.push(kid); acc.push(kid); }
      if (kid.shadowRoot) walk(kid.shadowRoot, acc, seen);
      if (kid.tagName === 'SLOT' && kid.assignedNodes) {
        let slotted = [];
        try { slotted = kid.assignedNodes({flatten: true}); } catch (e) { slotted = []; }
        for (const node2 of slotted) walk(node2, acc, seen);
      }
    }
    if (node.shadowRoot) walk(node.shadowRoot, acc, seen);
    return acc;
  };

  const readPseudo = (bucket, node) => {
    for (const which of ['::before', '::after']) {
      let content;
      try { content = getComputedStyle(node, which).content; }
      catch (e) { continue; }
      if (!content || content === 'none' || content === 'normal') continue;
      add(bucket, content);
      // Computed `content` comes back quoted and escaped; the tree shows the
      // string itself, so add that too.
      const quoted = /^"([\s\S]*)"$/.exec(content);
      if (quoted) add(bucket, quoted[1].replace(/\\(.)/g, '$1'));
    }
  };

  const readNode = (bucket, node) => {
    add(bucket, node.textContent);
    if (typeof node.value === 'string') add(bucket, node.value);
    // Individual text nodes as well as the concatenation: an accessible name
    // is built per element, so the pieces are what a tree shows.
    for (const child of node.childNodes || []) {
      if (child.nodeType === 3) add(bucket, child.nodeValue);
    }
    if (node.nodeType !== 1) return;  // a shadow root has no attrs or style
    for (const a of ATTRS) {
      try { add(bucket, node.getAttribute(a)); } catch (e) { /* exotic attr */ }
    }
    readPseudo(bucket, node);
    // An accessible name can be built from an element the subtree does not
    // contain. aria-labelledby/describedby are the two ways to say so, and the
    // text they point at reaches an ARIA snapshot as this node's own name.
    for (const rel of ['aria-labelledby', 'aria-describedby']) {
      let ids;
      try { ids = (node.getAttribute(rel) || '').split(/\s+/); } catch (e) { continue; }
      for (const id of ids) {
        if (!id) continue;
        let ref = null;
        try {
          const root = node.getRootNode();
          ref = root.getElementById ? root.getElementById(id)
                                    : document.getElementById(id);
        } catch (e) { ref = null; }
        if (ref) { add(bucket, ref.textContent); readPseudo(bucket, ref); }
      }
    }
  };

  for (const el of marked) {
    for (const node of walk(el, [], [])) readNode(inside, node);
  }
  // ...and everything the page *renders* that the mask is not covering.
  //
  // "Renders" is load-bearing and was learned the hard way. A first version
  // collected the text of every node, which included the page's own inline
  // `<script>` — so every literal in the fixture's source counted as "on
  // screen in the clear" and four keys stopped being masked at all. A hidden
  // element is the same mistake in miniature: an `aria-labelledby` source can
  // be `display:none` and still supply a redacted element's accessible name,
  // and exempting it because its text "appears outside" would be exempting it
  // on the strength of text nobody can read.
  const NOT_RENDERED = {SCRIPT: 1, STYLE: 1, TEMPLATE: 1, NOSCRIPT: 1,
                        LINK: 1, META: 1, HEAD: 1, TITLE: 1};
  // The recorder's own furniture does not get a vote on what the *app* renders
  // in the clear. The caption bar is the one that matters: a storyboard that
  // captions a redacted card's value puts that value into an element outside
  // the mask, and counting it here would exempt the value from masking in
  // every evidence file *and* in timeline.json — turning one authoring mistake
  // in the frames, which no recorder can undo, into the same mistake in the
  // files this skill tells people to commit, which it can.
  const CHROME = '__MARKER_IDS__';
  const chrome = (node) => {
    let n = node;
    while (n) {
      if (n.nodeType === 1) {
        const id = n.id || '';
        if (id.slice(0, CHROME.length) === CHROME) return true;
        if (id.slice(0, 6) === '__term') return true;
        try { if (n.hasAttribute(COVER)) return true; } catch (e) { /* ignore */ }
      }
      if (n.nodeType === 11) { n = n.host || null; continue; }
      n = n.parentNode;
    }
    return false;
  };
  // "Rendered" has to mean *painted*, and every relaxation of that has been a
  // leak. checkVisibility() with no arguments models `display` and
  // `content-visibility` and nothing else, so `opacity: 0`,
  // `visibility: hidden`, an .sr-only clip and `left: -9999px` all reported
  // true — and a value sitting in any of them was read as "already on screen
  // in the clear" and dropped from the mask, in every evidence file and in
  // timeline.json. Four conditions, each conservative on purpose: the cost of
  // being too strict here is masking one string more than necessary, and the
  // cost of being too lax is publishing a credential.
  const MIN_PAINT_PX = 2;
  const rendered = (node) => {
    if (NOT_RENDERED[node.tagName]) return false;
    if (chrome(node)) return false;
    try {
      if (typeof node.checkVisibility === 'function' &&
          !node.checkVisibility({opacityProperty: true, visibilityProperty: true,
                                 contentVisibilityAuto: true})) return false;
    } catch (e) { /* an older Chromium: the geometry test below still applies */ }
    // ...and geometry, which checkVisibility() models nothing about. A
    // screen-reader-only span is 1x1 with a clip; a skip link is at -9999px.
    // Both are visible to the accessibility tree, both are on nobody's screen.
    let rect;
    try { rect = node.getBoundingClientRect(); } catch (e) { return false; }
    if (!rect) return false;
    if (rect.width < MIN_PAINT_PX || rect.height < MIN_PAINT_PX) return false;
    // Off the top or left of the document entirely. Deliberately *not* a
    // viewport test: content below the fold is painted as soon as anyone
    // scrolls, and the recorder scrolls.
    if (rect.right <= 0 || rect.bottom <= 0) return false;
    return true;
  };
  for (const root of roots) {
    let all = [];
    try { all = root.querySelectorAll('*'); } catch (e) { continue; }
    for (const node of all) {
      if (covered(node) || !rendered(node)) continue;
      // Text nodes and generated content, and nothing else. Attributes and
      // `value` used to be read here too, on the assumption that this bucket
      // was collecting "what the page shows" — but `title`, `alt`,
      // `placeholder`, `aria-label`, `data-*` and `srcdoc` are not painted by
      // anything, and neither is the value of a password field or of an input
      // nobody has scrolled to. A copy-to-clipboard button carrying the key it
      // copies in `title` is ordinary UI, and it was enough to exempt that key
      // from masking everywhere.
      //
      // The same reasoning removed inline <script> text from this bucket one
      // round earlier, and `srcdoc` is a whole embedded document — the same
      // category, arrived at the same way. Note the feature contradicted
      // itself until this line changed: _EVIDENCE_HTML_JS strips exactly these
      // attributes from the markup *because* nothing renders them.
      for (const child of node.childNodes || []) {
        if (child.nodeType === 3) add(outside, child.nodeValue);
      }
      readPseudo(outside, node);
    }
  }
  const flat = (list) => list.map((s) => s.split(/\s+/).join(' ').trim())
                             .filter((s) => s).join('\n');
  return {inside: inside, outside: flat(outside)};
}"""

# The spotlight target's markup, cleaned, from a *clone* — nothing here may
# touch the live page, which is being recorded.
#
# Three things come out that `outerHTML` would otherwise put in a file nobody
# expects to hold them:
#
#   * `<script>` and `<style>` text, and `srcdoc` — source code and whole
#     embedded documents, none of it on screen. The smoke fixture's own key
#     literals are in its inline script, which is how this was noticed.
#   * anything the mask is covering: its children are replaced by the mask
#     text and its value-bearing attributes removed. Matched by the marker
#     *and* by the registered selectors, so an element the mask reached and an
#     element it is about to reach are treated the same.
#   * the recorder's own furniture — the covers, the paint gate, the caption
#     bar, the cursor — which is chrome, not app.
#
# The structural elision matters beyond tidiness: a value split across tags
# (`sk-live-<b>FAKE</b>`) has a `textContent` the string mask can find and an
# `outerHTML` it cannot, so a mask built only out of substring replacement
# would leave it in the markup whole.
_EVIDENCE_HTML_JS = r"""(el, opts) => {
  const [MARK, COVER, SELECTORS, MASK] = opts;
  // Value-bearing attributes. Every one of these can hold a string the page
  // never rendered — a `data-token`, a `data-cfg` holding a whole JSON config,
  // an `href` carrying a session id — and none is structure. Stripped from
  // *every* element, not only redacted ones: `redact()` covers where a value
  // renders, and an attribute that renders nowhere was never in a frame, a
  // still, a caption or the TTS cache. Serializing it here would make this
  // feature the only place it exists. `id`, `class`, `role` and `style` stay,
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
  drop(clone, '[' + COVER + '],[id^="__demo"],[id^="__term"]');
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
  const hide = (node) => {
    // textContent replaces the whole subtree, so every descendant of a
    // redacted element goes with it — which is what makes redacting a wrapper
    // enough.
    node.textContent = MASK;
    strip(node);
  };
  const isRedacted = (node) => {
    if (node.nodeType !== 1) return false;
    if (node.hasAttribute && node.hasAttribute(MARK)) return true;
    for (const sel of SELECTORS) {
      try { if (node.matches && node.matches(sel)) return true; }
      catch (e) { /* an ancestor-relative selector cannot match here */ }
    }
    return false;
  };
  // Elide *before* stripping attributes, because the marker is itself a
  // data-* attribute and stripping would take it with everything else.
  //
  // The spotlight target may be a *descendant* of what was redacted —
  // `wear()` marks only the element a selector matched, so spotlighting the
  // value inside a redacted card lands here with nothing in the clone marked
  // at all. Ancestry is checked on the live element, across shadow
  // boundaries, and covers the whole clone when it hits.
  let ancestor = el;
  let inherited = false;
  while (ancestor) {
    if (isRedacted(ancestor)) { inherited = true; break; }
    if (ancestor.nodeType === 11) { ancestor = ancestor.host || null; continue; }
    ancestor = ancestor.parentNode;
  }
  if (inherited) {
    hide(clone);
  } else {
    let nodes = [];
    try { nodes = Array.prototype.slice.call(clone.querySelectorAll('*')); }
    catch (e) { nodes = []; }
    for (const node of nodes) if (isRedacted(node)) hide(node);
  }
  let all = [];
  try { all = [clone].concat(Array.prototype.slice.call(
    clone.querySelectorAll('*'))); } catch (e) { all = [clone]; }
  for (const node of all) strip(node);
  return clone.outerHTML;
}"""

# How many times a beat's capture is retried when the redacted region moves
# while it is being read. Three, because the window is two round trips wide
# (~30 ms) and anything that will not hold still across three of those is a
# page whose mask cannot be built from a snapshot at all — at which point the
# beat's page text is dropped rather than written from a stale mask.
EVIDENCE_HARVEST_TRIES = 3

# How many distinct "what the page renders outside the mask" readings to keep.
# One per beat on a static page, one per *change* on a live one — and it is
# held for the whole take, so it needs a ceiling.
EVIDENCE_OUTSIDE_MAX = 200


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
        # Any navigation raises the paint gate, and only a checkpoint lowers
        # it — so every navigation has to be *noticed*, not just the ones
        # goto() makes. A link click, go_back(), a form submit, location.href
        # and a meta refresh all land here. The callback only sets a flag:
        # Playwright delivers page events on the same thread that is blocked
        # in a Playwright call, so calling back into the API from here is a
        # way to deadlock a take.
        self.page.on("framenavigated", self._note_navigation)
        # ...and attachment, not only navigation. A frame that attaches after
        # the parent's checkpoint has run has never been verified, and the
        # parent has already lowered the gate — one frame of a fresh iframe
        # painting before its own first apply() showed up as a single sharp
        # frame in one run out of six.
        self.page.on("frameattached", self._note_navigation)
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
            # the demo. `_discard_artifacts` names it too, for the same reason.
            self._frame_png.unlink(missing_ok=True)
            if hold is not None:
                hold.unlink(missing_ok=True)

    # -- redaction ----------------------------------------------------------

    @_beat_verb("redact")
    def redact(self, *selectors: str, style: str | None = None) -> None:
        """Blur everything matching these CSS selectors, for the rest of the
        take — frames and stills alike.

            rec.redact("#api-key", ".customer-email")

        **Plain CSS only**, unlike every other verb here, and the difference is
        deliberate. The layer that gives continuous cover is a stylesheet
        injected into the page, and a stylesheet can only express CSS. A
        `text=` or `xpath=` selector can be resolved — but only by asking
        Playwright, out of process, at whichever moments the recorder happens
        to ask. Measured on an ordinary fetch-then-render page, a `text=`
        selector read `filter: none` for four seconds of a ten-second take
        while its CSS-selector sibling holding the same value was masked
        throughout, and the end-of-take check then found it masked and passed.
        A guarantee that silently depends on when the element rendered is not
        one, so those dialects are refused with an error rather than accepted
        and half-honoured. Name the element with CSS, or register the text with
        `register_secret()`.

        Call it **before** the first `goto()`, at the top of the storyboard.
        The mask is a context init script, so it is in place before the page's
        own scripts run and before the first frame; matching elements are
        masked from the instant they enter the DOM, including ones the app has
        not created yet, and including inside an **open shadow root**, which
        `document.querySelectorAll` cannot see at all.

        Blurring happens **in the page, via CSS**, not in post. An ffmpeg blur
        box needs fixed coordinates, and elements move — they scroll, reflow,
        and re-render, and a box pinned to where the element was at second 3
        is aimed at nothing by second 9.

        **The radius comes from the largest text in the subtree**, not from the
        element the selector matched. Redacting a wrapper is the natural call —
        `redact("#card")` where the value is an 80 px child — and the wrapper's
        own font-size is whatever its label uses.

        **It fails rather than misses.** At every checkpoint the recorder asks
        Playwright, across every frame, how many elements each selector matches
        and whether each carries a radius *sufficient for the text inside it*.
        Too few masked, too small a radius, or a selector that never matched
        anything at all raises SecretLeak; the take writes no mp4 and deletes
        the stills it had already taken.

        This masks pixels only. It does not tell the recorder what the element
        *says*, so a value you also want kept out of captions, narration and
        the beat log has to be registered as text too — `register_secret()`, or
        by typing it as a `Secret`.
        """
        if self.page is None:
            raise RuntimeError("redact() only works inside the `with` block")
        if style is not None:
            if style not in ("erase", "blur"):
                raise ValueError(
                    f"redact(style={style!r}): use 'erase' (the default — an "
                    f"opaque cover) or 'blur'"
                )
            if style == "blur" and self._redacted:
                raise ValueError(
                    "redact(style='blur') after something was already "
                    "registered: the style is a property of the take, not of "
                    "one call. Set it on the first redact()."
                )
            self._redact_style = style
        new = [s for s in selectors if s and s not in self._redacted]
        if new and self.page.url not in ("", "about:blank"):
            # Not fatal — masking late still beats not masking — but every
            # frame already captured is on disk and cannot be un-captured, so
            # this is a warning about frames that may already be wrong rather
            # than about what happens next.
            print(
                f"demo-video: WARNING — redact({', '.join(repr(s) for s in new)}) "
                f"was called after navigating to {self.page.url}. Frames "
                f"recorded before this call may already show the value. Move "
                f"the redact() call above the first goto().",
                file=sys.stderr,
            )
        self._mask(new)

    def _require_css(self, selector: str, where: str) -> None:
        """Refuse a selector the in-page mask cannot express.

        The browser is the judge: whatever `querySelector` parses is CSS, and
        everything else — `text=`, `xpath=`, `>>` chains, `nth=`, Playwright's
        `:has-text()` — throws.
        """
        try:
            ok = self.page.evaluate(_CSS_ONLY_JS, selector)
        except Exception:  # noqa: BLE001 - an unparseable selector is a refusal
            ok = False
        if not ok:
            raise SecretLeak(
                f"{where} needs a plain CSS selector, and {selector!r} is not "
                f"one. Redaction is a stylesheet injected into the page, so it "
                f"can only cover what CSS can name; a Playwright-engine "
                f"selector (text=, xpath=, >>, nth=, :has-text) can only be "
                f"resolved out of process at checkpoints, which leaves the "
                f"element in the clear between them. Name it with CSS — an id, "
                f"a class, an attribute — or register the text with "
                f"register_secret() and keep it off the screen."
            )

    def _mask(self, selectors: list[str], require_match: bool = False) -> None:
        """Register selectors with the mask and apply it now.

        The half of redact() that does not warn — `type_into` masks a field the
        instant before it types into it, which is exactly on time however late
        in the take it happens. `require_match` is for that case: the field is
        about to be typed into, so a selector matching nothing right now is not
        "not rendered yet", it is a secret about to be typed in the clear.
        """
        new = [s for s in selectors if s and s not in self._redacted]
        if new:
            for selector in new:
                self._require_css(selector, f"redact({selector!r})")
            self._redacted += new
            # The script carries the full list, so every later navigation in
            # this context re-masks everything registered so far — and raises
            # the paint gate, because a fresh document has never been checked.
            self._context.add_init_script(self._mask_script(gated=True))
        self._sync_mask(require=new if require_match else [], reinject=True)

    def _mask_script(self, gated: bool = False) -> str:  # noqa: D401
        """The in-page mask, as a string.

        `gated` belongs to the *document*, not to the recorder: an init script
        runs in a document nothing has verified yet, so it raises the gate;
        re-injecting into a live document mid-take must not. Getting this
        backwards is how the gate outlives its navigation — a Python-side
        one-shot flag says "already lowered" while every new document raises
        its own, and the take records blank from the first link click on.
        """
        return (
            _REDACT_JS.replace("__BLURPX__", str(REDACT_BLUR_PX))
            .replace("__BLUREM__", f"{REDACT_BLUR_PX / REDACT_BLUR_REF_PX:.4f}")
            .replace("__MARK__", REDACT_MARK_ATTR)
            .replace("__GATE__", _REDACT_GATE_ID)
            .replace("__GATED__", "true" if gated else "false")
            .replace("__COVER__", REDACT_COVER_ATTR)
            .replace("__BLEED__", str(REDACT_COVER_BLEED_PX))
            .replace("__ERASE__", "false" if self._redact_style == "blur" else "true")
            .replace("__SELECTORS__", json.dumps(self._redacted))
        )

    def _checkpoint(self) -> None:
        """Re-establish and re-verify the mask, if anything is registered.

        Called from every verb that spends time — including `_idle`, which is
        where a storyboard spends most of it. Verifying only at `goto`, `shot`
        and the end of the take leaves `click`, `wait_for`, `scroll_to` and
        every `pause` unwatched, and those are where an app re-renders.

        Throttled, because a `pause(0.3)` between two verbs does not need the
        round trips; a pending navigation overrides the throttle, since that is
        the case where the page is behind a gate waiting to be let up.
        """
        if not self._redacted:
            return
        now = time.monotonic()
        if self._nav_pending:
            self._nav_pending = False
            self._sync_mask(reinject=True)
        elif now - self._last_sync >= 0.25:
            self._sync_mask()

    def _sync_mask(self, require: list[str] | None = None, reinject: bool = False) -> None:
        """Mask what Playwright can see, verify it, and lower the paint gate.

        This is the layer that makes the mask unable to miss quietly. The
        in-page script covers elements that do not exist yet; this covers
        everything Playwright's engine can reach, which is a different set —
        open shadow roots, and every frame rather than only the top document.
        """
        if not self._redacted:
            return
        self._last_sync = time.monotonic()
        frames = list(self.page.frames)
        if reinject:
            script = self._mask_script()
            for frame in frames:
                try:
                    frame.evaluate(script)
                except Exception:  # noqa: BLE001 - a detached/blank frame is fine
                    continue
        for selector in self._redacted:
            self._mask_selector(
                selector, frames, required=selector in (require or [])
            )
        # Everything registered is now resolved, masked and verified, so the
        # page may be shown. Unconditional, and in every frame: the gate is
        # raised per document by the init script, so "have I lowered one
        # already" is not a question Python can answer. Raising above skips
        # this, which is the safe direction — a take that could not verify its
        # mask records a blank frame instead of the secret.
        for frame in frames:
            try:
                frame.evaluate(
                    "() => window.__demoRedactUngate && window.__demoRedactUngate()"
                )
            except Exception:  # noqa: BLE001 - a detached/blank frame is fine
                continue

    def _mask_selector(
        self, selector: str, frames: list, required: bool = False
    ) -> None:
        """Mask every element any frame holds for one selector, and verify.

        Across frames, not just the main one: `page.locator()` does not descend
        into an iframe, so counting there alone reported zero matches for an
        element that was in fact masked — and then failed the take for a leak
        that did not exist.
        """
        matched = 0
        weak: list[str] = []
        skipped: list[str] = []
        for frame in frames:
            try:
                states = frame.locator(selector).evaluate_all(
                    "els => els.map(el => window.__demoRedactMark(el))"
                )
            except Exception as exc:  # noqa: BLE001 - classified below
                detail = str(exc)
                transient = (
                    "detach" in detail.lower()
                    or "navigat" in detail.lower()
                    or "Execution context was destroyed" in detail
                    or "Target closed" in detail
                    or "__demoRedactMark" in detail
                )
                if transient:
                    # A frame that went away between listing the frames and
                    # asking one of them, or one that has not run the init
                    # script yet. Ad slots, lazy embeds and a React key change
                    # on an <iframe> all do this several times a second, and
                    # killing the take for it made redact() read as "takes die
                    # randomly on iframe-heavy apps" — while blaming the mask.
                    # Recorded, not ignored: if every frame is unusable the
                    # selector simply never matches, and the end-of-take check
                    # says so.
                    skipped.append(f"{type(exc).__name__}: {detail.splitlines()[0]}")
                    continue
                raise SecretLeak(
                    f"redact({selector!r}) could not be applied: "
                    f"{type(exc).__name__}: {exc}. The mask cannot be "
                    f"verified, so this take is not trustworthy and writes no "
                    f"mp4."
                ) from exc
            for state in states:
                matched += 1
                if not state:
                    weak.append("no answer from the page")
                    continue
                # What is asked is not "did you apply something" — the old
                # check read back the value it had just set, which cannot
                # fail. It is "is the browser's own hit testing finding this
                # element's cover on top", which the recorder does not decide.
                if state.get("hidden"):
                    continue  # nothing painted, nothing to cover
                if not state.get("covered"):
                    weak.append(
                        f"{state.get('misses', '?')} of "
                        f"{state.get('samples', '?')} sampled points over it "
                        f"are painted by something else"
                    )
        if matched:
            self._mask_seen.add(selector)
        if weak:
            raise SecretLeak(
                f"redact({selector!r}) matched {matched} element(s) and "
                f"{len(weak)} of them are not covered: {'; '.join(weak[:3])}. "
                f"Something is painting over the mask — this take writes no "
                f"mp4."
            )
        if skipped and not matched:
            print(
                f"demo-video: redact({selector!r}) could not be checked in "
                f"{len(skipped)} frame(s) this time ({skipped[0]}); frames "
                f"that come and go are normal and the next checkpoint tries "
                f"again.",
                file=sys.stderr,
            )
        if required and not matched:
            raise SecretLeak(
                f"redact({selector!r}) matched nothing, and a secret was about "
                f"to be typed into it. Playwright cannot see that element "
                f"either — a *closed* shadow root is reachable by neither, and "
                f"a typo matches nothing anywhere. Nothing was typed."
            )

    def _verify_redaction_final(self) -> None:
        """Fail the take if a registered selector never matched anything.

        The silent no-op is the failure redaction can least afford: nothing
        warns, the storyboard says `redact("#api-ky")`, and the mp4 looks
        deliberate. Deferred to the end because the recommended call site is
        *before* the first goto(), where matching nothing is normal.
        """
        if not self._redacted:
            return
        self._sync_mask(reinject=True)
        never = [s for s in self._redacted if s not in self._mask_seen]
        if never:
            raise SecretLeak(
                f"redact() was told to hide {never!r}, and nothing ever "
                f"matched — so this take masked nothing while looking as "
                f"though it had. Either the selector is wrong, the element "
                f"never rendered, or it lives in a closed shadow root, which "
                f"neither Playwright nor an injected script can reach. No mp4 "
                f"was written."
            )

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
        look like when it died", which is a different moment — the failing
        verb ran after that capture — and it has to be there when evidence is
        switched off, because a crash is when it is wanted most.

        Called from `__exit__` **before** `_verify_redaction_final()`, so the
        mask this text is checked against is the same one the verifier is about
        to vouch for.

        **It harvests, and that is what makes the dump maskable at all.**
        `_evidence_forbidden()` is the registered secrets *plus*
        `self._evidence_masks`, and the only thing that ever filled that set
        was `_evidence_payload` — which runs under `if self._evidence_on`. So
        with `evidence=False` the forbidden list collapsed to the registered
        secrets alone, and `redact()` registers no text: it is a pixel control
        that covers where a value renders and leaves the value in the DOM,
        which is exactly what an ARIA tree dumps. Measured on one storyboard
        run twice with only the flag differing, `redact("#api-key")` and no
        `register_secret()`: with evidence on, no file held the key; with it
        off, `failure/screen.txt` held the line `- code: sk-live-FAKE…` in the
        clear. That is not a dead branch — `evidence=False` is a documented
        kwarg and env var, and `_write_evidence` *recommends* it on stderr for
        apps with large accessibility trees, i.e. precisely the apps whose
        dump is biggest.

        The harvest runs on **both sides** of the snapshot and the two must
        agree, exactly as `_evidence_payload` does and for the same reason: a
        card rewritten on a `setInterval` hands the harvest one value and the
        snapshot the next, and a mask built from a reading the snapshot never
        saw is a mask with a hole in it. Both readings feed the mask either
        way; if they will not settle, the page text is withheld and says so,
        rather than being written from a mask known to be out of date.

        No `_checkpoint()` first, unlike `_evidence_payload`, and deliberately.
        `_harvest()` re-resolves the registered selectors itself rather than
        trusting the marker, so it does not need a freshly applied mask — and a
        checkpoint here would raise `SecretLeak` inside `_capture_failure_screen`,
        whose whole job is to never raise. `_verify_redaction_final()` runs on
        the very next statement and re-syncs; a mask that has come off fails
        the take there, where the refusal is not swallowed.
        """
        if not self._redacted:
            return self._failure_page_text()
        for _ in range(EVIDENCE_HARVEST_TRIES):
            before, outside = self._harvest()
            text = self._failure_page_text()
            after, outside_after = self._harvest()
            self._evidence_masks.update(before)
            self._evidence_masks.update(after)
            # Bounded like the per-beat path, and erring the same way: past the
            # bound the recorder stops learning that a string renders in the
            # clear, which over-masks rather than under-masks.
            if len(self._evidence_outside) < EVIDENCE_OUTSIDE_MAX:
                self._evidence_outside.add(outside)
                self._evidence_outside.add(outside_after)
            if set(before) == set(after):
                return text
        return (
            f"[demo-video: what redact() is covering changed "
            f"{EVIDENCE_HARVEST_TRIES} times while this page was being read at "
            f"the end of the take, so the mask could not be built from what "
            f"the snapshot actually saw. No page text was written for this "
            f"failure. The last frame, the console log and the failing beat "
            f"are unaffected.]"
        )

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

    def _before_shot(self) -> None:
        """Re-assert and re-verify the mask immediately before a still.

        Web stills are full-bleed — the whole page, no window frame — so this
        is the likeliest of the four leak paths. The MutationObserver should
        already have repaired anything the app did, but a screenshot is a
        one-shot artifact that nobody re-checks, so it pays the round trip.
        """
        self._sync_mask()

    def _note_navigation(self, frame) -> None:
        """A frame navigated: the next checkpoint must re-inject and re-verify.

        Deliberately does nothing else — see `_start` for why touching
        Playwright from an event callback is not safe here.
        """
        self._nav_pending = True

    # -- evidence (issue #9) ------------------------------------------------

    def _harvest(self) -> tuple[list[str], str]:
        """(what the mask covers, what the page renders outside it).

        **The main frame only, and that is not an omission.** Nothing a
        sub-frame renders can reach an evidence file: `aria_snapshot` is taken
        of the top document's `body` and stops at the `iframe` node, and the
        markup dump strips `srcdoc` along with every other value-bearing
        attribute. Harvesting sub-frames was written first and removed — it was
        code whose only defence was an argument that nothing needs it, which is
        the kind that rots. The claim is held up instead by the byte sweep in
        tests/smoke, which requires the fixture's in-iframe key to be absent
        from every evidence file.
        """
        script = (
            _EVIDENCE_HARVEST_JS.replace("__MARK__", REDACT_MARK_ATTR)
            .replace("__COVER__", REDACT_COVER_ATTR)
            .replace("__MARKER_IDS__", "__demo")
        )
        found = self.page.evaluate(script, self._redacted) or {}
        return list(found.get("inside") or []), str(found.get("outside") or "")

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
            payload["html"] = target.evaluate(
                _EVIDENCE_HTML_JS,
                [REDACT_MARK_ATTR, REDACT_COVER_ATTR, self._redacted, SECRET_MASK],
            )
        return payload

    def _evidence_payload(self) -> dict:
        """What was on screen at the end of this beat, as text.

        The ARIA snapshot is the primary artifact and the page's is always
        taken: it is what lets a reviewer say what was on screen without
        decoding a frame. `outerHTML` is the spotlight target's only — never
        the page's — because the markup of a whole document is an order of
        magnitude larger than its ARIA tree and carries script text and
        `srcdoc` documents that were never on screen at all.

        **The harvest and the snapshot are separate round trips, and a page
        that repaints between them is a leak.** `aria_snapshot()` is a
        protocol call, not something a page evaluation can produce, so they
        cannot literally be one operation. A card rewritten on a 5 ms
        `setInterval` — a countdown, a ticker, a rotating token — hands the
        harvest one value and the snapshot the next, and the mask is then built
        from a value the snapshot does not contain.

        So the harvest is taken on *both* sides of the snapshot and the two
        must agree. If they do not, the redacted region moved while the page
        was being read and this beat's capture is retried; if it will not
        settle, the beat's page text is dropped rather than written from a mask
        that is known to be out of date. Both harvests feed the mask either
        way, so a value seen on either side is masked everywhere.

        A checkpoint first, and the *ordering* is the point rather than the
        frequency — `_checkpoint()` is throttled and `_idle` calls it anyway.
        What is about to happen is a read of the text of everything `redact()`
        covers, turned into the mask every evidence file and both timeline
        files are scrubbed against. Taking that reading a quarter-second after
        the last time anyone asked the browser whether the cover is still on
        the elements means building the mask from a stale idea of what is
        hidden. It also puts a cannot-verify-the-mask refusal on this path for
        real rather than in principle: `_capture_evidence` runs in a `finally`
        and must let a `SecretLeak` through, and this is where one comes from.
        """
        self._checkpoint()
        if not self._redacted:
            return self._capture_page()
        for attempt in range(EVIDENCE_HARVEST_TRIES):
            before, outside = self._harvest()
            payload = self._capture_page()
            after, outside_after = self._harvest()
            self._evidence_masks.update(before)
            self._evidence_masks.update(after)
            # Bounded, because a page whose content changes every beat yields a
            # distinct "outside" every time and this would otherwise grow with
            # the storyboard. Past the bound the recorder stops learning that a
            # string renders in the clear, which over-masks — the safe
            # direction, and the one worth erring in.
            if len(self._evidence_outside) < EVIDENCE_OUTSIDE_MAX:
                self._evidence_outside.add(outside)
                self._evidence_outside.add(outside_after)
            if set(before) == set(after):
                return payload
            if attempt == EVIDENCE_HARVEST_TRIES - 1:
                return {
                    "omitted": (
                        f"what redact() is covering changed "
                        f"{EVIDENCE_HARVEST_TRIES} times while this beat's "
                        f"page text was being read, so the mask could not be "
                        f"built from what the snapshot actually saw. No page "
                        f"text was captured for this beat."
                    )
                }
        raise AssertionError("unreachable")

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
        # Before networkidle, not after: the paint gate is up from the moment
        # the document was created, and waiting out a polling app's idle
        # timeout behind it would blank the window for up to ten seconds. The
        # DOM is up as soon as goto() returns, which is when the mask can be
        # verified and the page shown.
        self._nav_pending = False
        self._sync_mask(reinject=True)
        try:
            self.page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # apps that poll never go network-idle; the page is up
        # ...and again for whatever the page rendered while settling.
        self._checkpoint()

    @_beat_verb("terminal")
    def terminal(self, command: str) -> None:
        """Type a command in an on-screen terminal card, then perform the
        real action it describes right after this returns."""
        # Same rule as a caption: this text is authored, and it is drawn large
        # in the middle of the frame. A token in a curl line is an authoring
        # bug, so fail rather than blur.
        self._no_secrets(command, "terminal()")
        self.page.evaluate("cmd => window.__demoTerminal(cmd)", command)

    @_beat_verb("terminal_output")
    def terminal_output(self, text: str) -> None:
        """Reveal real command output inside the terminal card, line by
        line — run the command first, pass its actual (trimmed) output."""
        # Scrubbed, not fatal: unlike a caption or a command line, this text
        # is a program's output, which the storyboard author did not write and
        # cannot be asked to reword. Same reasoning as the terminal recorder's
        # PTY path (issue #5).
        self.page.evaluate("t => window.__demoTerminalOutput(t)", self.scrub(text))

    @_beat_verb("terminal_close")
    def terminal_close(self, stamp: str | None = None) -> None:
        """Stamp a closing line ('✓ delivered' by default, "" for none)
        on the terminal card and fade it out."""
        if stamp != "":
            # The stamp is drawn on the card exactly as terminal()'s command
            # is, and it is authored the same way — a caller pasting a request
            # id or a response line into it is the same leak. terminal() got
            # this guard and the stamp did not; both are authored text.
            self._no_secrets(stamp or "", "terminal_close()")
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
        spotlight target's `outerHTML` *including its style attribute*, and
        `redact()`'s observer re-asserts the mask off the same attribute. Both
        would then read a value that depends on when the compositor happened to
        fire, which is not a thing a storyboard can be written against. So when
        this returns, the previous element's inline style is byte-identical to
        what the spotlight found.

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
        self._checkpoint()
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
        self._checkpoint()
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
        self._checkpoint()
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
    def type_into(
        self, selector: str, text: str | Secret, delay_ms: int = 40
    ) -> None:
        """Click a field and type into it visibly, key by key — for form
        demos (checkout, login, search). For anything the verbs don't
        cover, `self.page` is the live Playwright page.

        Pass `Secret("sk-live-…")` for a credential: the field is blurred
        before the first keystroke, the value is registered so it can never
        appear in a caption or the beat log, and the keys are typed for real.
        """
        if isinstance(text, Secret):
            # Order matters: register and mask, *then* type. The field is
            # already blurred when the first character lands in it — masking
            # a field that is still empty is not late, so this goes through
            # _mask() rather than redact() and its after-the-fact warning.
            # require_match, because a field about to receive a credential
            # that the mask cannot find is the shadow-DOM leak: Playwright
            # would happily click and type into an element the mask never saw.
            self.register_secret(text)
            self._mask([selector], require_match=True)
            value = text.reveal()
        else:
            value = text
        self.click(selector)
        self.page.keyboard.type(value, delay=delay_ms)

    @_beat_verb("scroll_to")
    def scroll_to(self, selector: str) -> None:
        self._checkpoint()
        self.page.locator(selector).first.evaluate(
            "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
        )
        self.pause(1.2)

    @_beat_verb("wait_for")
    def wait_for(self, selector: str, timeout_s: float = 60) -> None:
        """Wait for something the app does on its own (a job, a run)."""
        self._checkpoint()
        self.page.locator(selector).first.wait_for(timeout=timeout_s * 1000)
