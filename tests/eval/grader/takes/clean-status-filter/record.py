# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Corpus take: a demo that genuinely shows both of its clauses.

One of two false-alarm controls. Nothing is planted here — the status filter
really does narrow the queue, and All really does restore it — so every clause
the reader flags is a false alarm, and that is the whole reason this take is in
the corpus. See `tests/eval/grader/README.md`.

Recorded by `tests/eval-grader record`, which starts `examples/ticket-queue/
serve` on an ephemeral port and passes it in `TICKET_QUEUE_URL`.
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

CRITERIA = {
    "AC-1": (
        "Choosing a status above the queue narrows the list to the tickets "
        "with that status."
    ),
    "AC-2": (
        "Choosing All restores the whole queue, and the heading above it "
        "names the queue being listed."
    ),
}

with Recorder(HERE, base_url=BASE_URL, criteria=CRITERIA) as rec:
    rec.goto("/")
    rec.wait_for(".ticket")

    rec.caption("Choosing Open leaves only the open tickets.", ac="AC-1")
    rec.click("button[data-status='open']")
    # The criterion, asserted: a filter that emptied the queue would fail the
    # take here rather than record a still of the bug.
    rec.wait_for(".ticket[data-id='TQ-101']")
    rec.hold()
    rec.shot("01-open", ac="AC-1")

    rec.caption("Choosing Waiting leaves only the waiting ones.", ac="AC-1")
    rec.click("button[data-status='waiting']")
    rec.wait_for(".ticket[data-id='TQ-103']")
    rec.hold()
    rec.shot("02-waiting", ac="AC-1")

    rec.caption("All brings the whole queue back.", ac="AC-2")
    rec.click("button[data-status='all']")
    rec.wait_for(".ticket[data-id='TQ-101']")
    rec.spotlight("#queue-heading")
    rec.hold()
    rec.shot("03-all", ac="AC-2")
    rec.spotlight()
    rec.caption("")
