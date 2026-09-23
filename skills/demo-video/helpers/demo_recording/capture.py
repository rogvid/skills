"""Screencast capture: every frame Chromium paints, stamped with wall-clock time.

Chromium sends a frame only when the page changes, so a static screen costs
nothing. Frames arrive while the recorder is inside a Playwright call; the
recorder's waits use `page.wait_for_timeout` for that reason, never `sleep`.

Chromium sends screencast frames at CSS-pixel size whatever the device scale
factor, so they are soft once scaled up to the video. They are only used
while something moves. Once the screen is still, `snapshot()` adds one
screenshot at the full device scale factor, and the hold that follows - what a
viewer actually reads, and what a spotlight zooms into - uses that.
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
        self._page = page
        self._painted = 0  # screencast frames so far
        self._snapped = -1  # ... when the last snapshot was taken
        self._running = False

    def _on_frame(self, event: dict) -> None:
        stamp = event.get("metadata", {}).get("timestamp") or time.time()
        name = f"{len(self.frames):06d}.jpg"
        (self.dir / name).write_bytes(base64.b64decode(event["data"]))
        self.frames.append((float(stamp), name))
        self.last_arrival = time.time()
        self._painted += 1
        try:
            self._cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:  # noqa: BLE001 - the page is closing
            pass

    def snapshot(self, stamp: float) -> None:
        """A full-resolution frame of the still screen, stamped `stamp`.
        Skipped when nothing was painted since the last one."""
        if self._painted == self._snapped:
            return
        # Playwright's screenshot, not raw CDP: a clipped CDP capture resets
        # the page's device scale factor, which changes how the app behaves.
        data = self._page.screenshot(type="jpeg", quality=95, caret="initial")
        name = f"{len(self.frames):06d}.jpg"
        (self.dir / name).write_bytes(data)
        self.frames.append((stamp, name))
        self._snapped = self._painted

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
