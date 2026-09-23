#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Demo: searching the support queue.

User story: as a support agent, I type part of a title or a requester's
name and the queue narrows as I type, so I find a ticket without scrolling.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or HERE / "../../../skills/demo-video")
sys.path.insert(0, str(SKILL / "helpers"))
from demo_recording import Recorder  # noqa: E402

with Recorder(HERE, base_url="http://127.0.0.1:8901", title="Ticket queue") as rec:
    rec.goto("/")
    rec.caption("The support queue: every ticket waiting on the team.")
    rec.hold()

    rec.caption("Type part of a title and the list narrows as you go.")
    rec.type_into("#queue-search", "invoice")
    rec.spotlight(".ticket")
    rec.hold()
    rec.shot("01-by-title")
    rec.spotlight()

    rec.caption("A requester's name works too.")
    rec.clear("#queue-search")
    rec.type_into("#queue-search", "mira")
    rec.spotlight(".ticket-requester")
    rec.hold()
    rec.shot("02-by-requester")
    rec.spotlight()

    rec.caption("Search combines with the status filter.")
    rec.click("role=button[name='Waiting']")
    rec.hold()

    rec.caption("Clear the box and the whole queue is back.")
    rec.clear("#queue-search")
    rec.click("role=button[name='All']")
    rec.hold()
    rec.caption("")
