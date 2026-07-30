"""Two helpers for writing a value into a markdown document.

**A leaf: this module imports nothing from the package**, and that is its whole
job. Three modules render markdown — `timeline`, `frames` and `failure` — and
these two functions were in `timeline`, which is fine until `failure` needs them
too: `timeline` imports `failure` for its paths, so `failure` importing back was
a cycle (#147).

Keeping them here rather than duplicating them matters more than the tidiness.
`_md_cell` is the only thing standing between an exception message holding a
pipe and a markdown table gaining a column, and a second copy is a second place
to forget the backslash.
"""

from __future__ import annotations

from typing import cast


def _md_cell(value: object) -> str:
    """A value made safe to drop into a markdown table cell."""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _fmt_t(value: object) -> str:
    # The `cast` is erased at run time, so this is byte-for-byte the behaviour
    # it had inside core.py — including the TypeError `float()` raises on a
    # beat whose timestamp is not a number. What changed is only that the
    # diagnostic is now visible: `[mypy-demo_recording.core]` disables
    # `arg-type` wholesale for one *stated* reason (a ViewportSize TypedDict),
    # and it was silencing this second, unrelated one for free. Moving the
    # function out from under a blanket suppression is how that surfaced.
    return "" if value is None else f"{float(cast('float', value)):.2f}"
