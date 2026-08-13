# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Corpus take: a second demo that genuinely shows both of its clauses.

The other false-alarm control, deliberately a different shape from
`clean-status-filter`: typing rather than clicking, and a clause whose evidence
is an absence on screen (the empty-state line) rather than a narrowed list. One
clean take cannot distinguish a reader that reads from a reader that agrees
with whatever it is shown; two of different shapes is the minimum for the
false-alarm number to mean anything.

Recorded by `tests/eval-grader record`.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_DEFAULT_SKILL_DIR = HERE.parents[4] / "skills" / "demo-video"
SKILL_DIR = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or _DEFAULT_SKILL_DIR)
if not (SKILL_DIR / "helpers" / "demo_recording" / "__init__.py").exists():
    sys.exit(f"demo-video skill not found at {SKILL_DIR} — set DEMO_VIDEO_SKILL_DIR")
sys.path.insert(0, str(SKILL_DIR / "helpers"))
from demo_recording import Recorder  # noqa: E402

BASE_URL = os.environ.get("TICKET_QUEUE_URL", "http://127.0.0.1:8901")
SEARCH = "#queue-search"

CRITERIA = {
    "AC-1": (
        "A search box above the queue narrows the list as you type, with no "
        "button to press."
    ),
    "AC-2": (
        "A search matching nothing shows a 'No tickets match this filter.' "
        "line instead of a blank queue."
    ),
}


def clear_search(rec):
    """Empty the search box the way a person would: select all, backspace."""
    rec.click(SEARCH)
    rec.page.keyboard.press("Control+A")
    rec.page.keyboard.press("Backspace")


with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")

    rec.caption("Typing invoice narrows the queue to one ticket.", ac="AC-1")
    rec.type_into(SEARCH, "invoice")
    # The criterion, asserted: a search that matched nothing would leave no
    # ticket listed and fail the take.
    rec.wait_for(".ticket[data-id='TQ-101']")
    rec.hold()
    rec.shot("01-invoice", ac="AC-1")

    rec.caption("Typing export narrows it to a different one.", ac="AC-1")
    clear_search(rec)
    rec.type_into(SEARCH, "export")
    rec.wait_for(".ticket[data-id='TQ-102']")
    rec.hold()
    rec.shot("02-export", ac="AC-1")

    rec.caption("A search that matches nothing says so.", ac="AC-2")
    clear_search(rec)
    rec.type_into(SEARCH, "refund")
    rec.wait_for(".queue-empty")
    rec.hold()
    rec.shot("03-no-match", ac="AC-2")
    rec.caption("")
