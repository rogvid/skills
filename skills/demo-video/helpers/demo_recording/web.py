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
    SECRET_MASK,
    Secret,
    SecretLeak,
    _beat_verb,
    _DemoBase,
    _env,
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
_EVIDENCE_HARVEST_JS = r"""(selectors) => {
  const MARK = '__MARK__';
  const ATTRS = ['value', 'title', 'alt', 'placeholder', 'aria-label',
                 'content', 'srcdoc', 'data-value'];
  const out = [];
  const push = (s) => { if (typeof s === 'string' && s.trim()) out.push(s); };
  const roots = [document];
  const findRoots = (root) => {
    let all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of all) {
      if (el.shadowRoot) { roots.push(el.shadowRoot); findRoots(el.shadowRoot); }
    }
  };
  findRoots(document);
  // Every node the subtree renders through, shadow roots at every depth.
  const walk = (node, acc) => {
    if (!node) return acc;
    acc.push(node);
    let kids = [];
    try { kids = node.querySelectorAll ? node.querySelectorAll('*') : []; }
    catch (e) { kids = []; }
    for (const kid of kids) {
      acc.push(kid);
      if (kid.shadowRoot) walk(kid.shadowRoot, acc);
    }
    if (node.shadowRoot) walk(node.shadowRoot, acc);
    return acc;
  };
  const harvest = (el) => {
    for (const node of walk(el, [])) {
      push(node.textContent);
      if (typeof node.value === 'string') push(node.value);
      // Individual text nodes as well as the concatenation: an accessible
      // name is built per element, so the pieces are what a tree shows.
      for (const child of node.childNodes || []) {
        if (child.nodeType === 3) push(child.nodeValue);
      }
      if (node.nodeType !== 1) continue;  // a shadow root has no attrs or style
      for (const a of ATTRS) {
        try { push(node.getAttribute(a)); } catch (e) { /* exotic attr */ }
      }
      for (const which of ['::before', '::after']) {
        let content;
        try { content = getComputedStyle(node, which).content; }
        catch (e) { continue; }
        if (!content || content === 'none' || content === 'normal') continue;
        push(content);
        // Computed `content` comes back quoted and escaped; the tree shows
        // the string itself, so push that too.
        const quoted = /^"([\s\S]*)"$/.exec(content);
        if (quoted) push(quoted[1].replace(/\\(.)/g, '$1'));
      }
    }
  };
  for (const root of roots) {
    for (const sel of selectors.concat(['[' + MARK + ']'])) {
      let hits = [];
      try { hits = root.querySelectorAll(sel); } catch (e) { continue; }
      for (const hit of hits) harvest(hit);
    }
  }
  return out;
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
  const clone = el.cloneNode(true);
  const drop = (root, sel) => {
    let hits = [];
    try { hits = root.querySelectorAll(sel); } catch (e) { return; }
    for (const hit of hits) hit.remove();
  };
  drop(clone, 'script,style,template,noscript,link,meta');
  drop(clone, '[' + COVER + '],[id^="__demo"],[id^="__term"]');
  let framed = [];
  try { framed = clone.querySelectorAll('[srcdoc]'); } catch (e) { framed = []; }
  for (const node of framed) node.setAttribute('srcdoc', MASK);
  const hide = (node) => {
    for (const a of ['value', 'title', 'alt', 'placeholder', 'aria-label',
                     'href', 'src', 'srcdoc', 'content', 'data-value']) {
      try { node.removeAttribute(a); } catch (e) { /* exotic attr */ }
    }
    node.textContent = MASK;
  };
  for (const sel of SELECTORS.concat(['[' + MARK + ']'])) {
    let hits = [];
    try { hits = clone.querySelectorAll(sel); } catch (e) { continue; }
    for (const hit of hits) hide(hit);
    // querySelectorAll never returns the root it was called on, and the root
    // is exactly the element a storyboard spotlights and redacts together.
    try { if (clone.matches && clone.matches(sel)) hide(clone); }
    catch (e) { /* an ancestor-relative selector cannot match a clone */ }
  }
  return clone.outerHTML;
}"""

# Transient frame failures, classified the same way `_mask_selector` does:
# frames come and go several times a second on ad-slot- and embed-heavy apps,
# and a diagnostic must not be the reason a take dies.
_EVIDENCE_TRANSIENT = (
    "detach", "navigat", "execution context was destroyed", "target closed",
)


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
    ) -> None:
        super().__init__(
            out_dir, segment=segment, accent_rgb=accent_rgb,
            terminal_title=terminal_title, terminal_prompt=terminal_prompt,
            viewport=viewport, speech=speech, voice_id=voice_id,
            speech_model=speech_model, strict=strict,
            deterministic=deterministic, clock=clock,
            timezone_id=timezone_id, locale=locale, evidence=evidence,
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

    def _init_context(self, context) -> None:
        context.add_init_script(_CURSOR_JS.replace("__ACCENT__", self._accent))
        context.add_init_script(
            _TERMINAL_JS.replace("__TERM_TITLE__", self._terminal_title)
            .replace("__TERM_PROMPT__", self._terminal_prompt)
        )
        context.add_init_script(_SPOTLIGHT_JS.replace("__ACCENT__", self._accent))

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

    def _redacted_rendered_text(self) -> list[str]:
        """Everything the mask is covering, as text, across every frame.

        Raises if the *main* frame cannot be read. A sub-frame that refuses is
        logged and skipped: frames detach and re-attach constantly on
        embed-heavy apps, and nothing a sub-frame renders reaches an evidence
        file anyway — the ARIA snapshot is taken of the top document's `body`
        and stops at an `iframe` node, and the markup dump replaces `srcdoc`
        wholesale. Harvesting sub-frames is defence in depth, so failing to is
        survivable; failing on the main frame is not.
        """
        found: list[str] = []
        script = _EVIDENCE_HARVEST_JS.replace("__MARK__", REDACT_MARK_ATTR)
        frames = list(self.page.frames)
        main = self.page.main_frame
        for frame in frames:
            try:
                found += frame.evaluate(script, self._redacted) or []
            except Exception as exc:  # noqa: BLE001 - classified, then re-raised
                if frame is main:
                    raise
                detail = str(exc)
                if not any(t in detail.lower() for t in _EVIDENCE_TRANSIENT):
                    raise
                print(
                    f"demo-video: a sub-frame could not be read while "
                    f"collecting what redact() hides ({type(exc).__name__}); "
                    f"nothing it renders reaches an evidence file, and the "
                    f"next beat tries again.",
                    file=sys.stderr,
                )
        return found

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

    def _evidence_payload(self) -> dict:
        """What was on screen at the end of this beat, as text.

        The ARIA snapshot is the primary artifact and the page's is always
        taken: it is what lets a reviewer say what was on screen without
        decoding a frame. `outerHTML` is the spotlight target's only — never
        the page's — because the markup of a whole document is an order of
        magnitude larger than its ARIA tree and carries script text and
        `srcdoc` documents that were never on screen at all.
        """
        # The marker attribute the elision below matches on is stamped by the
        # mask, and the mask is re-asserted at checkpoints. Take one now so the
        # page's idea of what is covered is not one re-render out of date.
        self._checkpoint()
        if self._redacted:
            try:
                self._evidence_masks.update(self._redacted_rendered_text())
            except Exception as exc:  # noqa: BLE001 - refuse, never guess
                # The one failure that must not degrade into a written file:
                # without this text the writer cannot mask what redact() is
                # hiding, and a DOM dump is not protected by a pixel cover.
                return {
                    "omitted": (
                        f"the recorder could not read what redact() is "
                        f"covering ({type(exc).__name__}), so no page text was "
                        f"captured for this beat"
                    )
                }
        aria, aria_format = self._aria(self.page.locator("body"))
        payload: dict = {
            "scope": self._spotlit,
            "url": self.page.url,
            "title": self.page.title(),
            "aria_format": aria_format,
            "aria": aria,
            "scope_aria": None,
            "html": None,
            "redacted": list(self._redacted),
        }
        if self._spotlit:
            target = self.page.locator(self._spotlit).first
            payload["scope_aria"] = self._aria(target)[0]
            payload["html"] = target.evaluate(
                _EVIDENCE_HTML_JS,
                [REDACT_MARK_ATTR, REDACT_COVER_ATTR, self._redacted, SECRET_MASK],
            )
        return payload

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
        spotlight() with no argument clears it."""
        self._checkpoint()
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
