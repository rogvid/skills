"""List what a storyboard can point at on the current page, with a selector
for each - so finding a selector costs one call instead of reading the app's
source."""

from __future__ import annotations

_JS = r"""
() => {
  const esc = s => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (r.right < 0 || r.bottom < 0 || r.left > innerWidth || r.top > innerHeight * 3) return false;
    const s = getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05;
  };
  const text = el => (el.innerText || el.value || el.getAttribute('aria-label')
    || el.getAttribute('title') || el.getAttribute('placeholder') || '')
    .replace(/\s+/g, ' ').trim();
  const role = el => {
    const r = el.getAttribute('role');
    if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a' && el.hasAttribute('href')) return 'link';
    if (t === 'button' || (t === 'input' && ['button','submit'].includes(el.type))) return 'button';
    if (t === 'input' && el.type === 'checkbox') return 'checkbox';
    if (t === 'input' || t === 'textarea') return 'textbox';
    if (t === 'select') return 'combobox';
    if (/^h[1-6]$/.test(t)) return 'heading';
    return null;
  };
  const unique = sel => { try { return document.querySelectorAll(sel).length === 1; } catch { return false; } };
  const selector = el => {
    const t = el.tagName.toLowerCase();
    if (el.id && /^[A-Za-z][\w-]*$/.test(el.id) && unique('#' + el.id)) return '#' + el.id;
    for (const a of ['data-testid', 'data-test', 'name', 'aria-label', 'title', 'placeholder']) {
      const v = el.getAttribute(a);
      if (v && v.length < 60) {
        const s = `${t}[${a}="${esc(v)}"]`;
        if (unique(s)) return s;
      }
    }
    const r = role(el), n = text(el);
    if (r && n && n.length <= 50) return `role=${r}[name="${esc(n)}"]`;
    if (n && n.length <= 40) return `${t}:has-text("${esc(n)}")`;
    return null;
  };
  const q = 'a[href],button,input,select,textarea,[role],[onclick],[tabindex]:not([tabindex="-1"]),h1,h2,h3,[data-testid]';
  const out = [], seen = new Set();
  for (const el of document.querySelectorAll(q)) {
    if (!visible(el) || seen.has(el)) continue;
    seen.add(el);
    const sel = selector(el);
    if (!sel) continue;
    const r = role(el) || el.tagName.toLowerCase();
    out.push([r, text(el).slice(0, 50), sel]);
    if (out.length >= 60) break;
  }
  // Repeated items (list rows, cards): what a wait_for usually waits on.
  const counts = new Map();
  for (const el of document.querySelectorAll('body [class]')) {
    if (!visible(el)) continue;
    for (const c of el.classList) {
      if (!/^[A-Za-z][\w-]*$/.test(c)) continue;
      const e = counts.get(c) || [0, el];
      counts.set(c, [e[0] + 1, e[1]]);
    }
  }
  const lists = [...counts].filter(([, [n]]) => n >= 3).sort((a, b) => b[1][0] - a[1][0]).slice(0, 8);
  for (const [c, [n, el]] of lists) out.push([`${n} items`, text(el).slice(0, 50), '.' + c]);
  return out;
}
"""


def describe(page) -> str:
    """One line per element: role, visible text, selector."""
    try:
        rows = page.evaluate(_JS)
    except Exception as e:  # noqa: BLE001 - mid-navigation, closed page
        return f"  (could not read the page: {e})"
    if not rows:
        return "  (nothing interactive is visible)"
    width = max(len(r[0]) for r in rows)
    return "\n".join(f"  {r[0]:<{width}}  {r[1][:40]!r:<44} {r[2]}" for r in rows)
