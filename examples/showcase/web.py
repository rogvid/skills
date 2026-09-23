#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Showcase, part 1: the ticket-queue web app."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or HERE / "../../skills/demo-video")
sys.path.insert(0, str(SKILL / "helpers"))
from demo_recording import Recorder  # noqa: E402

BASE = "http://127.0.0.1:8901"

with Recorder(HERE / "web", base_url=BASE, title="Ticket queue") as rec:
    rec.interlude("Ticket queue: the support team's inbox")
    rec.goto("/")
    rec.caption("Every ticket waiting on the support team, in one queue.")
    rec.hold()

    rec.caption("Type part of a title, and the queue narrows as you go.")
    rec.type_into("#queue-search", "invoice")
    rec.spotlight(".ticket")
    rec.hold()
    rec.spotlight()

    rec.caption("Open a ticket to read the whole story.")
    rec.click(".ticket")
    rec.spotlight("#detail")
    rec.hold()
    rec.shot("poster")
    rec.spotlight()

    rec.caption("Hand it to a team in two clicks.")
    rec.click("#open-assign")
    with rec.act("pick a team"):
        rec.page.select_option("#assignee", "Billing")
    rec.click("#assign-confirm")
    rec.spotlight(".assignee")
    rec.hold()
    rec.spotlight()

    rec.caption("Clear the search, and the whole queue is back.")
    rec.click("#clear-search")
    rec.hold()

    rec.caption("A slow server? The wait plays as a quick fast-forward.")
    rec.page.route(
        "**/api/tickets", lambda route: route.continue_(url=f"{BASE}/api/tickets?delay=8")
    )
    with rec.act("reload against a slow server"):
        rec.page.reload(wait_until="commit")
        rec.page.wait_for_selector(".ticket", timeout=30_000)
    rec.hold()
    rec.caption("")
