# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Clearing the queue search in one click, against the two criteria of #336.

Run the app first:

    examples/ticket-queue/serve --port 8934
    uv run examples/ticket-queue/demos/2026-08-18-clear-search/record.py

The storyboard is written from ticket #336 and declares its two acceptance
criteria on the recorder, so `timeline.md` carries a coverage table naming the
beat and the still that claims each one. It names the ticket too —
`ticket=TICKET` below — written down, never fetched: re-running this file has
to produce the same manifest in six months, whatever has happened to the issue
since.

The waits are assertions, not decoration. The `state="hidden"` wait on the
control fails the take if the × is drawn beside an empty box; the visible wait
after typing fails it if the control never appears. After the click, the take
demands the box empty, the control gone again, the heading say (4), and all
four open tickets listed — TQ-106 in particular, which the search had filtered
out, so its return can only mean the list was restored. The demo runs under
the Open filter on purpose: clearing into the seven-ticket All view would not
show that the *status filter alone* decides what comes back. A beat that only
holds cannot fail.
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

BASE_URL = os.environ.get("TICKET_QUEUE_URL", "http://127.0.0.1:8934")
SEARCH = "#queue-search"
CLEAR = "#clear-search"
# The ticket the two clauses below are quoted from. Written down, never
# fetched — see the docstring.
TICKET = "rogvid/skills#336"

CRITERIA = {
    "AC-1": (
        'While the search box holds text, a clear control ("×") is visible '
        "beside it. While the box is empty, the control is absent."
    ),
    "AC-2": (
        "Activating the clear control empties the box and restores the list "
        "to what the active status filter alone would show, with the heading "
        "count agreeing."
    ),
}


with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA, ticket=TICKET) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")

    rec.caption(
        "The search box is empty, and no clear control sits beside it.", ac="AC-1"
    )
    rec.spotlight(".queue-search")
    # The criterion's second sentence, asserted: a × drawn beside the empty
    # box would leave the control visible here and fail the take.
    rec.page.wait_for_selector(CLEAR, state="hidden")
    rec.hold()
    rec.shot("01-empty-box", ac="AC-1")
    rec.spotlight()

    # The scene change gets its own line, so a criterion's caption is never
    # up over a screen it does not yet describe.
    rec.caption("Choosing Open, so a status filter is active.")
    rec.click("button[data-status='open']")
    rec.wait_for(".ticket")

    rec.caption(
        "Typing a term narrows the list, and a × appears beside the box.", ac="AC-1"
    )
    rec.type_into(SEARCH, "invoice")
    rec.wait_for(".ticket")
    # The criterion's first sentence, asserted: the box holds text, so the
    # control has to be visible.
    rec.wait_for(CLEAR)
    rec.spotlight(CLEAR)
    rec.hold()
    rec.shot("02-control-appears", ac="AC-1")
    rec.spotlight()

    rec.caption("One click on the × empties the box.", ac="AC-2")
    rec.click(CLEAR)
    # The criterion, asserted piece by piece: the box is empty, the control
    # is gone with it, and the list is the Open filter's own again — TQ-106
    # was filtered out by the search, so only a restored list holds it.
    rec.page.wait_for_function("document.querySelector('#queue-search').value === ''")
    rec.page.wait_for_selector(CLEAR, state="hidden")
    rec.wait_for(".ticket[data-id='TQ-101']")
    rec.wait_for(".ticket[data-id='TQ-102']")
    rec.wait_for(".ticket[data-id='TQ-104']")
    rec.wait_for(".ticket[data-id='TQ-106']")
    # Park the cursor on the heading the next beat spotlights: left where the
    # × was, the dot reads as a residual control beside the empty box.
    rec.move_to("#queue-heading")
    rec.hold()
    rec.shot("03-restored", ac="AC-2")

    rec.caption("The heading counts what the Open filter lists.", ac="AC-2")
    # Four open tickets listed above, and the heading has to agree.
    rec.page.wait_for_selector("#queue-heading:has-text('(4)')")
    rec.spotlight("#queue-heading")
    rec.hold()
    rec.shot("04-heading", ac="AC-2")
    rec.spotlight()
    rec.caption("")
