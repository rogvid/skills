"""Recorder — records a web app by driving a Playwright page.

The web recorder records a wrapper page the recorder owns (issue #358,
design record #355, cutover #361): window chrome, a caption band reserved
below the app rect, the card layer and the cursor dot all live in the
wrapper document (see chrome.py), and the app loads into an iframe at true
pixel size. The recorded page *is* the framed picture — there is no
exit-time composite, so a take costs one video encode, not two.

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

History: the composite path this replaced screenshotted a window frame once
per run and had ffmpeg scale the app recording (~0.8) into it at exit —
which cost a second full-video encode per retake, put the card and the
window through two different encoders (the #291 colour mismatch and its
measured #301 compensation, `WEB_CARD_BODY`), and rendered captions at 34px
to survive the downscale. #355 records why in-page framing replaced it and
#361 is the cutover that deleted it.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from .chrome import (
    CURSOR_ID,
    chrome_geometry,
    chrome_html,
    opening_hold_script,
)
from .content import content_rect
from .core import (
    WEB_WINDOW_BODY,
    _beat_verb,
    _DemoBase,
    _env,
)
from .target import guard_target

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

#: How long the opt-in intro card holds before the storyboard's first beat,
#: before `pace` scales it. Reading time for a short title, same scale the
#: interlude default sits on.
INTRO_HOLD_S = 2.8

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
# An element that already carries a transform gets the ring only (#398) —
# see the condition in `__demoSpotlight` below.
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
  // Ring-only for transform carriers (#398): setting `transform` REPLACES the
  // inline declaration rather than composing with it, so an element positioned
  // by its own inline transform — a React Flow node's `translate(x,y)` is the
  // canonical case — teleports to its untransformed position for the whole
  // beat and jumps back when the clear restores `__spotPrev`. The restore is
  // correct; the during state is what the viewer watches. A computed (not
  // inline) read, because an inline scale would clobber a stylesheet
  // transform just as thoroughly. Such elements get ring + tint and keep
  // their position; the enlarge is skipped, which reads as emphasis all the
  // same.
  if (getComputedStyle(el).transform === 'none') {
    el.style.transform = 'scale(1.02)';
  }
  // Where the element sits **in the app's own viewport**, rounded to whole
  // pixels. `spotlight()` moves it into the recorded frame's coordinates and
  // opens a camera event over it (camera.py): the push-in is rendered after
  // the take, because a DOM transform cannot reach past the window chrome
  // into the composited frame — the page zoom this replaced scaled the page
  // inside the window and read as layout jitter, not as a move.
  //
  // The wrapper's offset is added in Python, not here: this script runs in
  // the app frame, which is cross-origin to the wrapper whenever the demo is
  // not served from the recorder's own origin, and `window.frameElement` is
  // null across that boundary. Reading it here put the push 156 px from the
  // element it was aimed at — measured on tests/smoke's spotlight take.
  const r = el.getBoundingClientRect();
  return {
    x: Math.round(r.left),
    y: Math.round(r.top),
    w: Math.round(r.width),
    h: Math.round(r.height),
  };
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


# What the recorder's own chrome is saying on screen, read out of the wrapper
# document's DOM at capture time — never out of `self._caption`, which is the
# beat log quoting itself (#134's blind spot). The caption and the cards left
# the app's document with the wrapper (#358), so an evidence file that only
# captured the app frame would silently stop saying which line was on screen —
# and "a reviewer holding only this file can state what the frame showed"
# (#9) includes the narration line the frame showed. Visibility-gated the way
# core's overlay probe is (#163): a cleared caption is opacity 0, not removed.
_CHROME_TEXT_JS = """() => {
  const line = (id, name) => {
    const el = document.getElementById(id);
    if (!el || !el.textContent) return null;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return null;
    if (parseFloat(style.opacity || '1') <= 0.5) return null;
    return name + ': ' + el.textContent;
  };
  return [
    line('__demo_caption', 'caption'),
    line('__demo_interlude', 'card'),
    line('__demo_bridge_t', 'bridge'),
  ].filter(Boolean).join('\\n');
}"""

# On-screen text the ARIA snapshot structurally cannot carry (issue #353).
#
# **Evidence claims to describe what the beat showed.** Two shapes of visible
# text never reach `aria_snapshot()`, and until this field they left no trace
# at all — the file read as a complete account of a screen it had only
# partly seen. Measured against Playwright 1.62.0, one page, seven input
# shapes filled and read back out of one `body` snapshot:
#
#   | shape                                   | in the snapshot |
#   |-----------------------------------------|-----------------|
#   | `contenteditable` with `role="textbox"` | **absent**      |
#   | subtree under `aria-hidden="true"`      | **absent**      |
#   | `contenteditable`, no role              | present         |
#   | `<input type="number">`                 | present         |
#   | `<input type="password">`               | present         |
#   | `readonly` input                        | present         |
#   | input under `role="presentation"`       | present         |
#   | input inside a shadow root              | present         |
#   | textbox inside `<dialog aria-modal>`    | present         |
#
# The last row is why this field exists in the shape it does. #353 was filed
# saying dialogs drop typed values; they do not, and an assertion written to
# that could never have failed. The real classes are the first two, and both
# are **structural**: a `textbox`'s accessible value is read off a `value`
# property a `div` does not have, and `aria-hidden` removes a subtree from the
# accessibility tree by definition while the pixels stay on screen.
#
# **Absent when there is nothing to say** (#24's rule), so every take that has
# no such element on screen writes exactly the evidence it wrote before.
#
# Written in the snapshot's own `- role "name": value` idiom rather than as
# JSON: the reader already knows how to read that, and a lint tokenising
# `aria` can tokenise this with the same code (#356).
_ARIA_OMITS_JS = r"""() => {
  const MAX_ENTRIES = 40, MAX_TEXT = 500;
  const out = [];
  const clip = (s) => {
    const t = (s || '').replace(/\s+/g, ' ').trim();
    return t.length > MAX_TEXT ? t.slice(0, MAX_TEXT) + '…' : t;
  };
  // The recorder's own furniture, if any of it ever lands in this document.
  // It is chrome rather than app, and `chrome` is the field that carries it.
  const ours = (el) => (el.id || '').startsWith('__demo')
    || (el.id || '').startsWith('__chrome');

  // 1. A rich-text editor. `role="textbox"` promises the tree an accessible
  //    *value*, which for a div is read off a property it does not have, so
  //    the node renders as `- textbox "Name"` with nothing after the colon.
  for (const el of document.querySelectorAll('[contenteditable]')) {
    if (out.length >= MAX_ENTRIES) break;
    const editable = el.getAttribute('contenteditable');
    if (editable === 'false') continue;
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (!['textbox', 'searchbox', 'combobox'].includes(role)) continue;
    if (ours(el)) continue;
    const text = clip(el.innerText);
    if (!text) continue;
    const name = el.getAttribute('aria-label') || el.getAttribute('title') || '';
    out.push('- ' + role + ' ' + JSON.stringify(name) + ': ' + text);
  }

  // 2. An `aria-hidden` subtree that is nonetheless painted. Outermost only —
  //    a nested one is already inside the text reported for its ancestor —
  //    and painted only, because the overwhelmingly common use of the
  //    attribute is on something already invisible, which is not an omission.
  for (const el of document.querySelectorAll('[aria-hidden="true"]')) {
    if (out.length >= MAX_ENTRIES) break;
    const parent = el.parentElement;
    if (parent && parent.closest('[aria-hidden="true"]')) continue;
    if (ours(el)) continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    if (parseFloat(style.opacity || '1') <= 0) continue;
    const text = clip(el.innerText || el.textContent);
    if (!text) continue;
    out.push('- aria-hidden: ' + text);
  }
  return out.join('\n');
}"""

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
        speech_stability: float | None = None,
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
        ticket: str | None = None,
        stills_only: bool | None = None,
        pace: float | None = None,
        intro: str | None = None,
        outro: str | None = None,
        window_title: str | None = None,
        window_scale: float | tuple[float, float] | None = None,
        caption_overlay: bool | None = None,
        preview: bool | None = None,
        preset: str | None = None,
        allow_private: bool | None = None,
    ) -> None:
        super().__init__(
            out_dir,
            segment=segment,
            accent_rgb=accent_rgb,
            terminal_title=terminal_title,
            terminal_prompt=terminal_prompt,
            viewport=viewport,
            speech=speech,
            voice_id=voice_id,
            speech_model=speech_model,
            speech_stability=speech_stability,
            strict=strict,
            deterministic=deterministic,
            clock=clock,
            timezone_id=timezone_id,
            locale=locale,
            evidence=evidence,
            criteria=criteria,
            ticket=ticket,
            allow_private=allow_private,
            stills_only=stills_only,
            pace=pace,
            intro=intro,
            outro=outro,
            window_title=window_title,
            window_scale=window_scale,
            caption_overlay=caption_overlay,
            preview=preview,
            preset=preset,
        )
        self.base_url = (base_url or _env("BASE_URL", "http://localhost:8000")).rstrip(
            "/"
        )
        # The base checked `DEMO_VIDEO_BASE_URL`; this checks what this take
        # actually resolved, which is the explicit argument when there is one.
        # Still before a browser exists — `__enter__` is what launches one.
        guard_target(
            self.base_url,
            self._allow_private,
            source="this take's base_url",
        )
        # The app iframe's Frame, once `_start` has mounted it.
        self._app_frame: object | None = None
        # Whether this take's opening hold has been cleared (#360). The hold
        # is up from frame 0 (see chrome.OPENING_HOLD_JS) and the first
        # goto() that lands is what clears it — the storyboard's first
        # content beat, the moment there is an app to reveal.
        self._hold_cleared = False
        # Where the take last commanded the pointer, in wrapper-page
        # coordinates. Seeded at the origin, where a fresh page's pointer
        # actually sits; `_glide` is the only writer.
        self._cursor_at: tuple[float, float] = (0.0, 0.0)
        # The caption keeps the base font size: the page is recorded at true
        # pixel size, so there is no downscale to compensate for. (The
        # composite path rendered captions at 34px to survive its ~0.8
        # scale — see the module docstring's history note.)
        #
        # The interlude card likewise needs no per-medium stylesheet here:
        # the wrapper document carries its own `__demoInterlude` in the card
        # layer (chrome.py, #360), declaring `WEB_WINDOW_BODY` uncompensated,
        # and the base init-script version never paints in it — the card
        # element already exists in the chrome markup, so the init script
        # only ever toggles it.
        #
        # What spotlight() is currently pointing at, which is what a beat's
        # evidence is scoped to. Held here rather than read back out of the
        # page: `window.__spotEl` is an element handle, not a selector, and the
        # selector is the thing worth writing down.
        self._spotlit: str | None = None
        # Set by the retained `framenavigated` listener. Nothing reads it;
        # see `_note_navigation` for why the listener is kept anyway.
        self._navigated = False

    def _content_rect(self) -> tuple[int, int, int, int] | None:
        """Where the app sits in the recorded frame (issue #97).

        `chrome.chrome_geometry` is the single source: the app records in
        the wrapper's content slot at true pixel size, so the slot's rect is
        the app's region of the encoded file — which is the only frame
        anybody watches. Everything outside it is the recorder's own chrome,
        and that chrome is exactly what made a whole-frame score rank a
        blank recording above a healthy one (issue #17).
        """
        geom = getattr(self, "_geom", None)
        if not geom:
            return None
        return content_rect((geom["appx"], geom["appy"], geom["appw"], geom["apph"]))

    @property
    def app(self):
        """The app's document — where the verbs point.

        The app iframe's Playwright `Frame`; the wrapper document around it
        is the recorder's own chrome, so `rec.app.locator(...)` is the
        escape hatch that reaches the app the way the verbs do. `rec.page`
        stays the wrapper `Page` — the whole browser surface, chrome
        included — so nothing an escape hatch could reach before is out of
        reach now.
        """
        if self._app_frame is None:
            raise RuntimeError(
                "this take has no app frame yet — rec.app exists once the "
                "recorder has entered (`with Recorder(...) as rec:`), which "
                "is what mounts the iframe"
            )
        return self._app_frame

    def _target(self):
        """What locator-driving verbs run against: the app iframe's frame."""
        return self.app

    def _init_context(self, context) -> None:
        # The opening hold (#360): frame 0 is the window's own colour over
        # the app rect, not a white iframe waiting for the first goto. An
        # init script for _OPENING_CARD_JS's reasons — see
        # chrome.OPENING_HOLD_JS — and the geometry is recomputed here
        # because init scripts are registered before the page (and therefore
        # before `_start` runs); `chrome_geometry` is pure, so the two calls
        # cannot disagree.
        #
        # No cursor script rides along: the dot lives in the wrapper
        # document (chrome.py) and is driven explicitly by the recorder
        # (`_glide`), so there is no event-following overlay for the app
        # iframe to draw a second dot with.
        width_scale, height_scale = self._window_scale
        context.add_init_script(
            opening_hold_script(
                chrome_geometry(
                    self._size["width"],
                    self._size["height"],
                    width_scale=width_scale,
                    height_scale=height_scale,
                    caption_overlay=self._caption_overlay,
                ),
                window_body=WEB_WINDOW_BODY,
            )
        )
        context.add_init_script(
            _TERMINAL_JS.replace("__TERM_TITLE__", self._terminal_title).replace(
                "__TERM_PROMPT__", self._terminal_prompt
            )
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

        The callback below never calls into Playwright. Page events are
        delivered on the same thread that is blocked inside a Playwright
        call, so calling back into the API from one of them is a way to
        deadlock a take.

        **Nothing here subscribes `domcontentloaded`.** The caption lives in
        the wrapper document, `goto()` navigates the app *iframe*, and the
        wrapper document is never replaced — a caption structurally cannot
        be destroyed by navigation, so the #134/#180 `caption_lost` class
        cannot exist on a web take and the recorder does not listen for it.
        Not listening rather than listening-and-never-firing is the honest
        shape: it makes "this issue cannot exist here" a property of the
        code instead of an observation about one Playwright's event routing,
        and the beats that keep reporting the caption across a mid-take goto
        are right — the line really is still on screen (this repository's
        `tests/smoke --wrapper-only` reads it out of the band's pixels
        across a full document load). Since #362 the terminal caption lives
        in the same chrome band, so caption death on navigation is no
        medium's concern — the `caption_lost` issue kind survives only in
        timelines committed before the cutovers.
        """
        # **Kept deliberately when the masking went** — #142's carve-out.
        # Written for the paint gate, which is gone; nothing reads the flag.
        #
        # `frameattached` went with the rest: it existed because a frame that
        # attached after the parent's checkpoint had never been verified, which
        # is a statement about a mask and about nothing else.
        page.on("framenavigated", self._note_navigation)

    def _chrome_title(self) -> str:
        """What the wrapper window's title bar says: the take's
        `window_title` when it has one, the app's host when it does not —
        a demo of `http://localhost:3000` opens titled for what it demos."""
        return self._window_title or urlparse(self.base_url).netloc or "app"

    def _start(self) -> None:
        """Build the wrapper page on the recorded page itself (issue #358).

        The chrome is the recording, not a still ffmpeg composites later: the
        recorded page carries the window, the caption band and the cursor
        overlay, and the app loads into an iframe sized to the app rect at
        true pixel size. `self._geom` is `chrome_geometry`'s dict, the one
        shape `_content_rect` and every other geometry consumer reads.
        """
        width_scale, height_scale = self._window_scale
        self._geom = chrome_geometry(
            self._size["width"],
            self._size["height"],
            width_scale=width_scale,
            height_scale=height_scale,
            caption_overlay=self._caption_overlay,
        )
        self.page.set_content(
            chrome_html(
                self._geom,
                title=self._chrome_title(),
                window_body=WEB_WINDOW_BODY,
                accent=self._accent,
                caption_font_px=self._caption_font_px,
            )
        )
        # The chrome document is written, not navigated to, so it never got
        # the motion rule (`_freeze_motion_here`). The app iframe below has
        # a document of its own and does get it from the init script; this
        # is for the chrome around it, so both media are one behaviour.
        self._freeze_motion_here()
        # Mounted here rather than shipped in the chrome document because the
        # iframe is the *web* medium's content — the terminal recorder mounts
        # xterm.js in the same slot (#362). Size comes from the slot's CSS
        # (chrome.py), which is the app rect exactly.
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
        self._raise_intro()

    def _raise_intro(self) -> None:
        """The opt-in opening title (`Recorder(intro=…)`, off by default).

        What is being presented, up over the wrapper from the take's first
        seconds — before the app has loaded, which is the point: the card
        covers the load instead of delaying it. The first `goto()` takes it
        down (the same evaluate that clears the recorder's cards on every
        navigation), so a storyboard needs nothing extra to end the intro.

        **Voiced when speech is on**, like any caption — a silent card over a
        narrated take reads as broken audio. The card rides the whole spoken
        line (criterion()'s pattern): held `INTRO_HOLD_S` scaled by `pace`,
        and never less than what is left of the line, so the voice never
        outlives the card it belongs to. With speech off the line is empty
        and the hold is just the reading time. The line's clip was
        synthesized in the constructor, off the capture clock — the raise
        starts the voice the moment the card is up, with no round trip of
        dead air between them.
        """
        if not self._intro:
            return
        self.page.evaluate("t => window.__demoInterlude(t)", self._intro)
        clip = self._prepare_line(self._intro, self._intro_clip)
        self._start_line(clip)
        hold = INTRO_HOLD_S * self._pace
        remaining = self._line_end - time.monotonic()
        self._idle(max(hold, remaining))

    def _raise_outro(self) -> None:
        """The opt-in closing card (`Recorder(outro=…)`, off by default).

        The intro's mirror at the other end of the take: raised over the
        wrapper by `__exit__` while the capture is still running, voiced when
        speech is on, and **deliberately left up** — it is the take's last
        frame, the way the opening hold was its first. The overlay probe
        waives the card it raised (core's `_note_overlays_up`), so a take
        that ends on its outro is clean, not "an overlay left up".
        """
        if not self._outro:
            return
        self.page.evaluate("t => window.__demoInterlude(t)", self._outro)
        # The cursor is wherever the story last left it — over the closing
        # card that is a stray dot parked on the take's final frame. It goes
        # as the card goes up, not after the hold, or it rides the card the
        # whole time. The pointer leaves with the take.
        self.page.evaluate(
            "id => { const c = document.getElementById(id);"
            " if (c) c.style.display = 'none'; }",
            CURSOR_ID,
        )
        clip = self._prepare_line(self._outro, self._outro_clip)
        self._start_line(clip)
        hold = INTRO_HOLD_S * self._pace
        remaining = self._line_end - time.monotonic()
        self._idle(max(hold, remaining))
        # Only after the hold: the envelope key and the probe waiver both
        # hang on this, so a raise that failed halfway claims nothing.
        self._outro_up = True

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

        Read off `_target()`: the page is the recorder's own chrome and the
        crash happened in the app, so the app frame is what a failure dump
        has to show.
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
        what #142 keeps, and it fires for any frame — the app iframe's own
        navigations included — and for same-document history navigation too.

        Deliberately does nothing else — see `_watch_page` for why touching
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
        """One pass: the ARIA snapshot, the URL, and the spotlight target.

        Captured from `_target()` (#358): the page's own body is the
        recorder's chrome and one opaque iframe node, so evidence read there
        would describe the recorder instead of the app.
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
            # The chrome's own on-screen text — the caption line, a card —
            # read from the wrapper document, which is the other half of the
            # screen now that the app frame no longer carries the recorder's
            # furniture (see _CHROME_TEXT_JS).
            "chrome": self.page.evaluate(_CHROME_TEXT_JS),
        }
        # What the snapshot above structurally could not carry (#353). The key
        # is written only when there is something to say, so a page with no
        # such element on screen produces exactly the document it always did.
        omits = doc.evaluate(_ARIA_OMITS_JS)
        if omits:
            payload["aria_omits"] = omits
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
        # **The storyboard's own argument, classified (issue #268).** The
        # construction-time guard runs over `DEMO_VIDEO_BASE_URL` and the
        # resolved `base_url` and over nothing else, so until now
        # `rec.goto("https://app.acme.com/")` recorded production on a take
        # whose `base_url` was loopback — and the guard is the reason a
        # storyboard author believes that cannot happen. A storyboard is the
        # thing an agent writes, so the argument it passes is exactly the
        # input that needs classifying.
        #
        # **The built URL, not the absolute branch of it**, and that is not
        # belt-and-braces. A *relative* path can change the host too: `path`
        # is concatenated, not joined, so `goto("@evil.com/")` builds
        # `http://127.0.0.1:8901@evil.com/`, in which the declared base is
        # **userinfo** and the host is `evil.com`. Measured against two local
        # servers: Chromium lands on the second one and the declared app is
        # never asked for anything. Issue #268 reasoned that only the absolute
        # branch could escape; it is the branch that escapes *visibly*.
        #
        # Nothing legitimate is refused by classifying the join, because the
        # join keeps `base_url`'s host in every case that is not this one, and
        # that host was accepted at construction — `goto("/orders")` and
        # `goto("about:blank")` both come back loopback on a loopback take.
        #
        # **`self._allow_private`, never the environment.** Re-reading
        # `DEMO_VIDEO_ALLOW_PRIVATE` here would let a take permitted at
        # construction be refused at beat 12 because something changed the
        # environment mid-run — a refusal at the worst possible moment, with
        # the browser open and the artifacts half-written. The flag this take
        # was built with is the flag that decides.
        #
        # Before the retry loop and before Playwright: a refused URL must not
        # reach the network even once.
        guard_target(url, self._allow_private, source="this goto()'s argument")
        # The *iframe* navigates; the wrapper document — which holds the
        # caption, the cursor and the chrome — never does, so a mid-take
        # goto cannot take the caption off the screen (see `_watch_extra`).
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
                # would buy is the artifact-lie this recorder must not ship
                # — a silently blank window recorded as a demo. Refuse
                # instead, naming the header (issue #358).
                if "ERR_BLOCKED_BY_RESPONSE" in str(exc):
                    raise RuntimeError(self._frame_refusal(url)) from exc
                if attempt == 2:
                    raise
        try:
            target.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # apps that poll never go network-idle; the page is up
        # A full page load used to take the recorder's cards down with the
        # app's document — the card was an element inside it — and SKILL.md's
        # segment pattern leans on that: interlude(...), then goto() to open
        # on the app. The cards live in the wrapper document now (#360), so
        # goto restores the contract deliberately: the verb that shows the
        # app takes the recorder's own cards off it, exactly as it clears
        # the opening hold below. Without this, a segment that opened on an
        # interlude recorded the card over the app to the end of the take
        # (seen red in tests/smoke --segments-only, as the recorder's own
        # overlay-left-up warning). The caption is deliberately NOT cleared:
        # its surviving navigation is #358/#360's whole point.
        self.page.evaluate(
            "() => { window.__demoInterlude(''); window.__demoBridge(''); }"
        )
        if not self._hold_cleared:
            # The storyboard's first content beat landed: there is an app in
            # the slot now, so the opening hold (up since frame 0 — see
            # chrome.OPENING_HOLD_JS) fades out. Inside this beat on purpose:
            # the beat log's account of when the app appeared is the goto.
            self.page.evaluate("() => window.__demoChromeHoldClear()")
            self._hold_cleared = True
            # Written onto this beat so the review sheet can say which
            # frames were cut inside the hold: the beat's own mid-point
            # frame shows a flat field in the window's colour where the app
            # will be, and a sheet that leaves that to the reader reads as a
            # failed load (#361's reporting sweep). A video offset, like
            # every beat timestamp; `stitch()` shifts it with the beat.
            if self._in_beat and self._beats:
                self._beats[-1]["opening_hold_until"] = round(
                    time.monotonic() - self._t0, 3
                )

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
            f"Chromium blocked the take's iframe. Recording on would produce "
            f"a silently blank window presented as a demo, so the take "
            f"refuses instead. Serve the demo target without that header, or "
            f"record it with a target that allows framing."
        )

    @_beat_verb("terminal")
    def terminal(self, command: str) -> None:
        """Type a command in an on-screen terminal card, then perform the
        real action it describes right after this returns.

        The card is raised in the app's document (`_target()`), so it
        appears over the app inside the window — a prop inside the demo's
        story, deliberately not on the chrome's card layer (see chrome.py).
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
        # every frame, so they exist in the app iframe too — and the element
        # being lit lives there.
        #
        # The camera pulls back when the pull *starts*, not when the fade
        # lands: the clear's `evaluate` waits out the exit transition, and
        # an event that ended when it returned would hold the push ~250 ms
        # past the spotlight that justified it.
        self._camera_close(time.monotonic() - self._t0)
        self._target().evaluate("() => window.__demoSpotlightClear()")
        rect = None
        if selector:
            rect = self._target().locator(selector).first.evaluate(
                "el => window.__demoSpotlight(el)"
            )
        # Set after the highlight actually landed, so a selector that matched
        # nothing (and raised above) never becomes the scope of a beat's
        # evidence — a scope naming an element that is not there would put
        # `"html": null` in the file with no explanation.
        self._spotlit = selector or None
        if rect:
            self._camera_raise(self._frame_rect(rect))
        self.pause(0.3)

    def _frame_rect(self, rect: dict) -> dict:
        """An app-document rect, moved into the recorded frame's coordinates.

        The app records inside the wrapper's content slot at true pixel size
        (#358, cutover #361), so the mapping is the slot's offset and no
        scale — the same one `tests/_pixels.to_video_rect` applies from the
        other side. It is done here rather than in the page because the app
        frame is cross-origin to the wrapper whenever the demo is not served
        from the recorder's own origin, and `window.frameElement` is null
        across that boundary.
        """
        geom = getattr(self, "_geom", None) or {"appx": 0, "appy": 0}
        return {
            "x": int(rect["x"]) + int(geom["appx"]),
            "y": int(rect["y"]) + int(geom["appy"]),
            "w": int(rect["w"]),
            "h": int(rect["h"]),
        }

    def _glide(self, x: float, y: float, fast: bool = False) -> None:
        """Move the pointer to page coordinates `(x, y)`, dot included.

        The dot lives in the wrapper document, and no wrapper listener can
        hear a move whose target is inside the iframe — the browser delivers
        it to the iframe's document — so the recorder drives the dot itself.
        One call commands the dot to the target and the browser eases it
        there over a duration set by the travel distance (#403): the
        compositor paints the dot's easeOutCubic in every frame, which is
        what the old per-step scheme could not do — its 30 CDP round-trips
        completed in ~250 ms of wall time, so the encode held ~6 frames of
        constant-velocity motion and a hard stop. The dot still moves only
        when the storyboard says so — a CSS transition toward a commanded
        target is commanded motion — so the #186/#202 class (a dot placed by
        an event the storyboard never sent) stays unreachable: nothing
        listens, so nothing synthetic can move it. The stated cost is
        unchanged: raw `rec.page.mouse` work moves the pointer and not the
        dot.

        The real pointer is paced along the same easing curve while the dot
        animates, so hover states track the visible motion and both land
        together. `fast=True` halves the duration — `click_fast`'s ask.

        Coordinates are wrapper-page coordinates — Playwright's
        `bounding_box()` answers relative to the main frame's viewport even
        for elements inside an iframe, so the app-rect offset is already in
        every box the verbs read.
        """
        sx, sy = self._cursor_at
        dist = math.hypot(x - sx, y - sy)
        # ~800 px/s reads as a hand, not a dart; clamped so a short hop is
        # not instant and a corner-to-corner run does not stall the story.
        ms = min(max(dist / 800.0 * 1000.0, 280.0), 1000.0)
        if fast:
            ms /= 2
        self.page.evaluate(
            "([x, y, ms]) => window.__demoChromeCursor(x, y, ms)", [x, y, ms]
        )
        t0 = time.monotonic()
        while True:
            t = min((time.monotonic() - t0) * 1000.0 / ms, 1.0)
            p = 1 - (1 - t) ** 3  # easeOutCubic — the dot's cubic-bezier(.33,1,.68,1)
            self.page.mouse.move(sx + (x - sx) * p, sy + (y - sy) * p)
            if t >= 1.0:
                break
            time.sleep(0.016)
        self._cursor_at = (x, y)

    def _cursor_pressed(self, down: bool) -> None:
        """Squeeze (or release) the wrapper document's cursor dot."""
        fn = "__demoChromeCursorDown" if down else "__demoChromeCursorUp"
        self.page.evaluate(f"() => window.{fn}()")

    @_beat_verb("move_to")
    def move_to(self, selector: str) -> None:
        """Glide the cursor onto an element (smooth, watchable motion)."""
        box = self._target().locator(selector).first.bounding_box()
        if box is None:
            raise RuntimeError(f"no visible element for {selector!r}")
        self._glide(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

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
        self._glide(x, y, fast=True)
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
        # The per-character delay is pacing — it exists so a viewer sees the
        # text appear rather than snap into place — and it is the one piece of
        # pacing that does not go through `_idle`, because Playwright owns the
        # loop. A stills-only run zeroes it here for the same reason the base
        # zeroes the rest (#372): a 40-character field costs 1.6 s of nothing.
        self.page.keyboard.type(text, delay=0 if self.stills_only else delay_ms)

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
