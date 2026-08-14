# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Corpus take: a clause the storyboard claims and the demo never shows.

The planted defect this product exists to catch. AC-2 is declared, and it is
tagged on a beat that spotlights the search box — so `coverage.claimed` names a
beat for it and the coverage table reports nothing unclaimed. The take then
never types a character: the list is never seen to narrow, so there is no frame
in which AC-2 happens.

Note what would *not* catch this. The coverage table would not: AC-2 is
claimed. A reviewer reading `timeline.md` would not, for the same reason. Only
somebody looking at the pictures for the thing the clause describes finds that
the evidence never arrives — which is the reader the brief is written for.

The caption on the claiming beat names the control and asserts nothing about
what it does. That is deliberate: an overclaiming caption is a different defect
with a different expected outcome, and it is `caption-overclaims`.

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
        "The queue lists every ticket with its id, its title and the person "
        "who raised it."
    ),
    "AC-2": (
        "A search box above the queue narrows the list as you type, with no "
        "button to press."
    ),
}

with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")

    rec.caption("The queue, with every ticket on it.", ac="AC-1")
    rec.hold()
    rec.shot("01-queue", ac="AC-1")

    rec.caption("Each row carries its id, its title and its requester.", ac="AC-1")
    rec.spotlight(".ticket[data-id='TQ-101']")
    rec.wait_for(".ticket[data-id='TQ-101'] .ticket-requester")
    rec.hold()
    rec.shot("02-row", ac="AC-1")
    rec.spotlight()

    # The plant. AC-2 is claimed here and nowhere else, and nothing after this
    # line types into the box or waits for the list to change.
    rec.caption("The queue's controls sit above the list.", ac="AC-2")
    rec.spotlight(SEARCH)
    rec.hold()
    rec.shot("03-controls", ac="AC-2")
    rec.spotlight()
    rec.caption("")
