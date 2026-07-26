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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from playwright.sync_api import Page, sync_playwright

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
_INTERLUDE_JS = """
window.__demoInterlude = (text) => {
  let el = document.getElementById('__demo_interlude');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_interlude';
    el.style.cssText = `
      position: fixed; inset: 0; display: flex; align-items: center;
      justify-content: center; background: #1c1a17; color: #f7f4ee;
      font: 500 30px/1.5 system-ui, sans-serif; text-align: center;
      padding: 0 12%; z-index: 2147483647; opacity: 0;
      transition: opacity .45s ease; pointer-events: none;
    `;
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = text ? '1' : '0';
};
"""


# Lightweight bridge: a centered label over a soft scrim, with the scene
# still visible behind it. For short segment transitions where a full-screen
# interlude card would feel heavy.
_BRIDGE_JS = """
window.__demoBridge = (text) => {
  let el = document.getElementById('__demo_bridge');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_bridge';
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


# -- secrets -----------------------------------------------------------------
#
# Demos run against seeded-but-realistic data, and a published video leaks
# permanently. Two registries, both living here in the base rather than in a
# medium's module, because every medium needs them and the terminal recorder's
# PTY scrubber (issue #5) is meant to read the same one the web recorder does:
#
#   register_secret(...)  literal text that must never be captioned, spoken,
#                         or written into the beat log
#   redact(...)           where the secret *renders* — a web selector today;
#                         medium-specific, so each medium defines its own
#
# What `register_secret` buys is deliberately blunt: a caption or an interlude
# line containing a registered secret raises SecretLeak and **fails the take**.
# It does not quietly mask the line, because a secret in a caption is an
# authoring bug — the storyboard said to put it on screen and speak it aloud,
# and the only safe answer is to stop and make the author fix the words.
# `scrub()` is the softer sibling, for output nobody authored (a shell's stdout
# on the terminal path).

# What `scrub()` leaves behind. Fixed-width-ish and obviously deliberate, so a
# reader of a scrubbed line can tell "something was removed here" from "the
# tool mangled my output".
SECRET_MASK = "[redacted]"


class SecretLeak(RuntimeError):
    """A registered secret reached something that leaves the machine.

    Raised out of the storyboard, so the take dies before the mp4 is written
    (`__exit__` skips conversion when an exception is in flight). Never carries
    the secret in its message.
    """


class Secret:
    """A value the demo must type but must never show, speak, or log.

        rec.type_into("#token", Secret("sk-live-..."))

    Registering happens as a side effect of using it, so there is no way to
    type one and forget to register it.

    Deliberately **not** a `str` subclass, which would be more convenient and
    considerably more dangerous: `_verb_target` below picks the first string
    argument of a verb as that beat's `selector`, so a str-subclassed Secret
    handed to any verb would be written into timeline.json verbatim — a file
    this skill tells people to commit. Being a distinct type also makes
    `isinstance` the test for "this needs redacting", and makes an accidental
    f-string print the mask instead of the value.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("Secret() takes a non-empty string")
        self._value = value

    def reveal(self) -> str:
        """The real value. The only way to get it, and named so that reading
        the storyboard shows exactly where the plaintext is used."""
        return self._value

    def __repr__(self) -> str:
        return f"Secret(<{len(self._value)} chars>)"

    def __str__(self) -> str:
        return SECRET_MASK


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


def media_duration(path: Path) -> float:
    """Duration of any media file in seconds, via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def tts_clip(
    text: str,
    cache_dir: Path,
    voice_id: str,
    model_id: str,
    api_key: str,
) -> Path:
    """Synthesize one narration line with ElevenLabs, cached by content.

    The cache key includes voice and model, so switching either re-generates.
    Cached clips make retakes free — the API is only hit for new lines.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice_id}|{model_id}|{text}".encode()).hexdigest()[:20]
    clip = cache_dir / f"{key}.mp3"
    if clip.exists():
        return clip
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": model_id}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    # Free-tier keys get 429 "system_busy" under load, and any network can
    # blip mid-recording — retry with backoff rather than losing a take.
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                partial = clip.with_suffix(".part")
                partial.write_bytes(resp.read())
                partial.rename(clip)  # atomic: no truncated clip is cached
            return clip
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(
                f"ElevenLabs TTS failed ({e.code}): {detail}"
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e
    raise AssertionError("unreachable")


# -- beat timeline -----------------------------------------------------------
#
# Every storyboard verb the recorder runs is logged as a *beat*: what was
# done, when, and what caption was on screen while it happened. On clean exit
# the log lands next to the media as timeline.json (machine-readable) and
# timeline.md (human-readable, with the stills embedded).
#
# This is a published contract, not a private convenience — beat-aligned frame
# extraction, per-beat evidence capture and acceptance-criterion coverage all
# read it. Treat it as append-only: adding a key to a beat or to the envelope
# is fine, renaming or repurposing one is not (bump TIMELINE_SCHEMA if you
# ever must).
#
# Envelope
#   schema        int    — TIMELINE_SCHEMA, bumped on any breaking change
#   generated_by  str    — always "demo-video"
#   recorder      str    — "Recorder" | "TerminalRecorder" (which medium), or
#                          "mixed" on a merged demo whose segments differ
#   segment       str?   — the segment name, or null for a whole demo
#   media         str    — the mp4 this timeline describes, e.g. "demo.mp4"
#   duration      float? — that mp4's real duration (ffprobe), null if absent
#   determinism   dict   — the conditions the take was recorded under:
#                          `deterministic` (was the clock frozen and motion
#                          flattened), `clock` (the frozen instant, null when
#                          the page's clock ran), `timezone_id`, `locale`.
#                          On a merged demo each value is the one every segment
#                          agrees on, or null where they disagree — the
#                          per-segment truth is in `segments`.
#   segments      list?   — merged demos only (`stitch`): one record per part,
#                          in order, each `segment`, `media`, `duration`
#                          (ffprobe), `offset` (where it starts in `media`),
#                          `beats`, `recorder`, `determinism`. Absent from a
#                          timeline a single take wrote.
#   beats         list   — the beats, in the order they ran
#   strict        bool   — whether strict mode was on for this take (on a
#                          merged demo: only if it was on for every segment)
#   issues        list   — the problems the take recorded (see "take issues")
#   issue_count   int    — how many were seen; > len(issues) only if capped
#
# Beat
#   index     int    — position in `beats`, 0-based. Renumbered by `stitch`, so
#                      it is always the beat's position *in this file*.
#   t_start   float  — seconds from the start of `media` to the verb starting
#   t_end     float  — seconds from the start of `media` to the verb returning
#   caption   str    — the caption text on screen during the beat (the new
#                      text for a `caption` beat, the line shown for an
#                      `interlude` beat); "" when no caption is up
#   verb      str    — the storyboard verb: "caption", "click", "run", ...
#   selector  str?   — what the verb acted on, as a string: a CSS selector for
#                      the web verbs, the command / keys / pattern for the
#                      terminal ones, the path for `goto`. Null when the verb
#                      has no target (`pause`, `hold`, a cleared `spotlight`).
#   still     str?   — for `shot` beats, the still's path relative to the
#                      timeline file ("images/01-dashboard.png"); else null
#   segment   str?   — the segment this beat was recorded in, or null
#   segment_index
#             int    — the beat's position within its own segment. Equal to
#                      `index` in a take's own timeline, and *unchanged* by a
#                      merge — so `(segment, segment_index)` names a beat the
#                      same way before and after `stitch`, which `index` alone
#                      cannot (see issue #22).
#   exit_code int?   — TerminalRecorder `run` beats only: the shell's status
#                      for that command, or null if it could not be read
#
# Only the verb a storyboard calls becomes a beat. The verbs recorders build
# out of other verbs (`click` glides with `move_to`, `type_into` clicks first)
# record one beat spanning the whole call, not one per internal step.
TIMELINE_SCHEMA = 1

# -- take issues -------------------------------------------------------------
#
# A demo that looks perfect while the app throws on every render passes any
# review that only watches pixels. So the recorders also watch the *app*: the
# browser console, uncaught page exceptions, requests that never completed,
# responses that came back >= 400, and — for TerminalRecorder — the exit status
# of every command `run()` typed. Each becomes an issue on the timeline, and
# each is attributed to the beat that was open when it fired, so a reviewer
# reads "the take broke during `click('#refresh')`" instead of "the take broke".
#
# Issue (part of the envelope's `issues`, same append-only rules as a beat)
#   kind     str   — one of ISSUE_KINDS below
#   t        float — seconds from the start of `media` to *observing* it
#   beat     int?  — index of the beat it is attributed to, or **null** when no
#                    beat can honestly claim it (see below)
#   verb     str?  — that beat's verb, denormalized so the list reads alone
#   caption  str   — the caption on screen at the time, same reason
#   message  str   — one human-readable line
#   plus kind-specific keys: `url`/`line` (console), `url`/`method`
#   (request_failed), `url`/`status` (http_error), `exit_code`/`command`
#   (nonzero_exit)
#
# `t` is when the problem was *observed*, which is not always when it happened:
# Playwright's sync API only delivers page events while it is being called, and
# a command's exit status is only knowable once the prompt comes back. `beat`
# is the attribution to trust; `t` is a hint.
#
# **`beat` is null whenever it cannot be established, and that is a feature.**
# The obvious implementation — blame the most recently started beat — is wrong
# in both directions: it hands an error thrown during a three-second hold to
# whatever beat makes the next Playwright call, quoting a caption that appeared
# after the error did, and it lets a beat that has already closed claim
# something that happened after it. So holds pump events as they wait
# (`_pump_events`), and an event is only attributed to a beat that was open,
# and had been open since events were last known to be flowing
# (`_attributed_beat`). A confidently wrong beat index is worse input for a
# reviewer — or for a conformance gate reading this file — than no answer.
ISSUE_KINDS = (
    "console_error",    # console.error(...) from the page
    "console_warning",  # console.warn(...) from the page
    "page_error",       # an uncaught exception / unhandled rejection
    "request_failed",   # a request that never got a response at all
    "http_error",       # a response with status >= 400
    "nonzero_exit",     # a TerminalRecorder run() whose command failed
)

# What `strict=True` refuses to pass: the app saying, in its own voice, that it
# is broken. `console_warning`, `request_failed` and `http_error` are recorded
# but not fatal on their own — a warning is not a failure, and a request the
# storyboard never depended on is the recorder's business to report, not to
# veto.
#
# In practice that distinction is narrower than it looks, and deliberately so:
# Chromium writes its own "Failed to load resource: …" line to the console for
# every request that fails or comes back >= 400, and that line is a genuine
# console error. So a strict take *does* fail on a 404 — including a favicon
# — because the browser complained about it out loud. Strict means strict; a
# demo of an app that cannot load its own assets is a demo of a broken app.
# Anything less deterministic than that belongs in the log, not in the verdict.
STRICT_KINDS = ("console_error", "page_error", "nonzero_exit")

# A page that throws on every render can throw thousands of times. Record the
# first MAX_ISSUES in full and keep counting the rest — `issue_count` in the
# envelope stays honest, and timeline.json stays a file somebody can open.
# Strict mode counts fatals separately and is *not* capped: a take whose 201st
# problem is its first console error still has to fail.
MAX_ISSUES = 200

# How often a hold gives Playwright a chance to deliver queued page events, and
# how stale that last delivery may be before a beat is no longer allowed to
# claim an event. See `_pump_events` and `_attributed_beat`.
PUMP_INTERVAL_S = 0.1
ATTRIBUTION_SLACK_S = 0.5


class StrictTakeFailed(RuntimeError):
    """A strict take finished, but recorded a problem it refuses to pass.

    Raised out of `__exit__` *after* the mp4, the stills and the timeline have
    been written — a broken take is exactly the one somebody wants to look at,
    so failing it must not also destroy the evidence.
    """


def timeline_paths(out_dir: Path | str, segment: str | None = None) -> tuple[Path, Path]:
    """(json, md) paths for a take's timeline.

    Mirrors how the media is named: a whole demo writes timeline.json next to
    demo.mp4, a segment writes <segment>.seg.timeline.json next to
    <segment>.seg.mp4, so segments of one demo never overwrite each other.
    """
    stem = f"{segment}.seg.timeline" if segment else "timeline"
    out_dir = Path(out_dir)
    return out_dir / f"{stem}.json", out_dir / f"{stem}.md"


def _md_cell(value: object) -> str:
    """A value made safe to drop into a markdown table cell."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def _fmt_t(value: object) -> str:
    return "" if value is None else f"{float(value):.2f}"


def render_timeline_md(doc: dict) -> str:
    """Render a timeline document as markdown, stills embedded.

    Pure function of the document, so anything that *builds* a document —
    a take on exit, or a stitch that merges several — renders the same way.
    """
    beats = doc.get("beats") or []
    head = [f"`{doc.get('media') or 'demo.mp4'}`"]
    if doc.get("segment"):
        head.append(f"segment `{doc['segment']}`")
    if doc.get("recorder"):
        head.append(str(doc["recorder"]))
    if doc.get("duration") is not None:
        head.append(f"{float(doc['duration']):.1f}s")
    head.append(f"{len(beats)} beats")
    # Where the seams are. A merged demo's beat times are continuous across
    # them, so nothing in the table below says a segment boundary happened —
    # and a reviewer wondering why the scene jumps at 8.4s deserves an answer.
    # It also changes what "do not edit this, regenerate it" means: a merged
    # document comes back from stitch(), not from re-recording.
    segments = doc.get("segments") or []
    out = [
        "# Demo timeline",
        "",
        " · ".join(head),
        "",
        "Written by the demo-video recorder when it stitched the segments "
        "below — do not edit it by hand, re-stitch instead."
        if segments
        else "Written by the demo-video recorder on every clean exit — do not "
        "edit it by hand, re-record instead.",
        "",
    ]
    if segments:
        spans = ", ".join(
            f"`{s.get('segment')}` "
            f"({_fmt_t(s.get('offset'))}–"
            f"{_fmt_t((s.get('offset') or 0) + (s.get('duration') or 0))}s)"
            for s in segments
        )
        out += [
            f"Stitched from {len(segments)} segments, in order: {spans}. Beat "
            f"times below are on the stitched video's clock.",
            "",
        ]
    # The exit column only exists when something in this take has one — a web
    # timeline would otherwise carry an empty column on every row. A `run` beat
    # whose status could not be read shows "?" rather than blank, so the
    # degraded case is visible here and not only in the JSON.
    shows_exit = any("exit_code" in b for b in beats)
    if shows_exit:
        out += [
            "| # | start | end | verb | target | exit | caption |",
            "|---:|---:|---:|---|---|---:|---|",
        ]
    else:
        out += [
            "| # | start | end | verb | target | caption |",
            "|---:|---:|---:|---|---|---|",
        ]
    for beat in beats:
        target = beat.get("selector")
        cells = [
            str(beat.get("index")),
            _fmt_t(beat.get("t_start")),
            _fmt_t(beat.get("t_end")),
            f"`{_md_cell(beat.get('verb'))}`",
            f"`{_md_cell(target)}`" if target else "",
        ]
        if shows_exit:
            if "exit_code" not in beat:
                cells.append("")
            elif beat["exit_code"] is None:
                cells.append("?")
            else:
                cells.append(_md_cell(beat["exit_code"]))
        cells.append(_md_cell(beat.get("caption")))
        out.append("| " + " | ".join(cells) + " |")
    issues = doc.get("issues") or []
    if issues:
        total = doc.get("issue_count", len(issues))
        out += [
            "",
            "## Issues",
            "",
            f"{total} recorded while this take ran — console errors, failed "
            f"requests, and non-zero exit codes, each attributed to the beat "
            f"it fired during. A demo can look perfect and still be a "
            f"recording of a broken app.",
            "",
        ]
        # A bullet list rather than a table on purpose: a table row starting
        # `| 0 |` is indistinguishable from a beat row to anything counting
        # the beat table above.
        for issue in issues:
            where = (
                "before the first beat"
                if issue.get("beat") is None
                else f"beat {issue['beat']} (`{_md_cell(issue.get('verb'))}`)"
            )
            out.append(
                f"- **{_md_cell(issue.get('kind'))}** — {where} at "
                f"{_fmt_t(issue.get('t'))}s: {_md_cell(issue.get('message'))}"
            )
        if total > len(issues):
            out.append(f"- …and {total - len(issues)} more, not recorded.")
        out.append("")
    stills = [b for b in beats if b.get("still")]
    if stills:
        out += ["", "## Stills", ""]
        for beat in stills:
            rel = str(beat["still"])
            name = rel.rsplit("/", 1)[-1].removesuffix(".png")
            out += [f"### {name} — {_fmt_t(beat.get('t_start'))}s", ""]
            if beat.get("caption"):
                out += [f"> {beat['caption']}", ""]
            out += [f"![{name}]({rel})", ""]
    return "\n".join(out).rstrip() + "\n"


def write_timeline(out_dir: Path | str, doc: dict) -> tuple[Path, Path]:
    """Write a timeline document as timeline.json + timeline.md."""
    json_path, md_path = timeline_paths(out_dir, doc.get("segment"))
    json_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_timeline_md(doc))
    return json_path, md_path


# -- beat-aligned review frames ----------------------------------------------
#
# Nobody driving this skill can watch a video, so every review of a demo is a
# review of frames pulled out of it. Sampling those uniformly in time
# (`ffmpeg -vf fps=1/3`) misses a short beat entirely and photographs a long
# static one twice, so the frames come off the beat log instead: one per beat,
# at the beat's **midpoint**. `t_start` is the wrong instant to photograph —
# for a `caption` beat it is 0% into the bar's fade-in, and for any other verb
# it is before the verb has done anything. The midpoint is inside the beat by
# construction, which is what `t_end` is on the record for.
#
# **These frames carry no caption, and that is deliberate.** The obvious next
# step is to print each frame under the line that was on screen when its beat
# ran, and it is not sound: the beat log and the video are on different clocks
# (issue #18), so a frame taken at a beat's timestamp can show the neighbouring
# line — and it would arrive labelled with the log's, which is worse than no
# label at all. An earlier version of this file tried to recover the mapping by
# finding caption transitions in the video. Review found it mislabelling frames
# on ordinary storyboards, three ways that are not fixable by tuning:
#
#   * two captions of the same length ("Step 1 of 3." -> "Step 2 of 3.") change
#     only glyph pixels — under 0.25 mean luma in the caption band, which is
#     no signal at all, so whatever else repainted in the window wins;
#   * an app that keeps repainting under the bar supplies a stronger edge than
#     the caption does, at a time of its own choosing;
#   * a mid-take `goto()` destroys the caption bar with the document and logs
#     no caption change at all, so there is nothing to measure and every later
#     frame is captioned with a line that is not on screen.
#
# All three are the same mistake — guessing which pixel change was the caption.
# The sound fix is for the recorder to *state* the mapping rather than have it
# inferred, by rendering the beat index into the frame where extraction can
# read it back. That changes every recording's pixels, so it is its own change:
# issue #60. Until then these frames are handed over bare, which is what the
# uniform sampling they replace did too — they are simply aimed better.
#
# `frames.md` therefore prints no caption, no verb and no selector. It is the
# sheet handed to a **context-free** reviewer who is asked what story the
# pictures tell; a `click('#refresh')` in the margin answers the question for
# them.
FRAMES_DIRNAME = "frames"
FRAMES_SCHEMA = 1

# Scene-change detection, the fallback for what the storyboard did not script.
# A beat that holds the frame for seconds can still contain a transition
# nobody wrote down — an app finishing a load, a toast appearing, a redirect —
# and beat alignment is blind to those by construction. Only for beats long
# enough that one could hide in them.
#
# The threshold is low because ffmpeg scores a whole frame and only part of one
# of these is the app: the recorder's own chrome is a fifth to a third of the
# picture and never moves. Measured over the reference takes — a page's first
# paint 0.041, a caption appearing 0.022-0.025, a table filtering to one row
# 0.013, an idle hold 0.007 and under. Issue #57 proposes scoring the app's own
# rect instead, which would make one threshold mean the same thing in both
# media.
SCENE_MIN_SPAN_S = 3.0
SCENE_THRESHOLD = 0.02
SCENE_MAX_EXTRA = 3

# Keep the last frame inside the file: an -ss exactly at the duration decodes
# nothing.
_FRAME_EDGE_S = 0.05


def frames_paths(out_dir: Path | str) -> tuple[Path, Path, Path]:
    """(dir, json, md) for a take's beat frames."""
    frames_dir = Path(out_dir) / FRAMES_DIRNAME
    return frames_dir, frames_dir / "frames.json", frames_dir / "frames.md"


def scene_times(
    mp4: Path,
    start: float,
    end: float,
    threshold: float = SCENE_THRESHOLD,
    limit: int = SCENE_MAX_EXTRA,
) -> list[float]:
    """Video times between `start` and `end` where the picture changes hard.

    The fallback for what the storyboard did not script. Returns at most
    `limit` times, in order, and an empty list for a stretch of video that
    holds still.
    """
    if end - start <= 0:
        return []
    # `metadata=print:file=-` rather than the filter's default: the default
    # writes through ffmpeg's logger at INFO level, which `-v error` throws
    # away — a silent way for this whole function to always return nothing.
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
         "-i", str(mp4),
         "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return []
    times = [
        start + float(match)
        for match in re.findall(r"pts_time:([0-9.]+)", proc.stdout)
    ]
    # The first decoded frame of a seek has nothing before it to be compared
    # with, and ffmpeg scores it 1.0. That is the seek, not a scene change.
    return sorted(t for t in times if t > start + 0.08)[:limit]


def _extract(mp4: Path, at: float, path: Path) -> bool:
    """One frame of `mp4` at `at` seconds, written to `path`."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(mp4),
         "-frames:v", "1", "-update", "1", str(path)],
        capture_output=True,
    )
    return proc.returncode == 0 and path.is_file()


def beat_frames(out_dir: Path | str, doc: dict | None = None) -> dict:
    """Write one review frame per beat, and an index to read them in order.

    Reads the timeline the take just wrote (or `doc`), extracts
    `frames/beat-NN.png` at each beat's midpoint, and writes `frames/frames.md`
    for a reviewer and `frames/frames.json` for a tool. Neither says anything
    about what is *in* a frame — see the section header.

    Returns the manifest. Safe to re-run: it is a pure function of the mp4 and
    the timeline, so a demo whose frames were deleted can get them back without
    re-recording, and a re-run takes the previous run's frames back off disk
    first rather than leaving stale ones in a directory somebody is about to
    hand to a reviewer.

    **Refuses to run for a segment take, and only for that.** A single
    segment's timeline numbers its beats from zero and describes a
    `<segment>.seg.mp4`, so two of them would write `beat-00.png` over each
    other and the sheet would name a file `stitch()` deletes. A *stitched*
    demo is a different thing: `stitch()` merges the parts into one timeline
    whose beats are renumbered and offset onto the joined video's clock, and
    that is a whole demo — it gets frames like any other, written by `stitch()`
    itself, and it is the case that needs a review sheet most, since a demo
    long enough to record in parts is a demo nobody wants to scrub by hand.
    """
    out_dir = Path(out_dir)
    if doc is None:
        doc = json.loads(timeline_paths(out_dir)[0].read_text())
    mp4 = out_dir / str(doc.get("media") or "demo.mp4")
    frames_dir, json_path, md_path = frames_paths(out_dir)
    beats = doc.get("beats") or []
    manifest: dict = {
        "schema": FRAMES_SCHEMA,
        "generated_by": "demo-video",
        "media": mp4.name,
        "duration": doc.get("duration"),
        "recorder": doc.get("recorder"),
        "frames": [],
        "skipped": None,
    }
    if doc.get("segment"):
        manifest["skipped"] = (
            f"{doc['segment']} is one segment of a demo, not a demo; its beats "
            f"are numbered from zero and its media is a .seg.mp4 that stitch() "
            f"deletes. stitch() writes the frames, off the merged timeline"
        )
        return manifest
    if not beats:
        manifest["skipped"] = "the take recorded no beats"
        return manifest
    if not mp4.is_file():
        manifest["skipped"] = f"there is no {mp4.name} to extract frames from"
        return manifest

    duration = doc.get("duration")
    if not isinstance(duration, (int, float)):
        try:
            duration = media_duration(mp4)
        except (subprocess.CalledProcessError, ValueError, OSError):
            duration = float(beats[-1].get("t_end") or 0.0)
    last = max(0.0, float(duration) - _FRAME_EDGE_S)

    planned: list[dict] = []
    for beat in beats:
        t_start, t_end = beat.get("t_start"), beat.get("t_end")
        if not isinstance(t_start, (int, float)):
            continue
        if not isinstance(t_end, (int, float)) or t_end < t_start:
            t_end = t_start
        middle = min(max((float(t_start) + float(t_end)) / 2, 0.0), last)
        index = int(beat.get("index", len(planned)))
        planned.append({
            "file": f"beat-{index:02d}.png",
            "kind": "beat",
            "beat": index,
            "t": round(middle, 3),
        })
        # Only for beats long enough to hide an unscripted transition. Beat
        # alignment sees what the storyboard wrote down; a redirect, a toast or
        # a load finishing inside a long hold is invisible to it.
        if float(t_end) - float(t_start) < SCENE_MIN_SPAN_S:
            continue
        window = (min(float(t_start), last), min(float(t_end), last))
        for n, cut in enumerate(scene_times(mp4, *window), 1):
            planned.append({
                "file": f"beat-{index:02d}-scene-{n}.png",
                "kind": "scene",
                "beat": index,
                "t": round(cut, 3),
            })

    # Take the previous run's sheet off disk before writing this one. A demo
    # whose storyboard lost beats would otherwise leave frames nobody planned
    # sitting in the directory SKILL.md tells you to hand over. Bounded to the
    # names this function writes — never the directory.
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*frames_dir.glob("beat-*.png"), json_path, md_path]:
        try:
            # missing_ok: the two manifests do not exist on a first run, and a
            # warning about failing to delete them would be on every take.
            stale.unlink(missing_ok=True)
        except OSError:  # noqa: PERF203 - a leftover is worth reporting, not fatal
            print(
                f"demo-video: WARNING — could not remove the stale {stale.name}",
                file=sys.stderr,
            )

    written: list[dict] = []
    for record in planned:
        if _extract(mp4, float(record["t"]), frames_dir / str(record["file"])):
            written.append(record)
        else:
            print(
                f"demo-video: WARNING — could not extract a frame at "
                f"{record['t']}s for beat {record['beat']}",
                file=sys.stderr,
            )
    manifest["frames"] = written
    # How far the video is *known* to have slid under the beat log, as a floor
    # rather than a correction. A beat that ends after the video does can only
    # mean capture loss (issue #18); it is usually zero, and when it is not it
    # is the one number that says how stale a frame's aim may be.
    over = float(beats[-1].get("t_end") or 0.0) - float(duration)
    manifest["capture_loss_at_least"] = round(max(0.0, over), 3)
    json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_frames_md(manifest))
    return manifest


def write_beat_frames(out_dir: Path | str, doc: dict, where: str) -> dict | None:
    """`beat_frames`, without letting a review sheet cost a recording.

    Everything it does is ffmpeg re-reading an mp4 that is already on disk, so
    a failure loses the sheet and nothing else — and raising out of a take's
    `__exit__`, or out of `stitch()` after the concat, would take the video,
    the stills and the beat log down with it. `where` names the caller in the
    warning, because "could not extract beat frames" during a stitch and during
    a take are different things to go looking at.
    """
    try:
        manifest = beat_frames(out_dir, doc)
    except Exception as exc:  # noqa: BLE001 - a review sheet is not a recording
        print(
            f"demo-video: WARNING — {where} could not extract beat frames: "
            f"{exc}. The video, the stills and the timeline are unaffected; "
            f"`beat_frames(out_dir)` re-runs it.",
            file=sys.stderr,
        )
        return None
    if manifest["skipped"]:
        # Say which, rather than announcing a directory that was never
        # created — a segment take reaches this on every run.
        print(
            f"demo-video: no review frames — {manifest['skipped']}",
            file=sys.stderr,
        )
        return manifest
    print(
        f"wrote {frames_paths(out_dir)[0]} ({len(manifest['frames'])} review frames)"
    )
    return manifest


def render_frames_md(manifest: dict) -> str:
    """The review sheet: the frames, in order, and nothing else.

    Pure function of the manifest, so it can be re-rendered without the video.

    **What it deliberately does not carry**: the caption each frame ran under,
    the verb, and the selector. The first is a claim the recorder cannot check
    (see the section header); the second and third are the storyboard, and this
    is the document handed to a reviewer who is asked what story the pictures
    tell on their own. `click('#refresh')` printed beside a frame answers that
    question for them, and the `fps=1/3` handoff this replaces did not leak it.
    """
    frames = manifest.get("frames") or []
    head = [f"`{manifest.get('media') or 'demo.mp4'}`"]
    if manifest.get("duration") is not None:
        head.append(f"{float(manifest['duration']):.1f}s")
    head.append(f"{len(frames)} frames")
    out = [
        "# Review frames",
        "",
        " · ".join(head),
        "",
        "One frame per beat of the demo — per thing the storyboard did — rather "
        "than one every N seconds, so nothing the demo does is missed and a "
        "held frame is photographed once. Read them in order. Written by the "
        "demo-video recorder on every clean exit; re-record rather than editing "
        "it.",
        "",
        "**They are not captioned, on purpose.** The recorder knows which line "
        "was on screen during each *beat*, but the beat log and the video run "
        "on different clocks — see "
        "[#18](https://github.com/rogvid/skills/issues/18) — so a caption "
        "printed under a frame can belong to the frame next to it. A frame with "
        "a confident wrong caption is worse than a frame with none. "
        "[#60](https://github.com/rogvid/skills/issues/60) is how the pairing "
        "gets earned back.",
        "",
    ]
    if manifest.get("skipped"):
        return "\n".join(out + [f"No frames were written: {manifest['skipped']}.", ""])
    loss = manifest.get("capture_loss_at_least") or 0.0
    if loss > 0.05:
        out += [
            f"This take lost at least {loss * 1000:.0f} ms of wall time to the "
            f"capture (its last beat ends after the video does), so a frame may "
            f"sit that much later in the demo than the beat it was aimed at.",
            "",
        ]
    out += [
        "| frame | at |",
        "|---|---:|",
    ]
    for frame in frames:
        out.append(f"| `{_md_cell(frame.get('file'))}` | {_fmt_t(frame.get('t'))} |")
    out.append("")
    for frame in frames:
        name = str(frame.get("file"))
        title = f"{name.removesuffix('.png')} — {_fmt_t(frame.get('t'))}s"
        if frame.get("kind") == "scene":
            title += " (an extra frame: the picture changed here)"
        out += [f"## {title}", "", f"![{name}]({name})", ""]
    return "\n".join(out).rstrip() + "\n"


def _verb_target(args: tuple, kwargs: dict) -> str | None:
    """The string a verb acted on, dug out of how it happened to be called."""
    if args and isinstance(args[0], str):
        return args[0]
    for name in ("selector", "path", "command", "text", "pattern", "name"):
        value = kwargs.get(name)
        if isinstance(value, str):
            return value
    return None


def _beat_verb(
    verb: str,
    target: Callable[[tuple, dict], str | None] = _verb_target,
) -> Callable:
    """Decorate a storyboard verb so calling it records one beat.

    A decorator rather than a `with` block inside every verb: it keeps the
    recorders' method bodies untouched, which is the difference between a
    one-line diff per verb and re-indenting three files.

    `target` extracts the beat's `selector` from the call; the default takes
    the first string argument (so `click("#go")`, `run("ls")` and
    `goto("/app")` all self-describe) and yields null for verbs called with
    none (`pause(2)`, `spotlight()`).
    """

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            with self._beat(verb, selector=target(args, kwargs)):
                return fn(self, *args, **kwargs)

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
    ) -> None:
        # Every setting resolves explicit parameter > DEMO_VIDEO_* env var
        # > built-in default (see SKILL.md for the variable names).
        out_dir = out_dir or _env("OUT_DIR")
        if out_dir is None:
            raise RuntimeError(
                "no output directory: pass out_dir or set DEMO_VIDEO_OUT_DIR"
            )
        self.out_dir = Path(out_dir)
        self.segment = segment
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
        # Redaction registries (see "secrets" above). `_secrets` is the shared
        # one — every medium's text path checks it; `_redacted` is filled in by
        # whatever the medium's own redact() means (CSS selectors for the web).
        self._secrets: list[str] = []
        self._redacted: list[str] = []
        # Selectors that have matched at least one element at some point. Used
        # only to tell "this selector never named anything" from "it named
        # something that is not on screen right now" — *not* as evidence that
        # anything is currently masked. Whether the mask is on, and big enough,
        # is re-decided from scratch at every checkpoint against the elements
        # that exist then; remembering a past success would let a re-render
        # drop the marker and still count as covered.
        self._mask_seen: set[str] = set()
        # Withhold the first paint of a navigation until the mask is verified.
        # The gate itself is per *document* and lives in the page; what is
        # tracked here is only whether a navigation is waiting to be checked.
        self._nav_pending = False
        self._last_sync = 0.0
        # "erase" paints an opaque cover over what the element renders;
        # "blur" is the aesthetic opt-out. See Recorder.redact().
        self._redact_style = "erase"
        # Stills this take wrote, so a take that fails to verify its mask can
        # take them back off disk (they are full-bleed, and may hold it).
        self._shots: list[Path] = []
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
                f"anything looks off. See SKILL.md, 'Determinism'.",
                file=sys.stderr,
            )
        else:
            print(
                f"demo-video: determinism OFF (the default) — timezone "
                f"{self._timezone_id}, locale {self._locale} and reduced motion "
                f"are still pinned, but the page's clock runs, so anything the "
                f"app renders from it differs between takes and two recordings "
                f"of this storyboard will not match. Recorder("
                f"deterministic=True) freezes it; read SKILL.md's 'Determinism' "
                f"section first, it changes what some apps do.",
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

    def _checkpoint(self) -> None:
        """Re-establish and re-verify the medium's masking, cheaply.

        Called wherever a take spends time. No-op unless the medium masks."""

    def _before_shot(self) -> None:
        """Last thing before `shot()` screenshots the page.

        Exists so a medium can re-assert its masking on the still path. Web
        stills are captured full-bleed — no window frame, the whole page — so
        this is the path where a secret is most exposed if masking is skipped.
        No-op by default."""

    # -- secrets (shared registry; see "secrets" at the top of this file) ----

    def register_secret(self, *values: str | Secret) -> None:
        """Register literal text that must never be captioned, spoken, or
        logged.

        A caption or interlude line containing a registered value raises
        SecretLeak and fails the take. Beat-log fields are scrubbed. It does
        **not** hide the value where the app renders it — that is what the
        medium's own redaction does (`Recorder.redact` for the web).

        Typing a `Secret` registers it for you; call this directly for a value
        the demo does not type but the app displays, or that a command prints.
        """
        for value in values:
            text = value.reveal() if isinstance(value, Secret) else value
            if not isinstance(text, str) or not text:
                raise ValueError("register_secret() takes non-empty strings")
            if text not in self._secrets:
                self._secrets.append(text)

    @property
    def secrets(self) -> tuple[str, ...]:
        """Every registered secret, longest first.

        Longest first so that scrubbing overlapping values (a token and the
        header line that contains it) masks the larger one whole instead of
        leaving its tail behind. This is the accessor a medium-specific
        scrubber should read — see issue #5's PTY path.
        """
        return tuple(sorted(self._secrets, key=len, reverse=True))

    def scrub(self, text: str) -> str:
        """`text` with every registered secret replaced by SECRET_MASK.

        For output nobody authored — a command's stdout, a page title. Text a
        *storyboard* wrote goes through `_no_secrets` instead, which fails the
        take rather than quietly editing what the author asked to say.
        """
        for secret in self.secrets:
            text = text.replace(secret, SECRET_MASK)
        return text

    def _verify_redaction_final(self) -> None:
        """Last word before conversion: raise if anything registered was
        never masked. No-op unless the medium implements masking."""

    def _scrub_deep(self, value: object) -> object:
        """`scrub()` over a whole structure, not just its top-level strings.

        A beat's `extra` keys and an issue's detail can be lists and dicts —
        a stack trace, a list of request URLs — and a scrub that only walked
        the outermost values left those untouched in the two files this skill
        tells people to commit.
        """
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, dict):
            return {key: self._scrub_deep(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._scrub_deep(item) for item in value]
        return value

    def _no_secrets(self, text: str, where: str) -> None:
        """Raise unless `text` is free of every registered secret.

        The message never contains the secret: it names the leak site and
        quotes the *scrubbed* line, which is enough to find the offending
        storyboard line without writing the value into a terminal, a CI log,
        or a bug report.
        """
        if not text:
            return
        for secret in self.secrets:
            if secret in text:
                raise SecretLeak(
                    f"{where} contains a registered secret ({len(secret)} "
                    f"chars) and would be burned into the frames"
                    + (" and spoken aloud" if self._speech else "")
                    + f": {self.scrub(text)!r}. A secret in narration is an "
                    f"authoring bug, not something to blur after the fact — "
                    f"reword the line. This take wrote no mp4."
                )

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
            self._context.add_init_script(_INTERLUDE_JS)
            self._context.add_init_script(_BRIDGE_JS)
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
        # A mask that never matched anything is the failure redaction can
        # least afford: the take looks redacted and is not. Checked while the
        # page is still alive, and remembered rather than raised, so the
        # browser and the Playwright driver still get torn down — then
        # re-raised at the end, having skipped conversion. A take that cannot
        # prove it masked what it was told to writes no mp4.
        #
        # The order of the next three statements is the whole guarantee, and
        # every one of them was wrong once:
        #
        #   * the narration tail runs **first**. It holds the frame open so a
        #     take does not end mid-sentence, and it pumps — a terminal take's
        #     child process is still running and still writing. Verifying
        #     before it vouched for frames that were not the frames recorded.
        #   * `_stop()` runs **second**, because a medium can be sitting on
        #     output: the terminal's stream scrubber withholds any trailing
        #     fragment that might still grow into a secret, and flushes it
        #     here. Verifying before that read a screen the recording does not
        #     end on.
        #   * the check runs **last, on every path out of the `with`**, not
        #     only the clean one. A storyboard that raises — a wait_for_text()
        #     timeout, a Ctrl-C on a hung demo — used to skip it altogether
        #     and keep its stills, and a terminal still is the raw screen.
        unmasked: BaseException | None = None
        if exc_type is None:
            self._finish_line(tail=0.5)  # don't end mid-sentence
        self._stop()
        try:
            self._verify_redaction_final()
        except SecretLeak as leak:
            unmasked = leak
        except Exception as exc_check:  # noqa: BLE001 - unverifiable is not clean
            # The check itself broke — a dead page, a closed context. On a
            # clean take that is a leak by another name: nothing can vouch for
            # the frames, so nothing is kept. On a take that had already
            # failed it is almost certainly a consequence of *that* failure,
            # so the artifacts still go, but the original exception is what
            # the author gets to read.
            unmasked = SecretLeak(
                f"the take's redaction could not be verified at the end "
                f"({type(exc_check).__name__}: {exc_check}), so nothing can "
                f"vouch for what is in the frames. This take wrote no mp4."
            )
        clean = exc_type is None and unmasked is None
        video = self.page.video
        self._context.close()
        webm = Path(video.path()) if video else None
        self._browser.close()
        self._pw.stop()
        try:
            if clean and webm and webm.exists():
                self._convert(webm)
            if clean:
                # The beat log is the durable, diffable record of the take — it
                # outlives the mp4, which is not committed. Written after
                # conversion so `duration` is the encoder's answer, not a guess.
                doc = self._timeline_doc()
                json_path, _ = write_timeline(self.out_dir, doc)
                print(f"wrote {json_path} ({len(self._beats)} beats)")
                self._write_beat_frames(doc)
        finally:
            # Whatever went wrong above, don't leave .video/ behind — the
            # next take into this directory would trip over it.
            for leftover in self._video_dir.glob("*"):
                leftover.unlink()
            self._video_dir.rmdir()
            # A take that could not vouch for its mask must not leave its
            # stills behind. They are full-bleed — the whole page, no window
            # frame — and they are the artifact somebody picks up first,
            # precisely because they are cheap to look at. The mp4 was never
            # written; these were, before the failure was known.
            # Any SecretLeak, not only the one raised on the way out. A leak
            # refused inside the storyboard — a captioned secret, a
            # terminal_close() stamp, a Secret typed into a field the mask
            # could not find — leaves the same stills behind, and SKILL.md
            # promises unconditionally that a SecretLeak keeps nothing.
            if unmasked is not None or (
                exc_type is not None and issubclass(exc_type, SecretLeak)
            ):
                self._discard_artifacts()
            # Always, strict or not, crashed or not: the problems a take
            # recorded are the one thing nobody thinks to go looking for, so
            # they have to arrive unasked.
            self._print_issue_summary()
        # Two failure modes that disagree about what to leave behind, and the
        # disagreement is deliberate:
        #
        #   StrictTakeFailed  the take recorded console errors or a bad exit
        #                     code. The mp4, the stills and the timeline are
        #                     written first and kept — they are the evidence
        #                     somebody needs to see what the app did.
        #   SecretLeak        the mask could not be verified. Nothing is kept:
        #                     the recording, the stills and the beat log may
        #                     each hold the value, and an artifact nobody can
        #                     vouch for is worse than no artifact at all.
        #
        # So the leak is raised first and suppresses everything, and the strict
        # verdict is only reached when there was no leak to suppress it.
        #
        # Except over a storyboard that had already raised. Replacing a
        # wait_for_text() timeout with a leak report costs the author the one
        # message that says what to fix, and the leak has already cost the
        # artifacts — which is the part that matters. So it is said loudly and
        # the original exception is left to propagate.
        if unmasked is not None:
            if exc_type is not None:
                print(f"demo-video: {unmasked}", file=sys.stderr)
                return
            raise unmasked
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

    def _pump_events(self) -> None:
        """Give Playwright a chance to deliver queued page events.

        The sync API dispatches `console`/`pageerror`/`requestfailed`/`response`
        only while it is inside a call, so a storyboard sitting still for three
        seconds queues everything the page throws and hands it all to whichever
        beat makes the next call. One trivial evaluate per PUMP_INTERVAL_S
        keeps delivery inside the beat the event belongs to. It paints nothing,
        touches no DOM, and is skipped if it fails — a pump is a diagnostic
        convenience, never a reason to lose a take.
        """
        now = time.monotonic() - self._t0
        if now - self._pumped_at < PUMP_INTERVAL_S:
            return
        try:
            self.page.evaluate("0")
        except Exception:  # noqa: BLE001 - the page may be closing
            return
        self._pumped_at = time.monotonic() - self._t0

    def _watch_page(self, page: Page) -> None:
        """Subscribe to everything the page can say about being broken."""
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)

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
        # Every string on a beat is scrubbed, not just the obvious one.
        # timeline.json and timeline.md are files this skill tells people to
        # commit, and a partially-cleaned record is worse than a dirty one:
        # a `[redacted]` selector sitting next to a plaintext `still` path
        # reads as evidence the log was cleaned.
        #
        #   selector  whatever string the verb was called with
        #   still     built from shot()'s name, which shot() scrubs before it
        #             names the file, so path and log agree
        #   caption   `self._caption` is sticky: a register_secret() that
        #             lands after the caption naming the value would
        #             otherwise stamp plaintext onto every later beat
        #
        # Scrubbed rather than fatal, because none of these is text a viewer
        # reads off the screen. Caption text reaches the screen through
        # caption(), which refuses it outright.
        record: dict = {
            "index": len(self._beats),
            "t_start": round(time.monotonic() - self._t0, 3),
            "t_end": None,
            "caption": self.scrub(self._caption if caption is None else caption),
            "verb": verb,
            "selector": self.scrub(selector) if selector else selector,
            "still": self.scrub(still) if still else still,
            "segment": self.segment,
            # Equal to `index` here, and deliberately written anyway: `stitch`
            # renumbers `index` across a merged demo and leaves this one alone,
            # so `(segment, segment_index)` is the beat's identity before and
            # after a merge. A consumer naming files after a beat (issue #9)
            # can use it without knowing which kind of timeline it is reading.
            "segment_index": len(self._beats),
        }
        record.update(extra)
        self._beats.append(record)
        try:
            yield record
        finally:
            record["t_end"] = round(time.monotonic() - self._t0, 3)
            self._in_beat = False

    def _write_beat_frames(self, doc: dict) -> None:
        """Extract this take's review frames (a no-op for a segment).

        The frames inherit the recording's redaction rather than re-deriving
        it: every one of them is a frame of `demo.mp4`, which is masked in the
        page before it is ever captured. `tests/smoke` measures that on the
        frames themselves instead of taking this paragraph's word for it.
        """
        write_beat_frames(self.out_dir, doc, "this take")

    def _media_path(self) -> Path:
        """The mp4 this take converts to on exit."""
        name = f"{self.segment}.seg.mp4" if self.segment else "demo.mp4"
        return self.out_dir / name

    def _timeline_doc(self) -> dict:
        """This take's beat log as a timeline document (see TIMELINE_SCHEMA)."""
        mp4 = self._media_path()
        duration = None
        if mp4.exists():
            try:
                duration = round(media_duration(mp4), 3)
            except (subprocess.CalledProcessError, ValueError, OSError):
                duration = None  # a timeline without it still beats none
        # Scrubbed again on the way out, over the whole log. `_beat` scrubs
        # what is registered *at the time the beat runs*, which is nothing at
        # all for a value registered later in the take — and registering late
        # is the ordering a hurried author actually produces. The frames from
        # before the registration keep the value (no recorder can un-paint a
        # caption), but the files this skill tells people to commit do not
        # have to.
        beats = [self._scrub_deep(beat) for beat in self._beats]
        # The issue log too: it quotes console messages, request URLs and
        # process output — none of it authored, all of it capable of carrying
        # a secret the app printed, and all of it written into the same two
        # committed files.
        issues = [self._scrub_deep(issue) for issue in self._issues]
        return {
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
            "beats": beats,
            "strict": self._strict,
            "issues": issues,
            "issue_count": self._issue_count,
        }

    # -- shared storyboard verbs -------------------------------------------

    def _idle(self, seconds: float) -> None:
        """Hold for `seconds`. Overridden by media that must keep working
        (pumping output) while the frame is held.

        Sliced against a deadline rather than one flat sleep, so page events
        are delivered while the beat they belong to is still open. Deadline,
        not accumulated slices: the pump costs about a millisecond and a
        storyboard's pacing must not drift by however many of them it took."""
        # Holding the frame is where a take spends most of its time, and it is
        # where a page that navigated on its own sits behind a raised paint
        # gate waiting for somebody to notice. Checking here is what keeps the
        # gate from outliving the navigation that raised it.
        self._checkpoint()
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

    def caption(self, text: str) -> None:
        """Show a narrator line at the bottom of the frame ("" hides it).

        With speech enabled the line is also spoken; the previous line
        always finishes before this one starts.
        """
        # Before anything else, and specifically before _prepare_line() —
        # which would synthesize the line and cache the audio on disk.
        self._no_secrets(text, "caption()")
        # Synthesizing and waiting out the previous spoken line happens
        # *before* the beat opens: the beat's t_start is when this caption
        # reaches the screen, which is what a reviewer extracting a frame at
        # that timestamp expects to see.
        clip = self._prepare_line(text)
        with self._beat("caption", caption=text):
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
        """Bridge a jump in the demo; "" fades it out. With speech enabled the
        line is spoken too.

        style="card" (default) is a full-screen title card — right for real
        time-skips (minutes of background work) between segments. style="light"
        is a centered label over a soft scrim with the scene still visible —
        lighter, for short transitions where a full takeover feels heavy."""
        self._no_secrets(text, "interlude()")
        clip = self._prepare_line(text)
        fn = "__demoBridge" if style == "light" else "__demoInterlude"
        with self._beat("interlude", selector=style, caption=text):
            self.page.evaluate(f"t => window.{fn}(t)", text)
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

    def _discard_artifacts(self) -> None:
        """Take back everything this take put on disk, and say what went.

        Only what *this* take wrote: `self._shots`, not `images/*.png`, so a
        failed retake into a directory holding a previous take's stills does
        not delete somebody's committed guide. The message names each file
        rather than claiming a general cleanup, because "cleaned up" without a
        list is exactly the sentence people believe and do not check.
        """
        gone: list[str] = []
        for path in self._shots + [self.out_dir / ".frame.png"]:
            try:
                if path.is_file():
                    path.unlink()
                    gone.append(path.name)
            except OSError:  # noqa: PERF203 - report what could not be removed
                print(
                    f"demo-video: WARNING — could not delete {path}, which may "
                    f"hold a secret this take failed to mask",
                    file=sys.stderr,
                )
        print(
            "demo-video: the take could not verify its mask, so it wrote no "
            "mp4 and no timeline, and deleted "
            + (", ".join(gone) if gone else "nothing (it had written nothing)")
            + ". The raw capture in .video/ is gone too.",
            file=sys.stderr,
        )

    def _safe_shot_name(self, name: str) -> str:
        """A still's name with any secret removed, safely.

        Scrubbing to the bare mask is not enough for something that becomes a
        *filename*: two shots whose names differ only inside the secret would
        both become `04-[redacted]` and the second would silently overwrite the
        first, and `[`/`]` are glob metacharacters for everything downstream
        that walks `images/`. So the mask is spelled plainly and a short digest
        of the original name is appended — stable across runs, distinct per
        name, and readable.
        """
        scrubbed = self.scrub(name)
        if scrubbed == name:
            return name
        digest = hashlib.sha256(name.encode()).hexdigest()[:8]
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", scrubbed.replace(SECRET_MASK, "redacted"))
        return f"{cleaned.strip('-')}-{digest}"

    def shot(self, name: str) -> Path:
        """Still for the written guide -> images/<name>.png."""
        # Scrubbed here rather than only in the beat record, so the file on
        # disk carries the same name the log does. Scrubbing the log alone
        # would leave images/04-sk-live-….png sitting next to a beat that
        # says the name was masked.
        name = self._safe_shot_name(name)
        path = self.images_dir / f"{name}.png"
        rel = path.relative_to(self.out_dir).as_posix()
        self._shots.append(path)
        with self._beat("shot", selector=name, still=rel):
            # Stills are the exposed path: the web recorder captures them
            # full-bleed — the whole page, no window frame — so a mask that
            # only covers the video would leave every still readable. Nothing
            # here re-derives the masking; it re-asserts the same in-page one
            # the frames get, immediately before the shutter.
            self._before_shot()
            self.page.screenshot(path=str(path))
        return path

    # -- speech (ElevenLabs narration) --------------------------------------

    def _prepare_line(self, text: str) -> Path | None:
        """Synthesize (or fetch cached) audio for a narration line, and wait
        out the previous line — never speak two lines at once, never show a
        caption while the voice is still on the previous one."""
        # The single choke point for everything this package speaks, and the
        # last thing that runs before text becomes a file in .tts/ — which is
        # keyed by the text and holds the spoken words as audio. Both callers
        # (caption, interlude) already checked; this is here so that a future
        # spoken path inherits the check instead of having to remember it.
        self._no_secrets(text, "a narration line")
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
        if self._speech:
            # Mix each narration clip in at the moment its line appeared.
            # Segments always get an aac track (silence if no lines) so
            # stitch()'s lossless concat sees uniform streams.
            if self._lines:
                for _, clip in self._lines:
                    cmd += ["-i", str(clip)]
                delayed = ";".join(
                    f"[{i + 1}:a]adelay={int(off * 1000)}:all=1[a{i}]"
                    for i, (off, _) in enumerate(self._lines)
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
        spoken = f", {len(self._lines)} spoken lines" if self._speech else ""
        print(f"wrote {mp4} ({mp4.stat().st_size // 1024} kB{spoken})")


def _shift(value: object, offset: float) -> float | None:
    """A timestamp moved `offset` seconds later, or None if there wasn't one."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(float(value) + offset, 3)


def _common(values: list, mixed: object = None) -> object:
    """The value every segment agrees on, or `mixed` when they do not."""
    if not values:
        return mixed
    first = values[0]
    return first if all(v == first for v in values[1:]) else mixed


def _merge_determinism(records: list[dict]) -> dict:
    """The determinism record of a merged demo, key by key.

    A value every segment agrees on is that value; anything they disagree on
    becomes null, because there is no honest single answer and the per-segment
    records are right there in `segments`. Silently taking the first segment's
    would say a demo was recorded on a frozen clock when half of it was not.
    """
    order: list[str] = []
    for record in records:
        for key in record or {}:
            if key not in order:
                order.append(key)
    return {
        key: _common([(record or {}).get(key) for record in records])
        for key in order
    }


# How far a segment's recorded `duration` may sit from what its .seg.mp4
# measures now. The recorder probed the same file with the same tool moments
# after writing it, so anything past this is not rounding — it is a log paired
# with a *different* recording of that segment (see _segment_timeline).
SEGMENT_STALE_S = 0.25


def _segment_timeline(out_dir: Path, segment: str, media: Path, probed: float) -> dict:
    """One segment's timeline document, checked against the media beside it.

    Refuses rather than guesses. A segment timeline that is missing, written
    to a different schema, or describing a different recording is not
    something a merge can quietly work around: the result would be a demo-wide
    timeline whose beats belong to a video nobody has, which is exactly the
    failure #7 exists to remove.

    The check that does the work here is the **duration** one. The `media`
    name is derived from the same segment string as the path this was loaded
    from, so those two can only disagree if somebody hand-edited the file —
    whereas re-recording one segment and merging it against the previous
    take's log is an ordinary Tuesday, produces a name that matches perfectly,
    and is precisely the stale pairing that would date-stamp the wrong beats
    onto this demo.
    """
    json_path, _ = timeline_paths(out_dir, segment)
    if not json_path.is_file():
        raise FileNotFoundError(
            f"{json_path} — segment {segment!r} has an mp4 but no beat log, so "
            f"its beats cannot be merged into the demo's timeline. Re-record "
            f"the segment (a clean take always writes one); note that a "
            f"previous stitch() deletes the segment logs unless it was passed "
            f"keep_parts=True."
        )
    doc = json.loads(json_path.read_text())
    if doc.get("schema") != TIMELINE_SCHEMA:
        raise ValueError(
            f"{json_path} is schema {doc.get('schema')!r}, but this package "
            f"writes and merges schema {TIMELINE_SCHEMA!r} — re-record the "
            f"segment rather than merging a document this code does not know "
            f"the shape of"
        )
    if doc.get("media") != media.name:
        raise ValueError(
            f"{json_path} describes {doc.get('media')!r}, not {media.name!r} — "
            f"it is a leftover from a different take, and merging it would "
            f"stamp somebody else's beats onto this demo"
        )
    logged = doc.get("duration")
    if isinstance(logged, (int, float)) and abs(float(logged) - probed) > SEGMENT_STALE_S:
        raise ValueError(
            f"{json_path} was written for a {float(logged):.2f}s recording, but "
            f"{media.name} is {probed:.2f}s — the log and the video are from "
            f"different takes of segment {segment!r}. Re-record the segment, or "
            f"delete the stale log: merging them would put this demo's beats at "
            f"timestamps belonging to a video that no longer exists."
        )
    return doc


# What every part must agree on before `concat -c copy` may join them. All of
# these are silent failures rather than loud ones, which is why they are
# checked here instead of being left to ffmpeg:
#
#   frame rate  a mismatch is accepted, ffmpeg exits 0, and the joined video
#               runs at one part's rate — measured putting a beat 1.92 s from
#               its frame, which is the merge's whole subject matter;
#   geometry    accepted silently, and the output keeps the first part's
#               dimensions, so the second is stretched or cropped. Reachable
#               through the very demo the merged envelope's "mixed" recorder
#               value exists for: a web segment and a terminal one;
#   audio       a silent part followed by a narrated one makes concat drop the
#               narration *entirely*. The recorders give every segment a track
#               (silence when there are no lines) for this reason, so a part
#               without one did not come from here.
#
# None of it is reachable through the shipped recorders, which pin -r 25, one
# viewport and an audio track per segment. Nothing enforced that at the join.
_STREAM_FIELDS = ("codec", "width", "height", "frame rate", "audio track")


def _stream_shape(path: Path) -> tuple:
    """(codec, width, height, r_frame_rate, has audio) for one part."""
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height,r_frame_rate", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    video = tuple(out.stdout.strip().split(","))
    audio = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return (*video, bool(audio.stdout.strip()))


def _check_stream_shapes(parts: list[Path]) -> None:
    """Refuse to concat parts that differ in anything concat cannot fix."""
    shapes = [_stream_shape(p) for p in parts]
    for shape, part in zip(shapes[1:], parts[1:], strict=True):
        if shape == shapes[0]:
            continue
        differing = ", ".join(
            f"{name} {a!r} vs {b!r}"
            for name, a, b in zip(_STREAM_FIELDS, shapes[0], shape, strict=False)
            if a != b
        )
        raise ValueError(
            f"{part.name} does not match {parts[0].name}: {differing}. "
            f"`concat -c copy` joins these without complaint and the result is "
            f"wrong in a way nothing downstream can see — a frame-rate mismatch "
            f"moves every beat of the later segments away from its frame, a "
            f"geometry mismatch keeps the first part's dimensions, and a part "
            f"with no audio track makes concat drop every later part's "
            f"narration. Re-record the segments with the same recorder settings."
        )


def _merged_timeline(
    segments: list[str],
    parts: list[Path],
    docs: list[dict],
    durations: list[float],
    demo: Path,
) -> dict:
    """One timeline for a stitched demo, built from its segments'.

    Each segment's beats are offset by the **real duration of the segments
    before it**, read off the encoded `.seg.mp4` with ffprobe rather than
    summed from the storyboard's nominal pacing. The encoder's answer is the
    only one that matches the file a reviewer scrubs: Chromium's screencast
    drops wall time during idle stretches (issue #18), so a segment's video is
    routinely shorter than the time its beats say it took. Nominal timing would
    put every beat of every later segment progressively past its frame.

    The consequence worth knowing: a stall *inside* a segment still skews that
    segment's own late beats against its own video, and the merge inherits it —
    but it cannot leak across a boundary, because the next segment's offset is
    measured, not accumulated from beats.
    """
    beats: list[dict] = []
    issues: list[dict] = []
    records: list[dict] = []
    offset = 0.0
    issue_count = 0
    strict = True
    for segment, part, doc, probed in zip(
        segments, parts, docs, durations, strict=True
    ):
        duration = round(probed, 3)
        base = len(beats)
        for beat in doc.get("beats") or []:
            merged = dict(beat)
            # `index` is documented as the position in *this* file, and
            # timeline.md's table, every "beat N" message and any positional
            # consumer read it that way — so it is renumbered. What that would
            # destroy, `segment_index` keeps: the pair (segment, segment_index)
            # names the same beat before and after the merge. See issue #22.
            merged["segment_index"] = beat.get("segment_index", beat.get("index"))
            merged["index"] = len(beats)
            merged["t_start"] = _shift(beat.get("t_start"), offset)
            merged["t_end"] = _shift(beat.get("t_end"), offset)
            beats.append(merged)
        for issue in doc.get("issues") or []:
            moved = dict(issue)
            moved["t"] = _shift(issue.get("t"), offset)
            # `beat` indexes the segment's own beat list; re-point it at the
            # merged one, or an issue arrives attributed to whatever beat of
            # segment one happens to sit at that index.
            if isinstance(issue.get("beat"), int) and not isinstance(
                issue.get("beat"), bool
            ):
                moved["beat"] = base + int(issue["beat"])
            issues.append(moved)
        issue_count += int(doc.get("issue_count") or 0)
        strict = strict and bool(doc.get("strict"))
        records.append(
            {
                "segment": segment,
                "media": part.name,
                "duration": duration,
                "offset": round(offset, 3),
                "beats": len(doc.get("beats") or []),
                "recorder": doc.get("recorder"),
                "determinism": doc.get("determinism"),
            }
        )
        offset = round(offset + duration, 3)
    total = None
    if demo.exists():
        try:
            total = round(media_duration(demo), 3)
        except (subprocess.CalledProcessError, ValueError, OSError):
            total = None  # a timeline without it still beats none
    return {
        "schema": TIMELINE_SCHEMA,
        "generated_by": "demo-video",
        "recorder": _common([r["recorder"] for r in records], "mixed"),
        "segment": None,  # this document is the whole demo, not a part of one
        "media": demo.name,
        "duration": total,
        "determinism": _merge_determinism([r["determinism"] for r in records]),
        "segments": records,
        "beats": beats,
        "strict": strict,
        # Same cap as a single take's, for the same reason: timeline.json has
        # to stay a file somebody can open. `issue_count` is the honest total.
        "issues": issues[:MAX_ISSUES],
        "issue_count": issue_count,
    }


def stitch(out_dir: Path, segments: list[str], keep_parts: bool = False) -> None:
    """Concatenate segment recordings into demo.mp4 and merge their beat logs.

    Each segment records its own <segment>.seg.mp4 and, beside it,
    <segment>.seg.timeline.json with timestamps relative to that segment's own
    start. This writes one demo.mp4 and one timeline.json / timeline.md next to
    it, with every beat moved onto the stitched video's clock — see
    `_merged_timeline` for how the offsets are derived and why they come from
    ffprobe rather than from the storyboard.

    Refuses before it encodes anything: every part must exist, be probeable,
    carry a beat log of this schema written for *this* recording of it, and
    agree with the other parts on everything `concat -c copy` cannot fix.

    keep_parts=True leaves the .seg.mp4 files on disk so a single segment
    can be re-recorded and re-stitched without redoing the expensive ones
    (segments are untracked; only demo.mp4 is committed). The per-segment
    timelines follow their media exactly: kept when the .seg.mp4 is kept —
    a re-stitch needs them — and deleted with it otherwise. Leaving them
    behind would leave a timeline naming a file that no longer exists, and
    the next stitch could not tell that stale log from a fresh one (#21).
    """
    out_dir = Path(out_dir)
    parts = [out_dir / f"{s}.seg.mp4" for s in segments]
    for p in parts:
        if not p.exists():
            raise FileNotFoundError(p)
    # Everything the merge needs is read and checked *before* a frame is
    # encoded — the durations included, not just the beat logs. Failing here
    # costs nothing; failing after the concat leaves a fresh demo.mp4 with no
    # timeline beside it, which is the one state a reader cannot tell from a
    # demo that never had beats. That is reachable without anyone's help: a
    # truncated .seg.mp4 makes concat exit 0 and ffprobe raise afterwards.
    durations = [media_duration(p) for p in parts]
    _check_stream_shapes(parts)
    docs = [
        _segment_timeline(out_dir, s, p, d)
        for s, p, d in zip(segments, parts, durations, strict=True)
    ]
    listing = out_dir / ".concat.txt"
    demo = out_dir / "demo.mp4"
    try:
        listing.write_text(
            "".join(
                # concat-demuxer quoting: a literal ' inside single quotes
                # is written as '\'' (paths like ".../Rógvi's Mac/..." occur).
                "file '{}'\n".format(str(p.resolve()).replace("'", "'\\''"))
                for p in parts
            )
        )
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
             str(demo)],
            check=True,
        )
    finally:
        # Even when ffmpeg failed: a stray .concat.txt in a demo folder is
        # untracked litter that outlives the run that made it.
        listing.unlink(missing_ok=True)
    merged = _merged_timeline(segments, parts, docs, durations, demo)
    json_path, _ = write_timeline(out_dir, merged)
    print(f"wrote {demo} and {json_path.name} from {len(segments)} segments")
    # The review sheet, from the merged log rather than from any part's. A
    # single segment's timeline cannot produce one — its beats start at zero
    # and name a `.seg.mp4` this function is about to delete — but the merged
    # document is a whole demo, and a demo long enough to record in parts is
    # the one nobody wants to review by scrubbing. Written here rather than in
    # each segment's `__exit__` for the same reason: this is the first moment
    # a whole demo exists. Re-stitching rewrites it, clearing the last one's
    # frames first.
    write_beat_frames(out_dir, merged, "stitch()")
    if not keep_parts:
        # missing_ok throughout, and the media and its log in one pass: a
        # segment named twice, or a part something else already removed, must
        # not abort this loop half-done and leave the orphans of #21 behind.
        for s, p in zip(segments, parts, strict=True):
            p.unlink(missing_ok=True)
            for path in timeline_paths(out_dir, s):
                path.unlink(missing_ok=True)
