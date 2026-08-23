"""The wrapper take's window chrome — one source for the frame both media share.

Issue #358 (design record: #355). A wrapper take records a recorder-owned
page carrying the window chrome: the pastel background, the dark rounded
window with its title bar and traffic lights, a **content slot** the medium
fills (the web recorder mounts the app iframe in it; #362 mounts xterm.js in
the same slot), a **caption band** reserved BELOW the slot, and a **card
layer** over the slot (#360). By construction the slot and the band share no
pixels — `chrome_geometry` is the arithmetic behind that sentence. This
repository's `tests/unit` (not shipped with the installed skill) grades it,
and this repository's `tests/smoke --wrapper-only` reads the same claim out
of a recorded take's frames.

**The card layer covers the app rect — not the chrome, not the caption
band.** `interlude()`, `criterion()` and the `light` bridge scrim render in
it, so a card replaces the *app's* content and nothing else: the window
frame and the narration line are the recorder's own furniture, and taking
them down to show a recorder-authored card would be the chrome hiding from
itself. The deleted composite path could not make that distinction — its
card was an element inside the app page, so full-bleed there meant the whole
page — which is why its card sat above the caption bar and this one sits
beside it. The decorative terminal prop (`Recorder.terminal()`) is deliberately
**not** here: it is content, a styled element inside the demo's story that
rides over the app the way an app dialog would, and the card layer stays
reserved for the recorder's own furniture — #362 mounts a *real* terminal in
the slot, and a prop living on the chrome layer would blur exactly that line.

**The wrapper card declares the window's own colour — no compensation.** The
card and the window body reach `demo.mp4` through one encoder on this path,
so both paint the `window_body` the document was built with
(`core.WEB_WINDOW_BODY` for the web recorder). The compensated pair the
deleted composite needed (#291/#301) is recorded in that constant's history
note; #361 deleted it with the composite.

The visual constants here were ported from the composite's window frame
(retired with it in #361) and from `terminal._TERM_HOST_JS`, whose copy
stays until #362 mounts the terminal in this chrome too.
"""

from __future__ import annotations

# The pastel gradient behind the window. terminal.py still paints its own
# copy (`_TERM_BG`) until #362; this one is the web recorder's since #361.
CHROME_BG = "linear-gradient(135deg, #f6d5f0 0%, #d7e3fb 52%, #cdeede 100%)"

# Title bar: height, fill and text colour, and the three traffic lights —
# the frame both media share; `_TERM_HOST_JS` (terminal) still matches it.
CHROME_BAR_PX = 36
CHROME_BAR_BG = "#232334"
CHROME_BAR_FG = "#9399b2"
TRAFFIC_LIGHTS = ("#ff5f57", "#febc2e", "#28c840")

# The pad the window keeps around the content slot, so its rounded corners
# stay visible — `_frame_geometry`'s 14, ported.
CHROME_PAD_PX = 14

# The caption band reserved below the content slot, inside the window. Sized
# for two lines of the wrapper caption font (2 x 26px x 1.36 line height +
# the bubble's 24px vertical padding = 95): a caption that needs a third line
# is clipped by the band rather than allowed to grow over the app — the whole
# point of the band is that the app never shares a pixel with the caption.
CAPTION_BAND_PX = 96

# The wrapper caption's font size: the base 26px, as declared, because the
# page is recorded at true pixel size — the same effective size the terminal
# recorder's captions have. (The deleted composite rendered captions at 34px
# to survive its ~0.8 downscale; web.py's history note has the story.)
CAPTION_FONT_PX = 26

# Element ids. The slot is what a medium fills; the band holds the caption
# element; the card layer holds the interlude/criterion card and the bridge
# scrim (#360). The caption element deliberately keeps the id
# `core._CAPTION_JS` uses, so "the caption element" is one selector whichever
# medium drew it. The cursor dot keeps the id the composite path's overlay
# used (`__demo_cursor`, so committed selectors keep working), and the card
# and scrim keep `core.INTERLUDE_ID`/`core.BRIDGE_ID` — that is what lets
# `interlude("")` and core's end-of-take overlay probe (`_OVERLAY_PROBE_JS`,
# issue #163) find them with no wrapper-specific dispatch.
SLOT_ID = "__chrome_slot"
BAND_ID = "__chrome_band"
CARD_ID = "__chrome_card"
HOLD_ID = "__chrome_hold"
CAPTION_ID = "__demo_caption"
CURSOR_ID = "__demo_cursor"

# The card layer's stacking, against the opening hold below it and the cursor
# dot above it. Root-context values: `#__chrome_win` is position:fixed with no
# z-index of its own, so it opens no stacking context and its children's
# z-indexes rank directly against the fixed-position hold's.
HOLD_Z = 2147483644
CARD_LAYER_Z = 2147483645


def chrome_geometry(
    width: int,
    height: int,
    *,
    pad: int = CHROME_PAD_PX,
    bar: int = CHROME_BAR_PX,
    band: int = CAPTION_BAND_PX,
) -> dict:
    """Where the window, the content slot and the caption band sit.

    All in recorded-frame pixels — the wrapper page is the video, unscaled.
    The slot is `int(width * 0.80)` wide (the composite's app width, kept so
    the window is the size viewers already know) and `int(height * 2/3)`
    tall, both forced even for the encoder. The band sits directly below the
    slot: `bandy == appy + apph`, so the two rectangles are disjoint by
    construction — the property `tests/unit` asserts on this function and
    `tests/smoke` asserts on the pixels.

    The `app*`/`win*` keys deliberately match `Recorder._frame_geometry`'s,
    so `_content_rect` and every geometry consumer reads one shape.
    """
    appw = int(width * 0.80) & ~1
    apph = int(height * 2 / 3) & ~1
    winw = appw + 2 * pad
    winh = bar + pad + apph + band + pad
    winx = (width - winw) // 2
    winy = (height - winh) // 2
    if winx < 0 or winy < 0:
        raise ValueError(
            f"a {width}x{height} viewport cannot hold the wrapper chrome: the "
            f"window would be {winw}x{winh}. Use a viewport of at least "
            f"{winw}x{winh}."
        )
    return {
        "pad": pad,
        "bar": bar,
        "band": band,
        "appw": appw,
        "apph": apph,
        "winw": winw,
        "winh": winh,
        "winx": winx,
        "winy": winy,
        "appx": winx + pad,
        "appy": winy + bar + pad,
        "bandx": winx + pad,
        "bandy": winy + bar + pad + apph,
        "bandw": appw,
        "bandh": band,
    }


# The wrapper document. Substitutions are literal tokens (replaced by
# `chrome_html`). The inline <script> runs after the recorder's context
# init scripts (init scripts run at document_start), so the band-aware
# `__demoCaption` below is the one `caption()` reaches in this document —
# core's fixed-bottom overlay version never paints here.
#
# The cursor dot is the wrapper document's, riding *over* the iframe, so an
# app navigation cannot destroy it (the wrapper never navigates). It is
# driven explicitly by the recorder — `__demoChromeCursor(x, y)` per pointer
# step — never by mouse events: events over the iframe are delivered to the
# iframe's document and no wrapper listener can hear them, and a dot that
# only moves when the storyboard says so is structurally immune to the
# synthetic-mousemove race of #186.
_CHROME_HTML = """<!doctype html><meta charset="utf-8"><title>__TITLE__</title>
<style>
  html, body { margin: 0; height: 100%; }
  body { background: __BG__; }
  #__chrome_win { position: fixed; left: __WINX__px; top: __WINY__px;
    width: __WINW__px; height: __WINH__px; border-radius: 14px;
    overflow: hidden; background: __WINBG__;
    box-shadow: 0 34px 90px rgba(20,16,40,.40), 0 8px 22px rgba(20,16,40,.28); }
  #__chrome_bar { height: __BAR__px; display: flex; align-items: center;
    gap: 8px; padding: 0 14px; background: __BARBG__;
    font: 13px/1 ui-monospace, monospace; color: __BARFG__; }
  .dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
  #__chrome_ttl { flex: 1; text-align: center; letter-spacing: .02em; }
  /* The slot's underlay is the browser's own white canvas, not the window
     body: an app document that paints no background of its own sits on
     white in any real browser, and a transparent about:blank iframe
     borrowing the recorder's window colour would make the opening hold
     unfalsifiable — with or without the hold, the app rect would read the
     same dark field. White underneath is what the hold exists to cover
     (#360), and what lets a frame-0 reading tell the two apart. */
  #__chrome_slot { position: absolute; left: __PAD__px;
    top: __SLOTTOP__px; width: __APPW__px; height: __APPH__px;
    overflow: hidden; background: #fff; }
  #__chrome_slot iframe { display: block; border: 0;
    width: __APPW__px; height: __APPH__px; }
  #__chrome_band { position: absolute; left: __PAD__px; top: __BANDTOP__px;
    width: __APPW__px; height: __BAND__px; overflow: hidden;
    display: flex; align-items: center; justify-content: center; }
  #__demo_caption { max-width: 90%; padding: 12px 30px; border-radius: 12px;
    background: rgba(22,20,16,.72); backdrop-filter: blur(3px);
    color: #f7f4ee; text-align: center;
    font: 600 __CAPFONT__px/1.36 system-ui, sans-serif; letter-spacing: .01em;
    pointer-events: none; opacity: 0;
    transition: opacity .3s ease; box-shadow: 0 6px 24px rgba(0,0,0,.28); }
  /* The card layer sits exactly on the content slot — the app rect and
     nothing else. See the module docstring for why a card covers the app
     and never the chrome or the caption band. */
  #__chrome_card { position: absolute; left: __PAD__px; top: __SLOTTOP__px;
    width: __APPW__px; height: __APPH__px; overflow: hidden;
    pointer-events: none; z-index: __CARDZ__; }
  /* The full card: the window's own colour, one flat field with the sentence
     on it — no compensation, one encoder (see the module docstring). Above
     the scrim and the opening hold, so a clause is legible over either. */
  #__demo_interlude { position: absolute; inset: 0; display: flex;
    align-items: center; justify-content: center;
    font: 500 30px/1.5 system-ui, sans-serif; text-align: center;
    padding: 0 12%; opacity: 0; transition: opacity .45s ease;
    background: __WINBG__; color: #f2f0ec; z-index: 3; }
  /* The light bridge: a soft scrim with the app still visible behind it. */
  #__demo_bridge { position: absolute; inset: 0; display: flex;
    align-items: center; justify-content: center; opacity: 0;
    transition: opacity .4s ease;
    background: radial-gradient(ellipse at center,
      rgba(18,15,28,.58) 0%, rgba(18,15,28,.16) 70%, rgba(18,15,28,0) 100%);
    z-index: 2; }
  #__demo_bridge_t { color: #fff; font: 600 34px/1.4 system-ui, sans-serif;
    text-align: center; max-width: 72%;
    text-shadow: 0 2px 22px rgba(0,0,0,.65); }
  /* The opening hold, in this document's own markup and **already opaque**
     (_OPENING_CARD_JS's construction): `set_content` replaces the initial
     document without re-running the context init scripts, measured — a
     hold that relied on the init script alone left frame 0 reading the
     slot's white canvas at 255 mean luma. The init script (OPENING_HOLD_JS)
     covers the documents before this one; whichever builds first owns the
     id. Below the cards: a storyboard that interludes before its first
     goto must show the clause over the hold. */
  #__chrome_hold { position: absolute; inset: 0; background: __WINBG__;
    opacity: 1; transition: opacity .45s ease; z-index: 1; }
  #__demo_cursor { position: fixed; top: -40px; left: -40px; width: 18px;
    height: 18px; border-radius: 50%; background: rgba(__ACCENT__,.45);
    border: 2px solid rgba(__ACCENT__,.95); pointer-events: none;
    z-index: 2147483647; transform: translate(-50%,-50%);
    transition: width .1s, height .1s; }
  #__demo_cursor.__down { width: 12px; height: 12px; }
</style>
<div id="__chrome_win">
  <div id="__chrome_bar">
    <span class="dot" style="background:__DOT1__"></span>
    <span class="dot" style="background:__DOT2__"></span>
    <span class="dot" style="background:__DOT3__"></span>
    <span id="__chrome_ttl">__TITLE__</span>
    <span style="width:44px"></span>
  </div>
  <div id="__chrome_slot"></div>
  <div id="__chrome_band"><div id="__demo_caption"></div></div>
  <div id="__chrome_card">
    <div id="__chrome_hold"></div>
    <div id="__demo_bridge"><div id="__demo_bridge_t"></div></div>
    <div id="__demo_interlude"></div>
  </div>
</div>
<div id="__demo_cursor"></div>
<script>
  window.__demoCaption = (text) => {
    const el = document.getElementById('__demo_caption');
    el.textContent = text;
    el.style.opacity = text ? '1' : '0';
    // How many pixels of this caption the band cannot show. The band has a
    // fixed height and overflow: hidden — the construction that keeps the
    // app rect caption-free — so a line too tall for it is shaved at the
    // band's edges. The recorder records that as a caption_clipped issue
    // (core.caption reads this return value); the in-page overlay version
    // of this function grows with its text and returns nothing.
    if (!text) return 0;
    const band = document.getElementById('__chrome_band');
    return Math.max(0, el.scrollHeight - band.clientHeight);
  };
  // The card and the scrim, band-aware for the same reason __demoCaption
  // above is: this document's versions render in the card layer over the app
  // rect, so the init-script versions (core's, which cover the *viewport*
  // they run in) never paint here. Same ids, same contract — text raises,
  // '' fades — so core's interlude(''), criterion() and end-of-take overlay
  // probe need no wrapper dispatch.
  window.__demoInterlude = (text) => {
    const card = document.getElementById('__demo_interlude');
    card.textContent = text;
    card.style.opacity = text ? '1' : '0';
  };
  window.__demoBridge = (text) => {
    document.getElementById('__demo_bridge_t').textContent = text;
    document.getElementById('__demo_bridge').style.opacity = text ? '1' : '0';
  };
  // Defined here as well as in OPENING_HOLD_JS: this document carries its
  // own hold element, and the reveal must not depend on when (or whether)
  // the context init script re-ran for it.
  window.__demoChromeHoldClear = () => {
    const el = document.getElementById('__chrome_hold');
    if (el) el.style.opacity = '0';
  };
  window.__demoChromeCursor = (x, y) => {
    const dot = document.getElementById('__demo_cursor');
    dot.style.left = x + 'px';
    dot.style.top = y + 'px';
  };
  window.__demoChromeCursorDown = () => {
    document.getElementById('__demo_cursor').classList.add('__down');
  };
  window.__demoChromeCursorUp = () => {
    document.getElementById('__demo_cursor').classList.remove('__down');
  };
</script>
"""


def chrome_html(
    geom: dict,
    *,
    title: str,
    window_body: str,
    accent: str,
    background: str = CHROME_BG,
    caption_font_px: int = CAPTION_FONT_PX,
) -> str:
    """The wrapper document, ready for `page.set_content`.

    `geom` is `chrome_geometry`'s dict. `window_body` is the window's fill
    **and the card's** — `core.WEB_WINDOW_BODY` for the web path. One
    parameter for both on purpose: the two ride one encoder here, so "the
    card is the window's own colour" is a single substitution rather than a
    compensated pair (see the module docstring, and #291/#301 for the pair
    the legacy composite still needs). `accent` is the recorder's `R,G,B`
    string, used only by the cursor dot. The slot ships empty: the medium
    mounts its content (an iframe, or #362's xterm host) into
    `#__chrome_slot`.
    """
    slot_top = geom["bar"] + geom["pad"]
    band_top = slot_top + geom["apph"]
    replacements = {
        "__TITLE__": title,
        "__BG__": background,
        "__WINBG__": window_body,
        "__BARBG__": CHROME_BAR_BG,
        "__BARFG__": CHROME_BAR_FG,
        "__DOT1__": TRAFFIC_LIGHTS[0],
        "__DOT2__": TRAFFIC_LIGHTS[1],
        "__DOT3__": TRAFFIC_LIGHTS[2],
        "__WINX__": str(geom["winx"]),
        "__WINY__": str(geom["winy"]),
        "__WINW__": str(geom["winw"]),
        "__WINH__": str(geom["winh"]),
        "__BAR__": str(geom["bar"]),
        "__PAD__": str(geom["pad"]),
        "__SLOTTOP__": str(slot_top),
        "__BANDTOP__": str(band_top),
        "__APPW__": str(geom["appw"]),
        "__APPH__": str(geom["apph"]),
        "__BAND__": str(geom["band"]),
        "__CAPFONT__": str(caption_font_px),
        "__ACCENT__": accent,
        "__CARDZ__": str(CARD_LAYER_Z),
    }
    html = _CHROME_HTML
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


# The opening hold: an opaque field in the window's own colour over the app
# rect, up in **frame 0** and cleared by the storyboard's first content beat
# (the web recorder clears it when its first `goto()` lands). It is what
# replaces the legacy composite's ffmpeg `enable='lt(t,held)'` second overlay
# (issue #360): with one encoder there is no exit-time compositing to hide a
# blank opening behind, so the blank opening is never on screen instead.
#
# An **init script**, and appended **already opaque** — both halves are
# `terminal._OPENING_CARD_JS`'s pattern, kept for its reasons: an init script
# runs on the wrapper page's *initial empty document*, which is earlier than
# any Python statement or `set_content` can reach; and an element whose
# computed opacity has been 1 since it entered the tree has no fade-in to run
# over the recorder's own setup. The chrome document then carries its own
# copy of the hold **in its markup** (`_CHROME_HTML`'s card layer) rather
# than relying on this script re-running for it: measured, the init script's
# re-run on the `set_content` document lands only at that document's
# DOMContentLoaded, after its first paint — frame 0 read the slot's white
# canvas at 255 mean luma. One id, and whichever document builds first owns
# it, so the two sources can never stack. The clear is a fade, because by
# then the app has painted underneath.
#
# Top-window guarded: context init scripts run in every frame, and the app
# iframe painting a copy of the hold over its own content would be the hold
# covering the thing it exists to reveal.
#
# The pastel paint on the document element is `terminal._init_context`'s
# issue-#25 guard, for the same white flash: the initial document is up
# before the chrome document replaces it, and an unpainted document is white.
OPENING_HOLD_JS = """
(() => {
  if (window !== window.top) return;
  const paint = (el) => { if (el) el.style.background = '__BG__'; };
  paint(document.documentElement);
  const build = () => {
    paint(document.documentElement);
    if (!document.body || document.getElementById('__chrome_hold')) return;
    const el = document.createElement('div');
    el.id = '__chrome_hold';
    el.style.cssText = 'position: fixed; left: __APPX__px; top: __APPY__px;'
      + ' width: __APPW__px; height: __APPH__px; background: __WINBG__;'
      + ' z-index: __HOLDZ__; pointer-events: none;'
      + ' transition: opacity .45s ease;';
    el.style.opacity = '1';
    document.body.appendChild(el);
  };
  if (document.body) build();
  else addEventListener('DOMContentLoaded', build);
  window.__demoChromeHoldClear = () => {
    const el = document.getElementById('__chrome_hold');
    if (el) el.style.opacity = '0';
  };
})();
"""


def opening_hold_script(
    geom: dict,
    *,
    window_body: str,
    background: str = CHROME_BG,
) -> str:
    """`OPENING_HOLD_JS` with this take's geometry and colours in it.

    `window_body` is the same fill `chrome_html` paints the window and the
    card with, so the hold, the card and the window are one declared colour
    on this path — the single-encoder point the module docstring makes.
    """
    replacements = {
        "__BG__": background,
        "__WINBG__": window_body,
        "__APPX__": str(geom["appx"]),
        "__APPY__": str(geom["appy"]),
        "__APPW__": str(geom["appw"]),
        "__APPH__": str(geom["apph"]),
        "__HOLDZ__": str(HOLD_Z),
    }
    script = OPENING_HOLD_JS
    for token, value in replacements.items():
        script = script.replace(token, value)
    return script
