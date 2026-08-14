# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Corpus take: the negative control — a caption asserting what the screen
does not do.

This is the defect the grader is **expected to miss**, and it is in the corpus
for that reason. When it was written, `demo-grade` named this exact case in its
own docstring as what it cannot catch: the storyboard author's caption is burned
into the pixels, so the blind reader and the author read the same sentence.

**That limit has since been retracted and `demo-grade` no longer names this
case.** The reader is not asked to compare the screen with the caption; it is
handed the ticket's clause text, and two independent runs disbelieved the
caption on this very take (`tests/eval/grader/readings/`). The real blind spot
is one level up — a declared clause text that is itself the misreading — and
this take is not an instance of it. The expectation below is deliberately left
as written anyway, so the score keeps saying out loud that the corpus's negative
control does not do its job; rebuilding it to plant a wrong paraphrase is
[#276](https://github.com/rogvid/skills/issues/276)'s work.

Here the overclaim is AC-3, the requester clause. The take types `webhook`,
which is a word from TQ-104's **title** and appears in no requester in
`data/tickets.json` — so nothing on screen demonstrates requester matching.
Everything else agrees with the caption: the queue really narrows to one row,
and that row really does carry a requester. A reader who takes the caption at
its word answers `seen`.

The app itself is not broken — `examples/ticket-queue` does match requesters.
The storyboard is what misreads the clause, which is the failure
`helpers/demo_recording/coverage.py` calls the tautology: a demo derived from
what the author believed rather than from the ticket.

AC-1 in the same take is genuinely shown, so this is a realistic storyboard
with one bad clause rather than a trap end to end.

**If a run scores this clause as caught, that is a finding and not a fixture
bug.** Do not edit the expectation to match the result; report it.

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
    "AC-3": (
        "Search matches the requester as well as the title — typing part of a "
        "name or an address finds that person's tickets."
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

    rec.caption("Typing invoice narrows the queue as you type.", ac="AC-1")
    rec.type_into(SEARCH, "invoice")
    rec.wait_for(".ticket[data-id='TQ-101']")
    rec.hold()
    rec.shot("01-invoice", ac="AC-1")

    # The overclaim. The caption says requester; `webhook` is TQ-104's title.
    # The wait_for is honest about what is actually being asserted — the row is
    # here, and its requester is on screen — which is exactly the trap: every
    # assertion in this storyboard passes.
    rec.caption("Part of a requester's name finds that person's tickets.", ac="AC-3")
    clear_search(rec)
    rec.type_into(SEARCH, "webhook")
    rec.wait_for(".ticket[data-id='TQ-104'] .ticket-requester")
    rec.hold()
    rec.shot("02-requester", ac="AC-3")

    rec.caption("Every row the search leaves shows who raised it.", ac="AC-3")
    rec.spotlight(".ticket[data-id='TQ-104'] .ticket-requester")
    rec.hold()
    rec.shot("03-who", ac="AC-3")
    rec.spotlight()
    rec.caption("")
