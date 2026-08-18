# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Corpus take: the real blind spot — a declared clause text that is itself
the misreading (#276).

The ticket this take pretends to demo asks, in its own words:

    Search matches the requester — typing part of a name or an address
    finds that person's tickets.

That sentence lives only here and in `expected.json`. Nothing fetches it,
which is the point: the storyboard author misread it, and AC-2 below is the
misreading — it says **title** where the ticket says **requester**. One
substitution, made before any frame existed.

Everything downstream is faithful to the paraphrase. The take types
`dashboard`, a word from TQ-106's title, the queue narrows to that ticket, and
a spotlight rings the matched title. The screen genuinely does what AC-2 says.
No caption overclaims, nothing claimed is missing from the frames — as a demo
of the declared clause, this take is clean.

That is why the reader is expected to miss it. The reader is handed the clause
text and the frames, and both are downstream of the paraphrase; the ticket's
own words reach no input it has. Agreement is the correct output of a blind
read here. Contrast `caption-overclaims`, where the true clause text is
declared and the reader can — and twice did — disbelieve the caption against
it. What would catch this take is a quotation check of the declared clause
against the ticket's own words, which is the other half of #276.

AC-1 is genuinely shown, so this is a realistic storyboard with one bad
clause rather than a trap end to end.

**If a run scores AC-2 as caught, that is a finding and not a fixture bug.**
Do not edit the expectation to match the result; report it.

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
    # The misreading. The ticket says requester; this says title.
    "AC-2": (
        "Search matches the ticket title — typing a word from the title "
        "narrows the queue to that ticket."
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

    rec.caption("Typing export narrows the queue as you type.", ac="AC-1")
    rec.type_into(SEARCH, "export")
    rec.wait_for(".ticket[data-id='TQ-102']")
    rec.hold()
    rec.shot("01-export", ac="AC-1")

    # Faithful to the declared clause, word for word: a title word, typed,
    # narrows the queue to that ticket. The defect is not in these beats.
    rec.caption("A word from the title finds that ticket.", ac="AC-2")
    clear_search(rec)
    rec.type_into(SEARCH, "dashboard")
    rec.wait_for(".ticket[data-id='TQ-106']")
    rec.hold()
    rec.shot("02-dashboard", ac="AC-2")

    rec.caption("The match is in the title.", ac="AC-2")
    rec.spotlight(".ticket[data-id='TQ-106'] .ticket-title")
    rec.hold()
    rec.shot("03-title", ac="AC-2")
    rec.spotlight()
    rec.caption("")
