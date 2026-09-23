#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Showcase, part 2: the same queue from its command-line tool."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or HERE / "../../skills/demo-video")
sys.path.insert(0, str(SKILL / "helpers"))
from demo_recording import TerminalRecorder  # noqa: E402

with TerminalRecorder(HERE / "terminal", cwd=HERE / "../ticket-queue", title="tickets") as rec:
    rec.caption("The same queue, from the terminal.")
    rec.run("./tickets list --status waiting")
    rec.hold(2.5)

    rec.caption("And any ticket in full.")
    rec.run("./tickets show TQ-104")
    rec.hold(2.5)
    rec.caption("")
