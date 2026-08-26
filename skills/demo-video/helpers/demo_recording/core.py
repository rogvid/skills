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

from .camera import camera_filter, video_dimensions
from .content import (
    content_report,
    media_duration,
    opening_gap,
    opening_report,
    opening_warning,
    overlay_warning,
    print_content_summary,
)
from .coverage import (
    _ac_field,
    _checked_criteria,
    _checked_shows,
    _checked_ticket,
    _shows_field,
    _ticket_field,
    coverage_report,
)
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
from .narration import (
    DEFAULT_STABILITY,
    clip_gain_db,
    mix_plan,
    tts_clip,
)
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
    capture_clock_shift,
    evidence_name,
    write_timeline,
)

# The caption, the interlude card and the bridge scrim all render in the
# wrapper chrome's own document (chrome.py): the caption in its reserved
# band below the app rect, the cards in the card layer over it. Both media
# mount that chrome — the web recorder since #358/#361, the terminal since
# #362 — so the chrome document's inline `__demoCaption`/`__demoInterlude`/
# `__demoBridge` are the only renderers left, and this module keeps only the
# element ids they share with the verbs and the end-of-take probe.
#
# History: until #362 this module carried the in-page overlay path — a
# `_CAPTION_JS` init script drawing a fixed-bottom caption bar inside the
# recorded page (`_caption_bottom_px` placed it), an `_INTERLUDE_JS` builder
# with a per-medium stylesheet (`INTERLUDE_CSS_TERMINAL`, the #110/#291
# palette work), and a `_BRIDGE_JS` builder — because the terminal page was
# its own document with no chrome to host them. The terminal now records the
# shared chrome, the last consumer went with it, and a caption that dies
# with its document died as a class: no recorded page navigates its own
# chrome.
INTERLUDE_ID = "__demo_interlude"

# The web window's body — the fill chrome.py paints the dark rounded window
# with, and with it the pad around the app rect, the opening hold, and the
# interlude/criterion card in the card layer. One declaration for all of
# them, on purpose: on the wrapper path they all reach demo.mp4 through one
# encoder, so "the card is the window's own colour" is a single substitution
# (#360) — and the sameness is still graded out of the encoded pixels, never
# out of declarations (#297's two recorded anti-patterns).
#
# History (#291/#301/#355): the exit-time composite this outlived sent the
# card (a DOM element, through Chromium's VP8 screencast) and the window (a
# lossless screenshot, encoded once) to demo.mp4 through two different
# encoders. One declared colour arrived as two, five levels apart, spotted
# by eye in a shipped frame (#291); "the window's own colour" itself was the
# answer a human chose over warm paper and a bordered card, both rejected on
# watching (recorded on #291). Matching *as encoded* then required declaring
# two slightly different colours — the measured compensation constant
# `WEB_CARD_BODY = "#181726"`, swept over a hundred candidates to land one
# level off the window (#301). #355's structural half retired the class:
# one encoder, one declaration, and #361 deleted the compensated pair.
WEB_WINDOW_BODY = "#181825"

# How long a `criterion()` card stays up when the storyboard does not say.
#
# Not `interlude()`'s flat 2.8 s, because the two cards carry different things.
# An interlude is a phrase the storyboard author wrote to bridge a jump, and
# they can shorten it. A criterion is a clause out of somebody else's ticket,
# quoted verbatim precisely so that nobody can shorten it — and the whole point
# of putting it on screen is that a viewer reads it. So the default is reading
# speed over the words that are actually there (the same 0.6 + 0.34·words
# `_caption_hold` uses), floored at the interlude default so a three-word
# clause is not a flicker, and capped because a demo is 30-60 s and one card
# must not eat a fifth of it.
#
# A clause too long to read inside the cap is a clause too long for a card:
# pass `hold=` and accept the cost, or quote the sentence rather than the
# paragraph. Both bounds are graded one word either side of where they take
# over, in tests/unit.
CRITERION_HOLD_MIN_S = 2.8
CRITERION_HOLD_MAX_S = 9.0


# Lightweight bridge: a centered label over a soft scrim, with the scene
# still visible behind it. For short segment transitions where a full-screen
# interlude card would feel heavy. Rendered by the chrome document's own
# `__demoBridge` (chrome.py) — see the history note over INTERLUDE_ID.
BRIDGE_ID = "__demo_bridge"

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
#   * the recorder's own furniture (`#__demo…`, `#__term…`, `#__chrome…`) —
#     its motion is triggered by the storyboard, so it is already as
#     repeatable as the storyboard is, and killing it would only make
#     captions pop. `#__chrome…` joined the list in #362, when the rule
#     first reached the chrome document at all: the hold's 450 ms reveal is
#     recorder motion by the same reading as a caption's fade;
#   * anything carrying `data-demo-video-animate` — the documented opt-out for
#     an element that must keep painting. Chromium's screencast emits a frame
#     when the page paints (issue #18), so "no motion at all" is not a free
#     choice: a harness or a storyboard that needs the compositor awake marks
#     the element it keeps alive, and this rule cannot match it.
_FREEZE_MOTION_JS = """
(() => {
  const KEEP =
    ':not([data-demo-video-animate]):not([id^="__demo"]):not([id^="__term"])'
    + ':not([id^="__chrome"])';
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
            f"{step['delta'] * 1000:+.0f} ms at {step['t']:.1f}s" for step in self.steps
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


#: Finish every animation that has an end (see `_settle_animations`). Returns
#: the count, which nothing reads today — the value is that a future caller
#: can tell "settled nothing" from "could not run".
_SETTLE_JS = """() => {
  let done = 0;
  for (const a of document.getAnimations()) {
    try { a.finish(); done += 1; } catch (e) { /* infinite, or detached */ }
  }
  return done;
}"""


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
            "_opening_card",
            "_raise_outro",
            # extension points, each beside the sealed member it extends
            "_watch_extra",
            "_before_shot",
            "_hold_frame",
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
        speech_stability: float | None = None,
        strict: bool | None = None,
        deterministic: bool | None = None,
        clock: str | None = None,
        timezone_id: str | None = None,
        locale: str | None = None,
        evidence: bool | None = None,
        criteria: dict[str, str] | None = None,
        ticket: str | None = None,
        stills_only: bool | None = None,
        pace: float | None = None,
        intro: str | None = None,
        outro: str | None = None,
        window_title: str | None = None,
        # Window scale override (issue #397). Allows consumers to request a
        # larger/smaller app rect within the wrapper window. Accepts a single
        # float (applied to both width and height) or a tuple of (width_scale, height_scale).
        window_scale: float | tuple[float, float] | None = None,
        # Last, and kept last. `tests/unit`'s "a way to permit a public host
        # appears as a constructor argument" injection anchors on this line
        # followed by the closing paren, and a parameter added after it makes
        # that injection stop landing — which the fault-injection driver
        # refuses on (exit 3) rather than quietly passing.
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
        # Which ticket those clauses were copied out of (issue #275), as the
        # author wrote it. Stored and written down; never fetched, never
        # resolved — see `coverage.py`.
        self._ticket = _checked_ticket(ticket)
        self.images_dir = self.out_dir / "images"
        self._video_dir = self.out_dir / ".video"
        # Run the storyboard for its pictures and skip the video (issue #372).
        # Every verb still runs; what goes is the pacing, which exists for a
        # viewer's eyes and for nothing else — the field take this was measured
        # on spent 68% of 124 s holding frames, and `shot()` is a plain
        # `page.screenshot()` that has never had anything to do with the
        # recording.
        #
        # A *mode*, not a faster take, and the difference is written down
        # everywhere it could be mistaken: no screencast is attached, so there
        # is no webm, no encode, and no picture to measure; `timeline.json`
        # carries `mode: "stills"` with `media: null` and no `content`; and the
        # consumers that cut frames out of an mp4 refuse the directory by name.
        # This supersedes #354, which asked for the same run with the pictures
        # thrown away — one flag, because two would be two ways to be wrong.
        if stills_only is None:
            stills_only = _env_flag("STILLS_ONLY")
        self.stills_only = False if stills_only is None else bool(stills_only)
        if accent_rgb is None:
            raw = _env("ACCENT_RGB", "235,110,20")
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) != 3 or not all(p.isdigit() for p in parts):
                raise RuntimeError(
                    f"DEMO_VIDEO_ACCENT_RGB must be 'R,G,B', got {raw!r}"
                )
            accent_rgb = tuple(int(p) for p in parts)  # type: ignore[assignment]
        self._accent = ",".join(str(c) for c in accent_rgb)
        # The wrapper window's title bar. None means the medium picks its own
        # default: a web take names the app it is pointed at (its base_url's
        # host), a terminal take its `terminal_title`.
        self._window_title = window_title or _env("WINDOW_TITLE")
        # The opt-in opening title (web medium only — the terminal medium has
        # its own `interlude=` opening card). Empty string is off, same as
        # None: an intro that says nothing is no intro.
        self._intro = (intro or _env("INTRO") or "").strip() or None
        # The opt-in closing card, same terms. `_outro_up` is what turns the
        # envelope key on: a take that asked for an outro and lost it to a
        # late failure does not claim one.
        self._outro = (outro or _env("OUTRO") or "").strip() or None
        self._outro_up = False
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
        # Window scale override (issue #397). Allows consumers to request a
        # larger/smaller app rect within the wrapper window. Resolved from
        # explicit parameter > DEMO_VIDEO_WINDOW_SCALE env var > built-in default.
        if window_scale is None:
            raw_scale = _env("WINDOW_SCALE")
        else:
            raw_scale = str(window_scale)
        if raw_scale is None:
            width_scale = 0.80
            height_scale = 2 / 3
        else:
            parts = [p.strip() for p in raw_scale.split(",")]
            if len(parts) == 1:
                width_scale = height_scale = float(parts[0])
            elif len(parts) == 2:
                width_scale = float(parts[0])
                height_scale = float(parts[1])
            else:
                raise RuntimeError(
                    f"DEMO_VIDEO_WINDOW_SCALE must be 'WIDTH_SCALE' or 'WIDTH_SCALE,HEIGHT_SCALE', got {raw_scale!r}"
                )
        if not (0 < width_scale <= 1 and 0 < height_scale <= 1):
            raise RuntimeError(
                f"DEMO_VIDEO_WINDOW_SCALE values must be in (0, 1], got {width_scale},{height_scale}"
            )
        self._window_scale = (width_scale, height_scale)
        # Audience pacing (SKILL.md, "Pacing and perception"). A multiplier
        # over the holds this recorder *computes* — the no-speech caption
        # read time, and the defaults of hold(), interlude() and criterion()
        # — so one storyboard can serve a hurried viewer (pace < 1) or a
        # deliberate one (pace > 1) without being rewritten. A duration the
        # author wrote stays literal: pause(s), hold(min_s=…) and
        # interlude(hold=…) passed explicitly are requests, not defaults.
        # stills_only zeroes pacing entirely, so rehearsal speed does not
        # depend on whatever a take sets here.
        if pace is None:
            raw_pace: float | str = _env("PACE", "1.0")
        else:
            raw_pace = pace
        try:
            pace = float(raw_pace)
        except (TypeError, ValueError):
            raise RuntimeError(
                f"DEMO_VIDEO_PACE must be a number, got {raw_pace!r}"
            ) from None
        if pace <= 0:
            raise RuntimeError(
                f"DEMO_VIDEO_PACE must be positive, got {pace!r} — a take at "
                f"pace 0 never shows anything"
            )
        self._pace = pace
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
            raise RuntimeError("speech is forced on but ELEVENLABS_API_KEY is not set")
        if speech is True and self.stills_only:
            raise RuntimeError(
                "speech is forced on for a stills-only run, which encodes no "
                "mp4 and so has no audio track to mix a voice onto. Drop "
                "speech=True, or record a take."
            )
        self._speech = bool(api_key) if speech is None else speech
        if self.stills_only:
            self._speech = False
        self._api_key = api_key
        # Default voice "Sarah" is premade — works on free-tier keys.
        self._voice_id = voice_id or _env("VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
        self._speech_model = speech_model or _env(
            "SPEECH_MODEL", "eleven_multilingual_v2"
        )
        # Pinned voice stability (see narration.DEFAULT_STABILITY for the
        # measurement behind the default): without it the model's per-sentence
        # pacing wanders and consecutive lines read as different speeds.
        if speech_stability is None:
            raw_stability: float | str = _env(
                "SPEECH_STABILITY", str(DEFAULT_STABILITY)
            )
        else:
            raw_stability = speech_stability
        try:
            speech_stability = float(raw_stability)
        except (TypeError, ValueError):
            raise RuntimeError(
                f"DEMO_VIDEO_SPEECH_STABILITY must be a number, got {raw_stability!r}"
            ) from None
        if not 0.0 < speech_stability <= 1.0:
            raise RuntimeError(
                f"DEMO_VIDEO_SPEECH_STABILITY must be between 0 and 1, got "
                f"{speech_stability!r}"
            )
        self._speech_stability = speech_stability
        self._tts_dir = self.out_dir / ".tts"
        # The intro and outro cards are voiced from clips synthesized *here*,
        # in the constructor — never when the card is raised. The raise runs
        # on the capture clock, and the round trip paid there was 3.4 s of
        # silent card at the top of the delivered exec demo (its first line
        # mixed at t=3.557 for exactly this reason). A card raised over a
        # take must have its voice already in hand; the cache makes every
        # run after the first free.
        self._intro_clip = self._pre_synth(self._intro)
        self._outro_clip = self._pre_synth(self._outro)
        # Caption font size in px, handed to `chrome_html` by each medium's
        # `_start`. Both media record at true pixel size, so this is the
        # size on screen in the chrome's caption band. (The deleted
        # composite scaled the web page ~0.8 and compensated with 34px — see
        # web.py's history note.)
        self._caption_font_px = 26
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
        # The camera (see camera.py): each spotlight interval as geometry,
        # pushed in after the take, in _convert. An open event is the
        # spotlight on screen right now; it closes when the next spotlight
        # clears it, or with the take.
        self._camera: list[dict] = []
        self._camera_open: dict | None = None
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
            print(f"demo-video: narration ON (voice {self._voice_id})", file=sys.stderr)
        elif self.stills_only:
            print(
                "demo-video: narration OFF — a stills-only run encodes no "
                "mp4, so there is no track for a voice to go on.",
                file=sys.stderr,
            )
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
        # ...and, loudest of the three, that this run is not a recording. The
        # other two describe a take; this one says there is no take. Somebody
        # who set the env var in a shell three commands ago and then wondered
        # where demo.mp4 went is the reader.
        if self.stills_only:
            print(
                "demo-video: STILLS-ONLY run — the storyboard runs in full, "
                "every shot() is written to images/, and no video is "
                "recorded. Pacing is zeroed, narration is off, and "
                "timeline.json says mode: stills with media: null, so nothing "
                "downstream can read this as a take. Unset "
                "DEMO_VIDEO_STILLS_ONLY (or pass stills_only=False) to "
                "record one.",
                file=sys.stderr,
            )

    def _freeze_motion_here(self) -> None:
        """Re-attach the motion rule to a document `set_content` just wrote.

        `page.set_content` writes a new document into the same window. The
        `<style>` the context init script appended goes with the old one,
        and the init script does **not** run again — measured directly: a
        probe init script's counter stays at 1 across `set_content` while
        its style element is gone. Globals survive (same realm), which is
        why the frozen clock needs nothing here and this does.

        It went unnoticed while the only document either medium wrote its
        chrome into was the web wrapper, whose app is an iframe with a
        document of its own where the init script does run. #362 put the
        terminal's content *in* the written document, so every
        animation probe in this repository's `tests/smoke --terminal-only`
        read its authored duration — 2 s where the rule says 1 ms.

        A no-op unless `deterministic=True`, like the init script it
        repeats: the rule is opt-in and this does not widen that.
        """
        if not self.deterministic:
            return
        self.page.evaluate("() => {" + _FREEZE_MOTION_JS + "}")

    # -- subclass hooks -----------------------------------------------------

    def _init_context(self, context) -> None:
        """Add medium-specific context init scripts (runs before the page
        exists, so scripts re-inject on every navigation)."""

    def _start(self) -> None:
        """Post-page setup: navigate, inject assets, spawn processes."""

    def _stop(self) -> None:
        """Teardown before the browser closes (kill child processes, etc.)."""

    def _postprocess(self, mp4: Path) -> None:
        """Transform the finished mp4 in place. No-op by default, and both
        shipped recorders leave it that way: each frames itself in-page, so
        the recorded page is the finished picture and a take costs one video
        encode. (The web recorder's exit-time window composite was the one
        override; #361 deleted it — see web.py's history note.) The hook
        stays as the seam a future medium that must transform its file would
        use."""

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
            # Declining the screencast is the whole saving of a stills-only
            # run, and this is the only place it can be declined: Chromium
            # starts capturing with the page. `page.video` is then None, so
            # every downstream "did this take encode anything" answer —
            # `_converted`, `duration`, `content`, the beat-frame sheet —
            # follows from the recording that does not exist rather than from
            # a second flag somebody has to remember to check.
            self._context = self._browser.new_context(
                viewport=self._size,
                record_video_dir=(None if self.stills_only else str(self._video_dir)),
                record_video_size=None if self.stills_only else self._size,
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
            # No caption/card init scripts ride along: the chrome document
            # each medium's `_start` builds carries its own renderers
            # (chrome.py), and nothing calls them before it is up — see the
            # history note over INTERLUDE_ID.
            # Medium-specific init scripts (opening hold, spotlight, ...).
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
            # The opt-in closing card, while the page is alive and the
            # capture still running — the mirror of the intro, at the other
            # end. Never fatal: a take that recorded everything and lost its
            # outro to a late failure is a take without an outro, not a take
            # to throw away; the envelope key is what says whether it happened.
            if exc_type is None:
                try:
                    self._raise_outro()
                except Exception:  # noqa: BLE001 - the take is already on disk
                    pass
        # A spotlight still on at the take's end is a camera event with no
        # end; it ends with the take. On the failure path too — the timeline
        # is written either way, and an open event it never mentions would
        # describe a push the mp4 does not contain.
        self._camera_close()
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
                kind,
                message.text,
                url=where.get("url") or None,
                line=where.get("lineNumber"),
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
                url=request.url,
                method=request.method,
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
                "http_error",
                f"HTTP {response.status} {response.url}",
                url=response.url,
                status=response.status,
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
            f"  {i['kind']} in {self._issue_where(i)}: {i['message']}" for i in shown
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
        # Every field goes in as the storyboard gave it — the caption, the
        # selector, the still's name. Nothing here filters, and `caption()`
        # refuses nothing either (#138), so `timeline.json` is committed
        # carrying whatever the storyboard put in these arguments.
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
        from the page: every one of them is a frame of `demo.mp4`, so a
        reviewer reads what the video showed and not a second render that
        could differ from it. `tests/smoke` requires each PNG to be
        byte-identical to that second cut out of the mp4 again, instead of
        taking this paragraph's word for it.
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
            "media": self._media_name(),
            "beat": {
                key: beat.get(key)
                for key in (
                    "index",
                    "t_start",
                    "t_end",
                    "verb",
                    "selector",
                    "caption",
                    "still",
                    "evidence",
                )
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
            (
                out / evidence_name(beat["index"], self.segment),
                self._evidence_doc(beat, payload),
            )
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

        Called on the failure path only, **after `_stop()` and before the
        medium has been stopped** — that slot is the whole design. After
        `_stop()` because a medium can be sitting on output (`TerminalRecorder`
        holds back a possible half exit-marker and flushes it there), so an
        earlier reading is not the screen the recording ends on. Before the
        browser goes away, because there is no page to read afterwards. The
        third constraint this slot used to satisfy — read it *before* the
        redaction verifier, the hole PR #58 was blocked on — went with that
        verifier in #144, and nothing vouches for this text now.
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
        """The machine-readable half of `failure/`.

        Envelope, the failing beat in full, the issue log, and what was
        recorded — all of it as it came, because there is no masking anywhere
        in this recorder (#138). Nothing in here is read from the page either:
        the page text was buffered by `_capture_failure_screen` and only its
        presence is reported here, the issues and the beats have been in memory
        since they happened, and the media is named rather than opened.
        """
        beat = failed_beat(self._beats)
        doc: dict = {
            "schema": FAILURE_SCHEMA,
            "generated_by": "demo-video",
            "recorder": type(self).__name__,
            "segment": self.segment,
            "when": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
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
            "media": self._media_name(),
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

        The frame comes out of the mp4 with ffmpeg rather than off the page
        because by the time this runs there is no page: `__exit__` closes the
        context, the browser and Playwright before `_convert`, and this is
        called after all of it. It used to be argued for the other way round —
        the frame inheriting a guarantee the take had already earned — and the
        machinery that issued that guarantee went in #144. The PNG carries none
        now: it is the last frame of this take's recording, as it was recorded,
        and no more is claimed for it than for any other artifact here. Gated on
        `self._converted`, not on the file existing — a previous run's demo.mp4
        is not a picture of this crash (issue #20).
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
            (
                out / "failure.json",
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            ),
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

    def _media_name(self) -> str | None:
        """What an artifact should call this take's video — None on a stills
        run, where there is not one (issue #372).

        Null rather than the name it *would* have had. A name is a pointer,
        and in a directory that has been recorded into before — which is the
        ordinary case, because `record.py` is committed so it can be re-run —
        `demo.mp4` is sitting right there from a previous take. Writing the
        name anyway would point this run's timeline, its evidence documents
        and its failure dump at that file: the stale-`duration` lie of #20,
        one field over and in three more places.
        """
        return None if self.stills_only else self._media_path().name

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
            ids = [str(i) for i in up]
            if self._outro_up:
                # The outro card is this take's deliberate last frame, raised
                # by the recorder itself seconds ago. Warning "an overlay the
                # recorder left up" about the take's own ending would be the
                # probe grading its own feature. The bridge is not waived: an
                # outro never raises one, so a bridge up here is still a bug.
                ids = [i for i in ids if i != INTERLUDE_ID]
            if ids:
                self._overlay_note = overlay_warning(ids)

    def _raise_outro(self) -> None:
        """The opt-in closing card (`Recorder(outro=…)`, off by default).

        A no-op in the base: the card machinery is the wrapper document's,
        and only a medium that builds one can raise anything over it.
        """
        return None

    def _opening_card(self) -> dict | None:
        """What this take's **first frame** showed, for a medium that can say.

        A hook rather than an override (issue #235): `_measure_content` is
        sealed, because it is what guarantees every take a `content` block —
        and the medium seam's whole rule is that a medium extends by
        implementing a hook it was offered.

        Only `TerminalRecorder` answers. Its takes open on the chrome's hold
        (or the clause card `interlude=` raised over it), and a strip of the
        app rect says in one number whether that cover was up when the
        recording began (#362 moved the strip inside the window — see
        `terminal.OPENING_STRIP`). The web recorder answers None — its
        opening hold is graded by `tests/smoke --wrapper-only` and named by
        the review sheet on the frames cut inside it (frames.py) rather
        than this field claiming a card the medium did not measure — so None
        lands in the artifact as `content.opening.card: null`.
        """
        return None

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
            # The opening frame is *not* measured over `_content_rect`'s
            # answer — a medium whose chrome geometry survived still knows
            # where to look — so a take that lost one measurement does not
            # have to lose the other (issue #235). Without this the whole
            # `opening` block was null on this path, which is an absence
            # with no reason in it: a terminal take that had its geometry
            # and not its `#__term_host` box said nothing at all about the
            # frame it opened on, and nothing said why. `gap` genuinely
            # could not be measured here, and the note is where that is
            # written down.
            self._content["opening"] = opening_report(
                None,
                "the app rect could not be worked out, so the opening gap was "
                "not measured; `card` below is read off this medium's own "
                "window and is unaffected",
                self._opening_held,
            )
            self._content["opening"]["card"] = self._opening_card()
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
            # And what that first frame *was*, from the medium that can read
            # its own (issue #235). Reported, never enforced: it appends no
            # warning here, and see `opening_card_report` for the loaded-runner
            # measurement that decided it.
            self._content["opening"]["card"] = self._opening_card()
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
        elif self.stills_only:
            # Not a warning. A stills-only run encoding nothing is the mode
            # working, and printing the take's "no mp4" alarm over it would
            # train a reader to ignore the line that matters.
            print(
                "demo-video: stills-only run — no video was recorded, so "
                "timeline.json says mode: stills, media: null and "
                "duration: null."
                + (
                    f" The {mp4.name} in {self.out_dir} is a previous run's, "
                    f"and this timeline does not describe it."
                    if mp4.exists()
                    else ""
                ),
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
            # The ticket this take was recorded against, exactly as the
            # storyboard wrote it (issue #275). Absent on a take recorded
            # outside one, so a timeline written before this key existed reads
            # as it always did. Nothing here fetched or resolved it.
            **_ticket_field(self._ticket),
            "media": self._media_name(),
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
            # `_content_report`): this file is committed, nothing in this
            # recorder filters what goes into it, so a field that grows a
            # quoted string later publishes that string as it was written.
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
            # Built from the same `beats` list this document publishes, not
            # from `self._beats` again, so the coverage table and the beat log
            # can never disagree about what a beat claimed (issue #12).
            # Null on a take recorded outside a ticket.
            "coverage": coverage_report(self._criteria, beats),
            "beats": beats,
            "strict": self._strict,
            "issues": issues,
            "issue_count": self._issue_count,
        }
        # Present only when this take moved off the default pacing, for the
        # same reason `mode` and `failure` are absent on an ordinary take:
        # absence is the signal, and a reader skimming a fast take's
        # timeline.json sees why it is fast instead of guessing.
        if self._pace != 1.0:
            doc["pace"] = self._pace
        # Same absence-as-signal: a take that opened on an intro card says so,
        # and carries the sentence that was on it — the one string a reader of
        # frame 0 cannot recover from the beat table, which never shows it.
        if self._intro:
            doc["intro"] = self._intro
        # Presence is the signal, and the signal is also the honesty: an
        # outro that was asked for but never raised (a late TTS failure) is
        # a take without one, and this key is what says so.
        if self._outro_up:
            doc["outro"] = self._outro
        # The camera moves this take's mp4 was rendered with (see camera.py).
        # Presence is the signal, like intro and outro: a take without
        # push-ins reads as it always did. The rects are in output-frame
        # pixels — the coordinates a reader maps onto demo.mp4 — so the
        # moves can be re-rendered, audited, or graded without the take.
        if self._camera:
            doc["camera"] = [dict(event) for event in self._camera]
        # Both of these are the `failure` construction below, for the same
        # reason: **presence is the signal** (issue #372).
        #
        # `mode` is absent on a take, so a take's timeline.json is byte-for-byte
        # what it was before stills-only runs existed, and a reader that has
        # never heard of one is never handed `mode: "take"` to interpret.
        #
        # `content` is *removed* rather than left null, and the difference is
        # a real one. On a take, `content: null` means an mp4 was expected and
        # the picture could not be measured — the answer #97 exists to give.
        # A stills run has no frames at all, so it makes no claim about them:
        # the key is not there, and `mode` says why.
        if self.stills_only:
            doc.pop("content")
            doc["mode"] = "stills"
        # Absent on a clean take, so a successful take's timeline.json is
        # byte-for-byte what it was before this key existed — and so that its
        # presence is the whole signal, with no `failure: null` to skim past.
        if failure is not None:
            doc["failure"] = failure
        return doc

    # -- shared storyboard verbs -------------------------------------------

    def _idle(self, seconds: float) -> None:
        """Hold the frame for `seconds` — the one place this package waits.

        Every paced verb arrives here: `pause`, `hold`, the tail of a caption,
        an interlude, a criterion card, the terminal's per-keystroke delay.
        That is why the stills-only short-circuit is *here* and why `_idle`
        itself is sealed (issue #372). A medium extends the waiting by
        implementing `_hold_frame`; it cannot reach past the mode check, so
        there is no medium in which a stills-only run quietly still paces.

        The pump survives the short-circuit. Playwright's sync API delivers
        `console`/`pageerror` only while it is inside a call, so skipping it
        would hand every event a stills run provokes to whichever beat made
        the next call — the storyboard would run fast and misattribute what it
        found.

        What is deliberately *not* here is landing the animations the pacing
        used to land. That belongs to `shot()` and only there: a stills run's
        one visual output is the stills, so settling anywhere else would be a
        cost paid per beat for a picture nobody takes.
        """
        if self.stills_only:
            self._pump_events()
            return
        self._hold_frame(seconds)

    def _settle_animations(self) -> None:
        """Land every running animation on its end state (stills-only).

        **Zeroing the pacing is not enough on its own, and this is the half
        that was measured.** The determinism rule spares the recorder's own
        overlays — `#__demo*`, `#__chrome*`, anything marked
        `data-demo-video-animate` — precisely so a spotlight, a caption and an
        interlude card *do* fade on camera. In a take the hold after the verb
        is what lets them finish. Take the hold away and nothing does: the
        first stills run of the reference storyboard caught its criterion card
        mid-fade and its spotlight's scrim half-faded — dimming the whole app
        instead of picking out the tile the caption names — at 12.0 dB and
        21.7 dB PSNR from the take's own stills. A difference anyone would
        see, in the direction of showing less.

        So the mode restores by construction what the pacing used to restore
        by waiting. Every frame, not just the wrapper's: the app's own
        transitions were settled by the same hold, and a still of a panel
        halfway open is the same lie one field over.

        Called from `shot()` and nowhere else. Everything a stills run leaves
        behind is a document except the stills, and a document does not care
        what a transition was halfway through — so one evaluate per picture
        is the whole cost, rather than one per beat.

        Skipped rather than forced where there is no end to jump to — an
        infinite animation (a spinner) throws on `finish()`, and a spinner
        still spinning is what a take would have shown too. Never fatal: like
        the pump, this is here to make the picture right and is not a reason
        to lose a run.
        """
        for frame in self.page.frames:
            try:
                frame.evaluate(_SETTLE_JS)
            except Exception:  # noqa: BLE001 - a detached frame, mid-navigation
                continue

    def _hold_frame(self, seconds: float) -> None:
        """Wait out `seconds`. Overridden by media that must keep working
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

    def caption(
        self,
        text: str,
        ac: str | Sequence[str] | None = None,
        shows: str | None = None,
    ) -> None:
        """Show a narrator line at the bottom of the frame ("" hides it).

        With speech enabled the line is also spoken; the previous line
        always finishes before this one starts.

        `ac` names the acceptance criterion this line is here to demonstrate —
        `caption("The overdraft is rejected at submit.", ac="AC-3")`. It is a
        **claim**, recorded as one: see "acceptance criteria and coverage".

        `shows="unmet"` points the claim the other way (issue #374): this
        beat is evidence the clause is **not** met. It needs an `ac=` — unmet
        what — and it is the storyboard author's assertion, recorded as one
        exactly like the ordinary direction. Nothing in this recorder read the
        ticket or judged the frame.
        """
        claims = self._checked_ac(ac, "caption()")
        polarity = _checked_shows(shows, claims, "caption()")
        # Synthesizing and waiting out the previous spoken line happens
        # *before* the beat opens: the beat's t_start is when this caption
        # reaches the screen, which is what a reviewer extracting a frame at
        # that timestamp expects to see.
        clip = self._prepare_line(text)
        with self._beat(
            "caption", caption=text, **_ac_field(claims), **_shows_field(polarity)
        ):
            clipped = self.page.evaluate("t => window.__demoCaption(t)", text)
            self._note_caption_clipped(text, clipped)
            self._caption = text
            self._start_line(clip)
            self.pause(self._caption_hold(text))

    def _note_caption_clipped(self, text: str, clipped: object) -> None:
        """A caption surface that measured itself clipped gets written down.

        The chrome's `__demoCaption` (chrome.py, #358) returns the number:
        its caption band has a fixed height and `overflow: hidden` — the
        construction that keeps the app rect caption-free — so a caption
        too tall for the band is shaved at the band's edges while the beat
        log records the full sentence. Without this, that is `timeline.json`
        claiming a line the pixels do not show: measured on a 174-character
        caption, the band's flex centring shaved ~17 px off the top of the
        first line and the bottom of the third, `warnings` stayed empty and a
        strict take stayed green. Both media share the band since #362, so
        this fires on a terminal take exactly as on a web one. (The retired
        in-page overlay grew with its text and returned nothing — the None
        guard below is also what keeps a scripted page that answers nothing
        from minting an issue.)

        The text is deliberately **not** capped or reflowed — the honest
        artifact is the point. An issue rather than a refusal, and not in
        `STRICT_KINDS`: like `caption_lost` (#180), this is the storyboard's
        mistake, not the app saying it is broken. Attributed to the caption
        beat explicitly — it is the beat that painted the line.
        """
        if not isinstance(clipped, (int, float)) or clipped <= 0:
            return
        beat = self._beats[-1] if self._in_beat and self._beats else None
        self._note_issue(
            "caption_clipped",
            f"the caption {text!r} is {round(clipped)}px taller than the "
            f"caption band, so the band's edges shave its first and last "
            f"lines and the frames do not show the sentence the beat log "
            f"records — shorten the line, or split it over two captions",
            beat=beat,
            clipped_px=round(clipped),
        )

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
        return min(6.0, max(1.4, 0.6 + words * 0.34)) * self._pace

    def interlude(
        self, text: str, hold: float | None = None, style: str = "card"
    ) -> None:
        """Bridge a jump in the demo; "" takes it down, whichever style is up.

        With speech enabled the line is spoken too, and `hold` is how long the
        card stays before the storyboard moves on (a clear always takes 0.6 s,
        long enough for the fade). The default hold — 2.8 s — is scaled by
        this take's `pace`; an explicit `hold` stays literal.

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
            self.pause((2.8 * self._pace if hold is None else hold) if text else 0.6)

    def criterion(self, ac: str, hold: float | None = None) -> None:
        """Put a declared acceptance criterion's own sentence on screen.

        `rec.criterion("AC-2")` raises the full-screen card carrying the text
        of AC-2 **out of the `criteria=` map this take was constructed with** —
        never a string the storyboard retyped. That is the whole of the verb: a
        storyboard author cannot show a viewer a different sentence from the one
        the coverage table and the ticket quote carry, because there is one
        string and this reads it.

        The beat claims AC-2, so the card appears in `coverage` like any other
        claim. It claims **only itself**: the beats that follow are untouched,
        because a claim nobody typed is indistinguishable in the report from one
        somebody did.

        Refused when the id was never declared, and when the take declared no
        `criteria=` at all — the same two refusals, at the line that made them,
        for the same reasons as `caption(ac=...)`. One id and not a list: a card
        shows one sentence, and handed two it would have to drop one silently.

        The card is the element `interlude()` raises, so `interlude("")` takes
        it down and the "card left up" warning applies unchanged. **Take it
        down explicitly** — nothing else will notice (reference/limits.md).

        `hold` defaults to how long the clause takes to read, and to the whole
        spoken line when narration is on: see CRITERION_HOLD_MIN_S.
        """
        if not isinstance(ac, str):
            raise TypeError(
                f"criterion() was given ac={ac!r}: one criterion id, as a "
                f"string. A card shows one sentence — to claim several ids on "
                f"one screen, tag a caption or a shot with ac=[...]."
            )
        key = self._checked_ac(ac, "criterion()")[0]
        text = self._criteria[key]
        # Synthesized before the beat opens, exactly as `caption()` does it:
        # the beat's t_start has to be when the clause reached the screen, or a
        # reviewer extracting a frame at that timestamp gets the beat before.
        clip = self._prepare_line(text)
        with self._beat("criterion", selector=key, caption=text, **_ac_field([key])):
            self.page.evaluate("t => window.__demoInterlude(t)", text)
            self._start_line(clip)
            self.pause(self._criterion_hold(text) if hold is None else hold)

    def _criterion_hold(self, text: str) -> float:
        """How long a clause stays up when the storyboard does not say.

        Read speed over the clause, bounded by the two constants and scaled
        by `pace` like every other computed hold — never less than what is
        left of the line being spoken, because a card that leaves mid-sentence
        while the voice is still reading the clause is the one failure this
        verb exists to remove.
        """
        reading = (
            min(
                CRITERION_HOLD_MAX_S,
                max(CRITERION_HOLD_MIN_S, 0.6 + len(text.split()) * 0.34),
            )
            * self._pace
        )
        return max(reading, self._line_end - time.monotonic())

    @_beat_verb("hold")
    def hold(self, min_s: float | None = None) -> None:
        """Keep the current frame up until the narration for the current
        caption finishes speaking — so a spotlight or highlight stays on
        screen for the whole spoken line instead of flashing. Holds at least
        `min_s` (a perception floor: ~1.5 s to notice and fixate on a change),
        which is also what governs pacing when narration is off. Use it right
        after setting a spotlight/emphasis.

        The floor is 1.5 s scaled by this take's `pace` when `min_s` is not
        passed; an explicit `min_s` is the author's number and stays literal.
        """
        floor = 1.5 * self._pace if min_s is None else min_s
        remaining = self._line_end - time.monotonic()
        self._idle(max(floor, remaining))

    def _before_shot(self) -> None:
        """Bring the screen up to date before a still is taken.

        The hook that keeps `shot` sealed. A medium sitting on buffered output
        (the terminal reads its PTY here) flushes it, and everything a still
        is *for* — the beat, the `ac` claim, the file the coverage report
        points at — stays the base's to guarantee.
        """

    def shot(
        self,
        name: str,
        ac: str | Sequence[str] | None = None,
        shows: str | None = None,
    ) -> Path:
        """Still for the written guide -> images/<name>.png.

        `ac` names the acceptance criterion this still is here to demonstrate.
        A tagged `shot` is the strongest thing a coverage report can hand a
        reviewer — a committed picture of the moment, at a known timestamp.

        `shows="unmet"` says this picture is evidence the clause is **not**
        met — `shot("03-no-flag", ac="AC-2", shows="unmet")` (issue #374).
        That is the case worth the most to a reviewer, because it is the one
        reading the diff would not have told them. It is still a claim: the
        storyboard author asserted it, the recorder wrote it down, and nothing
        here compared the picture with the ticket.

        **Sealed** (see `MEDIUM_HOOKS`): a medium that replaced this would take
        the beat and its `ac` claim with it, and the coverage report reads
        nothing else. Medium-specific work goes in `_before_shot`.
        """
        # A stills run has no hold for the recorder's own overlays to finish
        # inside, so this is where they are finished (#372). Here and not in
        # `_idle`: the still is the only thing such a run renders. Read
        # `_settle_animations` — the picture it exists for was measured
        # 12.0 dB wrong without it.
        if self.stills_only:
            self._settle_animations()
        self._before_shot()
        claims = self._checked_ac(ac, "shot()")
        polarity = _checked_shows(shows, claims, "shot()")
        path = self.images_dir / f"{name}.png"
        rel = path.relative_to(self.out_dir).as_posix()
        with self._beat(
            "shot",
            selector=name,
            still=rel,
            **_ac_field(claims),
            **_shows_field(polarity),
        ):
            # The recorded page, chrome and all. On the wrapper path (#358)
            # that page *is* the framed picture, so a still and the frame the
            # video shows at the same instant are the same image — which is
            # what lets a stills-only run stand in for one (#372). The
            # comment this replaces described the composite, where the still
            # was full-bleed and the video was not; #368 deleted that path.
            self.page.screenshot(path=str(path))
        return path

    # -- camera (see camera.py) ----------------------------------------------

    def _camera_raise(self, rect: dict) -> None:
        """Open a camera event over the element just spotlighted. `rect` is
        the spotlight's own measurement of where the element sits in the
        recorded frame, in output-frame pixels."""
        self._camera_open = {
            "t_start": round(time.monotonic() - self._t0, 3),
            "rect": [rect["x"], rect["y"], rect["w"], rect["h"]],
        }

    def _camera_close(self, t_end: float | None = None) -> None:
        """End the open camera event, at `t_end` (now, unless given — the
        spotlight's clear hands in the moment the pull *starts*, because its
        evaluate waits out the fade). A degenerate event is dropped: a
        camera move with no length is not a move, and the timeline carries
        only what the mp4 will show."""
        if self._camera_open is None:
            return
        event = dict(self._camera_open)
        self._camera_open = None
        end = round(time.monotonic() - self._t0, 3) if t_end is None else round(t_end, 3)
        if end > event["t_start"]:
            event["t_end"] = end
            self._camera.append(event)

    def _camera_on_the_video_clock(self, record: object) -> list[dict]:
        """The camera events moved onto the clock the video is on.

        The events' times are beat-log instants — `time.monotonic()` minus
        `_t0` — and the video is stamped with the wall clock, so a host that
        stepped puts every event after the step that far ahead of the frames
        it names. The narration mix corrects its lines through
        `capture_clock_shift` (issue #226); the moves ride the same
        correction. An interval the step swallowed whole is dropped rather
        than rendered as a push with no length. The list is replaced, so the
        timeline this take writes describes the moves demo.mp4 actually
        carries."""
        place, _ = capture_clock_shift(record)
        corrected = []
        for event in self._camera:
            moved = dict(event)
            moved["t_start"] = round(place(event["t_start"]).at, 3)
            moved["t_end"] = round(place(event["t_end"]).at, 3)
            if moved["t_end"] > moved["t_start"]:
                corrected.append(moved)
        return corrected

    # -- speech (ElevenLabs narration) --------------------------------------

    def _pre_synth(self, text: str | None) -> Path | None:
        """Synthesize a card's line off the clock — the constructor calls this
        for the intro and outro, whose raises happen on the capture clock."""
        if not (self._speech and text):
            return None
        return tts_clip(
            text,
            self._tts_dir,
            self._voice_id,
            self._speech_model,
            self._api_key,
            stability=self._speech_stability,
        )

    def _prepare_line(self, text: str, preset: Path | None = None) -> Path | None:
        """Resolve the audio for a narration line, and wait out the previous
        line — never speak two lines at once, never show a caption while the
        voice is still on the previous one. `preset` is a clip already
        synthesized off the clock (a card's line); when it is handed in there
        is nothing left to synthesize and none is paid for."""
        clip = None
        if preset is not None:
            clip = preset
        elif self._speech and text:
            clip = tts_clip(
                text,
                self._tts_dir,
                self._voice_id,
                self._speech_model,
                self._api_key,
                stability=self._speech_stability,
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
        # The camera (see camera.py): one eased push-in per spotlight
        # interval, rendered here, in the same encode as the narration mix.
        # A take with no spotlight intervals builds no chain and encodes
        # exactly as it did before the camera existed.
        #
        # **The camera renders in its own pass, and that is load-bearing.**
        # The mix below maps video straight from its input and filters only
        # audio — one graph output, `-shortest` cutting the pad. Adding the
        # camera chain as a second graph output next to that audio made
        # ffmpeg buffer the whole video through the interleaving queue:
        # measured at 2.8 GB resident and "No space left on device" on a
        # 54 s take, and a plain `fps,scale` video branch hangs the same
        # way, so it is the two-output shape, not zoompan. A video-only
        # pre-pass is a single-output graph — the shape the mix always
        # used — and the mix then reads its frames like any other input.
        source = webm
        if self._camera:
            self._camera = self._camera_on_the_video_clock(
                self._capture_clock.report()
            )
        if self._camera:
            src_w, src_h = video_dimensions(webm)
            chain = camera_filter(
                self._camera,
                src_w=src_w,
                src_h=src_h,
                out_w=self._size["width"],
                out_h=self._size["height"],
            )
            source = webm.with_suffix(".camera.mp4")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-i", str(webm),
                    "-filter_complex", f"[0:v]{chain}[v]",
                    "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                    "-r", "25",
                    str(source),
                ],
                check=True,
            )
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source)]
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
                    [off for off, _ in self._lines],
                    self._capture_clock.report(),
                    # The clips' own lengths: without them the corrected
                    # placements cannot be serialized, and a backward step
                    # between two lines mixes one voice over another
                    # (measured at 1.6 s of overlap on a −1.65 s step).
                    [media_duration(clip) for _, clip in self._lines],
                )
                narration = {"lines": plan, "clock_correction": clock}
                for _, clip in self._lines:
                    cmd += ["-i", str(clip)]
                # Per-clip gain to one loudness target. ElevenLabs returns
                # clips at whatever level the model produced, and mixed as-is
                # consecutive lines sit at audibly different levels. Measured
                # per clip, applied here where the mix is built; a clip that
                # cannot be measured gains nothing and says so in its line.
                gains = [clip_gain_db(clip) for _, clip in self._lines]
                for line, gain in zip(plan, gains, strict=True):
                    if abs(gain) >= 0.1:
                        line["gain_db"] = gain
                delayed = ";".join(
                    f"[{i + 1}:a]"
                    + (f"volume={gain:.2f}dB," if abs(gain) >= 0.1 else "")
                    + f"adelay={int(round(line['at'] * 1000))}:all=1[a{i}]"
                    for i, (line, gain) in enumerate(zip(plan, gains, strict=True))
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
                cmd += [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                ]
                filt = "[1:a]apad[aud]"
            cmd += [
                "-filter_complex",
                filt,
                "-map",
                "0:v",
                "-map",
                "[aud]",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
            ]
        cmd += [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            "-r",
            "25",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
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
