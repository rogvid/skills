"""The edit list that maps the take's wall clock onto the video's clock.

A take runs as fast as the app allows. The pacing a viewer needs - holds,
cursor glides, title cards - is inserted afterwards as frozen frames, and
long waits on the app are squeezed into a short fast-forward. So the video's
timeline is a list of pieces over the take's wall-clock time:

    ("real",   a, b, out)   wall-clock a..b plays over `out` seconds
    ("insert", t, out)      the frame at wall-clock t is held for `out` seconds

Overlays (captions, cursor, spotlights) are recorded directly in video time
via `now()`, so only screencast frames ever need the reverse mapping.
"""

from __future__ import annotations

import bisect
import time

# App waits up to this long play at normal speed; longer ones are squeezed.
FF_REAL_MAX_S = 1.5
# A squeezed wait lasts this long on screen, growing slowly with the wait.
FF_OUT_MIN_S = 1.5
FF_OUT_MAX_S = 3.0


def ff_duration(real_s: float) -> float:
    """How long a wait on the app lasts in the video."""
    if real_s <= FF_REAL_MAX_S:
        return real_s
    return min(FF_OUT_MAX_S, max(FF_OUT_MIN_S, 1.2 + 0.05 * real_s))


class Clock:
    def __init__(self) -> None:
        self.t0 = time.time()
        self.pieces: list[tuple] = []
        self._mark = self.t0  # wall-clock end of the last closed piece
        self._out = 0.0  # video time at `_mark`

    def _close_real(self, until: float) -> None:
        """Close the normal-speed stretch up to `until`."""
        if until > self._mark:
            self.pieces.append(("real", self._mark, until, until - self._mark))
            self._out += until - self._mark
            self._mark = until

    def now(self) -> float:
        """The current moment, in video seconds."""
        return self._out + max(0.0, time.time() - self._mark)

    def insert(self, seconds: float) -> None:
        """Hold the current frame for `seconds` of video."""
        if seconds <= 0:
            return
        t = time.time()
        self._close_real(t)
        self.pieces.append(("insert", t, seconds))
        self._out += seconds

    def retime(self, since: float, out: float) -> tuple[float, float]:
        """Play wall-clock `since`..now over `out` seconds. Returns the
        stretch's (start, end) in video time."""
        t = time.time()
        since = max(since, self._mark)
        self._close_real(since)
        start = self._out
        if t > since:
            self.pieces.append(("real", since, t, out))
            self._out += out
            self._mark = t
        return start, self._out

    def finish(self) -> float:
        self._close_real(time.time())
        return self._out


class SourceMap:
    """Video time -> wall-clock time, for picking the screencast frame."""

    def __init__(self, pieces: list) -> None:
        self.starts: list[float] = []
        self.pieces = pieces
        out = 0.0
        for p in pieces:
            self.starts.append(out)
            out += p[-1]
        self.total = out

    def __call__(self, tau: float) -> float:
        if not self.pieces:
            return 0.0
        i = max(0, bisect.bisect_right(self.starts, tau) - 1)
        p = self.pieces[i]
        into = tau - self.starts[i]
        if p[0] == "insert":
            return p[1]
        _, a, b, out = p
        if out <= 0:
            return b
        return a + (b - a) * min(1.0, into / out)
