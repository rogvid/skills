# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""The ticket's own sentence, then the app doing it — issue #280.

Storyboard for `criterion()`, against two of the four acceptance criteria of
ticket #129. Run the app first:

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-08-11-criterion-card/record.py

**Why this demo exists, and why it is separate from the queue-search one.**
`demos/2026-07-28-queue-search/` already declares all four of #129's criteria
and runs 57 s. Raising a card for each of them would add about fourteen seconds
and push it past the 30-60 s the skill targets — and SKILL.md's own answer to a
story that does not fit is two demos rather than faster captions. So this one
takes the two clauses whose evidence is most visible and shows the shape the
verb is for: the clause, then the screen that satisfies it.

Nothing here retypes a criterion. `CRITERIA` is the same map ticket #129's
storyboard declares; `rec.criterion("AC-1")` reads AC-1's text out of it and
puts *that string* on screen, so the card, the coverage table in `timeline.md`
and the quote a reviewer compares against the ticket cannot say three different
things.

The `wait_for()` calls are assertions, not decoration. `.ticket` after typing
`invoice` fails the take if the search left nothing listed, and the
`.ticket[data-id='TQ-103'] .ticket-requester` wait fails it if the requester
match — the whole of AC-3 — did not happen: TQ-103's *title* holds no such
word, so that row can only be listed because the requester matched. A beat that
only holds cannot fail, which is issue #132.
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

# Ticket #129, verbatim — the same two clauses `demos/2026-07-28-queue-search`
# is recorded against. Only the two this demo shows are declared: a criterion
# nothing claims is a finding, and declaring the other two here would report
# them unclaimed against a storyboard that never set out to show them.
CRITERIA = {
    "AC-1": (
        "A search box above the queue narrows the list as you type, "
        "case-insensitively, with no button to press."
    ),
    "AC-3": (
        "Search matches the requester as well as the title — typing part of a "
        "name or address finds that person's tickets."
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

    # Both of this storyboard's framing lines were rewritten in review round 1.
    # A fresh agent reading only the frames reported that "a reviewer should not
    # have to hold the ticket in their head" and "two clauses, each one screen
    # away from its evidence" were claims no frame ever evidenced — the first
    # about reviewers, who are not in the demo, and the second about "clauses",
    # a word nothing on screen uses. Both are now about what the pictures show.
    rec.caption("Seven tickets, and a search box above them.")
    rec.hold()
    rec.shot("01-queue", ac="AC-1")
    rec.caption("")

    # The clause, in the ticket's own words. Taken down explicitly on the next
    # line — a card left up occludes everything after it and almost nothing
    # notices (SKILL.md, "What this does not do").
    rec.criterion("AC-1")
    rec.interlude("")

    rec.caption("Typing invoice in lower case narrows the list.", ac="AC-1")
    rec.type_into(SEARCH, "invoice")
    # The criterion, asserted: a search that matched nothing would leave no
    # ticket listed and fail the take instead of recording a convincing video
    # of an empty queue.
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("02-invoice", ac="AC-1")

    rec.caption("No button was pressed, and the case never matched.", ac="AC-1")
    rec.spotlight(SEARCH)
    rec.hold()
    rec.spotlight()
    rec.caption("")

    rec.criterion("AC-3")
    rec.interlude("")

    rec.caption("Mira is a requester, not a word in any title.", ac="AC-3")
    clear_search(rec)
    rec.type_into(SEARCH, "mira")
    rec.wait_for(".ticket[data-id='TQ-103'] .ticket-requester")
    rec.hold()
    rec.shot("03-requester", ac="AC-3")

    rec.caption("Part of an address finds that person's tickets too.", ac="AC-3")
    clear_search(rec)
    rec.type_into(SEARCH, "petrova@north")
    rec.wait_for(".ticket[data-id='TQ-105'] .ticket-requester")
    rec.hold()
    rec.shot("04-address", ac="AC-3")

    rec.caption("Title, then requester — each after the sentence asking for it.")
    rec.hold()
    rec.caption("")
