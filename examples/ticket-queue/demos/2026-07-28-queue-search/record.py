# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Searching the queue by text, against the four criteria of ticket #129.

Run the app first:

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-07-28-queue-search/record.py

The storyboard is written from ticket #129 and declares its four acceptance
criteria on the recorder, so `timeline.md` carries a coverage table naming the
beat and the still that claims each one.

The `wait_for()` calls are assertions, not decoration: `.ticket` after typing
`invoice` fails the take if the search left nothing listed, and `.queue-empty`
after typing a term the queue has no match for fails it if the queue goes
blank instead of saying why.

The two AC-3 beats name the row they expect *and* the requester element on it,
because the version of this storyboard that shipped with #129 held neither.
It typed `mira`, held over an empty queue, and recorded a still of the bug —
issue #132. A beat that only holds cannot fail.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_DEFAULT_SKILL_DIR = HERE.parents[3] / "skills" / "demo-video"
SKILL_DIR = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or _DEFAULT_SKILL_DIR)
if not (SKILL_DIR / "helpers" / "demo_recording" / "__init__.py").exists():
    sys.exit(f"demo-video skill not found at {SKILL_DIR} — set DEMO_VIDEO_SKILL_DIR")
sys.path.insert(0, str(SKILL_DIR / "helpers"))
from demo_recording import Recorder  # noqa: E402

BASE_URL = os.environ.get("TICKET_QUEUE_URL", "http://127.0.0.1:8901")
SEARCH = "#queue-search"

CRITERIA = {
    "AC-1": (
        "A search box above the queue narrows the list as you type, "
        "case-insensitively, with no button to press."
    ),
    "AC-2": (
        "Search and the status filter combine, and the heading count agrees "
        "with what is listed."
    ),
    "AC-3": (
        "Search matches the requester as well as the title — typing part of a "
        "name or address finds that person's tickets."
    ),
    "AC-4": (
        "A search matching nothing shows the same 'No tickets match this "
        "filter.' line, and clearing the box restores the status filter's list."
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

    rec.caption("A search box sits above the queue.", ac="AC-1")
    rec.spotlight(SEARCH)
    rec.hold()
    rec.shot("01-search-box", ac="AC-1")
    rec.spotlight()

    rec.caption("Typing invoice in lower case narrows the list.", ac="AC-1")
    rec.type_into(SEARCH, "invoice")
    # The acceptance criterion, asserted: a search that matched nothing here
    # would leave no ticket in the list and fail the take.
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("02-invoice", ac="AC-1")

    rec.caption("Every row carries its requester, and the search reads it.", ac="AC-3")
    clear_search(rec)
    rec.type_into(SEARCH, "mira")
    # The criterion, asserted twice over: TQ-103's *title* holds no such word,
    # so the row can only be here because the requester matched — and the
    # requester has to be on screen for a viewer to see why. Issue #132 was
    # exactly this beat recording an empty queue and nobody's take failing.
    rec.wait_for(".ticket[data-id='TQ-103'] .ticket-requester")
    rec.hold()
    rec.shot("03-requester", ac="AC-3")

    rec.caption("Part of an address finds that person's tickets.", ac="AC-3")
    clear_search(rec)
    rec.type_into(SEARCH, "petrova@north")
    rec.wait_for(".ticket[data-id='TQ-105'] .ticket-requester")
    rec.hold()
    rec.shot("04-address", ac="AC-3")

    # The scene change gets its own line, so the criterion's caption is never
    # up over a screen it does not yet describe.
    rec.caption("Clearing the box, choosing Open.")
    clear_search(rec)
    rec.click("button[data-status='open']")
    rec.wait_for(".ticket")

    rec.caption("With Open chosen, search narrows within the open tickets.", ac="AC-2")
    rec.type_into(SEARCH, "re")
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("05-open-and-search", ac="AC-2")

    rec.caption("The heading counts what is listed.", ac="AC-2")
    rec.spotlight("#queue-heading")
    rec.hold()
    rec.shot("06-heading", ac="AC-2")
    rec.spotlight()

    rec.caption("A search that matches nothing says so.", ac="AC-4")
    clear_search(rec)
    rec.type_into(SEARCH, "refund")
    rec.wait_for(".queue-empty")
    rec.hold()
    rec.shot("07-no-match", ac="AC-4")

    rec.caption("Clearing the box restores what the status filter shows.", ac="AC-4")
    clear_search(rec)
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("08-restored", ac="AC-4")
    rec.caption("")
