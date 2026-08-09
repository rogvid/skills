"""Shared machinery for the demo-video skill's recorders.

`_DemoBase` owns everything that does not care what is being recorded:
the headless-Chromium video capture, the ElevenLabs narration engine, the
caption/interlude overlays, stills, segments, config resolution, and the
ffmpeg conversion. Medium-specific recorders subclass it:

    Recorder          (web.py)      -- drives a web app via Playwright
    TerminalRecorder  (terminal.py) -- runs a CLI/TUI in xterm.js over a PTY

Both record the same Chromium page, so the split is small: a subclass adds
its own context init scripts (`_init_context`), does post-page setup
(`_start`), tears down (`_stop`), and adds its medium's verbs. The frame
source is opaque to `_convert`, which is the seam a future desktop/GUI
backend would reuse.

Configuration: every constructor parameter falls back to a DEMO_VIDEO_*
environment variable so projects can set defaults in .env and keep
storyboards clean. Explicit parameters always win. See the skill's
SKILL.md for the full variable list.
"""

from __future__ import annotations

import datetime as _dt
import functools
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from playwright.sync_api import Page, sync_playwright

from .content import (
    content_report,
    media_duration,
    opening_gap,
    opening_report,
    opening_warning,
    overlay_warning,
    print_content_summary,
)
from .coverage import _ac_field, _checked_criteria, coverage_report
from .failure import (
    FAILURE_DIR,
    FAILURE_MARKER,
    FAILURE_MESSAGE_CHARS,
    FAILURE_SCHEMA,
    clear_failure_dir,
    clear_failure_marker,
    failed_beat,
    failure_summary,
    render_failure_marker,
    render_failure_md,
)
from .frames import _FRAME_EDGE_S, _extract, write_beat_frames
from .narration import mix_plan, tts_clip
from .target import guard_target
from .timeline import (
    ATTRIBUTION_SLACK_S,
    EVIDENCE_DIR,
    EVIDENCE_DIR_WARN_BYTES,
    EVIDENCE_LIMITS,
    EVIDENCE_MAX_SCREEN,
    EVIDENCE_SCHEMA,
    MAX_ISSUES,
    PUMP_INTERVAL_S,
    STRICT_KINDS,
    TIMELINE_SCHEMA,
    StrictTakeFailed,
    _cap_text,
    evidence_name,
    write_timeline,
)

# Caption bar: a narrator line burned into the recording (and stills), so
# the video explains itself to someone watching with no other context.
_CAPTION_JS = """
window.__demoCaption = (text) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    el.style.cssText = `
      position: fixed; left: 50%; bottom: __CAPBOTTOM__px; transform: translateX(-50%);
      max-width: 90%; padding: 12px 30px; border-radius: 12px;
      background: rgba(22,20,16,.72); backdrop-filter: blur(3px);
      color: #f7f4ee; text-align: center;
      font: 600 __CAPFONT__px/1.36 system-ui, sans-serif; letter-spacing: .01em;
      pointer-events: none; z-index: 2147483646; opacity: 0;
      transition: opacity .3s ease; box-shadow: 0 6px 24px rgba(0,0,0,.28);
    `;
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""

# Interlude: a full-screen title card for jumps over real-world time the
# recording skips (minutes of background work between two segments).
#
# The card's styling is a module constant because a *second* thing builds this
# same element: a segment that opens on a card raises it from an init script,
# before the recorder's own setup and before the page has painted at all
# (issue #110, and see terminal.py's `_OPENING_CARD_JS`). Both have to produce
# an element `__demoInterlude` will then recognise and fade out, which means
# one id and one stylesheet, in one place.
INTERLUDE_ID = "__demo_interlude"
INTERLUDE_CSS = (
    "position: fixed; inset: 0; display: flex; align-items: center;"
    " justify-content: center; background: #1c1a17; color: #f7f4ee;"
    " font: 500 30px/1.5 system-ui, sans-serif; text-align: center;"
    " padding: 0 12%; z-index: 2147483647; opacity: 0;"
    " transition: opacity .45s ease; pointer-events: none;"
)
_INTERLUDE_JS = """
window.__demoInterlude = (text) => {
  let el = document.getElementById('__ID__');
  if (!el) {
    el = document.createElement('div');
    el.id = '__ID__';
    el.style.cssText = '__CSS__';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""


# Lightweight bridge: a centered label over a soft scrim, with the scene
# still visible behind it. For short segment transitions where a full-screen
# interlude card would feel heavy.
BRIDGE_ID = "__demo_bridge"
_BRIDGE_JS = """
window.__demoBridge = (text) => {
  let el = document.getElementById('__ID__');
  if (!el) {
    el = document.createElement('div');
    el.id = '__ID__';
    el.style.cssText = `
      position: fixed; inset: 0; display: flex; align-items: center;
      justify-content: center; z-index: 2147483647; opacity: 0;
      transition: opacity .4s ease; pointer-events: none;
      background: radial-gradient(ellipse at center,
        rgba(18,15,28,.58) 0%, rgba(18,15,28,.16) 70%, rgba(18,15,28,0) 100%);
    `;
    const t = document.createElement('div');
    t.id = '__demo_bridge_t';
    t.style.cssText = `
      color: #fff; font: 600 34px/1.4 system-ui, sans-serif; text-align: center;
      max-width: 72%; text-shadow: 0 2px 22px rgba(0,0,0,.65);
    `;
    el.appendChild(t);
    document.body.appendChild(el);
  }
  document.getElementById('__demo_bridge_t').textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""

# The two overlays this module puts on the page, by element id.
#
# One tuple because three separate things now need the same answer: the scripts
# above create these elements, `interlude("")` takes **both** down whatever
# style raised them (issue #162), and `_note_overlays_up()` asks the page at the
# end of a take whether either is still showing (issue #163). Written here rather
# than duplicated at each site, because a fourth id that only two of the three
# knew about is exactly how the clear came to be style-dependent in the first
# place.
OVERLAY_IDS = (INTERLUDE_ID, BRIDGE_ID)

# Which of `OVERLAY_IDS` is still *visible*, not merely present in the tree.
#
# Visibility, because a cleared overlay is not removed — both scripts above
# toggle `opacity`, and `terminal.py`'s opening card leaves a fully faded
# element behind on every healthy terminal take. Asking "does the element
# exist" would warn on all of them.
#
# `getComputedStyle` rather than the inline style, so an in-flight fade reads
# as the number it is actually painting at. Both callers of the clear pause
# well past the 0.4-0.45 s transition before the take ends, so a cleared
# overlay reads 0 rather than an interpolated value.
_OVERLAY_PROBE_JS = """
(ids) => ids.filter((id) => {
  const el = document.getElementById(id);
  if (!el) return false;
  const style = getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  return parseFloat(style.opacity || '1') > 0.01;
})
"""


# -- determinism -------------------------------------------------------------
#
# Re-recording a storyboard should produce the same video, or "did the UI
# actually change?" is unanswerable and last month's committed still cannot be
# compared with today's. Three things *in the browser* make it not: the wall
# clock, locale/timezone formatting, and animation phase.
#
# They are not equally safe to pin, so they are not pinned together:
#
#   * **Timezone, locale and `prefers-reduced-motion` are always on.** They cost
#     an app nothing — an app that honours reduced motion was built to — and
#     they remove the difference between a recording made on a laptop in
#     Tórshavn and one made on a CI runner.
#
#   * **The frozen clock and the motion rule are opt-in** (`deterministic=True`,
#     `DEMO_VIDEO_DETERMINISTIC=1`). Both change what an app *does*, and mostly
#     they do it silently. Measured on five adversarial pages: a lodash-shaped
#     debounce never fires because `now - last` is always 0, an elapsed-time bar
#     sticks at 0%, a token gate renders "not yet valid", a "last 7 days" chart
#     draws no bars — four of the five produce a plausible wrong screen with no
#     exception, nothing on the console, and nothing in timeline.json. The fifth
#     wedges a `while (Date.now() - t0 < ms)` spin until the navigation times
#     out and no mp4 is written at all. A demo recorder whose default can put a
#     confidently wrong screen in front of a reviewer is worse than one that
#     records a fresh timestamp each take, so the default records the truth and
#     the storyboard asks for reproducibility when it wants it.
#
# What the freeze deliberately leaves alone: `performance.now()`, the document
# animation timeline, and `requestAnimationFrame`. Only the *wall* clock stops.
# Freezing monotonic time as well would stop the compositor, and a page that
# never paints is a page Chromium's screencast never records — it would lose
# wall time (issue #18) in exchange for determinism it does not need. It is also
# why an element that opts out of the motion rule below still animates: nothing
# here touches the clock its animation runs on.
DEFAULT_CLOCK = "2025-01-01T09:00:00Z"
DEFAULT_TIMEZONE = "UTC"
DEFAULT_LOCALE = "en-US"

# Freeze the wall clock at a fixed instant: `Date.now()` and `new Date()` stop
# moving, so a rendered timestamp, a "3 minutes ago", or a date-formatted cell
# reads the same in every take.
#
# Every line below closes a hole that was measured open, so none of it is
# defensive decoration:
#
#   * `Date.now` is *defined on the real constructor*, once, as a named
#     function — not synthesized by a proxy `get` trap. A trap mints a new
#     arrow function per read, so `Date.now !== Date.now`, its `.name` is "",
#     and `Object.getOwnPropertyDescriptor(Date, 'now').value` is the real
#     clock the trap never saw.
#   * `Date.prototype.constructor` is repointed at the proxy. Left alone it is
#     the *unproxied* Date, which makes `Date.prototype.constructor === Date`
#     false — a live type-detection idiom in deep-clone and serialization
#     helpers — and hands out an unfrozen clock via `new Date().constructor`.
#   * `Intl.DateTimeFormat.prototype.format()` with no argument formats "now"
#     from the *internal* clock, which no patch of the `Date` global reaches.
#     It is the highest-impact hole of the set: it is how apps render dates.
#   * `performance.timeOrigin` and `document.lastModified` are wall-clock
#     readings that survive everything above.
#   * A `Worker` gets its own global, so init scripts never run there. The
#     wrapper re-injects the freeze ahead of the real script via a blob
#     shim. Module workers cannot `importScripts` and are passed through
#     unfrozen (issue #29).
_FROZEN_CLOCK_JS = """
(() => {
  const FIXED = __EPOCH_MS__;

  // Shared by the page and by the worker shim below, hence a named function
  // whose source can be stringified rather than a closure.
  function __demoFreezeDate(scope, FIXED) {
    const Real = scope.Date;
    const now = function now() { return FIXED; };
    Real.now = now;
    // Only the zero-argument "what time is it" forms are answered from the
    // freeze; explicit arguments, Date.parse and Date.UTC pass straight
    // through. A Proxy rather than a subclass because `Date()` called as a
    // function must return a string, which a class cannot do.
    const Frozen = new Proxy(Real, {
      apply: () => new Real(FIXED).toString(),
      construct: (t, args, nt) =>
        Reflect.construct(t, args.length ? args : [FIXED], nt),
    });
    scope.Date = Frozen;
    Object.defineProperty(Real.prototype, 'constructor',
      {value: Frozen, writable: true, configurable: true});
    return Real;
  }

  const Real = __demoFreezeDate(window, FIXED);

  // Intl reads its own clock, not the global Date.
  const proto = Intl.DateTimeFormat.prototype;
  for (const name of ['format', 'formatToParts']) {
    const desc = Object.getOwnPropertyDescriptor(proto, name);
    if (!desc) continue;
    if (desc.get) {
      // V8 exposes `format` as a getter returning a bound formatter.
      Object.defineProperty(proto, name, {
        configurable: true,
        get() {
          const bound = desc.get.call(this);
          return function (value, ...rest) {
            return bound(value === undefined ? FIXED : value, ...rest);
          };
        },
      });
    } else if (typeof desc.value === 'function') {
      const real = desc.value;
      Object.defineProperty(proto, name, {
        configurable: true, writable: true,
        value: function (value, ...rest) {
          return real.call(this, value === undefined ? FIXED : value, ...rest);
        },
      });
    }
  }

  try {
    Object.defineProperty(performance, 'timeOrigin',
      {configurable: true, get: () => FIXED});
  } catch (e) { /* non-fatal: one reading of many */ }

  try {
    const d = new Real(FIXED);
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + '/'
      + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
      + ':' + pad(d.getSeconds());
    Object.defineProperty(document, 'lastModified',
      {configurable: true, get: () => stamp});
  } catch (e) { /* non-fatal */ }

  const RealWorker = window.Worker;
  if (typeof RealWorker === 'function') {
    const prelude = '(' + __demoFreezeDate.toString() + ')(self,' + FIXED + ');';
    window.Worker = class Worker extends RealWorker {
      constructor(url, options) {
        let target = url;
        try {
          if (!options || options.type !== 'module') {
            const absolute = new URL(url, location.href).href;
            const src = prelude + '\\nimportScripts('
              + JSON.stringify(absolute) + ');';
            target = URL.createObjectURL(
              new Blob([src], {type: 'text/javascript'}));
          }
        } catch (e) { target = url; }
        super(target, options);
      }
    };
  }
})();
"""

# Land every animation and transition on its finished state, so no frame of the
# recording depends on when the take happened to start.
#
# **1 ms, not 0s.** A transition with a combined duration of zero never starts,
# and a transition that never starts fires no `transitionend` — which stalls
# every accordion, modal, carousel and wizard that advances on that event, and
# does it in a way no amount of "move the frozen instant" advice helps with.
# One millisecond is over before the first frame is composited and still fires
# the whole event sequence.
#
# **Authored delays are left alone.** Forcing `animation-delay: 0s` made a
# snackbar declared `dismiss .4s ease 4s forwards` invisible from frame zero:
# the four seconds it is meant to be readable collapsed to nothing. A delay is
# measured from the animation's own start, not from the wall clock, so honouring
# it costs no reproducibility.
#
# **`animation-fill-mode` is left alone too.** Forcing `forwards` looks like it
# guards content that animates in from `opacity: 0`, but such content is always
# authored `forwards` already — and forcing it makes an `alternate` animation
# hold the far keyframe instead of returning, which is not where the browser
# would have left it. `iteration-count: 1` is forced, because an *infinite*
# animation has no finished state to land on and would otherwise resample every
# frame; a finite one ends where it would have ended.
#
# Two things are spared, and both matter:
#   * the recorder's own overlays (`#__demo…`, `#__term…`) — their motion is
#     triggered by the storyboard, so it is already as repeatable as the
#     storyboard is, and killing it would only make captions pop;
#   * anything carrying `data-demo-video-animate` — the documented opt-out for
#     an element that must keep painting. Chromium's screencast emits a frame
#     when the page paints (issue #18), so "no motion at all" is not a free
#     choice: a harness or a storyboard that needs the compositor awake marks
#     the element it keeps alive, and this rule cannot match it.
_FREEZE_MOTION_JS = """
(() => {
  const KEEP =
    ':not([data-demo-video-animate]):not([id^="__demo"]):not([id^="__term"])';
  // The pseudo-element arms are not padding: an animated ::after is the most
  // common spinner on the web.
  const CSS = ['', '::before', '::after'].map((p) => '*' + KEEP + p).join(',') + `{
      animation-duration: 1ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 1ms !important;
    }`;
  const attach = () => {
    const root = document.head || document.documentElement;
    if (!root || document.getElementById('__demo_motion')) return;
    const style = document.createElement('style');
    style.id = '__demo_motion';
    style.textContent = CSS;
    root.appendChild(style);
  };
  // attach() self-guards on purpose. An init script runs before the document
  // has a documentElement, and an appendChild that throws here would take the
  // listener below with it — measured, and it silently left a real navigation
  // with no rule at all while every other determinism control looked fine.
  attach();
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', attach);
})();
"""


def _clock_epoch_ms(value: str) -> int:
    """Epoch milliseconds for a frozen-clock setting, given as ISO 8601.

    A naive timestamp is read as UTC, so the frozen instant does not depend on
    the recording machine's own timezone.
    """
    try:
        parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(
            f"DEMO_VIDEO_CLOCK must be an ISO 8601 timestamp like "
            f"{DEFAULT_CLOCK!r}, got {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return int(parsed.timestamp() * 1000)


# -- the clock the video is on (issues #18, #215) -----------------------------
#
# Everything this package times is `time.monotonic()`. **The video is not on
# that clock**, and until this was measured nothing said so.
#
# Playwright records by acking Chromium's `Page.screencastFrame`, and the only
# clock a frame carries is that event's `metadata.timestamp` — which the
# protocol defines as `Network.TimeSinceEpoch`, i.e. the host's *wall* clock.
# Playwright's `FfmpegVideoRecorder` turns it straight into the frame's
# position in the webm (`frameNumber = (ts - firstFrameTs) * 25`). So the
# video's clock is CLOCK_REALTIME and the beat log's is CLOCK_MONOTONIC, and
# on a host whose wall clock *steps* the two part company by exactly the size
# of the step, at exactly the instant of it.
#
# Measured on the WSL2 box this was found on (Chromium 151.0.7922.34,
# Playwright 1.62.0), with the driver instrumented to log every frame:
#
#   ARRIVE 1146491075.755  ts=1785603308090.391   two consecutive screencast
#   ARRIVE 1146491159.407  ts=1785603307379.542   frames, 84 ms apart on the
#                                                 monotonic clock and 711 ms
#                                                 *backwards* on Chromium's
#
# **What that host does, re-measured on 2026-08-08** (issue #247; the numbers
# below are this file's own, taken with a 1 ms sampler over 300 s, and they
# replace the "-0.75 to -0.81 s every 32.2 s" this comment used to state as a
# constant). The wall clock is a **rectangular pulse train**: the offset jumps
# +10.03 to +10.10 s, holds flat for 40-230 ms, then falls 10.53-10.60 s, and
# lands 0.43-0.56 s *below* where it started. Period 5.509 s (5.500-5.517
# across 55 pulses), and between pulses the offset is flat to under 10 us.
# CLOCK_REALTIME_COARSE moves with it, so this is the kernel's timekeeper
# being written, not a vDSO read glitch.
#
# The permanent part of that is a **rate error, not a metronome**: against an
# NTP server over 90 s, CLOCK_MONOTONIC ran +10.01 % fast and CLOCK_REALTIME
# kept true time to -0.40 %, and `adjtimex` reports `tick = 11000` — the
# kernel's +10 % clamp. Something (Hyper-V/`systemd-timesyncd` on WSL2) is
# re-stepping the wall clock every 5.5 s to undo a monotonic clock that is
# running fast. **So the size and the period are properties of one sick host
# on one day, not of this recorder** — #215's 0.78 s every 32.2 s and this
# 0.50 s every 5.5 s are the same shape at different settings. Nothing here
# may be tuned to either.
#
# None of that is fixable here. The clock is the host's, the timestamp is the
# protocol's, and the recorder cannot re-stamp a frame it never sees. What it
# can do is **measure the same clock Chromium reads**, which needs no browser
# at all, and write the result next to the beats — so a consumer holding a
# beat at `t_start` can work out that the beat really sits at
# `t_start + (sum of the steps before it)` in the video, instead of
# discovering it as an unexplained 0.8 s.
#
# **That correction was verified against the encode, and it is exact.** Six
# takes, seven caption transitions each, the transitions read off `demo.mp4`'s
# pixels and compared with the beat log: uncorrected, the video ran up to
# 1.50 s ahead of the log by 13.5 s into the take; corrected by a *correctly
# sampled* wall-clock offset, every one of the 38 transitions landed within
# 101 ms, and within 40 ms at the caption-on edges (a caption fade takes two
# frames to cross, which is the other 60). #245 read the same field as noise;
# it was not the field, it was the sampler — see `INTERVAL_S` below.
class _CaptureClock:
    """CLOCK_REALTIME against CLOCK_MONOTONIC, for the life of one capture.

    A daemon thread, because the storyboard is blocking in Playwright calls
    for the whole take and a step has to be seen when it happens. It touches
    nothing but `time` and its own list.
    """

    # A step is instantaneous, so this bounds only *where* it gets reported,
    # and 20 ms is inside the 40 ms one frame of the 25 fps encode covers —
    # under the resolution anything reading the answer has.
    #
    # **The sleep between samples must not be timed on the clock being
    # sampled, and `threading.Event.wait` is** (issue #247, and this cost a
    # whole issue's worth of wrong diagnosis). On the interpreter `uv`
    # installs — CPython 3.13.11 from python-build-standalone, built against
    # a glibc without `sem_clockwait` — a lock acquire with a timeout falls
    # back to `sem_timedwait`, whose deadline is an absolute CLOCK_REALTIME
    # instant. So a sampler that happens to call `wait()` while the host's
    # +10 s pulse is up has set a deadline 10 s in the future, the pulse ends,
    # and it sleeps until the wall clock climbs back — which on this host is
    # the *next* pulse, 5.5 s later. Measured directly: 81 waits of 20 ms in
    # 25 s instead of ~1140, five of them 5.44-5.49 s long, every one entered
    # with the offset elevated.
    #
    # Once trapped the sampler is phase-locked into the pulses and every
    # sample it takes from then on is taken *inside* one, so it reports the
    # top of the transient it exists to reject. Eight idle 20 s runs of the
    # old loop against a 1 ms reference: `total` wrong by +10.59 to +10.60 s,
    # every time. Six recorded takes: `total` +9.09 s where the truth was
    # -2.00 s. `time.sleep` is `clock_nanosleep(CLOCK_MONOTONIC)` and is not
    # affected; `stop()` therefore costs up to one interval of latency, which
    # is the whole price.
    INTERVAL_S = 0.02
    # Under this a reading is the scheduling gap between the two `time` calls,
    # not a step. Measured idle: below 0.4 ms, four orders under a real one.
    MIN_STEP_S = 0.005
    # ...and how much has to have accumulated before the recorder says so out
    # loud. One frame of the encode: below that the video and the log still
    # agree about which frame a beat is on.
    WARN_S = 0.04
    # **The record only means anything if the sampler kept its interval.** A
    # step is found by differencing consecutive samples, so a sampler that was
    # away for a second cannot say when — or whether — the clock moved inside
    # it, and a consumer summing `steps` before a beat would be adding up
    # something nobody watched. So the widest gap between samples is measured
    # and reported, and over this bound the record refuses to answer instead
    # of guessing. 250 ms is 12x the nominal interval, and 22x under the
    # 5.5 s the trapped sampler above produced: the two populations are an
    # order of magnitude apart, not a comfortable margin.
    MAX_GAP_S = 0.25

    def __init__(self) -> None:
        self.steps: list[dict] = []
        # The widest interval between two consecutive samples, and how many
        # were taken. Both are the sampler grading its own coverage; see
        # MAX_GAP_S.
        self.max_gap = 0.0
        self.samples = 0
        self._t0 = 0.0
        self._started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, t0: float) -> None:
        self._t0 = t0
        self._started = True
        self._thread = threading.Thread(
            target=self._run, name="demo-video-clock", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        previous = time.time() - time.monotonic()
        last = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - last)
            last = now
            self.samples += 1
            offset = time.time() - time.monotonic()
            delta = offset - previous
            if abs(delta) >= self.MIN_STEP_S:
                self.steps.append(
                    {
                        "t": round(now - self._t0, 3),
                        "delta": round(delta, 4),
                    }
                )
            previous = offset
            # Not `self._stop.wait(...)` — see INTERVAL_S.
            time.sleep(self.INTERVAL_S)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @property
    def total(self) -> float:
        return sum(step["delta"] for step in self.steps)

    @property
    def measured(self) -> bool:
        """Did the sampler cover the take closely enough to be believed?"""
        return self._started and self.samples > 1 and self.max_gap <= self.MAX_GAP_S

    def note(self) -> str | None:
        """Why the record is refusing to answer, or None when it is not."""
        if self.measured:
            return None
        if not self._started or self.samples <= 1:
            return (
                "the wall-clock sampler never ran, so nothing here knows "
                "whether the video's clock moved under the beat log"
            )
        return (
            f"the wall-clock sampler was away for up to {self.max_gap:.2f}s "
            f"against its {self.INTERVAL_S:.2f}s interval, so it cannot say "
            f"when — or whether — the clock moved inside that gap. Reporting "
            f"nothing rather than a total nobody watched (issue #247)"
        )

    def report(self) -> dict:
        """The `capture_clock` envelope field. See timeline.py for the schema.

        `measured` first, and `steps`/`total` empty and null when it is false:
        a consumer that reaches straight for `total` gets `None` and fails
        loudly, rather than correcting a beat by a number the sampler did not
        see. Same shape as `content`, for the same reason.
        """
        ok = self.measured
        return {
            "measured": ok,
            "note": self.note(),
            "steps": list(self.steps) if ok else [],
            "total": round(self.total, 4) if ok else None,
            "sample_interval": self.INTERVAL_S,
            "min_step": self.MIN_STEP_S,
            "max_gap": round(self.max_gap, 4),
            "max_gap_limit": self.MAX_GAP_S,
        }

    def warning(self) -> str | None:
        """What to tell the author, or None when the two clocks agreed."""
        if not self.measured:
            return (
                f"demo-video: WARNING — this take's wall clock could not be "
                f"measured: {self.note()}. demo.mp4 is on the host's wall "
                f"clock and the beat log is on the monotonic one, so if they "
                f"parted company during the take, nothing in timeline.json "
                f"can tell you by how much. `capture_clock.measured` is false."
            )
        if abs(self.total) < self.WARN_S:
            return None
        when = ", ".join(
            f"{step['delta'] * 1000:+.0f} ms at {step['t']:.1f}s"
            for step in self.steps
        )
        return (
            f"demo-video: WARNING — this host's wall clock stepped while the "
            f"take was recording ({when}; {self.total * 1000:+.0f} ms in "
            f"total). Chromium stamps every screencast frame with that clock, "
            f"so demo.mp4 is {abs(self.total):.2f}s "
            f"{'shorter' if self.total < 0 else 'longer'} than the take's own "
            f"wall time and every beat after the step sits that far "
            f"{'ahead of' if self.total < 0 else 'behind'} the frame it names. "
            f"timeline.json records it as `capture_clock`; issues #18, #215, "
            f"#247."
        )


def _env(name: str, default: str | None = None) -> str | None:
    """A DEMO_VIDEO_-prefixed environment variable, or the default."""
    value = os.environ.get(f"DEMO_VIDEO_{name}", "").strip()
    return value or default


def _env_flag(name: str) -> bool | None:
    """Tri-state env flag: True/False when set, None when absent."""
    value = _env(name)
    if value is None:
        return None
    return value.lower() in ("1", "true", "yes", "on")


def _verb_target(fn: Callable) -> Callable[[tuple, dict], str | None]:
    """Build the default beat-target extractor for one storyboard verb.

    The target is the verb's **first parameter after `self`**, whatever it is
    named, and it is read the same way whether the caller passed it by
    position or by keyword: `click("#go")` and `click(selector="#go")` are one
    call written two ways, and a beat log that describes only one of them is
    describing something that did not happen.

    This used to be a fixed allowlist of keyword names — `selector`, `path`,
    `command`, `text`, `pattern`, `name` — so a verb whose first parameter was
    called anything else logged `selector: null` the moment somebody passed it
    by keyword (issue #177). Nothing noticed: the beat was recorded, the
    timeline was well-formed, and the only symptom was a null in a committed
    artifact. Reading the signature removes the list rather than lengthening
    it, so the next verb is right without anyone remembering this.

    A verb that wants something else — `key(*names)`, whose target is the
    whole chord — passes its own extractor to `_beat_verb`.
    """
    try:
        params = list(inspect.signature(fn).parameters.values())[1:]  # drop self
    except (TypeError, ValueError):  # pragma: no cover - callables without one
        params = []
    first = params[0] if params else None

    def target(args: tuple, kwargs: dict) -> str | None:
        # Positionally the first argument *is* the first parameter, so this
        # branch is what the allowlist version did and stays byte-identical.
        if args:
            return args[0] if isinstance(args[0], str) else None
        if first is None or first.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            return None
        value = kwargs.get(first.name)
        return value if isinstance(value, str) else None

    return target


def _beat_verb(
    verb: str,
    target: Callable[[tuple, dict], str | None] | None = None,
) -> Callable:
    """Decorate a storyboard verb so calling it records one beat.

    A decorator rather than a `with` block inside every verb: it keeps the
    recorders' method bodies untouched, which is the difference between a
    one-line diff per verb and re-indenting three files.

    `target` extracts the beat's `selector` from the call; left out, the verb's
    own signature supplies it (see `_verb_target`), so `click("#go")`,
    `run("ls")`, `goto("/app")` and `goto(path="/app")` all self-describe, and
    a verb called with nothing to name (`pause(2)`, `spotlight()`) yields null.
    """

    def decorate(fn: Callable) -> Callable:
        extract = _verb_target(fn) if target is None else target

        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with self._beat(verb, selector=extract(args, kwargs)):
                return fn(self, *args, **kwargs)

        # The verb name, on the method. `tests/unit` sweeps every verb on both
        # recorders and calls each one twice — once positionally, once by
        # keyword — to hold #177 shut for verbs nobody has written yet, and a
        # sweep that has to guess which methods are verbs would quietly stop
        # covering the one somebody adds next.
        wrapper._demo_verb = verb  # type: ignore[attr-defined]
        return wrapper

    return decorate


class _DemoBase:
    """Recording + narration substrate shared by every demo medium.

    A subclass supplies three hooks — `_init_context` (add context init
    scripts before the page exists), `_start` (post-page setup), `_stop`
    (teardown) — plus its own storyboard verbs. Exiting the context
    manager converts the recording to demo.mp4 (or <segment>.seg.mp4).

    Speech: when ELEVENLABS_API_KEY is set (or speech=True), every caption
    and interlude line is also narrated — synthesized via ElevenLabs, cached
    in .tts/, and mixed onto the mp4 at the moment the line appeared. Pacing
    self-adjusts: a new line waits for the previous one to finish speaking.

    Determinism: the timezone, the locale and `prefers-reduced-motion` are
    always pinned. `deterministic=True` additionally freezes the page's wall
    clock and lands animations on their finished state, so re-recording a
    storyboard reproduces it — at the cost of changing what a clock-reading app
    does, which is why it is opt-in. Either way it controls the *browser* only:
    the app's own randomness, its server data, and network timing are the
    storyboard author's to pin down. See the determinism section above.
    """

    # -- the medium seam ----------------------------------------------------
    #
    # **Every base member not named here is sealed**, and `__init_subclass__`
    # below refuses — at import — a medium that shadows one.
    #
    # This exists because the seam used to be prose. `_DemoBase`'s docstring
    # named the hooks, nothing checked, and while #181 was landing a medium
    # added a method called `_watch_page` — a name the base already used for
    # the `console`/`pageerror`/`requestfailed`/`response` subscription. Python
    # resolved the override, web takes recorded zero problems, `strict=True`
    # refused nothing, and `timeline.json` stayed well-formed and empty. No
    # error, no warning, no failing unit test: the whole error-detection
    # surface was off because a subclass picked a name.
    #
    # The rule that follows is the one the accident argues for: a medium
    # *extends* by implementing a hook it was offered, never by re-declaring
    # something the base already promises to do. Two hooks here exist only to
    # give the shape somewhere to go — `_watch_extra` (subscribe more) and
    # `_before_shot` (do something before a still) — because sealing a member
    # a medium legitimately needed to reach would just move the problem.
    #
    # Adding a name here is a deliberate act with a cost: it says a medium may
    # replace that behaviour wholesale, and nothing downstream may rely on it
    # any more.
    MEDIUM_HOOKS = frozenset(
        {
            "__init__",
            # lifecycle
            "_init_context",
            "_start",
            "_stop",
            "_postprocess",
            # what only this medium can answer
            "_content_rect",
            "_evidence_payload",
            "_failure_screen",
            "_media_path",
            # extension points, each beside the sealed member it extends
            "_watch_extra",
            "_before_shot",
            "_idle",
        }
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a medium that shadows a sealed base member.

        Import time, not call time: the failure this replaces was invisible
        precisely because the shadowed method still *ran* — the wrong one.
        A `TypeError` while the module loads is the loudest available moment
        and the only one that cannot be reached by a take.

        Identity, not `in vars(cls)`: a mixin listed ahead of the recorder in
        the MRO shadows exactly as effectively as a method on the class
        itself, and `tests/unit` uses one.
        """
        super().__init_subclass__(**kwargs)  # type: ignore[call-arg]
        broken = []
        for name in vars(_DemoBase):
            # Read off `_DemoBase`, never off `cls`: a subclass that could
            # widen its own permit would have the escape hatch this exists to
            # remove, and it would read as configuration rather than as a
            # mistake.
            if name in _DemoBase.MEDIUM_HOOKS or name == "__init_subclass__":
                continue
            promised = getattr(_DemoBase, name, None)
            if not callable(promised):
                continue
            if getattr(cls, name, None) is not promised:
                broken.append(name)
        if broken:
            raise TypeError(
                f"{cls.__module__}.{cls.__qualname__} overrides "
                f"{', '.join(sorted(broken))} — sealed on _DemoBase, so this "
                f"silently replaces a guarantee every take is owed rather "
                f"than extending one. A medium may override only "
                f"_DemoBase.MEDIUM_HOOKS: "
                f"{', '.join(sorted(_DemoBase.MEDIUM_HOOKS))}."
            )

    def __init__(
        self,
        out_dir: Path | str | None = None,
        segment: str | None = None,
        accent_rgb: tuple[int, int, int] | None = None,
        terminal_title: str | None = None,
        terminal_prompt: str | None = None,
        viewport: tuple[int, int] | None = None,
        speech: bool | None = None,
        voice_id: str | None = None,
        speech_model: str | None = None,
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
        allow_private: bool | None = None,
    ) -> None:
        # Every setting resolves explicit parameter > DEMO_VIDEO_* env var
        # > built-in default (see SKILL.md for the variable names).
        #
        # **The target is classified before anything else is set up.** A demo
        # is an outbound artifact and the refusal has to happen while there is
        # nothing to leak — no browser, no page, no frame. `DEMO_VIDEO_BASE_URL`
        # is checked for *every* medium, not only the web one: it is how a
        # runner tells a take which application it is pointed at, and a
        # terminal storyboard reads it as readily as a web one. The web
        # recorder additionally checks the `base_url` it actually resolved,
        # which is where an explicit constructor argument shows up. There is
        # no `allow_public`, here or anywhere (see `target.py`).
        if allow_private is None:
            allow_private = _env_flag("ALLOW_PRIVATE")
        self._allow_private = bool(allow_private)
        guard_target(
            _env("BASE_URL"),
            self._allow_private,
            source=(
                "DEMO_VIDEO_BASE_URL in the environment — unset it, or export "
                "a target this take may be recorded against"
            ),
        )
        out_dir = out_dir or _env("OUT_DIR")
        if out_dir is None:
            raise RuntimeError(
                "no output directory: pass out_dir or set DEMO_VIDEO_OUT_DIR"
            )
        self.out_dir = Path(out_dir)
        self.segment = segment
        # The ticket's acceptance criteria, if this take is being recorded
        # against one (issue #12). Declared up front rather than accumulated
        # from the `ac=` tags, because the useful half of a coverage report is
        # the criteria **nothing** claimed — and that is underivable from the
        # tags alone. Absent here, `coverage` is null and `ac=` is refused.
        self._criteria = _checked_criteria(criteria)
        self.images_dir = self.out_dir / "images"
        self._video_dir = self.out_dir / ".video"
        if accent_rgb is None:
            raw = _env("ACCENT_RGB", "235,110,20")
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise RuntimeError(
                    f"DEMO_VIDEO_ACCENT_RGB must be 'R,G,B', got {raw!r}"
                )
            accent_rgb = tuple(int(p) for p in parts)  # type: ignore[assignment]
        self._accent = ",".join(str(c) for c in accent_rgb)
        self._terminal_title = terminal_title or _env("TERMINAL_TITLE", "terminal")
        self._terminal_prompt = terminal_prompt or _env("TERMINAL_PROMPT", "$ ")
        if viewport is None:
            raw = _env("VIEWPORT", "1280x720")
            w, sep, h = raw.lower().partition("x")
            if not (sep and w.strip().isdigit() and h.strip().isdigit()):
                raise RuntimeError(
                    f"DEMO_VIDEO_VIEWPORT must be 'WIDTHxHEIGHT', got {raw!r}"
                )
            viewport = (int(w), int(h))
        self._size = {"width": viewport[0], "height": viewport[1]}
        # Determinism (see the section above). Opt-in, because the frozen clock
        # and the motion rule change what an app does and mostly do it
        # silently; timezone, locale and reduced motion are pinned regardless.
        # The clock is parsed even when it is off, so a typo in
        # DEMO_VIDEO_CLOCK is reported when it is written rather than the first
        # time someone turns determinism on.
        if deterministic is None:
            deterministic = _env_flag("DETERMINISTIC")
        self.deterministic = False if deterministic is None else bool(deterministic)
        self._clock = clock or _env("CLOCK", DEFAULT_CLOCK)
        self._clock_ms = _clock_epoch_ms(self._clock)
        self._timezone_id = timezone_id or _env("TIMEZONE", DEFAULT_TIMEZONE)
        self._locale = locale or _env("LOCALE", DEFAULT_LOCALE)
        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        if speech is None:
            speech = _env_flag("SPEECH")
        if speech is True and not api_key:
            raise RuntimeError(
                "speech is forced on but ELEVENLABS_API_KEY is not set"
            )
        self._speech = bool(api_key) if speech is None else speech
        self._api_key = api_key
        # Default voice "Sarah" is premade — works on free-tier keys.
        self._voice_id = voice_id or _env("VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
        self._speech_model = speech_model or _env(
            "SPEECH_MODEL", "eleven_multilingual_v2"
        )
        self._tts_dir = self.out_dir / ".tts"
        # Caption font size in px. The web recorder raises this so captions
        # stay readable after its window composite scales the frame down.
        self._caption_font_px = 26
        # Caption distance from the frame bottom, in px. The web recorder
        # composites (and scales ~0.8) its page into a centered window, which
        # lifts an in-page bottom:44px caption to ~89px in the final frame;
        # non-composited media (terminal) raise this so the caption lands at
        # the same height, keeping caption placement uniform across media.
        self._caption_bottom_px = 44
        self._lines: list[tuple[float, Path]] = []  # (video offset s, clip)
        # Both are readings of time.monotonic(). Nothing in this package
        # measures elapsed time any other way — not the beat log, not narration
        # pacing, not the terminal recorder's idle pump, not a wait_for
        # deadline — because time.time() steps (NTP, a VM resuming; a WSL2 box
        # was measured stepping 573 ms backwards inside 8 s). One such step
        # puts every beat and narration cue after it on a different clock from
        # the frames they describe, and makes every sleep-until loop in here
        # over- or under-run by the size of the step.
        self._line_end = 0.0  # when the current line stops speaking
        self._t0 = 0.0  # when video capture started
        # ...and the one clock in here that is *not* monotonic, because the
        # video is on it and nothing else can reach it. See _CaptureClock.
        self._capture_clock = _CaptureClock()
        self.page: Page = None  # type: ignore[assignment]
        # The beat log (see "beat timeline" above) and the caption currently
        # on screen, which every beat is stamped with.
        self._beats: list[dict] = []
        self._caption = ""
        self._in_beat = False
        # The problem log (see "take issues" above). `strict` decides whether
        # a take that recorded a fatal one is allowed to succeed.
        if strict is None:
            strict = _env_flag("STRICT")
        self._strict = bool(strict)
        self._issues: list[dict] = []
        self._issue_count = 0
        # Counted outside the MAX_ISSUES cap: the verdict must not depend on
        # how much noise came before the thing that matters.
        self._fatal_count = 0
        # Offset from _t0 at which Playwright was last known to be delivering
        # page events. Attribution is only as good as this is fresh.
        self._pumped_at = 0.0
        # Did *this* take encode an mp4? Not "is there an mp4 in the folder" —
        # that question has a stale answer, and every consumer of it was
        # reading the previous run's file: `duration` in timeline.json (issue
        # #20), the review frames extracted off `media`, and the last frame in
        # `failure/`. Set in `_convert`, after ffmpeg returns.
        self._converted = False
        # Where this take's spoken lines were put in that mp4, and whether the
        # host's wall clock could be corrected for when they were (issue #226).
        # Null until `_convert` has mixed them, so a take that narrated
        # nothing — or encoded nothing — says nothing rather than claiming an
        # empty mix. See `narration.mix_plan`.
        self._narration: dict | None = None
        # What the *picture* turned out to be (issue #97). Measured off the
        # encoded mp4 in `__exit__`, so it is null on any take that wrote none,
        # and it is the one thing in the timeline that describes the frames
        # rather than the storyboard. See the "did the recording show
        # anything?" section.
        self._content: dict | None = None
        # Whether the recorder's own overlays were still on screen when the
        # take ended (issue #163), read off the page in `__exit__` and folded
        # into `content.warnings` by `_measure_content`. None means "nothing
        # was up", which is what a healthy take reads.
        self._overlay_note: str | None = None
        # Seconds of blank opening this take's encode covered over, or None for
        # a recorder that does not do that at all (issue #119). Null and 0.0 are
        # different answers here — "never claimed to" against "had nothing to
        # cover" — and `opening_warning` reads the difference.
        self._opening_held: float | None = None
        # The medium's screen, read once on the failure path after `_stop()`
        # has flushed. See the "failure artifacts" section.
        self._failure_screen_text: str | None = None
        self._failure_json: dict | None = None
        self._failure_docs: list[tuple[Path, str]] = []
        # Per-beat evidence. Buffered as (beat record, medium payload) while
        # the page is alive and turned into documents in `__exit__`, which is
        # what keeps the capture off the page's critical path.
        if evidence is None:
            evidence = _env_flag("EVIDENCE")
        self._evidence_on = True if evidence is None else bool(evidence)
        self._evidence: list[tuple[dict, dict]] = []
        self._evidence_docs: list[tuple[Path, dict]] = []
        # Announce narration state up front — a silent recording when the
        # user expected voice (usually the key just isn't in this process's
        # env) is otherwise a confusing surprise only noticed after the fact.
        if self._speech:
            print(f"demo-video: narration ON (voice {self._voice_id})",
                  file=sys.stderr)
        else:
            print(
                "demo-video: narration OFF — no ELEVENLABS_API_KEY in this "
                "environment, so captions record silently. Export the key "
                "(e.g. `set -a; source .env; set +a`) before recording to "
                "enable spoken narration.",
                file=sys.stderr,
            )
        # ...and determinism state, at the same volume and for the same reason.
        # Which clock produced a take is not visible in the video, and both
        # answers surprise somebody: a frozen clock can hand a reviewer a
        # confidently wrong screen, and a live one means two takes never match.
        if self.deterministic:
            print(
                f"demo-video: determinism ON — the page's clock is frozen at "
                f"{self._clock}, its timezone is {self._timezone_id}, its "
                f"locale {self._locale}, and animations land on their finished "
                f"state. Re-recording reproduces the take. But an app that "
                f"*reads* the clock (a debounce, an elapsed-time bar, a token's "
                f"validity window, a 'last 7 days' chart) can render a "
                f"plausible wrong screen rather than failing loudly — check the "
                f"stills against the app by hand this once, and pass "
                f"deterministic=False (or DEMO_VIDEO_DETERMINISTIC=0) if "
                f"anything looks off. See the skill's "
                f"reference/determinism.md.",
                file=sys.stderr,
            )
        else:
            print(
                f"demo-video: determinism OFF (the default) — timezone "
                f"{self._timezone_id}, locale {self._locale} and reduced motion "
                f"are still pinned, but the page's clock runs, so anything the "
                f"app renders from it differs between takes and two recordings "
                f"of this storyboard will not match. Recorder("
                f"deterministic=True) freezes it; read the skill's "
                f"reference/determinism.md first, it changes what some apps do.",
                file=sys.stderr,
            )

    # -- subclass hooks -----------------------------------------------------

    def _init_context(self, context) -> None:
        """Add medium-specific context init scripts (runs before the page
        exists, so scripts re-inject on every navigation)."""

    def _start(self) -> None:
        """Post-page setup: navigate, inject assets, spawn processes."""

    def _stop(self) -> None:
        """Teardown before the browser closes (kill child processes, etc.)."""

    def _postprocess(self, mp4: Path) -> None:
        """Transform the finished mp4 in place (e.g. composite it into a
        window on a background). No-op by default; the terminal recorder
        frames itself in-page, so only the web recorder overrides this."""

    def _content_rect(self) -> tuple[int, int, int, int] | None:
        """Where the app sits in the **encoded** frame, caption band trimmed.

        The one thing the picture check (issue #97) cannot work out for itself,
        and the one thing the recorder already knows exactly: it composited the
        frame. Returning None is honest and supported — the report then says
        nothing was measured, rather than scoring the recorder's own chrome and
        calling a blank take healthy (issue #17).

        **Must not touch the page.** It is called after the browser is gone,
        because the mp4 it describes does not exist until then. A medium whose
        geometry comes from a live element reads it in `_start()` and remembers
        it — which is also the honest thing to do, since the recording was made
        against that layout and not against whatever the last frame had.
        """
        return None


    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "_DemoBase":
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._video_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
            # Always pinned. Locale and timezone are context options rather
            # than init scripts because a page cannot fake its own Intl data
            # convincingly, and every date/number the app formats has to come
            # out the same on a machine in Tórshavn as on a CI runner in
            # us-east-1. None of the three changes what an app computes, so
            # none of them is gated on `deterministic`.
            self._context = self._browser.new_context(
                viewport=self._size,
                record_video_dir=str(self._video_dir),
                record_video_size=self._size,
                locale=self._locale,
                timezone_id=self._timezone_id,
                reduced_motion="reduce",
            )
            if self.deterministic:
                # Opt-in: both of these change what an app *does*.
                # The clock first, so the app's own scripts never see a live one.
                self._context.add_init_script(
                    _FROZEN_CLOCK_JS.replace("__EPOCH_MS__", str(self._clock_ms))
                )
                self._context.add_init_script(_FREEZE_MOTION_JS)
            # Overlays common to every medium.
            self._context.add_init_script(
                _CAPTION_JS.replace("__CAPFONT__", str(self._caption_font_px))
                .replace("__CAPBOTTOM__", str(self._caption_bottom_px))
            )
            self._context.add_init_script(
                _INTERLUDE_JS.replace("__ID__", INTERLUDE_ID)
                .replace("__CSS__", INTERLUDE_CSS)
            )
            self._context.add_init_script(_BRIDGE_JS.replace("__ID__", BRIDGE_ID))
            # Medium-specific init scripts (cursor, spotlight, ...).
            self._init_context(self._context)
            self.page = self._context.new_page()
            # Chromium's screencast starts with the page, so this — not the
            # end of _start() — is frame zero of the recording. Setting it
            # any later shifts every beat timestamp and every narration
            # offset earlier than the frame it describes, by however long
            # the medium's setup takes (~250 ms for the web recorder's
            # window-frame render, and it is not a constant).
            self._t0 = time.monotonic()
            # Started with `_t0` and stopped with the capture, so its window is
            # exactly the window the screencast was stamping frames in.
            self._capture_clock.start(self._t0)
            # Before _start(), so the very first navigation is watched too —
            # a page that throws on load is the whole point of this.
            self._watch_page(self.page)
            self._start()
            # _start() ends in real Playwright work, so events were flowing as
            # it returned. Without this the first storyboard beat looks like it
            # began after an unexplained gap and cannot claim anything.
            self._pumped_at = time.monotonic() - self._t0
        except Exception:
            # __exit__ never runs when __enter__ raises — don't leak the
            # Playwright driver (typical cause: chromium not installed).
            self._capture_clock.stop()
            try:
                self._stop()
            except Exception:
                pass
            self._pw.stop()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # **The order of the next three statements is load-bearing, and the
        # reason it was written down is gone while the requirement is not.**
        # The redaction verifier that used to run last was what this sequence
        # was argued for; #144 deleted it. Two of the three constraints
        # survive it untouched, and both were wrong once:
        #
        #   * the narration tail runs **first**. It holds the frame open so a
        #     take does not end mid-sentence, and it pumps — a terminal take's
        #     child process is still running and still writing, and a take
        #     that stops pumping here loses that output from the recording.
        #   * `_stop()` runs **second**, because a medium can be sitting on
        #     output: the terminal flushes what its exit-marker reader was
        #     holding back here, and a screen read before that is not the
        #     screen the recording ends on.
        #   * the failure screen is read **after both**, on every path out of
        #     the `with` that carries an exception, for exactly that reason.
        if exc_type is None:
            self._finish_line(tail=0.5)  # don't end mid-sentence
        # The last thing asked of the live page, and it has to be here rather
        # than beside the rest of the picture check: `_measure_content` runs
        # after the browser is gone, off a file, and the one occlusion nothing
        # in a file can be asked about is the recorder's *own* (issue #163).
        # Before `_stop()` so a medium that kills its child process cannot take
        # the page with it, and outside the `exc_type is None` guard because a
        # storyboard that raised under an overlay is still a take somebody has
        # to be told about.
        self._note_overlays_up()
        self._stop()
        # Buffered in memory here and turned into a file by `_build_failure`
        # below — see that split, which survives #144 for a reason unrelated
        # to the one it was written for.
        if exc_type is not None:
            self._capture_failure_screen()
        # Evidence documents are assembled here, after `_stop()`, and that is
        # safe rather than merely convenient: the captures were buffered per
        # beat while the page was alive, and this turns them into documents in
        # memory — it opens no beat, touches no page, and writes no file.
        #
        # It runs on the **failure** path too, which is issue #11 step 1 rather
        # than a liberty: every beat in the timeline this take is about to
        # write carries an `evidence` path, so writing that timeline while
        # skipping this would point every beat at a file that is not there.
        failure: dict | None = (
            None if exc_type is None else failure_summary(exc_type, exc, self._beats)
        )
        self._build_evidence()
        if failure is not None:
            self._build_failure(failure)
        # **Every take keeps what it had** — issue #11 (with #32). The old
        # guard was `exc_type is None`, so a storyboard that raised threw away
        # the webm the browser already had in hand, wrote no beat log for beats
        # that were sitting in memory, and left nothing at all behind. In CI,
        # where there is no screen to look at, that means blind retries — and
        # #3 had already settled the principle in the other direction: a strict
        # take fails *after* writing every artifact, because a broken take is
        # precisely the one somebody wants to see.
        #
        # The one thing that used to keep *nothing* was an unverifiable mask,
        # and #144 removed it. There is no longer any path out of this method
        # that discards what the take recorded.
        convert_error: BaseException | None = None
        video = self.page.video
        self._context.close()
        # The screencast has stopped stamping frames, so the window this
        # sampler had to cover is closed. Stopping it any later would attribute
        # a step taken during conversion to the recording (issue #215).
        self._capture_clock.stop()
        clock_warning = self._capture_clock.warning()
        if clock_warning:
            print(clock_warning, file=sys.stderr)
        webm = Path(video.path()) if video else None
        self._browser.close()
        self._pw.stop()
        try:
            if webm and webm.exists():
                try:
                    self._convert(webm)
                except Exception as exc_convert:  # noqa: BLE001 - see below
                    # ffmpeg failing must not also cost the beat log. It is the
                    # only remaining way a take writes a timeline and no mp4,
                    # and it is exactly the state issue #20 is about: the
                    # folder may still hold a *previous* run's demo.mp4, and
                    # `_timeline_doc` now reports `duration: null` rather than
                    # that file's length. Re-raised at the end if nothing else
                    # is already on its way out.
                    convert_error = exc_convert
                    print(
                        f"demo-video: WARNING — ffmpeg could not convert this "
                        f"take's recording ({type(exc_convert).__name__}: "
                        f"{exc_convert}). The beat log is still written, with "
                        f"duration: null; no review frames were extracted, "
                        f"because the only mp4 here would be a previous run's.",
                        file=sys.stderr,
                    )
            # Before the timeline, because the timeline carries the answer
            # (issue #97). Gated on `self._converted` for the same reason
            # `duration` is: measuring a previous run's demo.mp4 and filing
            # the result under this take's beats is the exact class of lie
            # this check exists to remove. On a take that crashed but is
            # being kept, this still runs — the mp4 is that take's, however
            # short, and a partial recording of nothing is worth saying.
            self._measure_content()
            # Before the timeline, because every beat in it carries an
            # `evidence` path: a timeline pointing at files that are not
            # there yet is the one ordering a reader can be caught by.
            self._write_evidence()
            # The beat log is the durable, diffable record of the take — it
            # outlives the mp4, which is not committed. Written after
            # conversion so `duration` is the encoder's answer, not a guess.
            doc = self._timeline_doc(failure)
            json_path, _ = write_timeline(self.out_dir, doc)
            print(f"wrote {json_path} ({len(self._beats)} beats)")
            if failure is not None:
                self._write_failure()
            # Only off a recording *this* take encoded. `beat_frames()`
            # otherwise reads `media` out of the timeline, finds a previous
            # run's demo.mp4 sitting there, and hands a reviewer a sheet of
            # frames from a different recording under this take's beat
            # names — the same lie as the stale `duration` (issue #20), one
            # directory down.
            if self._converted:
                self._write_beat_frames(doc)
        finally:
            # Whatever went wrong above, don't leave .video/ behind — the
            # next take into this directory would trip over it.
            for leftover in self._video_dir.glob("*"):
                leftover.unlink()
            self._video_dir.rmdir()
            # The marker (#46), and its removal, in the one place that runs on
            # every path out of `__exit__`.
            #
            # The condition is "this take did not write its own complete set of
            # artifacts", and it is deliberately wider than "the storyboard
            # raised". Three ways to get there, and the second is the one the
            # issue is actually about:
            #
            #   exc_type        the storyboard raised. demo.mp4 is this take's,
            #                   partial, and the marker says so.
            #   convert_error   the storyboard finished and ffmpeg did not, so
            #                   the timeline is this week's and any mp4 is not.
            #
            # A third way in — a take whose mask could not be verified, which
            # kept nothing and left a previous run's files sitting there — was
            # the case #46 was actually filed about, and #144 removed it.
            #
            # A strict failure is none of these: it writes every artifact and
            # they are all current, so its marker is cleared like any success's.
            marker_failure = failure
            if marker_failure is None and convert_error is not None:
                marker_failure = {
                    "type": type(convert_error).__name__,
                    "message": str(convert_error)[:FAILURE_MESSAGE_CHARS],
                    "beat": None,
                    "verb": None,
                }
            if marker_failure is not None:
                self._write_failure_marker(marker_failure)
                if failure is not None:
                    self._report_failure(failure, wrote_dump=True)
            else:
                clear_failure_marker(self.out_dir)
                clear_failure_dir(self.out_dir)
            # Always, strict or not, crashed or not: the problems a take
            # recorded are the one thing nobody thinks to go looking for, so
            # they have to arrive unasked.
            self._print_issue_summary()
            # Last, so it is the line still on screen when the take ends. A
            # recording nobody can see is not something to bury above ffmpeg's
            # output (issue #97).
            print_content_summary(self._content, self._media_path().name)
        # `StrictTakeFailed` is the take's verdict when it recorded console
        # errors or a bad exit code — and it is raised *after* the mp4, the
        # stills and the timeline are written and kept, because they are the
        # evidence somebody needs to see what the app did.
        # A storyboard that raised propagates its own exception — returning
        # None from here is what lets it. Only when nothing is already on its
        # way out does the encoder failure get to be the take's verdict; it
        # must not replace a wait_for_text() timeout, which is the message that
        # says what to fix.
        if exc_type is None and convert_error is not None:
            raise convert_error
        if exc_type is None and self._strict and self._fatal_count:
            raise StrictTakeFailed(self._strict_message())

    # -- take issues --------------------------------------------------------

    def _note_issue(
        self,
        kind: str,
        message: str,
        beat: dict | None = None,
        **extra: object,
    ) -> None:
        """Log one problem, attributed to `beat` (default: whichever beat can
        honestly claim it, which is often none — see `_attributed_beat`).

        Never raises, and means it: the whole body is guarded. Page events are
        delivered inside Playwright callbacks and `_record_exit_code` runs from
        the PTY pump mid-recording, so an exception here would surface
        somewhere unrelated and lose a take over a diagnostic.
        """
        try:
            self._issue_count += 1
            if kind in STRICT_KINDS:
                # Outside the cap, and before the early return below it: the
                # verdict must not depend on how much noise preceded this.
                self._fatal_count += 1
            if len(self._issues) >= MAX_ISSUES:
                return
            if beat is None:
                beat = self._attributed_beat()
            record: dict = {
                "kind": kind,
                "t": round(time.monotonic() - self._t0, 3),
                "beat": None if beat is None else beat.get("index"),
                "verb": None if beat is None else beat.get("verb"),
                "caption": "" if beat is None else beat.get("caption", ""),
                "message": message,
            }
            record.update(extra)
            self._issues.append(record)
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            pass

    def _attributed_beat(self) -> dict | None:
        """The beat an event observed *now* may honestly be blamed on.

        `self._beats[-1]` is the most recently *started* beat, which is not the
        same question. Two conditions, both required:

          * a beat is actually open — storyboard code between two verbs is
            nobody's beat, and letting a closed beat claim an event that
            happened after it ended is how "the take broke during wait_for"
            gets written about something that broke later;
          * it was already open the last time events are known to have been
            delivered, so nothing could have fired before it started. Holds
            pump (`_pump_events`), which keeps this true for ordinary beats;
            what it screens out is a long *non*-Playwright gap — narration
            being synthesized, say — with a beat opening at the end of it.

        Otherwise None, and the issue records `beat: null`.
        """
        if not self._in_beat or not self._beats:
            return None
        beat = self._beats[-1]
        t_start = beat.get("t_start")
        if not isinstance(t_start, (int, float)):
            return None
        if t_start > self._pumped_at + ATTRIBUTION_SLACK_S:
            return None
        return beat

    def _pump_events(self, force: bool = False) -> None:
        """Give Playwright a chance to deliver queued page events.

        The sync API dispatches `console`/`pageerror`/`requestfailed`/`response`
        only while it is inside a call, so a storyboard sitting still for three
        seconds queues everything the page throws and hands it all to whichever
        beat makes the next call. One trivial evaluate per PUMP_INTERVAL_S
        keeps delivery inside the beat the event belongs to. It paints nothing,
        touches no DOM, and is skipped if it fails — a pump is a diagnostic
        convenience, never a reason to lose a take.

        `force` skips the interval, and `_beat` is the one caller that passes
        it (issue #214). The interval is a *rate limit on a hold*, and at a
        beat boundary it is exactly wrong: a click returns roughly a
        millisecond after the `pause(0.4)` inside it pumped, so the beat that
        follows the click — the one carrying a caption the navigation just
        took off the screen — is the beat the interval would skip. Measured
        against Chromium 151 with a recording context attached: 0.955 ms mean,
        1.37 ms p95 per round trip (0.899 / 1.14 under 8-way CPU contention),
        so a 40-beat storyboard pays about 38 ms for it.
        """
        now = time.monotonic() - self._t0
        if not force and now - self._pumped_at < PUMP_INTERVAL_S:
            return
        try:
            self.page.evaluate("0")
        except Exception:  # noqa: BLE001 - the page may be closing
            return
        self._pumped_at = time.monotonic() - self._t0

    def _watch_page(self, page: Page) -> None:
        """Subscribe to everything the page can say about being broken.

        **Sealed** (see `MEDIUM_HOOKS`). These four listeners are what the
        issue log is made of and what `strict=True` refuses a take over, and a
        medium that replaced this method would take all four off itself
        without changing anything a reader of `timeline.json` could see. A
        medium adds to them through `_watch_extra`, which cannot subtract.
        """
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)
        self._watch_extra(page)

    def _watch_extra(self, page: Page) -> None:
        """Subscriptions this medium wants on top of the four above.

        Called once, from `_watch_page`, before `_start()` — so the first
        navigation is watched too. Do not subscribe from `_start` as well:
        two subscriptions record every event twice.

        A handler here should only set an attribute. Playwright delivers page
        events on the thread that is blocked inside a Playwright call, so
        calling back into the API from one is a way to deadlock a take.
        """

    def _on_console(self, message) -> None:
        try:
            kind = {
                "error": "console_error",
                "warning": "console_warning",
            }.get(message.type)
            if kind is None:
                return  # log/info/debug is an app talking, not an app failing
            where = message.location or {}
            self._note_issue(
                kind, message.text,
                url=where.get("url") or None, line=where.get("lineNumber"),
            )
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            pass

    def _on_page_error(self, error) -> None:
        try:
            text = getattr(error, "message", None) or str(error)
            self._note_issue("page_error", str(text).strip().split("\n")[0])
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            pass

    def _on_request_failed(self, request) -> None:
        try:
            self._note_issue(
                "request_failed",
                f"{request.failure or 'request failed'} — {request.url}",
                url=request.url, method=request.method,
            )
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            pass

    def _on_response(self, response) -> None:
        try:
            # >= 400, not "non-2xx": 3xx is a redirect the browser follows and
            # is not a fault, and counting it would flag every canonical URL.
            if response.status < 400:
                return
            self._note_issue(
                "http_error", f"HTTP {response.status} {response.url}",
                url=response.url, status=response.status,
            )
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            pass

    def _issue_where(self, issue: dict) -> str:
        if issue.get("beat") is None:
            return "before the first beat"
        return f"beat {issue['beat']} ({issue.get('verb')})"

    def _print_issue_summary(self) -> None:
        """One end-of-take report, on stderr, whether or not anything broke."""
        if not self._issue_count:
            print(
                "demo-video: no console errors, failed requests or non-zero "
                "exits recorded",
                file=sys.stderr,
            )
            return
        counts: dict[str, int] = {}
        for issue in self._issues:
            counts[issue["kind"]] = counts.get(issue["kind"], 0) + 1
        tally = ", ".join(f"{k} x{n}" for k, n in sorted(counts.items()))
        print(
            f"demo-video: {self._issue_count} problem(s) recorded during this "
            f"take ({tally})",
            file=sys.stderr,
        )
        for issue in self._issues:
            print(
                f"  [{issue['t']:.2f}s] {issue['kind']} in "
                f"{self._issue_where(issue)}: {issue['message']}",
                file=sys.stderr,
            )
        if self._issue_count > len(self._issues):
            print(
                f"  …and {self._issue_count - len(self._issues)} more, over "
                f"the {MAX_ISSUES}-issue cap ({self._fatal_count} of all of "
                f"them fatal under strict)",
                file=sys.stderr,
            )

    def _strict_message(self) -> str:
        recorded = [i for i in self._issues if i["kind"] in STRICT_KINDS]
        shown = recorded[:5]
        lines = [
            f"  {i['kind']} in {self._issue_where(i)}: {i['message']}"
            for i in shown
        ]
        if not shown:
            lines.append(
                f"  (none of them recorded in detail — every one arrived past "
                f"the {MAX_ISSUES}-issue cap)"
            )
        elif self._fatal_count > len(shown):
            lines.append(f"  …and {self._fatal_count - len(shown)} more")
        return (
            f"strict=True and this take recorded {self._fatal_count} problem(s) "
            "the app should not have produced:\n" + "\n".join(lines) + "\n"
            "The recording, its stills and its timeline were still written — "
            "read timeline.md's Issues section. Pass strict=False (or unset "
            "DEMO_VIDEO_STRICT) to record anyway."
        )

    # -- beat log -----------------------------------------------------------

    @contextmanager
    def _beat(
        self,
        verb: str,
        selector: str | None = None,
        still: str | None = None,
        caption: str | None = None,
        **extra: object,
    ) -> Iterator[dict | None]:
        """Record one beat around a storyboard verb.

        Re-entrant calls are folded into the beat already open, so a verb
        built out of other verbs (`click` glides with `move_to` first) logs
        the call the storyboard made and not the machinery underneath it.
        `extra` keys land on the record as-is — the seam for slices that
        want to say more about a beat than the base schema does.
        """
        if self._in_beat:
            yield None
            return
        self._in_beat = True
        # Scrubbed rather than fatal, because none of these is text a viewer
        # reads off the screen. Caption text reaches the screen through
        # caption(), which refuses it outright.
        record: dict = {
            "index": len(self._beats),
            "t_start": round(time.monotonic() - self._t0, 3),
            "t_end": None,
            "caption": self._caption if caption is None else caption,
            "verb": verb,
            "selector": selector,
            "still": still,
            "segment": self.segment,
            # Equal to `index` here, and deliberately written anyway: `stitch`
            # renumbers `index` across a merged demo and leaves this one alone,
            # so `(segment, segment_index)` is the beat's identity before and
            # after a merge. A consumer naming files after a beat (issue #9)
            # can use it without knowing which kind of timeline it is reading.
            "segment_index": len(self._beats),
        }
        if self._evidence_on:
            # Written onto the beat rather than left for a reader to derive
            # from `index`, so a merge that renumbers beats (issue #7) does
            # not silently repoint every beat at somebody else's evidence.
            record["evidence"] = (
                f"{EVIDENCE_DIR}/{evidence_name(record['index'], self.segment)}"
            )
        record.update(extra)
        self._beats.append(record)
        if caption is None:
            # **The line this beat inherited, re-read after the page has had
            # its say** (issue #214). `goto()` waits for the load, so the
            # caption is already cleared when it returns; a click is not —
            # measured identically on Chromium 136, 147 and 151, a link click,
            # a form submit and a `location.href` button all return after
            # `framenavigated` alone, and the `domcontentloaded` that clears
            # the caption arrives during whichever Playwright call comes next.
            # That call used to be this beat's verb, one stamp too late, so
            # the first beat after a click-driven navigation reported a line
            # the load had already taken off the screen — #134's artifact, one
            # beat wide.
            #
            # Pumped *after* the record is appended and `_in_beat` is set, so
            # anything the pump delivers is attributed to this beat and not to
            # the closed one before it (`_attributed_beat`). Only an inherited
            # caption is re-read: a beat carrying its own — `caption()`,
            # `interlude()` — is about to put that line on the screen itself,
            # and the load it just learned about took away the *previous* one.
            self._pump_events(force=True)
            record["caption"] = self._caption
        try:
            yield record
        except BaseException as raised:
            # A verb that threw did not do what its beat says it did, and the
            # `finally` below closes the record either way — so without this
            # the beat carries a plausible `t_start`, a plausible `t_end`, and
            # nothing at all to tell it from one that returned. That was
            # invisible while an exception meant no timeline was written; it
            # stops being invisible the moment anything catches, which is what
            # `__exit__` now does (issue #11), and it is a lie a conformance
            # gate reading this file would believe (issue #12).
            #
            # `BaseException`, not `Exception`: a Ctrl-C on a hung demo is
            # exactly the take somebody is about to go looking at, and
            # `KeyboardInterrupt` does not derive from `Exception`.
            #
            # The message is not the recorder's: `wait_for_text()` quotes a
            # thousand characters of terminal screen into its timeout, and that
            # screen can hold anything the program printed. It is written
            # through verbatim — this recorder scrubs nothing (#138).
            record["error"] = {
                "type": type(raised).__name__,
                "message": str(raised),
            }
            raise
        finally:
            # Captured before `t_end` is stamped, so the round trips it costs
            # are accounted for *inside* the beat that paid for them and no
            # unexplained gap opens up between one beat and the next. Nested
            # try/finally so `t_end` is stamped even when the capture refuses
            # (the beat is closed either way, so the log stays honest).
            try:
                if self._evidence_on:
                    self._capture_evidence(record)
            finally:
                record["t_end"] = round(time.monotonic() - self._t0, 3)
                self._in_beat = False

    def _write_beat_frames(self, doc: dict) -> None:
        """Extract this take's review frames (a no-op for a segment).

        The frames come out of the recording rather than being re-derived
        it: every one of them is a frame of `demo.mp4`, which is masked in the
        page before it is ever captured. `tests/smoke` measures that on the
        frames themselves instead of taking this paragraph's word for it.
        """
        write_beat_frames(self.out_dir, doc, "this take")

    # -- per-beat evidence (see the section at the top of this file) --------

    def _evidence_payload(self) -> dict:
        """What this medium can say about the screen right now.

        Overridden per medium (`Recorder` -> ARIA + outerHTML, `TerminalRecorder`
        -> the rendered screen). Every medium answers with the text it read;
        there is no refusal path here any more — the one that existed, an
        `{"omitted": reason}` payload for text the mask could not vouch for,
        went with the mask in #144. A capture that *raises* still gets a file,
        carrying `error`; see `_capture_evidence`.
        """
        return {}

    def _capture_evidence(self, beat: dict) -> None:
        """Buffer one beat's evidence.

        A failure here is a diagnostic and must not lose an otherwise fine
        take: the beat gets a file saying what went wrong, which keeps the
        `evidence` pointer on every beat pointing at something real.
        """
        try:
            payload = self._evidence_payload()
        except Exception as exc:  # noqa: BLE001 - a diagnostic must not kill a take
            payload = {"error": f"{type(exc).__name__}: {exc}"}
            print(
                f"demo-video: could not capture evidence for beat "
                f"{beat.get('index')} ({beat.get('verb')}): "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        self._evidence.append((beat, payload))

    @staticmethod
    def _flatten(text: str) -> str:
        """Whitespace collapsed to single spaces, ends trimmed."""
        return " ".join(text.split())


    def _evidence_doc(self, beat: dict, payload: dict) -> dict:
        """One evidence document: the envelope, the payload, then the caps.

        The envelope names the take — schema, recorder, segment, media — and
        copies the beat this evidence belongs to, so a file read on its own
        says which moment of which recording it is of. The medium's payload
        (ARIA and the spotlight's markup, or the rendered screen) is merged in
        as it came back: nothing is removed from it here, because there is no
        masking anywhere in this recorder.

        Only the caps act. Each field named in `EVIDENCE_LIMITS` is cut to its
        budget and listed in `truncated`, so a field that was shortened is
        never read as a page that was short.
        """
        doc: dict = {
            "schema": EVIDENCE_SCHEMA,
            "generated_by": "demo-video",
            "recorder": type(self).__name__,
            "segment": self.segment,
            "media": self._media_path().name,
            "beat": {
                key: beat.get(key)
                for key in ("index", "t_start", "t_end", "verb", "selector",
                            "caption", "still", "evidence")
            },
        }
        doc.update(payload)
        truncated: list[str] = []
        for field, limit in EVIDENCE_LIMITS.items():
            text = doc.get(field)
            if not isinstance(text, str):
                continue
            capped, cut = _cap_text(text, limit)
            if cut:
                truncated.append(field)
                doc[field] = capped
        doc["truncated"] = sorted(truncated)
        doc["limits"] = {k: v for k, v in EVIDENCE_LIMITS.items() if k in doc}
        return doc

    def _build_evidence(self) -> None:
        """Turn the buffered captures into documents. Writes nothing.

        Separate from writing on purpose: a document that cannot be made safe
        raises here, before the first byte of the first file has been written,
        so the failure cannot leave half an evidence directory behind.
        """
        if not self._evidence_on:
            return
        out = self.out_dir / EVIDENCE_DIR
        self._evidence_docs = [
            (out / evidence_name(beat["index"], self.segment),
             self._evidence_doc(beat, payload))
            for beat, payload in self._evidence
        ]

    def _stale_evidence(self, keep: set[Path] | None = None) -> list[Path]:
        """This take's own evidence files that this take is not writing.

        Only files this take's naming owns — `beat-NN.json` for a whole demo,
        `<segment>.seg.beat-NN.json` for a segment — so re-recording one segment
        of a multi-segment demo does not delete the others.
        """
        directory = self.out_dir / EVIDENCE_DIR
        if not directory.is_dir():
            return []
        prefix = f"{self.segment}.seg." if self.segment else ""
        mine = re.compile(rf"^{re.escape(prefix)}beat-\d+\.json$")
        keep = keep or set()
        return [
            path
            for path in sorted(directory.glob("*.json"))
            if mine.match(path.name) and path not in keep
        ]

    def _clear_stale_evidence(self, keep: set[Path] | None = None) -> None:
        """Delete evidence a previous take into this directory left behind.

        Re-recording into the same folder is how this skill is *meant* to be
        used — `record.py` is committed precisely so it can be re-run — and a
take with fewer beats than the last one would otherwise leave the
        previous take's files sitting beside its own, named for beats this
        take never recorded. Nothing else here has that shape: the mp4 is
        overwritten, and a still is only kept because it might be a committed
        guide. Evidence is never committed, so
        there is no such thing as one worth keeping.
        """
        for path in self._stale_evidence(keep):
            try:
                path.unlink()
            except OSError:
                print(
                    f"demo-video: WARNING — could not delete {path}, which is "
                    f"a previous take's evidence and describes a beat this "
                    f"take did not record",
                    file=sys.stderr,
                )

    def _write_evidence(self) -> None:
        # Runs even when there is nothing to write, and even with evidence
        # switched off: a previous take's files are the hazard, not this one's.
        keep = {path for path, _ in self._evidence_docs}
        self._clear_stale_evidence(keep)
        if not self._evidence_docs:
            return
        (self.out_dir / EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
        for path, doc in self._evidence_docs:
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        total = sum(path.stat().st_size for path, _ in self._evidence_docs)
        print(
            f"wrote {self.out_dir / EVIDENCE_DIR} "
            f"({len(self._evidence_docs)} beats, {total // 1024} kB)"
        )
        if total > EVIDENCE_DIR_WARN_BYTES:
            print(
                f"demo-video: evidence/ is {total // 1024} kB over "
                f"{len(self._evidence_docs)} beats. The per-field caps are "
                f"working, but this app's accessibility tree is large — pass "
                f"Recorder(evidence=False) (or DEMO_VIDEO_EVIDENCE=0) if the "
                f"round trips are costing more than the files are worth.",
                file=sys.stderr,
            )

    # -- failure artifacts (see the section at the top of this file) --------

    def _failure_screen(self) -> str | None:
        """The medium's page text, for a failure dump. None if it has none.

        Called on the failure path only, **after `_stop()` and before
        the medium has been stopped** — that slot is the whole design. After
        `_stop()` because a medium can be sitting on output (the terminal
        scrubber withholds a trailing fragment and flushes it there), so an
        earlier reading is not the screen the recording ends on. Before the
        verifier because the verifier is what decides whether any of this may
        be kept: read after it, this would be page text nothing has vouched
        for, which is the exact hole PR #58 was blocked on.
        """
        return None

    def _capture_failure_screen(self) -> None:
        """Buffer `_failure_screen()`. Never raises.

        A page that is already gone is the ordinary reason a take is failing,
        so a dump that cannot read it says so and carries the console log, the
        last frame and the failing beat instead. Losing those as well because
        the DOM was unreadable would be losing the whole point.
        """
        try:
            self._failure_screen_text = self._failure_screen()
        except Exception as exc:  # noqa: BLE001 - a dump is not a recording
            self._failure_screen_text = (
                f"[demo-video: the page text could not be read at the end of "
                f"this take — {type(exc).__name__}: {exc}]"
            )

    def _failure_doc(self, failure: dict) -> dict:
        """The machine-readable half of `failure/`, masked and checked.

        Same order and same reasons as `_evidence_doc`: mask first, check the
        serialized bytes last, raise rather than write. Nothing in here is read
        from the page — `screen` was buffered before the verifier ran, the
        issues and the beats have been in memory since they happened, and the
        media is named rather than opened.
        """
        beat = failed_beat(self._beats)
        doc: dict = {
            "schema": FAILURE_SCHEMA,
            "generated_by": "demo-video",
            "recorder": type(self).__name__,
            "segment": self.segment,
            "when": _dt.datetime.now(_dt.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "failure": failure,
            # The failing beat in full, not just its index: this file is meant
            # to answer "which beat, and what was on screen" without anyone
            # having to open timeline.json and count.
            "beat": None if beat is None else dict(beat),
            "beats_recorded": len(self._beats),
            # What the app said it was doing wrong, whether or not strict was
            # on. A crash and a console error one beat earlier are the same
            # story surprisingly often.
            "issues": [dict(issue) for issue in self._issues],
            "issue_count": self._issue_count,
            "media": self._media_path().name,
            "screen_captured": self._failure_screen_text is not None,
        }
        return doc

    def _build_failure(self, failure: dict) -> None:
        """Turn the crash into documents. Writes nothing.

        **The split from `_write_failure` survives #144, and its original
        reason does not.** It was argued for as "a document that cannot be made
        safe raises before the first byte" — there is nothing to refuse now.
        What it also carries is the `_convert` ordering: this runs *before* the
        encode, which is why the two facts that depend on whether the mp4 was
        written — `media_written_by_this_take` and the last frame — are filled
        in by `_write_failure` instead. Building them here produced a dump that
        said "this take encoded no mp4" beside an mp4 this take had just
        encoded, which is the class of lie the whole `failure/` feature exists
        to remove.
        """
        out = self.out_dir / FAILURE_DIR
        self._failure_json = self._failure_doc(failure)
        docs: list[tuple[Path, str]] = []
        screen = self._failure_screen_text
        if screen is not None:
            # Its own file rather than a JSON field: a terminal buffer or an
            # ARIA tree is what somebody greps, and `\n` written as the two
            # characters `\` and `n` is not greppable.
            capped, _ = _cap_text(screen, EVIDENCE_MAX_SCREEN)
            docs.append((out / "screen.txt", capped))
        self._failure_docs = docs

    def _write_failure(self) -> None:
        """Put the built dump on disk, plus the last frame of the recording.

        The frame comes out of the mp4 with ffmpeg rather than off the page:
        it is a frame of the recording the take already
        vouched for, so it inherits that guarantee whole and reads nothing
        after the verifier ran. Gated on `self._converted`, not on the file
        existing — a previous run's demo.mp4 is not a picture of this crash
        (issue #20).
        """
        if self._failure_json is None:
            return
        out = self.out_dir / FAILURE_DIR
        out.mkdir(parents=True, exist_ok=True)
        # The one thing `_build_failure` could not know, filled in by the code
        # that does. See its docstring.
        doc = dict(self._failure_json)
        doc["media_written_by_this_take"] = self._converted
        written = 0
        for path, text in [
            (out / "failure.json", json.dumps(doc, indent=2, ensure_ascii=False) + "\n"),
            (out / "failure.md", render_failure_md(doc)),
            *self._failure_docs,
        ]:
            path.write_text(text)
            written += 1
        frame = out / "last-frame.png"
        frame.unlink(missing_ok=True)  # a previous failure's, if any
        if self._converted:
            mp4 = self._media_path()
            at = 0.0
            try:
                at = max(0.0, media_duration(mp4) - _FRAME_EDGE_S)
            except (subprocess.CalledProcessError, ValueError, OSError):
                at = 0.0
            if _extract(mp4, at, frame):
                written += 1
            else:
                print(
                    f"demo-video: WARNING — could not extract the last frame "
                    f"of {mp4.name} into {FAILURE_DIR}/. The rest of the dump "
                    f"is there.",
                    file=sys.stderr,
                )
        print(f"wrote {out} ({written} files)")

    def _write_failure_marker(self, failure: dict) -> None:
        """Say, in the demo folder itself, that this take failed (issue #46).

        Written whenever this take did not write its own complete set of
        artifacts — the storyboard raised, or ffmpeg failed to convert — and
        **not** on every abnormal exit: a `strict=True` refusal is an abnormal
        exit whose artifacts are all current, and its marker is cleared like a
        success's. `__exit__` holds that condition; `render_failure_marker`
        states it in the file, which is where a reader can act on it (#115).

        The case it exists for is the one where the artifacts left behind
        disagree with each other: ffmpeg failing to convert writes this take's
        `timeline.json` beside whatever `demo.mp4` a *previous* run left in the
        same directory. That reads as a successful take, and the video is a
        recording of different code — in a review gate, a confident approval of
        something that was never recorded. `stale` below is exactly that
        condition, and the marker names it rather than leaving a reader to
        notice.

        Never raises, and that is deliberate: the absence of this file means
        "the last take succeeded", so failing to write it is itself the lie it
        exists to prevent. The exception's message is trimmed to fit rather
        than allowed to stop the write.
        """
        marker = self.out_dir / FAILURE_MARKER
        mp4 = self._media_path()
        # Rendered before the `try`, as the body always was: the only failure
        # this is allowed to swallow is the write.
        body = render_failure_marker(
            failure,
            mp4.name,
            _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            stale=mp4.exists() and not self._converted,
            converted=self._converted,
        )
        try:
            marker.write_text(body)
        except OSError as exc:
            print(
                f"demo-video: WARNING — could not write {marker} ({exc}), so "
                f"nothing in this folder says the take failed",
                file=sys.stderr,
            )

    def _report_failure(self, failure: dict, wrote_dump: bool) -> None:
        """Say on stderr which beat killed the take and where to look.

        The exception itself propagates and is what a caller sees, but it is
        raised by the storyboard and cannot name the recorder's own artifacts.
        Nothing else in the output says "beat 7" or "look in failure/".
        """
        beat = failure.get("beat")
        where = (
            f"beat {beat} — {failure.get('verb')}()"
            if beat is not None
            else "between beats; no verb was running"
        )
        print(
            f"demo-video: this take FAILED at {where}, with "
            f"{failure.get('type')}. "
            + (
                f"Everything it had was still written: "
                f"{self._media_path().name if self._converted else 'no mp4'}, "
                f"timeline.json, and {FAILURE_DIR}/ (last frame, console log, "
                f"page text, failing beat). {FAILURE_MARKER} says so in the "
                f"folder itself."
                if wrote_dump
                else f"Nothing was kept — see the message above. "
                f"{FAILURE_MARKER} says so in the folder itself."
            ),
            file=sys.stderr,
        )

    def _media_path(self) -> Path:
        """The mp4 this take converts to on exit."""
        name = f"{self.segment}.seg.mp4" if self.segment else "demo.mp4"
        return self.out_dir / name

    def _note_overlays_up(self) -> None:
        """Ask the page whether this recorder's own overlays are still showing.

        **Exact, not heuristic, and that is the whole scope.** The recorder
        created these elements and knows their ids, so "is the interlude card
        still up" is a question with an answer rather than something to infer
        from luma. It says nothing about an app's own modal, a `<dialog>` the
        page opened, or anything else covering the app — that is unbounded and
        is declared in `reference/limits.md`, not attempted here.

        It exists because the measurement that should have caught this scored
        it backwards. On three takes of one storyboard, one clean and two with
        a `light` scrim over the app for the last 17 s of 48, `content.score`
        read 26.74 for the clean take and 32.94/32.95 for the covered ones: the
        scrim is a gradient, gradient inside the measured rect is variance, and
        variance is what the score arm measures. No threshold separates those
        numbers in the right direction, so this asks a different question.

        Lives in the base rather than in either recorder: the overlays are
        `_DemoBase`'s own init scripts, and both media record the same page.

        Never raises. A page that is already gone is the ordinary state of a
        failing take, and losing the take over a diagnostic would be worse than
        the diagnostic being absent.
        """
        try:
            up = self.page.evaluate(_OVERLAY_PROBE_JS, list(OVERLAY_IDS))
        except Exception:  # noqa: BLE001 - a diagnostic must not kill a take
            return
        if isinstance(up, list):
            self._overlay_note = overlay_warning([str(i) for i in up])

    def _measure_content(self) -> None:
        """Fill in `self._content` off the mp4 this take just encoded.

        Guarded twice over, because a picture check must never be able to cost
        somebody a recording: `content_report` already refuses to raise, and
        this catches whatever a subclass's `_content_rect` might. A take whose
        measurement fails records *that*, in the timeline, rather than quietly
        omitting the field and reading like a take nobody thought to check.
        """
        if not self._converted:
            return
        try:
            rect = self._content_rect()
        except Exception as exc:  # noqa: BLE001 - see the docstring
            self._content = content_report(self._media_path(), None)
            self._content["note"] = (
                f"the recorder could not work out where the app sits in the "
                f"frame ({type(exc).__name__}: {exc}), so nothing about the "
                f"picture was measured"
            )
        else:
            # The beat log goes in, and it is what makes the held-picture arm
            # mean anything: without it a demo narrating over a rendered screen
            # and a demo nobody can see are the same number. See
            # CONTENT_ACTING_VERBS.
            self._content = content_report(self._media_path(), rect, self._beats)
            # What the take opened on, measured off the **encoded** mp4 — the
            # file a reviewer watches, and the one the opening hold has already
            # been applied to. That ordering is the whole check: a hold that
            # silently did nothing leaves a non-zero gap right here (#119).
            gap, note = opening_gap(self._media_path(), rect)
            self._content["opening"] = opening_report(gap, note, self._opening_held)
            warning = opening_warning(self._content["opening"])
            if warning:
                self._content["warnings"].append(warning)
        # On **both** paths above, and last. An overlay this recorder left up is
        # a fact about the picture whether or not the rect could be worked out,
        # and it is a `content` warning rather than an issue on purpose: it
        # answers the question `content` exists to answer, `stitch()` already
        # carries a segment's content warnings into the merged demo tagged with
        # the segment they came from, and `print_content_summary` suppresses
        # "shows a picture" when the list is non-empty — which is exactly the
        # line issue #163 measured being printed over an occluded take.
        if self._overlay_note:
            self._content["warnings"].append(self._overlay_note)

    def _timeline_doc(self, failure: dict | None = None) -> dict:
        """This take's beat log as a timeline document (see TIMELINE_SCHEMA).

        `failure`, when given, lands on the envelope as `failure` and is
        omitted entirely otherwise — see TIMELINE_SCHEMA.
        """
        mp4 = self._media_path()
        duration = None
        # `self._converted`, not `mp4.exists()` (issue #20). Re-recording into
        # a folder that already holds an older demo.mp4 is the ordinary way
        # this skill is used — `record.py` is committed so it can be re-run —
        # and a take that wrote no mp4 used to probe that file and report the
        # *previous* take's duration next to this take's beats. Silently, with
        # nothing for a consumer to tell it by, and `stitch()` offsets every
        # later segment's beats by exactly this number.
        if self._converted:
            try:
                duration = round(media_duration(mp4), 3)
            except (subprocess.CalledProcessError, ValueError, OSError):
                duration = None  # a timeline without it still beats none
                print(
                    f"demo-video: WARNING — {mp4.name} was written but ffprobe "
                    f"could not measure it, so timeline.json says "
                    f"duration: null. The beats are still right; anything "
                    f"that needs the length has to probe the file itself.",
                    file=sys.stderr,
                )
        else:
            print(
                "demo-video: this take encoded no mp4, so timeline.json says "
                "duration: null and nothing was measured. "
                + (
                    f"There *is* a {mp4.name} in {self.out_dir} — it is a "
                    f"previous run's, and this timeline does not describe it."
                    if mp4.exists()
                    else f"There is no {mp4.name} in {self.out_dir}."
                ),
                file=sys.stderr,
            )
        beats = [dict(beat) for beat in self._beats]
        issues = [dict(issue) for issue in self._issues]
        doc: dict = {
            "schema": TIMELINE_SCHEMA,
            "generated_by": "demo-video",
            "recorder": type(self).__name__,
            "segment": self.segment,
            "media": mp4.name,
            "duration": duration,
            # Which clock produced this take. Without it a still committed to a
            # repo carries no record of the conditions it was recorded under,
            # and a future diff cannot tell "the UI changed" from "the frozen
            # instant changed" — which is the one question this whole feature
            # exists to answer. `clock` is null when the page's clock was live.
            "determinism": {
                "deterministic": self.deterministic,
                "clock": self._clock if self.deterministic else None,
                "timezone_id": self._timezone_id,
                "locale": self._locale,
            },
            # The one field here that describes the *frames* rather than the
            # storyboard (issue #97). Null on a take that encoded no mp4 —
            # there is nothing to measure and a previous run's file is not this
            # take's — and a dict with `measured: false` and a `note` whenever
            # it could not be measured. Never silently absent.
            #
            # It carries no selector today and deliberately so (see
            # `_content_report`): this file is committed, and a field that
            # grows a quoted string
            # later must not be the one place the mask does not reach.
            "content": self._content,
            # The clock demo.mp4 is actually on, and the only field here that
            # is not a reading of `time.monotonic()` (issues #18, #215). See
            # _CaptureClock: Chromium stamps every screencast frame with the
            # host's wall clock, so a host that steps it moves the video out
            # from under the beats by exactly that much. `steps` is empty on
            # a host that did not step, which is the healthy answer and is
            # *not* the same as the key being absent.
            "capture_clock": self._capture_clock.report(),
            # Where the spoken lines landed in that mp4, and whether the clock
            # above could be corrected for when they did (issue #226). Null on
            # a take that mixed no speech, which is the same answer a take
            # that encoded nothing gives — in both cases there is no audio
            # track this could describe. Taken from `_convert`, not recomputed
            # here: what belongs in the artifact is what the mix did.
            "narration": self._narration,
            # Built from the *scrubbed* beats, not from `self._beats`, so a
            # still path or a caption that the mask reached is masked here too
            # rather than reappearing in the coverage table (issue #12).
            # Null on a take recorded outside a ticket.
            "coverage": coverage_report(self._criteria, beats),
            "beats": beats,
            "strict": self._strict,
            "issues": issues,
            "issue_count": self._issue_count,
        }
        # Absent on a clean take, so a successful take's timeline.json is
        # byte-for-byte what it was before this key existed — and so that its
        # presence is the whole signal, with no `failure: null` to skim past.
        if failure is not None:
            doc["failure"] = failure
        return doc

    # -- shared storyboard verbs -------------------------------------------

    def _idle(self, seconds: float) -> None:
        """Hold for `seconds`. Overridden by media that must keep working
        (pumping output) while the frame is held.

        Sliced against a deadline rather than one flat sleep, so page events
        are delivered while the beat they belong to is still open. Deadline,
        not accumulated slices: the pump costs about a millisecond and a
        storyboard's pacing must not drift by however many of them it took."""
        # Holding the frame is where a take spends most of its time, and it is
        end = time.monotonic() + seconds
        while True:
            self._pump_events()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(PUMP_INTERVAL_S, remaining))

    @_beat_verb("pause")
    def pause(self, seconds: float) -> None:
        """Hold the frame so viewers can read what is on screen."""
        self._idle(seconds)

    def _checked_ac(self, ac: object, where: str) -> list[str]:
        """The criterion ids this beat claims, validated against the declared
        set (issue #12).

        **Refused at the call, not recorded and sorted out later.** A tag
        naming a criterion that does not exist is an authoring typo, and the
        cost of letting it through is paid by the reader: the criterion the
        author *meant* comes back `unclaimed` while the storyboard looks like
        it covered everything. Same posture as `caption()` refusing a secret —
        an authoring error is cheapest to fix at the line that made it.
        """
        if ac is None:
            return []
        if isinstance(ac, str):
            ids = [ac]
        elif isinstance(ac, Sequence):
            ids = list(ac)
        else:
            # Checked before iterating: `list(7)` raises "'int' object is not
            # iterable", which names neither the verb nor the argument.
            raise TypeError(
                f"{where} was given ac={ac!r}: a criterion id is a string, or "
                f"a list of them"
            )
        for key in ids:
            if not isinstance(key, str):
                raise TypeError(
                    f"{where} was given ac={ac!r}: a criterion id is a string, "
                    f"or a list of them"
                )
        if not self._criteria:
            raise ValueError(
                f"{where} tags {', '.join(map(repr, ids))}, but this take "
                f"declared no acceptance criteria. Pass them to the recorder — "
                f"criteria={{'AC-1': 'the text from the ticket', ...}} — so the "
                f"timeline can report which of them nothing claimed."
            )
        unknown = [key for key in ids if key not in self._criteria]
        if unknown:
            raise ValueError(
                f"{where} tags {', '.join(map(repr, unknown))}, which "
                f"{'is' if len(unknown) == 1 else 'are'} not among this take's "
                f"declared criteria ({', '.join(map(repr, self._criteria))}). "
                f"A tag that names nothing would leave the criterion you meant "
                f"reported as unclaimed while the storyboard looks complete."
            )
        # De-duplicated, order kept: `ac=["AC-1", "AC-1"]` claims it once, and
        # `claimed` is a list of beats rather than a count of tags.
        return list(dict.fromkeys(ids))

    def caption(self, text: str, ac: str | Sequence[str] | None = None) -> None:
        """Show a narrator line at the bottom of the frame ("" hides it).

        With speech enabled the line is also spoken; the previous line
        always finishes before this one starts.

        `ac` names the acceptance criterion this line is here to demonstrate —
        `caption("The overdraft is rejected at submit.", ac="AC-3")`. It is a
        **claim**, recorded as one: see "acceptance criteria and coverage".
        """
        claims = self._checked_ac(ac, "caption()")
        # Synthesizing and waiting out the previous spoken line happens
        # *before* the beat opens: the beat's t_start is when this caption
        # reaches the screen, which is what a reviewer extracting a frame at
        # that timestamp expects to see.
        clip = self._prepare_line(text)
        with self._beat("caption", caption=text, **_ac_field(claims)):
            self.page.evaluate("t => window.__demoCaption(t)", text)
            self._caption = text
            self._start_line(clip)
            self.pause(self._caption_hold(text))

    def _caption_hold(self, text: str) -> float:
        """Minimum time a caption stays up. With speech on, the spoken line's
        duration governs pacing (a later line waits for it), so a short hold
        is enough. With speech off, hold long enough to actually read it —
        roughly reading speed, so viewers can read and watch at once."""
        if not text:
            return 0.3
        if self._speech:
            return 0.4
        words = len(text.split())
        return min(6.0, max(1.4, 0.6 + words * 0.34))

    def interlude(self, text: str, hold: float = 2.8, style: str = "card") -> None:
        """Bridge a jump in the demo; "" takes it down, whichever style is up.

        With speech enabled the line is spoken too, and `hold` is how long the
        card stays before the storyboard moves on (a clear always takes 0.6 s,
        long enough for the fade).

        style="card" (default) is a full-screen title card — right for real
        time-skips (minutes of background work) between segments. style="light"
        is a centered label over a soft scrim with the scene still visible —
        lighter, for short transitions where a full takeover feels heavy.

        **Raising dispatches on `style`; clearing does not** (issue #162).
        `style` describes how a label *appears*, and making it load-bearing on
        the way out gave `interlude("")` — the call this docstring and SKILL.md
        both document — a silent no-op against a `light` scrim, because the
        default `style="card"` sent the clear at the other element. Measured
        cost of that: a scrim and a stale label over the app for the last 17 s
        of a 48 s demo, with `warnings: []`, `issues: []` and
        "demo.mp4 shows a picture" on stderr. So a clear takes down whatever is
        up: both overlays, unconditionally, and it is cheap because taking down
        an overlay that was never raised does nothing visible either way."""
        clip = self._prepare_line(text)
        with self._beat("interlude", selector=style, caption=text):
            if text:
                fn = "__demoBridge" if style == "light" else "__demoInterlude"
                self.page.evaluate(f"t => window.{fn}(t)", text)
            else:
                self.page.evaluate(
                    "() => { window.__demoInterlude(''); window.__demoBridge(''); }"
                )
            self._start_line(clip)
            self.pause(hold if text else 0.6)

    @_beat_verb("hold")
    def hold(self, min_s: float = 1.5) -> None:
        """Keep the current frame up until the narration for the current
        caption finishes speaking — so a spotlight or highlight stays on
        screen for the whole spoken line instead of flashing. Holds at least
        `min_s` (a perception floor: ~1.5 s to notice and fixate on a change),
        which is also what governs pacing when narration is off. Use it right
        after setting a spotlight/emphasis."""
        remaining = self._line_end - time.monotonic()
        self._idle(max(min_s, remaining))


    def _before_shot(self) -> None:
        """Bring the screen up to date before a still is taken.

        The hook that keeps `shot` sealed. A medium sitting on buffered output
        (the terminal reads its PTY here) flushes it, and everything a still
        is *for* — the beat, the `ac` claim, the file the coverage report
        points at — stays the base's to guarantee.
        """

    def shot(self, name: str, ac: str | Sequence[str] | None = None) -> Path:
        """Still for the written guide -> images/<name>.png.

        `ac` names the acceptance criterion this still is here to demonstrate.
        A tagged `shot` is the strongest thing a coverage report can hand a
        reviewer — a committed picture of the moment, at a known timestamp.

        **Sealed** (see `MEDIUM_HOOKS`): a medium that replaced this would take
        the beat and its `ac` claim with it, and the coverage report reads
        nothing else. Medium-specific work goes in `_before_shot`.
        """
        self._before_shot()
        claims = self._checked_ac(ac, "shot()")
        path = self.images_dir / f"{name}.png"
        rel = path.relative_to(self.out_dir).as_posix()
        with self._beat("shot", selector=name, still=rel, **_ac_field(claims)):
            # Full-bleed on the web recorder — the whole page, no window
            # frame — so a still is not a crop of the video.
            self.page.screenshot(path=str(path))
        return path

    # -- speech (ElevenLabs narration) --------------------------------------

    def _prepare_line(self, text: str) -> Path | None:
        """Synthesize (or fetch cached) audio for a narration line, and wait
        out the previous line — never speak two lines at once, never show a
        caption while the voice is still on the previous one."""
        clip = None
        if self._speech and text:
            clip = tts_clip(
                text, self._tts_dir, self._voice_id, self._speech_model,
                self._api_key,
            )
        self._finish_line()
        return clip

    def _start_line(self, clip: Path | None) -> None:
        """Log the line as starting now, at the current video offset."""
        if clip is not None:
            now = time.monotonic()
            self._lines.append((now - self._t0, clip))
            self._line_end = now + media_duration(clip)

    def _finish_line(self, tail: float = 0.0) -> None:
        remaining = self._line_end - time.monotonic()
        if remaining > 0:
            self._idle(remaining + tail)

    # -- media conversion ---------------------------------------------------

    def _convert(self, webm: Path) -> None:
        mp4 = self._media_path()
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm)]
        narration: dict | None = None
        if self._speech:
            # Mix each narration clip in at the moment its line appeared —
            # **in the video**, which is not the moment the beat log recorded
            # (issue #226). See `mix_plan`: the log is `time.monotonic()`, the
            # frames are stamped with the host's wall clock, and a step between
            # the two is a voice that trails its caption for the rest of the
            # take. `self._capture_clock` has already been stopped by
            # `__exit__` at this point, so the record is the whole capture's.
            #
            # Segments always get an aac track (silence if no lines) so
            # stitch()'s lossless concat sees uniform streams.
            if self._lines:
                plan, clock = mix_plan(
                    [off for off, _ in self._lines], self._capture_clock.report()
                )
                narration = {"lines": plan, "clock_correction": clock}
                for _, clip in self._lines:
                    cmd += ["-i", str(clip)]
                delayed = ";".join(
                    f"[{i + 1}:a]adelay={int(round(line['at'] * 1000))}:all=1[a{i}]"
                    for i, line in enumerate(plan)
                )
                inputs = "".join(f"[a{i}]" for i in range(len(self._lines)))
                # aformat pins the layout: mixed mono TTS clips would
                # otherwise yield a mono track that -c copy concat can't
                # join with the stereo silence of a line-less segment.
                filt = (
                    f"{delayed};{inputs}amix=inputs={len(self._lines)}"
                    ":normalize=0,"
                    "aformat=sample_rates=44100:channel_layouts=stereo,"
                    "apad[aud]"
                )
            else:
                cmd += ["-f", "lavfi", "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=44100"]
                filt = "[1:a]apad[aud]"
            cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[aud]",
                    "-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-r", "25", "-movflags", "+faststart", str(mp4)]
        subprocess.run(cmd, check=True)
        self._postprocess(mp4)
        # Only now. Everything that reads `duration`, extracts a review frame,
        # or pulls the last frame into `failure/` asks this flag rather than
        # `mp4.exists()`, because the file may be a previous take's and the
        # flag cannot be (issue #20).
        self._converted = True
        # Set here rather than where it is computed, and for the same reason:
        # `timeline.json` would otherwise describe an audio track that ffmpeg
        # refused to write. A take whose conversion raised keeps
        # `narration: null`, which is what a take that mixed nothing says too —
        # and neither of them has an mp4 for it to be about.
        self._narration = narration
        spoken = f", {len(self._lines)} spoken lines" if self._speech else ""
        print(f"wrote {mp4} ({mp4.stat().st_size // 1024} kB{spoken})")
