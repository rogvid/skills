"""The wrapper take's window chrome — one source for the frame both media share.

Issue #358 (design record: #355). A wrapper take records a recorder-owned
page carrying the window chrome: the pastel background, the dark rounded
window with its title bar and traffic lights, a **content slot** the medium
fills (the web recorder mounts the app iframe in it; #362 mounts xterm.js in
the same slot), a **caption band** reserved BELOW the slot, and an empty card
layer #360 will use. By construction the slot and the band share no pixels —
`chrome_geometry` is the arithmetic behind that sentence, and `tests/unit`
grades it while `tests/smoke --wrapper-only` reads the same claim out of a
recorded take's frames.

Every visual constant here is ported from `web._FRAME_HTML` and
`terminal._TERM_HOST_JS`, which stay untouched while the legacy composite
path exists; #361 and #362 retire those copies. The window body colour is
**not** declared here — it stays `core.WEB_WINDOW_BODY`, because the interlude
card's compensated colour (`core.WEB_CARD_BODY`, #291/#301) is documented
against it and the two must be read together.
"""

from __future__ import annotations

# The pastel gradient behind the window. The same string web.py and
# terminal.py paint today (`_WEB_BG`, `_TERM_BG`); this copy is the one the
# wrapper path reads, and the one that survives #361/#362.
CHROME_BG = "linear-gradient(135deg, #f6d5f0 0%, #d7e3fb 52%, #cdeede 100%)"

# Title bar: height, fill and text colour, and the three traffic lights —
# ported from `_FRAME_HTML` (web) which `_TERM_HOST_JS` (terminal) matches.
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

# The wrapper caption's font size. The composite path renders captions at
# 34px because ffmpeg scales the page by ~0.8 into the window (~27px on
# screen); the wrapper page is recorded at true pixel size, so the caption
# uses the base 26px directly — the same effective size the terminal
# recorder's captions have. No compensation, because there is no scale.
CAPTION_FONT_PX = 26

# Element ids. The slot is what a medium fills; the band holds the caption
# element; the card layer is #360's mount point and ships empty this slice.
# The caption element deliberately keeps the id `core._CAPTION_JS` uses, so
# "the caption element" is one selector whichever path drew it. The cursor
# dot keeps `web._CURSOR_JS`'s id for the same reason.
SLOT_ID = "__chrome_slot"
BAND_ID = "__chrome_band"
CARD_ID = "__chrome_card"
CAPTION_ID = "__demo_caption"
CURSOR_ID = "__demo_cursor"


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


# The wrapper document. Substitutions are literal tokens, same pattern as
# `web._FRAME_HTML`. The inline <script> runs after the recorder's context
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
  #__chrome_slot { position: absolute; left: __PAD__px;
    top: __SLOTTOP__px; width: __APPW__px; height: __APPH__px;
    overflow: hidden; }
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
  #__chrome_card { position: absolute; inset: 0; display: none; }
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
  <div id="__chrome_card"></div>
</div>
<div id="__demo_cursor"></div>
<script>
  window.__demoCaption = (text) => {
    const el = document.getElementById('__demo_caption');
    el.textContent = text;
    el.style.opacity = text ? '1' : '0';
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

    `geom` is `chrome_geometry`'s dict. `window_body` is the window's fill —
    `core.WEB_WINDOW_BODY` for the web path (see this module's docstring for
    why it is not declared here). `accent` is the recorder's `R,G,B` string,
    used only by the cursor dot. The slot ships empty: the medium mounts its
    content (an iframe, or #362's xterm host) into `#__chrome_slot`.
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
    }
    html = _CHROME_HTML
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html
