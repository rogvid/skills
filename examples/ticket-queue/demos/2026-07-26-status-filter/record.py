# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Filtering the support queue by status, on the page and on the command line.

Storyboard for issue #90. Run the app first:

    examples/ticket-queue/serve --port 8901
    uv run examples/ticket-queue/demos/2026-07-26-status-filter/record.py
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parents[1]
_DEFAULT_SKILL_DIR = HERE.parents[3] / "skills" / "demo-video"
SKILL_DIR = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or _DEFAULT_SKILL_DIR)
if not (SKILL_DIR / "helpers" / "demo_recording" / "__init__.py").exists():
    sys.exit(f"demo-video skill not found at {SKILL_DIR} — set DEMO_VIDEO_SKILL_DIR")
sys.path.insert(0, str(SKILL_DIR / "helpers"))
from demo_recording import Recorder, TerminalRecorder, stitch  # noqa: E402

BASE_URL = os.environ.get("TICKET_QUEUE_URL", "http://127.0.0.1:8901")

# --- part 1: the page -------------------------------------------------------

with Recorder(HERE, base_url=BASE_URL, segment="part1") as rec:
    rec.goto("/")
    rec.wait_for(".ticket")
    rec.caption("The support queue, every ticket the team holds.")
    rec.hold()
    rec.shot("01-queue")

    rec.caption("A status filter sits above the list.")
    rec.spotlight("#status-filter")
    rec.hold()
    rec.spotlight()

    rec.caption("Open lists only the open tickets.")
    rec.click("button[data-status='open']")
    rec.hold()
    rec.shot("02-open")

    rec.caption("The heading counts what the filter left.")
    rec.spotlight("#queue-heading")
    rec.hold()
    rec.spotlight()

    rec.caption("Waiting lists the rest.")
    rec.click("button[data-status='waiting']")
    rec.hold()
    rec.shot("03-waiting")

    # The caption says what the frame shows, not what the ticket asked for:
    # criterion 3 of #90 wanted "No tickets match this filter." here, and the
    # queue renders nothing at all. Claiming otherwise would put the demo's
    # word above the app's.
    rec.caption("Escalated matches nothing. The list is empty.")
    rec.click("button[data-status='escalated']")
    rec.hold()
    rec.shot("04-escalated")

    rec.caption("All brings the whole queue back.")
    rec.click("button[data-status='all']")
    rec.hold()
    rec.shot("05-all")
    rec.caption("")

# --- part 2: the command line ----------------------------------------------

# The PTY child inherits this process's directory, so the demo can type the
# commands the README documents rather than a path into the repo.
os.chdir(APP_DIR)

with TerminalRecorder(HERE, segment="part2") as rec:
    rec.interlude("The same filter, on the command line.")
    # Nothing else clears a card. A TerminalRecorder never navigates, so
    # without this the card covers the whole segment and the terminal records
    # underneath it, unseen — issue #91, which cost this demo its first take.
    rec.interlude("")

    rec.caption("The CLI reads the same queue.")
    rec.run("./tickets list")
    rec.wait_for_prompt()
    rec.hold()
    rec.shot("06-cli-list")

    rec.caption("--status open narrows it the same way.")
    rec.run("./tickets list --status open")
    rec.wait_for_prompt()
    rec.hold()
    rec.shot("07-cli-open")

    rec.caption("An unknown status is refused.")
    rec.run("./tickets list --status frozen")
    rec.wait_for_prompt()
    rec.hold()
    rec.shot("08-cli-unknown")
    rec.caption("")

stitch(HERE, ["part1", "part2"])
