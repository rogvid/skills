"""Frame geometry, and the overlay images the renderer composites.

Every overlay - the window, caption pills, title cards, badges, the cursor -
is drawn once as a PNG by Chromium, so text uses the browser's font stack and
looks the same as the page it sits on.
"""

from __future__ import annotations

import html
from pathlib import Path

FONT = (
    'Inter, "SF Pro Text", "Segoe UI", system-ui, -apple-system, '
    '"Noto Sans", "DejaVu Sans", sans-serif'
)
BACKDROP = (
    "radial-gradient(at 12% 18%, #f7d9ee 0, transparent 55%),"
    "radial-gradient(at 88% 12%, #d8e4fb 0, transparent 50%),"
    "radial-gradient(at 80% 92%, #d5f0e6 0, transparent 55%),"
    "radial-gradient(at 15% 90%, #e6ddfb 0, transparent 50%), #eef0f7"
)
THEMES = {
    "light": {
        "bar": "#ececf0",
        "bar_text": "#5d5d68",
        "body": "#ffffff",
        "card": "#f6f6f9",
        "card_text": "#1b1b26",
    },
    "dark": {
        "bar": "#232334",
        "bar_text": "#8e8ea6",
        "body": "#181825",
        "card": "#15151f",
        "card_text": "#ffffff",
    },
}


def _frame(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The margin around the window (the same on every side, and deep enough
    below it for a two-line caption), the title bar's height, and the room
    left for the app."""
    w, h = size
    margin = round(0.1 * h)
    bar = round(0.034 * h)
    return margin, bar, w - 2 * margin, h - 2 * margin - bar


def default_viewport(size: tuple[int, int], width: int) -> tuple[int, int]:
    """A viewport `width` CSS pixels wide, shaped like the room for the app,
    so the margin around the window comes out even."""
    _, _, room_w, room_h = _frame(size)
    return width, round(width * room_h / room_w)


def geometry(size: tuple[int, int], viewport: tuple[int, int]) -> dict:
    """Where the window, the app's content and the caption band sit in the
    output frame. A viewport shaped differently from the room for the app
    leaves a wider margin on one axis."""
    w, h = size
    vw, vh = viewport
    margin, bar, room_w, room_h = _frame(size)
    scale = min(room_w / vw, room_h / vh)
    cw, ch = round(vw * scale), round(vh * scale)
    x = (w - cw) // 2
    y = (h - ch - bar) // 2
    return {
        "size": [w, h],
        "scale": scale,
        "window": [x, y, cw, ch + bar],
        "content": [x, y + bar, cw, ch],
        "bar": bar,
        # Captions sit centred in the margin below the window, off the app.
        "caption_y": round((y + ch + bar + h) / 2),
        "radius": round(0.011 * h),
        "unit": h / 1080,
    }


class Overlays:
    """Renders overlay PNGs into `out_dir` with a browser page of its own."""

    def __init__(self, browser, out_dir: Path, geom: dict, theme: str, accent: str) -> None:
        self.dir = out_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.geom = geom
        self.theme = THEMES[theme]
        self.accent = accent
        w, h = geom["size"]
        self._context = browser.new_context(viewport={"width": w, "height": h})
        self._page = self._context.new_page()
        self._cache: dict[str, str] = {}
        self._n = 0

    def close(self) -> None:
        self._context.close()

    def _px(self, v: float) -> int:
        return max(1, round(v * self.geom["unit"]))

    def _element(self, key: str, body: str, css: str) -> str:
        """Screenshot `#o` from `body`, transparent around it. Cached by key."""
        if key in self._cache:
            return self._cache[key]
        self._n += 1
        name = f"o{self._n:04d}.png"
        self._page.set_content(
            f"<html><head><style>html,body{{margin:0;background:transparent}}"
            f"#o{{font-family:{FONT};-webkit-font-smoothing:antialiased}}{css}</style>"
            f"</head><body>{body}</body></html>"
        )
        self._page.locator("#o").screenshot(path=str(self.dir / name), omit_background=True)
        self._cache[key] = name
        return name

    def window(self, title: str) -> str:
        """The whole frame: backdrop, the window with its title bar, and the
        content area filled with the window's body colour."""
        g, t = self.geom, self.theme
        wx, wy, ww, wh = g["window"]
        w, h = g["size"]
        dot = self._px(12)
        css = f"""
        #o {{ position:relative; width:{w}px; height:{h}px; background:{BACKDROP}; }}
        .win {{ position:absolute; left:{wx}px; top:{wy}px; width:{ww}px; height:{wh}px;
          border-radius:{g["radius"]}px; overflow:hidden; background:{t["body"]};
          box-shadow:0 {self._px(24)}px {self._px(70)}px rgba(20,20,40,.28),
                     0 0 0 1px rgba(0,0,0,.08); }}
        .bar {{ height:{g["bar"]}px; background:{t["bar"]}; display:flex; align-items:center;
          padding:0 {self._px(14)}px; gap:{self._px(8)}px; position:relative; }}
        .dot {{ width:{dot}px; height:{dot}px; border-radius:50%; }}
        .title {{ position:absolute; left:0; right:0; text-align:center; color:{t["bar_text"]};
          font-size:{self._px(14)}px; font-weight:500; }}
        """
        body = (
            '<div id="o"><div class="win"><div class="bar">'
            '<span class="dot" style="background:#ff5f57"></span>'
            '<span class="dot" style="background:#febc2e"></span>'
            '<span class="dot" style="background:#28c840"></span>'
            f'<span class="title">{html.escape(title)}</span></div></div></div>'
        )
        return self._element("window:" + title, body, css)

    def caption(self, text: str) -> str:
        cw = self.geom["content"][2]
        css = f"""
        #o {{ display:inline-block; max-width:{round(cw * 0.8)}px; box-sizing:border-box;
          padding:{self._px(11)}px {self._px(24)}px; border-radius:{self._px(14)}px;
          background:rgba(18,18,26,.88); color:#fff; font-size:{self._px(26)}px;
          font-weight:600; line-height:1.35; text-align:center; text-wrap:balance;
          letter-spacing:-.005em; }}
        """
        return self._element("caption:" + text, f'<div id="o">{html.escape(text)}</div>', css)

    def card(self, text: str) -> str:
        _, _, cw, ch = self.geom["content"]
        t = self.theme
        css = f"""
        #o {{ width:{cw}px; height:{ch}px; display:flex; align-items:center;
          justify-content:center; background:{t["card"]}; }}
        #o div {{ max-width:70%; color:{t["card_text"]}; font-size:{self._px(46)}px; font-weight:650;
          line-height:1.25; text-align:center; text-wrap:balance; letter-spacing:-.01em; }}
        """
        return self._element(
            "card:" + text, f'<div id="o"><div>{html.escape(text)}</div></div>', css
        )

    def badge(self, text: str) -> str:
        """A small pill: the fast-forward marker and pressed keys."""
        css = f"""
        #o {{ display:inline-flex; align-items:center; gap:{self._px(8)}px;
          padding:{self._px(8)}px {self._px(16)}px; border-radius:999px;
          background:rgba(18,18,26,.82); color:#fff; font-size:{self._px(20)}px;
          font-weight:600; font-variant-numeric:tabular-nums; }}
        """
        return self._element("badge:" + text, f'<div id="o">{html.escape(text)}</div>', css)

    def cursor(self) -> tuple[str, list[int]]:
        """The pointer, and its hotspot within the image."""
        size = self._px(30)
        pad = self._px(6)
        css = f"#o {{ padding:{pad}px; width:{size}px; height:{size}px; }}"
        svg = (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" '
            'style="filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))">'
            '<path d="M5 2.5 L5 20 L9.6 15.8 L12.6 22 L15.4 20.8 L12.5 14.7 L18.6 14.7 Z" '
            'fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
        )
        name = self._element("cursor", f'<div id="o">{svg}</div>', css)
        tip = pad + round(size * 5 / 24)
        return name, [tip, pad + round(size * 2.5 / 24)]
