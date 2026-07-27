# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""A filter that matches nothing explains itself instead of going blank.

Storyboard for issue #112, acceptance criterion 3 of ticket #90. Run the app
first:

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-07-27-empty-state/record.py

`wait_for(".queue-empty")` after the click is the assertion, not decoration:
with the feature absent the queue renders an empty string, the selector never
appears, and the take fails and dumps `failure/` rather than recording a
convincing video of nothing happening.
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

with Recorder(HERE, base_url=BASE_URL) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")
    rec.caption("The support queue, filtered by status.")
    rec.hold()
    rec.shot("01-queue")

    rec.caption("No ticket in the queue is escalated today.")
    rec.spotlight("#status-filter")
    rec.hold()
    rec.spotlight()

    rec.caption("Choosing Escalated used to leave blank space.")
    rec.click("button[data-status='escalated']")
    # The acceptance criterion, asserted. A timeout here fails the take.
    rec.wait_for(".queue-empty")
    rec.hold()

    rec.caption("Now the queue says why it is empty.")
    rec.spotlight(".queue-empty")
    rec.hold()
    rec.shot("02-empty")
    rec.spotlight()

    rec.caption("The heading agrees: nothing matched.")
    rec.spotlight("#queue-heading")
    rec.hold()
    rec.spotlight()

    rec.caption("All brings the whole queue back.")
    rec.click("button[data-status='all']")
    rec.wait_for(".ticket")
    rec.hold()
    rec.shot("03-all")
    rec.caption("")
