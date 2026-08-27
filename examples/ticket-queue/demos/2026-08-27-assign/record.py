# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Assigning a ticket, against the four acceptance criteria of #413.

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-08-27-assign/record.py

The defect #413 describes is a dialog that announced "Ticket assigned." and
changed nothing. That is a hard thing to *demonstrate* — the fix's whole
content is a change that now happens where none did — so this storyboard is
built around the pair a viewer can actually compare:

    an unassigned ticket, opened, with no Assigned row
    the same ticket after confirming, with the row and the queue chip

and, at the end, the cancel path leaving a second ticket untouched. The
contrast is the demonstration; a take that only showed the happy path would be
satisfied by an app that assigned every ticket on load, which is exactly the
class of thing `test`'s injections break.

`ticket=TICKET` is written down, never fetched: re-running this file must not
depend on the tracker being reachable (#275). CI re-reads the ticket separately
and reports each clause as matched, not verbatim, or not checked (#276).
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
TICKET = "rogvid/skills#413"

# #413's four clauses, verbatim. All four are declared because this storyboard
# shows all four — a criterion nothing claims is a finding, and declaring one
# this take does not demonstrate would report it unclaimed.
CRITERIA = {
    "AC-1": (
        "Confirming the assign dialog sets the ticket's assignee to the team "
        "chosen in the dropdown."
    ),
    "AC-2": (
        "The detail pane shows an Assigned row for a ticket that has an "
        "assignee, and no such row for one that does not."
    ),
    "AC-3": (
        "The queue row shows the assignee, so the queue can be read without "
        "opening every ticket."
    ),
    "AC-4": "Cancelling the dialog leaves the ticket unassigned.",
}

with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA, ticket=TICKET) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")
    rec.caption("The support queue. Nothing here has an owner yet.")
    rec.shot("01-queue")

    # The "before" half of AC-2, claimed here rather than after the assignment:
    # the *absence* is the half a viewer cannot check later, once every frame
    # has an Assigned row in it.
    #
    # Claimed with `ac=` on the caption and the shot rather than with
    # `criterion()`. A criterion card is full-screen, so a shot taken while one
    # is up is a picture of the card — which is what the first cut of this
    # storyboard recorded, and why every still showed a sentence instead of
    # the app.
    rec.caption("Open a ticket — no Assigned row.", ac="AC-2")
    rec.click(".ticket[data-id='TQ-101']")
    rec.wait_for("#detail dl")
    rec.shot("02-before", ac="AC-2")

    rec.caption("Assign it to Platform.")
    rec.click("#open-assign")
    rec.wait_for("#assign-modal .modal-card")
    # `rec.app`, not `rec.page`: the recorder frames the app in an iframe
    # (#358), so the wrapper document `rec.page` refers to holds the chrome and
    # not the dialog. `rec.app` is the documented escape hatch to the app's own
    # frame — the same place every verb points.
    rec.app.select_option("#assignee", "Platform")
    rec.hold()
    rec.shot("03-dialog")

    rec.caption("Confirmed — the ticket now says who owns it.", ac="AC-1")
    rec.click("#assign-confirm")
    # Asserted, not held: a hold cannot fail, and the whole of AC-1 is that
    # this text is the team that was *chosen*. `:has-text()` is what makes the
    # beat able to go red — waiting for `.assignee` alone would pass against an
    # app that assigned the wrong team, or every team.
    rec.wait_for("#detail .assignee:has-text('Platform')")
    rec.shot("04-assigned", ac="AC-1")

    rec.caption("And the queue reads without opening anything.", ac="AC-3")
    rec.spotlight(".ticket[data-id='TQ-101'] .ticket-assignee")
    rec.wait_for(".ticket[data-id='TQ-101'] .ticket-assignee:has-text('Platform')")
    rec.shot("05-queue-chip", ac="AC-3")
    rec.spotlight()

    rec.caption("Cancelling leaves a ticket alone.", ac="AC-4")
    rec.click(".ticket[data-id='TQ-102']")
    rec.click("#open-assign")
    rec.wait_for("#assign-modal .modal-card")
    rec.app.select_option("#assignee", "Billing")
    rec.hold()
    rec.click("#assign-cancel")
    # The control on the three above. TQ-102 must have no Assigned row after a
    # cancel that selected a team — the one path the original defect and the
    # fix are indistinguishable on, so it gets a beat and a picture of its own.
    rec.wait_for(".ticket[data-id='TQ-102']")
    rec.shot("06-cancelled", ac="AC-4")
