"""Screencast capture: every frame Chromium paints, stamped with wall-clock time.

Chromium sends a frame only when the page changes, so a static screen costs
nothing. Frames arrive while the recorder is inside a Playwright call; the
recorder's waits use `page.wait_for_timeout` for that reason, never `sleep`.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path


class Screencast:
    def __init__(self, context, page, out_dir: Path, width: int, height: int) -> None:
        self.dir = out_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.frames: list[tuple[float, str]] = []
        self.last_arrival = 0.0  # host time of the latest frame, for settling
        self._cdp = context.new_cdp_session(page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        self._size = (width, height)
        self._running = False

    def _on_frame(self, event: dict) -> None:
        stamp = event.get("metadata", {}).get("timestamp") or time.time()
        name = f"{len(self.frames):06d}.jpg"
        (self.dir / name).write_bytes(base64.b64decode(event["data"]))
        self.frames.append((float(stamp), name))
        self.last_arrival = time.time()
        try:
            self._cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:  # noqa: BLE001 - the page is closing
            pass

    def start(self) -> None:
        width, height = self._size
        self._cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 92, "maxWidth": width, "maxHeight": height},
        )
        self._running = True

    def stop(self) -> None:
        if self._running:
            self._running = False
            try:
                self._cdp.send("Page.stopScreencast")
            except Exception:  # noqa: BLE001 - the browser is already gone
                pass
