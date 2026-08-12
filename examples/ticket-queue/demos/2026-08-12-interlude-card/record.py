# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""A card over the app, and not a terminal — issue #291.

Run the app first:

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-08-12-interlude-card/record.py

**Why this demo exists.** The full-screen card `interlude()` and `criterion()`
raise was painted the same near-black on a web take as on a terminal one. The
web recorder composites the page into a dark window frame with a title bar and
traffic-light dots, so that card filled that frame with a flat dark field and a
line of centred text — and a human watching
`demos/2026-08-11-criterion-card/` read the result as *a terminal window*, not
as a card over a web app. Nothing in any artifact was wrong; the take was a
`Recorder` take from first beat to last, and every frame, beat and snapshot said
so.

What went wrong was contrast, not geometry: the card had always stopped at the
app rect, with the recorder's pad and title bar drawn around it. It was 1.3 luma
levels from that frame, so the boundary was there and nobody could see it. The
card is now black, its text near-white, and it carries an 18 px gutter in the
window's own colour so it visibly stops short of the window's inside edge.

Which makes this demoable by the repo's own test: the acceptance criterion is
that **a viewer can tell a card from a terminal**, and it is verified by
watching. What a reviewer should look at, in order:

1. the queue, so the app is on screen and recognisable;
2. the criterion card — black, over the app, with that same dark window frame
   still visible as a band all the way around it;
3. the app again, with the search doing the thing the clause asked for;
4. a plain `interlude()` card, which is the same element and the same palette.

Beats 2 and 4 are the picture the issue is about. Compare them against
`demos/2026-08-11-criterion-card/` recorded before the fix, where the same
element filled the same frame in `#1c1a17` and the frame vanished into it.

Deliberately **not** what this shows: whether the clause is legible, whether
the wording is right, or anything about a terminal take. A terminal segment
still opens on the dark card `eca42c5` tuned for it (#110), which no web
storyboard can show; `tests/smoke --polish-only` grades that one from pixels.
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

# Ticket #129's AC-1, verbatim — the same string `demos/2026-07-28-queue-search`
# and `demos/2026-08-11-criterion-card` declare. `criterion()` reads the card's
# sentence out of this map, so nothing here retypes a clause.
CRITERIA = {
    "AC-1": (
        "A search box above the queue narrows the list as you type, "
        "case-insensitively, with no button to press."
    ),
}

with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")

    rec.caption("Seven tickets, in a browser window.")
    rec.hold()
    rec.shot("01-queue", ac="AC-1")
    rec.caption("")

    # The picture #291 is about. Taken down explicitly on the line after the
    # still: a card left up occludes everything after it and almost nothing
    # notices (SKILL.md, "What this does not do").
    rec.criterion("AC-1")
    rec.shot("02-criterion-card", ac="AC-1")
    rec.interlude("")

    # The app is still there, and doing what the clause asked for. `wait_for`
    # is the assertion: a search that matched nothing would leave no ticket
    # listed and fail the take rather than record a convincing empty queue.
    rec.caption("The card is gone, and the queue is back.")
    rec.type_into(SEARCH, "invoice")
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("03-invoice", ac="AC-1")
    rec.caption("")

    # The same element, raised by the other verb that raises it, so the card a
    # storyboard uses to bridge a jump is in the recording too.
    rec.interlude("Same card, no clause — this is what bridges a time skip.")
    rec.shot("04-interlude-card")
    rec.interlude("")

    rec.caption("Queue, card, queue again — the card sits over the app.")
    rec.hold()
    rec.caption("")
