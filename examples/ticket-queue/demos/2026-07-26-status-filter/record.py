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

    # This caption used to read "the list is empty", because it did: criterion
    # 3 of #90 was unimplemented and the queue rendered nothing at all. #112
    # implemented it, so the old line now describes a frame that no longer
    # exists — which is exactly the kind of stale caption that makes a demo
    # lie. Re-recorded with the caption the app now earns.
    rec.caption("Escalated matches nothing, and the queue says so.")
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

# The card is the recorder's, not a beat: `interlude=` raises it from an init
# script before capture starts, and clears it when its hold is up. Written as
# the storyboard's first statement instead — `rec.interlude(…)` inside the
# `with` — it cannot paint until the terminal already has, and the segment
# opens on ~300 ms of bare prompt (issues #110, #206, three human sightings).
# It also settles #91's half of the same seam, which cost this demo its first
# take: a TerminalRecorder never navigates, so a card no one takes down covers
# the whole segment, and a card the recorder raises is one it clears.
with TerminalRecorder(
    HERE, segment="part2", interlude="The same filter, on the command line."
) as rec:
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
    # The refusal *is* the demonstration, so the exit code is declared rather
    # than tolerated (#405). Without this the take cannot rehearse:
    # `demo-rehearse` pins strict=True, and strict read every non-zero exit as
    # a defect — so the one storyboard showing that bad input is rejected was
    # the one storyboard that could not pass the gate.
    rec.run("./tickets list --status frozen", expect_exit=2)
    rec.wait_for_prompt()
    rec.hold()
    rec.shot("08-cli-unknown")
    rec.caption("")

stitch(HERE, ["part1", "part2"])
