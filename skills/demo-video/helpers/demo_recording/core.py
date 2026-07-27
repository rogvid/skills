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
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from html import unescape as html_unescape
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

# Shortest value `register_secret()` will accept.
#
# The floor is not a guess about what a secret looks like — it is a bound on
# what registering one *costs everything else*. A registered value is replaced
# by `scrub()` wherever it appears: in a beat's `selector`, in a still's
# filename, in caption text, in every line of terminal output, and in every
# evidence file. `register_secret("1234")` therefore rewrites a `:nth-child(1234)`
# selector, an account number in an unrelated table, and the `1234` in a
# timestamp — and the damage reads exactly like redaction working, which is the
# one failure mode that never gets noticed.
#
# Eight, because that is where a literal stops colliding with ordinary output by
# accident and starts being a value somebody chose. Below it the honest control
# is `redact()`, which covers the pixels an element paints and touches no text
# at all — so a four-digit PIN is still hideable, just not by find-and-replace.
SECRET_MIN_LEN = 8


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
#   content       dict?  — what the *picture* turned out to be, measured off
#                          the encoded mp4 over the region the app occupies:
#                          `measured` (bool), `note` (why not, when it is
#                          false), `rect`, `sample_fps`, `frames`, `score`
#                          (median luma stddev), `floor`, `static_for` (the
#                          longest stretch in seconds where nothing in the rect
#                          changed), `static_from`, `static_limit`, and
#                          `warnings` (empty on a healthy take). **Null** on a
#                          take that encoded no mp4. This is the only field in
#                          this document that describes the frames rather than
#                          the storyboard — see "did the recording show
#                          anything?" for why it had to exist.
#   beats         list   — the beats, in the order they ran
#   strict        bool   — whether strict mode was on for this take (on a
#                          merged demo: only if it was on for every segment)
#   issues        list   — the problems the take recorded (see "take issues")
#   issue_count   int    — how many were seen; > len(issues) only if capped
#   failure       dict?  — **absent** from a take that exited cleanly, which is
#                          what makes its presence mean something. On an
#                          abnormal exit: `type` and `message` of what came out
#                          of the `with`, `beat` (index of the beat whose verb
#                          raised, or null when the failure happened between
#                          beats) and that beat's `verb`. See "failure
#                          artifacts" below.
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
#   evidence  str?   — path, relative to the timeline file, of this beat's
#                      evidence file ("evidence/beat-04.json"); null when
#                      evidence capture is off. See "per-beat evidence" below
#   exit_code int?   — TerminalRecorder `run` beats only: the shell's status
#                      for that command, or null if it could not be read
#   error     dict?  — **absent** on a verb that returned. Present, with the
#                      exception's `type` and its scrubbed `message`, on a verb
#                      that raised. Absent-on-success rather than
#                      `error: null`-on-success on purpose: a consumer asking
#                      "did this beat do what it says" wants the answer to be
#                      structurally missing when there is nothing to say, and
#                      a take recorded before this key existed then reads the
#                      same way as one that succeeded. See issue #24.
#
# Only the verb a storyboard calls becomes a beat. The verbs recorders build
# out of other verbs (`click` glides with `move_to`, `type_into` clicks first)
# record one beat spanning the whole call, not one per internal step.
TIMELINE_SCHEMA = 1

# -- per-beat evidence -------------------------------------------------------
#
# A reviewing agent handed only frames has to infer the DOM from pixels. The
# recorder is *driving* the page — it has the real thing — so at the end of
# every beat it also writes down what was on screen, in text, next to the
# frame the beat's timestamps point at.
#
# What is captured, per medium:
#
#   Recorder          the page's ARIA snapshot (Playwright's `aria_snapshot`,
#                     a compact YAML tree of roles and accessible names) —
#                     semantic, an order of magnitude smaller than the markup,
#                     and stable across restyling. Plus `url` and `title`. When
#                     a spotlight is up, the same snapshot *scoped to the
#                     spotlight target* and that element's `outerHTML`.
#   TerminalRecorder  the rendered screen, ANSI already stripped by xterm.js
#                     (`_screen()`), scrollback included.
#
# **`outerHTML` is only ever the spotlight target's, never the page's**, and
# that is a safety decision as much as a size one. `document.body.outerHTML`
# on the smoke fixture is 24 kB against 2.3 kB of ARIA, and it carries two
# things ARIA does not: the text of every inline `<script>`, and `srcdoc`
# attributes — i.e. source code and whole embedded documents that nobody put
# on screen. The clone that is serialized drops both (see web.py).
#
# **Evidence is plain text, and that makes it the leak path with the fewest
# natural defences.** Every other artifact this package writes is pixels, and
# `redact()` is a *pixel* control: it covers where a value renders and leaves
# the value in the DOM, which is exactly what is being dumped here. So:
#
#   * every string written is masked against the registered secrets *and*
#     against the rendered text of everything `redact()` is covering, harvested
#     from the page at capture time (see `Recorder._redacted_rendered_text`);
#   * nothing reaches the disk until the take has exited cleanly and the mask
#     has been verified — the documents are built in memory and written
#     alongside timeline.json, so a take that dies on a SecretLeak leaves no
#     evidence file to delete;
#   * a document that still holds a forbidden literal when it is serialized
#     raises SecretLeak and kills the take rather than being written.
#
# Naming, and issue #22. A beat's `index` is its position in *its own take*, so
# two segments of one demo both start at 0. Evidence therefore does two things
# that make renumbering a non-event: a segment's files carry the segment in
# their name (`evidence/part1.seg.beat-03.json`, mirroring how
# `<segment>.seg.timeline.json` is named), and the path is written *onto the
# beat* as `evidence` rather than derived from `index` by whoever reads the
# log. A merge that renumbers beats (issue #7) has only to carry that string
# across; nothing has to be renamed, and every evidence file names its own
# `segment` and `index` internally.
EVIDENCE_SCHEMA = 1
EVIDENCE_DIR = "evidence"

# Per-field character budgets. A TUI's scrollback is 5000 lines and a real
# app's ARIA tree is unbounded, so an uncapped evidence directory is bigger
# than the mp4 it describes. Truncation is *marked*, never silent: a reviewer
# reading a cut-off tree has to be able to tell it was cut off, and the file
# says so twice — inline where the text stops, and in `truncated`.
EVIDENCE_MAX_ARIA = 12_000
EVIDENCE_MAX_HTML = 8_000
EVIDENCE_MAX_SCREEN = 12_000
EVIDENCE_LIMITS = {
    "aria": EVIDENCE_MAX_ARIA,
    "scope_aria": EVIDENCE_MAX_ARIA,
    "html": EVIDENCE_MAX_HTML,
    "screen": EVIDENCE_MAX_SCREEN,
}
EVIDENCE_TRUNCATED = "\n…[demo-video: truncated here, {n} more characters]"

# What `html` says instead of markup when a registered or redacted value is
# interleaved with elements inside it. Spelled out rather than left null, so a
# reader can tell "no spotlight was up" from "the markup was withheld".
EVIDENCE_HTML_WITHHELD = (
    "[demo-video: markup withheld — a registered or redacted value is split "
    "across elements here, and there is no safe way to edit it out of the "
    "serialization. The ARIA snapshot above is unaffected.]"
)

# A token this long or longer, found with whitespace *inside* it, was broken by
# something that reflowed the text rather than written that way. A terminal wrap
# is the case that matters: xterm.js emits one buffer row per line, so a 28-
# character credential that crosses column 120 comes back as
# `"…sk-live-WRAP0000\n00000000…"` and an exact search finds neither half.
#
# Eight is where "no natural text breaks this in the middle" starts being true.
# Below it, allowing whitespace between every character turns a two-character
# mask into a pattern that matches ordinary prose — `ok` would match `o k`, and
# over-masking is the failure this whole `outside` machinery exists to prevent.
# Above it, the cost of being wrong is that a value the author registered gets
# masked in one more place than strictly necessary.
EVIDENCE_WRAP_MIN_TOKEN = 8

# The escapes `json.dumps` introduces, undone for *detection* by
# `_evidence_probe`. The backstop runs over the serialized document, where a
# newline is the two characters `\` and `n` — which no amount of elastic
# whitespace in a pattern can match, so the backstop used to miss exactly what
# the mask missed. A backstop that fails in the same direction as the thing it
# backs up is not one.
_JSON_STRING_ESCAPE = re.compile(r'\\[nrtbf"/\\]')
_JSON_ESCAPES = {
    r"\n": "\n", r"\r": "\r", r"\t": "\t", r"\b": "\b", r"\f": "\f",
    r"\"": '"', r"\/": "/", "\\\\": "\\",
}
_JSON_UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")

# Harvested text shorter than this is not used as a mask. `redact()` pointed at
# an element rendering "$" would otherwise replace every dollar sign in every
# evidence file, which costs the evidence its meaning and hides nothing: a
# one-character secret is not one. Registered secrets are masked at any length
# — `register_secret()` was told, explicitly, that the value matters.
EVIDENCE_MIN_MASK_LEN = 2

# Print a warning past this much evidence in one take. Not a cap — the
# per-field budgets are the cap — but a large accessibility tree times a long
# storyboard is a real cost (issue #49) and it should not arrive silently.
EVIDENCE_DIR_WARN_BYTES = 2_000_000


def evidence_name(index: int, segment: str | None = None) -> str:
    """The file one beat's evidence is written as.

    Mirrors `timeline_paths`: a whole demo writes `beat-04.json`, a segment
    writes `<segment>.seg.beat-04.json`, so two segments of one demo never
    collide and no merge has to rename anything (issue #22).
    """
    stem = f"{segment}.seg." if segment else ""
    return f"{stem}beat-{index:02d}.json"


def _cap_text(text: str, limit: int) -> tuple[str, int]:
    """`text` cut to `limit` characters, with an explicit marker. -> (text, cut)"""
    if len(text) <= limit:
        return text, 0
    cut = len(text) - limit
    return text[:limit] + EVIDENCE_TRUNCATED.format(n=cut), cut


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
        else "Written by the demo-video recorder when the take that produced "
        "it *failed* — do not edit it by hand, fix the storyboard and "
        "re-record."
        if doc.get("failure")
        else "Written by the demo-video recorder on every clean exit — do not "
        "edit it by hand, re-record instead.",
        "",
    ]
    # Before the beat table, not after it. A reader who opens this file after a
    # crash is reading it *because* something went wrong, and a timeline that
    # only mentions the failure in a footnote is the artifact-lies problem in
    # miniature — the table above it looks like an ordinary take's.
    failure = doc.get("failure")
    if isinstance(failure, dict):
        where = (
            f"beat {failure['beat']} (`{_md_cell(failure.get('verb'))}`)"
            if failure.get("beat") is not None
            else "between beats — no verb was running, so no beat is blamed"
        )
        out += [
            "## This take did not finish",
            "",
            f"It came out of the `with` block on a "
            f"**{_md_cell(failure.get('type'))}**, at {where}.",
            "",
            f"> {_md_cell(failure.get('message'))}",
            "",
            f"Everything below was still written — a broken take is the one "
            f"somebody wants to look at. `{FAILURE_DIR}/` beside this file has "
            f"the last frame, the console log, the page text and the failing "
            f"beat; `{FAILURE_MARKER}` says the same thing to anyone who only "
            f"opens the folder."
            + (
                ""
                if doc.get("duration") is not None
                else f" **No mp4 was encoded by this take**, so `duration` is "
                f"null; any `{doc.get('media') or 'demo.mp4'}` in this folder "
                f"is a previous run's."
            ),
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
        # A beat whose verb raised is marked in the table itself, not only in
        # the JSON. `t_start` and `t_end` are stamped either way, so without
        # this the row is indistinguishable from a row that worked (issue #24).
        error = beat.get("error")
        cells = [
            str(beat.get("index")),
            _fmt_t(beat.get("t_start")),
            _fmt_t(beat.get("t_end")),
            f"`{_md_cell(beat.get('verb'))}`"
            + (
                f" **raised {_md_cell(error.get('type'))}**"
                if isinstance(error, dict)
                else ""
            ),
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


# -- failure artifacts (issues #11, #20, #24, #32, #46) ----------------------
#
# What a take leaves behind when it does not finish. The rule the whole section
# is built to satisfy: **after an abnormal exit, every artifact present is
# either current, or absent, or explicitly marked stale.** Three things used to
# violate it, and all three lived in `__exit__`:
#
#   * a take that raised converted nothing and wrote nothing, so the one
#     recording anybody wanted to look at was deleted with `.video/` (#32).
#     In CI there is no screen, so that means blind retries.
#   * `_timeline_doc()` probed `demo.mp4` unconditionally, so a take that wrote
#     no mp4 reported the *previous* take's duration beside this take's beats
#     (#20) — and `stitch()` offsets segment timelines by exactly that number.
#   * a failed re-record left the previous run's `demo.mp4` sitting in the
#     folder looking current (#46), which in a review gate produces a confident
#     approval of something that was never recorded.
#
# What is written now, on any abnormal exit the recorder is allowed to keep
# artifacts from:
#
#   demo.mp4              the partial recording, converted from the webm that
#                         was already in hand
#   timeline.json/.md     the beats, with `error` on the one that raised (#24)
#                         and `failure` on the envelope
#   failure/              this section: a self-contained account of the crash
#   demo-video-FAILED.md  the marker (#46), written whether or not anything
#                         else was, and deleted by the next take that succeeds
#
# **The redaction ordering is the constraint that shapes all of it.** A crash
# dump of a page mid-secret is the worst leak path this package has, and
# `_verify_redaction_final()` — the thing that decides whether *any* of it may
# be kept — runs after `_stop()` and vouches for the page as it then is.
# So nothing here reads the page after that point:
#
#   * the last frame is extracted from `demo.mp4` with ffmpeg. It is a frame of
#     the recording the verifier already vouched for, so it inherits the whole
#     guarantee and costs no page access at all;
#   * the DOM / terminal screen is read **once, before** the verifier runs
#     (`_failure_screen()`), buffered in memory, and only masked and written
#     after the verifier has passed;
#   * the console log and the failing beat were in memory the whole time.
#
# Everything textual then goes through `_evidence_forbidden()` — the registered
# secrets *and* the harvested rendered text of everything `redact()` covers —
# is masked with it, and is checked with `_evidence_holds()` over the serialized
# bytes. A document that still holds a forbidden literal raises `SecretLeak`,
# and it raises it while the dump is still in memory, so the failure cannot
# leave half a directory behind. That is the same shape `_build_evidence()` /
# `_write_evidence()` already have, for the same reason.
FAILURE_DIR = "failure"
FAILURE_SCHEMA = 1

# The marker (#46). Named visibly rather than as the dotfile the issue sketched
# (`.demo-video-failed`): the artifact it exists to contradict is a `demo.mp4`
# somebody is about to watch, and a hidden file next to it is exactly as easy
# to miss as the problem. `ls` shows this one, and so does a file browser.
FAILURE_MARKER = "demo-video-FAILED.md"

# How much of an exception message reaches the marker and the dump. A
# `wait_for_text()` timeout quotes a thousand characters of terminal screen,
# and a Playwright error quotes the selector, a call log and a page snippet;
# past a point that is a file nobody opens rather than a report. The timeline's
# per-beat `error.message` is **not** capped — it is the machine-readable copy
# and something may want to match on it — so nothing is lost by capping here.
FAILURE_MESSAGE_CHARS = 2_000


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
        "demo-video recorder whenever it encodes an mp4 — which now includes a "
        "take that crashed, whose recording stops where the storyboard gave up "
        "(see `failure/`); re-record rather than editing it.",
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


# -- did the recording show anything? (issue #97) ----------------------------
#
# Everything above this line describes what the storyboard **did**. The beat
# log, the evidence documents, the exit codes, the stills and the captions are
# all statements about the program and about the verbs that drove it, and every
# one of them can be completely correct while the recording shows nothing at
# all.
#
# That is not hypothetical. Take 1 of this repo's own reference demo had a
# title card covering the terminal for 24.3 s of a 60.2 s video — 40% of the
# recording, with the real CLI running underneath it, invisible. `timeline.json`
# had all 17 terminal beats in order with correct exit codes; `evidence/*.json`
# held the full command output, because the xterm.js buffer was right and
# merely covered; the stills, the captions and the stderr summary all read like
# a healthy take. A reviewing agent handed the criteria plus `evidence/` and
# `timeline.md` certified the CLI criterion as demonstrated. Only `frames/`
# disagreed — 17 consecutive identical PNGs — and only because somebody looked
# at the pictures.
#
# So the recorder measures the picture too, and writes the answer where the
# text tier is read: `content` in the timeline envelope, plus a line on stderr.
# Two independent arms, because the failure above defeats one of them:
#
#   score       median luma standard deviation over the content rect. Catches
#               a recording that never rises above blank — a black take, a page
#               that never painted, a mask that covered everything.
#   static_for  the longest run of consecutive sampled frames that do not
#               change, in seconds. Catches a recording that is *covered* or
#               frozen, which the score cannot: the #91 card is dark with a
#               line of white text on it and scores ~12, comfortably "content".
#
# **Three things about the rect, and each one was a defect somewhere.**
#
# 1. It is the region the *app* occupies, not the frame. A fifth to a third of
#    every frame is the recorder's own chrome — a pastel gradient at ~230 luma
#    framing a window at ~35 — and it never changes. Scored whole-frame, a
#    blank recording measured 61.8 against a healthy one's 60.2: the metric ran
#    backwards, and the chrome is why (issue #17). The recorder knows its own
#    geometry, so it hands over the rect rather than guessing at one.
# 2. The caption band is cut off the bottom (`CONTENT_CAPTION_TRIM`). The
#    caption bar is burned into the recording and it is the recorder's own
#    drawing, not the app's — leaving it in lets a caption supply the contrast
#    for a blank app on the score arm, and lets a caption *change* count as the
#    picture changing on the static arm. Either one turns a broken take green.
# 3. It is sampled from the encoded mp4, after compositing, which is the file a
#    reviewer actually watches. Measuring the raw webm would grade something
#    nobody is handed.
#
# **Warn, never refuse.** A demo legitimately holding one frame through a long
# narrated beat is ordinary, and a heuristic that fails takes is worse than a
# heuristic that misses one — the same argument that scoped the terminal
# verifier to registered values only (issue #5). Nothing here raises, nothing
# here deletes an artifact, and a check that cannot run says so in `content`
# rather than being silently absent.
#
# **What this deliberately does not do** is judge whether the demo shows the
# *right* thing. That is issue #12's job, and a human's. This answers exactly
# one question: did the recording capture anything at all.

# Frames sampled per second of video. Two, not one: `static_for` is quantised
# to this step, so at 1 fps the shortest reportable run is a full second and
# the number a reviewer reads is coarser than the thing it describes. Past ~4
# the decode starts to cost more than the check is worth on a 60 s take.
CONTENT_SAMPLE_FPS = 2

# Every frame is reduced to this before any arithmetic — one ffmpeg pass, no
# image library, no extra dependency. Small on purpose: it is a blur, and a
# blur is what makes "did this change" robust against encoder noise. It is also
# why the static arm cannot see a single character change (~0.02 mean absolute
# luma at this size, far under CONTENT_STATIC_DIFF) and does not try to; a
# blinking cursor is not the demo showing something.
_CONTENT_W, _CONTENT_H = 160, 90

# How much of the content rect's height is dropped off the bottom before
# scoring. Sized for the caption bar plus its shadow at either recorder's
# geometry — the web caption's top edge sits at 84.2% of the app rect's height
# and the terminal's at 85.7%, with a 24 px shadow above each — and it is the
# same 0.8 keep that tests/smoke has used for its own content floor since #17.
#
# **This is why the static arm needs the beat log, and the reasoning is worth
# keeping.** Excluding the caption bar is not optional: the bar is the
# recorder's own drawing, it renders *over* an interlude card as readily as
# over the app, and leaving it in would let a caption change count as the
# picture changing — which defeats the detector on exactly the occlusion it
# exists for. But the exclusion has a cost, and it is not a small one: the two
# things this skill hands an author for keeping a still screen alive — swapping
# captions, and narration pacing — are both invisible here **by construction**.
# A perfectly healthy demo that tours a rendered screen with three captions
# holds the measured region still for 20-22 s, which is indistinguishable from
# a card covering the terminal for 23 s.
#
# So a held stretch on its own says nothing about whether anything is wrong,
# and `CONTENT_ACTING_VERBS` below is what turns it into a signal. Two stated
# limits survive that, both narrower:
#
#   * whatever happens in the bottom fifth of the app is not measured at all;
#     on a terminal that is the last rows before the screen starts scrolling.
#   * a demo that genuinely holds still *through* an acting verb warns, and is
#     right to be looked at even though nothing is broken.
CONTENT_CAPTION_TRIM = 0.2

# Median luma standard deviation under which the content rect is "blank".
#
# Measured over the trimmed rect, on every take tests/smoke records plus this
# repo's reference demo:
#
#   blank                            0.2 - 1.1   (a real recording with the app
#                                                 rect painted flat scores 0.21)
#   healthy, sparsest terminal       2.0         (one failing command, nothing
#                                                 else on screen)
#   healthy, ordinary terminal       4.6 - 14.3
#   healthy, web                    16.0 - 36.1
#
# One floor for both media rather than two, and it sits at 1.0 — 2x under the
# sparsest healthy take in the suite and roughly 5x over a blank one. The
# asymmetry is deliberate and it is not a compromise: this arm has a partner.
# A page that never painted does not change either, so the static arm below
# catches the blank case a second time, and a floor set high enough to catch
# every blank take on its own would warn about honest, nearly-empty terminal
# demos — which costs the warning its credibility everywhere.
#
# tests/smoke keeps its own, higher, per-medium floors as a *gate*. This is the
# floor shipped to somebody else's app, where a false alarm is the expensive
# failure.
CONTENT_BLANK_FLOOR = 1.0

# When two consecutive samples count as "the same picture": fewer than
# CONTENT_MOVED_PIXELS of the 14 400 reduced pixels moved by more than
# CONTENT_PIXEL_DELTA luma levels.
#
# **A mean absolute difference does not work here, and that was measured, not
# assumed.** libx264 re-quantises a held frame at every I-frame, and on the
# occluded reference take that redrew the card's glyph edges hard enough to
# move the mean by 0.43 — while the *smallest real change* in the healthy take
# of the same storyboard moved it by 0.71. A 1.6x gap is not a threshold, it is
# a coin toss, and setting it either way loses the detector or floods it.
#
# Counting pixels separates the two cleanly, because the two phenomena have
# different shapes: re-quantisation is a fraction of a level smeared over the
# whole rect, while a command running or a page repainting moves a *region* by
# tens of levels. Measured over the same two takes, per consecutive pair:
#
#   covered (a card over the whole terminal)   0 pixels, every pair of 46
#   healthy terminal, real changes             2, 13, 20, 27, 31, ... 1256
#   healthy web, real changes                 10, 13, 14, 16, 17, ... 991
#
# So the bar sits at 4: it never fires on the covered take (which reported
# 0.43 mean and would have defeated any mean-based bar) and it is 2.5x under
# the smallest change either healthy take makes. The 2-pixel terminal pair is
# the tail of a transition whose leading edge already registered 1256 pixels
# half a second earlier — missing it costs nothing.
CONTENT_PIXEL_DELTA = 12
CONTENT_MOVED_PIXELS = 4

# How long the content rect may hold still before it is worth looking at, *and*
# an acting verb ran inside that stretch. `static_for` is reported always,
# whatever it is; this and CONTENT_ACTING_VERBS together decide whether stderr
# and `warnings` mention it.
#
# Measured, on the longest stretch a take holds one frame:
#
#   reference demo, web part                       4.5 s   healthy
#   reference demo, terminal part                  5.0 s   healthy
#   tests/smoke's content-shown take               6.0 s   healthy
#   tests/smoke's terminal take                   10.0 s   healthy
#   a terminal demo touring a screen, 2 captions  16.5 s   healthy
#   a web demo touring a screen, 3 captions       20.0 s   healthy
#   a terminal demo touring a screen, 3 captions  22.0 s   healthy
#   reference demo take 1, card over the terminal 23.0 s   the defect
#   tests/smoke's content-covered take            30.5 s   the defect
#
# **Read that table before touching this constant.** There is no value of it
# that separates the last two rows from the three above them: a healthy demo
# narrated over a rendered screen and a demo nobody can see produce the same
# number. That is not a tuning problem, it is what excluding the caption band
# costs (see CONTENT_CAPTION_TRIM), and it is why duration alone never warns.
#
# What this constant does is set how long a stretch has to be before it is worth
# reporting at all. 15 s is comfortably over every healthy take's ordinary holds
# and under the shortest occlusion measured.
CONTENT_STATIC_WARN_S = 15.0

# The storyboard verbs that **act on the app**. A held picture spanning one of
# these is worth a human's attention; a held picture spanning only the others is
# a narrated hold — which is exactly what this skill tells authors to write:
#
#     "during unavoidable waits, tour what's on screen or swap the caption"
#
# This is the whole difference between a detector and a timer. Without it the
# static arm fires on ordinary demos on both media — measured at 16.5-22.0 s on
# three healthy takes, against 23.0 s for the defect it exists to catch — and
# the sentence it prints blames an occlusion that did not happen. An artifact
# confidently attributing something to the wrong cause is the precise failure
# issue #97 exists to remove, so the detector must not commit it.
#
# The split is by *what the verb does to the picture*, not by how long it takes:
#
#   acting    it changed the app, the page or the terminal screen, so something
#             should have moved in the measured region and nothing did.
#   passive   it narrated, waited, held, or photographed. A still picture is the
#             expected outcome there, not a symptom.
#
# `wait_for*` are passive on purpose: a wait that returns immediately because
# its condition already held changes nothing, and cannot be told apart here from
# one that really waited. Guessing would put the false positive straight back.
#
# tests/smoke asserts this covers **every** verb the recorders define, so a verb
# added later cannot quietly default into either bucket.
CONTENT_ACTING_VERBS = frozenset(
    {
        "click",
        "click_fast",
        "goto",
        "key",
        "move_to",
        "redact",
        "run",
        "scroll_to",
        "send",
        "spotlight",
        "terminal",
        "terminal_close",
        "terminal_output",
        "type_into",
    }
)
CONTENT_PASSIVE_VERBS = frozenset(
    {
        "bridge",
        "caption",
        "hold",
        "interlude",
        "pause",
        "shot",
        "wait_for",
        "wait_for_prompt",
        "wait_for_text",
    }
)

# How many of the beats a held stretch spans are named in the report. Enough to
# see what was going on, few enough that `timeline.json` stays a file somebody
# opens.
CONTENT_STATIC_BEATS_MAX = 8


def content_rect(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """An app rect with the recorder's own caption band cut off the bottom.

    Both recorders' `_content_rect` funnel through this, so "what the check
    measures" is one definition rather than two that drift.
    """
    x, y, w, h = rect
    return (
        max(0, int(x)),
        max(0, int(y)),
        max(2, int(w)),
        max(2, int(h * (1.0 - CONTENT_CAPTION_TRIM))),
    )


def _content_frames(
    mp4: Path, rect: tuple[int, int, int, int], sample_fps: int
) -> list[bytes]:
    """`mp4`'s content rect, sampled and reduced to grayscale frames."""
    x, y, w, h = rect
    chain = (
        f"fps={sample_fps},crop={w}:{h}:{x}:{y},"
        f"scale={_CONTENT_W}:{_CONTENT_H},format=gray"
    )
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", chain,
         "-an", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg could not sample {mp4.name}: "
            f"{proc.stderr.decode(errors='replace').strip()[:300]}"
        )
    size = _CONTENT_W * _CONTENT_H
    raw = proc.stdout
    return [raw[i : i + size] for i in range(0, len(raw) - size + 1, size)]


def _luma_stddev(frame: bytes) -> float:
    """How much picture is in one reduced frame. A flat frame scores 0."""
    n = len(frame)
    mean = sum(frame) / n
    return (sum((b - mean) ** 2 for b in frame) / n) ** 0.5


def _moved_pixels(a: bytes, b: bytes) -> int:
    """How many reduced pixels moved by more than `CONTENT_PIXEL_DELTA`.

    The question a mean cannot answer: *did part of the picture change*, as
    opposed to *did the whole thing shift by a fraction of a level*. See the
    constants above for the measurement that made the difference matter.
    """
    return sum(
        1 for x, y in zip(a, b, strict=True) if abs(x - y) > CONTENT_PIXEL_DELTA
    )


def _beats_within(beats: list[dict], start: float, end: float) -> list[dict]:
    """The beats that **began** inside [start, end], classified.

    Began, not overlapped and not midpoint-inside, and the difference is the
    whole correctness of this. A held stretch begins at the first sample after
    something changed — and the thing that changed is very often the verb
    immediately before it. Measured on a healthy fixture: `run("seq 1 4")`
    spanning 2.32-2.85 s, its output landing at 2.50 s, and the stretch
    therefore starting at 2.50 s. By midpoint (2.585 s) that `run` is "inside a
    stretch where nothing changed" — while in fact it is the thing that *ended*
    the previous stretch and started this one. The warning that produced was
    exactly the false positive this correlation exists to remove.

    So a beat qualifies only if it started at or after the stretch did. The
    error this trades for is a miss: a long acting verb that begins before the
    stretch and runs silently through it is not counted. That is the direction
    to be wrong in — quieter than the truth, never louder — and it is also the
    direction the beat/video clock skew (issue #18) pushes an edge case.
    """
    found = []
    for beat in beats or []:
        t_start = beat.get("t_start")
        if not isinstance(t_start, (int, float)):
            continue
        if not start <= float(t_start) <= end:
            continue
        verb = str(beat.get("verb") or "")
        found.append(
            {
                "index": beat.get("index"),
                "verb": verb,
                "acting": verb in CONTENT_ACTING_VERBS,
            }
        )
    return found


def content_report(
    mp4: Path | str,
    rect: tuple[int, int, int, int] | None,
    beats: list[dict] | None = None,
    *,
    floor: float = CONTENT_BLANK_FLOOR,
    sample_fps: int = CONTENT_SAMPLE_FPS,
    static_limit: float = CONTENT_STATIC_WARN_S,
) -> dict:
    """Does this recording show anything? See the section header.

    A function of the mp4, the rect and the beat log, so it can be re-run on a
    demo somebody already has without re-recording:

        doc = json.loads((d / "timeline.json").read_text())
        content_report(d / "demo.mp4", tuple(doc["content"]["rect"]), doc["beats"])

    `rect` is the app's region in *video* pixels, already trimmed by
    `content_rect`; pass None and the report says, in the document itself, that
    nothing was measured and why.

    **`beats` is what makes the held-picture arm a detector rather than a
    timer**, and leaving it out is a supported, conservative choice rather than
    an optimisation: without it `static_for` is still measured and reported, and
    it never warns, because there is no way to tell a demo narrating over a
    rendered screen from a demo nobody can see. See CONTENT_ACTING_VERBS.

    Never raises — the whole body is guarded, not just the ffmpeg call. This
    runs inside `__exit__` before the timeline, the evidence and the review
    frames are written, so an exception escaping here would cost a take every
    artifact that section promises can never be lost.
    """
    try:
        return _content_report(
            mp4, rect, beats, floor=floor, sample_fps=sample_fps,
            static_limit=static_limit,
        )
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return {
            "measured": False,
            "note": (
                f"the picture check itself failed ({type(exc).__name__}: "
                f"{exc}), so nothing is claimed about these frames"
            ),
            "rect": list(rect) if rect else None,
            "sample_fps": sample_fps,
            "frames": 0,
            "score": None,
            "floor": floor,
            "static_for": None,
            "static_from": None,
            "static_beats": None,
            "static_limit": static_limit,
            "warnings": [],
        }


def _content_report(
    mp4: Path | str,
    rect: tuple[int, int, int, int] | None,
    beats: list[dict] | None,
    *,
    floor: float,
    sample_fps: int,
    static_limit: float,
) -> dict:
    """`content_report` without the guard. Call that, not this."""
    mp4 = Path(mp4)
    report: dict = {
        "measured": False,
        "note": None,
        "rect": list(rect) if rect else None,
        "sample_fps": sample_fps,
        "frames": 0,
        "score": None,
        "floor": floor,
        "static_for": None,
        "static_from": None,
        # The beats the held stretch spans, and whether each acted on the app.
        # Null when no beat log was supplied — which is *not* the same as an
        # empty list, and the difference decides whether the arm may warn.
        "static_beats": None,
        "static_limit": static_limit,
        "warnings": [],
    }
    if rect is None:
        report["note"] = (
            "this recorder does not know where the app sits in the frame, so "
            "nothing about the picture was measured — see content_report()"
        )
        return report
    if not mp4.is_file():
        report["note"] = f"there is no {mp4.name} to measure"
        return report
    try:
        frames = _content_frames(mp4, rect, sample_fps)
    except Exception as exc:  # noqa: BLE001 - a measurement is not a recording
        report["note"] = f"{type(exc).__name__}: {exc}"
        return report
    if len(frames) < 2:
        report["note"] = (
            f"only {len(frames)} frame(s) could be sampled from {mp4.name} at "
            f"{sample_fps} fps, which is too few to say anything"
        )
        report["frames"] = len(frames)
        return report

    report["measured"] = True
    report["frames"] = len(frames)
    # Median, not mean and not min: one blank opening frame must not condemn a
    # take (every web take opens on a page that has not painted yet), and one
    # good frame must not excuse a blank one.
    score = statistics.median(_luma_stddev(f) for f in frames)
    report["score"] = round(score, 2)

    # The longest run of consecutive samples that do not change, measured in
    # gaps rather than frames: two identical samples 0.5 s apart is 0.5 s of
    # held picture, not 1.0 s.
    step = 1.0 / sample_fps
    best_gaps = best_start = run_gaps = run_start = 0
    for i in range(1, len(frames)):
        if _moved_pixels(frames[i - 1], frames[i]) < CONTENT_MOVED_PIXELS:
            run_gaps += 1
        else:
            run_gaps, run_start = 0, i
        if run_gaps > best_gaps:
            best_gaps, best_start = run_gaps, run_start
    held = best_gaps * step
    began, ended = best_start * step, (best_start + best_gaps) * step
    report["static_for"] = round(held, 2)
    report["static_from"] = round(began, 2)

    # What the storyboard was doing while the picture stood still. Verb and
    # index only — never the selector: a selector can hold a value somebody
    # registered as a secret, and this string goes to stderr before the take's
    # scrubbing has run. The index is enough; the beat is in the same file.
    spanned = None if beats is None else _beats_within(beats, began, ended)
    acting = [b for b in (spanned or []) if b["acting"]]
    if spanned is not None:
        report["static_beats"] = spanned[:CONTENT_STATIC_BEATS_MAX]

    warnings: list[str] = []
    if score < floor:
        warnings.append(
            f"there is no picture where the app should be: the content rect "
            f"scores {score:.2f} luma stddev (median of {len(frames)} sampled "
            f"frames over {tuple(rect)}), under the {floor} blank floor. These "
            f"frames are featureless — a page that never painted, a take "
            f"recorded black, or a rect that is not where the app ended up."
        )
    # Both conditions, and the second is the one that stops this being a timer.
    # A long held stretch on its own is *ordinary*: a demo touring a rendered
    # screen with three captions holds it for 20-22 s, which is what the defect
    # this exists for also measures. Only a stretch that swallowed a verb which
    # acted on the app is worth a human's time.
    if held >= static_limit and acting:
        named = ", ".join(f"beat {b['index']} `{b['verb']}`" for b in acting[:4])
        more = f" (+{len(acting) - 4} more)" if len(acting) > 4 else ""
        warnings.append(
            f"the content rect held one picture for {held:.1f}s "
            f"({began:.1f}s-{ended:.1f}s) while {len(acting)} verb(s) that act "
            f"on the app ran inside it: {named}{more}. Nothing changed in the "
            f"measured region while they ran. **What was measured**: the app "
            f"rect {tuple(rect)}, which excludes the recorder's own caption bar "
            f"— so a caption change is invisible here by design and is not what "
            f"this reports. An overlay left up, a modal that never closed and an "
            f"app that stopped painting all look like this; so does a demo that "
            f"genuinely holds still through these verbs. The frames cannot tell "
            f"those apart — open {mp4.name} at {began:.1f}s and look."
        )
    report["warnings"] = warnings
    return report


def merge_content(records: list[dict]) -> dict:
    """The content report for a demo stitched out of several segments.

    `records` are the merged timeline's per-segment records, each with its own
    `content` (the report that segment wrote when it encoded its `.seg.mp4`).
    Nothing is re-measured: a stitched demo can join a web part and a terminal
    part, and there is no single rect for the join. So the merged answer is the
    **worst** of the parts on each arm, and every warning is kept, attributed
    to the segment it came from.

    Under-reports rather than over-reports, in two known ways, both preferred
    to a confident guess: a held stretch spanning a cut is reported as the
    longer of its two halves rather than their sum, and a segment that could
    not be measured at all lowers nothing.
    """
    parts = [
        (record.get("segment"), record.get("content"))
        for record in records
        if isinstance(record.get("content"), dict)
    ]
    measured = [content for _, content in parts if content.get("measured")]
    return {
        "measured": bool(measured),
        "note": (
            None
            if measured
            else "no segment of this demo reported a measured picture — see "
            "each segment's own `content` under `segments`"
        ),
        "rect": None,  # per segment; a merged demo may mix two geometries
        "sample_fps": _common([c.get("sample_fps") for c in measured]),
        "frames": sum(int(c.get("frames") or 0) for c in measured),
        "score": min(
            (c["score"] for c in measured if c.get("score") is not None),
            default=None,
        ),
        "floor": _common([c.get("floor") for c in measured]),
        "static_for": max(
            (c["static_for"] for c in measured if c.get("static_for") is not None),
            default=None,
        ),
        # Both deliberately null: the worst run belongs to one segment's own
        # clock and to that segment's own beat numbering, and restating either
        # against the merged video would be a confidently wrong timestamp and a
        # confidently wrong beat index. The segment's own record has both.
        "static_from": None,
        "static_beats": None,
        "static_limit": _common([c.get("static_limit") for c in measured]),
        "warnings": [
            f"segment {name!r}: {warning}"
            for name, content in parts
            for warning in (content.get("warnings") or [])
        ],
    }


def print_content_summary(content: dict | None, media: str) -> None:
    """Say what the picture check found, on stderr, unasked.

    The whole point of issue #97 is that nobody was going to open the video, so
    this is printed on every take rather than only when something is wrong: a
    reviewer who has never seen the healthy line has no baseline for the
    unhealthy one.
    """
    if not isinstance(content, dict):
        return
    if not content.get("measured"):
        print(
            f"demo-video: the picture in {media} was not measured — "
            f"{content.get('note')}",
            file=sys.stderr,
        )
        return
    for warning in content.get("warnings") or []:
        print(f"demo-video: WARNING — {media}: {warning}", file=sys.stderr)
    if content.get("warnings"):
        return
    held = content.get("static_for")
    limit = content.get("static_limit")
    # A long held stretch that did *not* warn is worth one clause rather than
    # silence: it is the ordinary shape of a narrated demo, and a reader who
    # only ever sees the number when something is wrong will read it as wrong.
    why = ""
    if isinstance(held, (int, float)) and isinstance(limit, (int, float)):
        if held >= limit:
            why = (
                " — over the "
                f"{limit}s limit, but every beat inside it was narration, a "
                "hold or a wait, which is what a still screen is supposed to "
                "look like"
            )
    print(
        f"{media} shows a picture (content {content.get('score')} over the "
        f"app rect, longest still stretch {held}s{why})"
    )


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
        evidence: bool | None = None,
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
        # Did *this* take encode an mp4? Not "is there an mp4 in the folder" —
        # that question has a stale answer, and every consumer of it was
        # reading the previous run's file: `duration` in timeline.json (issue
        # #20), the review frames extracted off `media`, and the last frame in
        # `failure/`. Set in `_convert`, after ffmpeg returns.
        self._converted = False
        # What the *picture* turned out to be (issue #97). Measured off the
        # encoded mp4 in `__exit__`, so it is null on any take that wrote none,
        # and it is the one thing in the timeline that describes the frames
        # rather than the storyboard. See the "did the recording show
        # anything?" section.
        self._content: dict | None = None
        # The medium's screen, read once on the failure path *before* the final
        # redaction check vouches for it, and turned into a file only if that
        # check passes. See the "failure artifacts" section.
        self._failure_screen_text: str | None = None
        self._failure_json: dict | None = None
        self._failure_docs: list[tuple[Path, str]] = []
        # Per-beat evidence (see "per-beat evidence" above). Buffered as
        # (beat record, medium payload) and only turned into files on a clean
        # exit — nothing plaintext reaches the disk before the mask has been
        # verified, which is why there is no evidence file for
        # _discard_artifacts to take back. `_evidence_masks` accumulates the
        # rendered text of everything redact() is covering; the union is
        # applied to *every* beat's evidence on the way out, so a value first
        # seen at beat 20 is masked out of beat 3 as well.
        if evidence is None:
            evidence = _env_flag("EVIDENCE")
        self._evidence_on = True if evidence is None else bool(evidence)
        self._evidence: list[tuple[dict, dict]] = []
        self._evidence_masks: set[str] = set()
        # Text the page renders *outside* every redacted subtree, deduplicated
        # across beats. A harvested string found in here is rendered in the
        # clear somewhere, so masking it would only damage the evidence — see
        # `_evidence_forbidden`.
        self._evidence_outside: set[str] = set()
        self._evidence_res: dict[str, re.Pattern[str]] = {}
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

        Values shorter than `SECRET_MIN_LEN` are refused. Registering one is
        find-and-replace over every text artifact the take writes, and a short
        literal matches ordinary output — see `SECRET_MIN_LEN`. The error names
        the length, never the value: an exception message ends up in terminal
        scrollback, CI logs and bug reports, which is the set of places this
        method exists to keep the value out of.
        """
        for value in values:
            text = value.reveal() if isinstance(value, Secret) else value
            if not isinstance(text, str) or not text:
                raise ValueError("register_secret() takes non-empty strings")
            if len(text) < SECRET_MIN_LEN:
                raise ValueError(
                    f"register_secret() was given a {len(text)}-character "
                    f"value, and the floor is {SECRET_MIN_LEN}. Registering is "
                    f"a literal find-and-replace over the beat log, the still "
                    f"filenames, the caption text, every line of terminal "
                    f"output and every evidence file — a value this short "
                    f"matches things that are not it (a selector, an index, a "
                    f"timestamp), and the corruption reads as redaction "
                    f"working. To hide a short value on screen use redact(), "
                    f"which covers the pixels and rewrites no text."
                )
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

    def _no_secrets(self, text: "str | Secret", where: str) -> None:
        """Raise unless `text` is free of every registered secret.

        The message never contains the secret: it names the leak site and
        quotes the *scrubbed* line, which is enough to find the offending
        storyboard line without writing the value into a terminal, a CI log,
        or a bug report.

        A `Secret` handed in where a string belongs is refused here rather than
        left to fail somewhere downstream, and this is the single choke point
        every authored-text verb already goes through — `caption`,
        `interlude`, `terminal`, `terminal_close`, `run`, `key`, `send`, and
        `_prepare_line`. `Secret` is deliberately not a `str` (see its
        docstring), so `caption(Secret(v))` used to die three different obscure
        deaths depending on whether the registry happened to be empty: a
        `TypeError: argument of type 'Secret' is not iterable` from `secret in
        text`, or a serialization failure much later, or nothing until the
        value reached the TTS cache. None of them said what was wrong.
        """
        if isinstance(text, Secret):
            raise SecretLeak(
                f"{where} was given a Secret, and a Secret is the one thing it "
                f"can never take: a caption is burned into every frame and "
                f"spoken aloud, and the other authored-text verbs are drawn on "
                f"screen the same way. Secret() exists to be typed, not shown "
                f"— pass it to type_into() or send(). If the *words* need to "
                f"mention it, reword them; if the value has to be on screen "
                f"and hidden, that is redact()."
            )
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
            self._context.add_init_script(
                _INTERLUDE_JS.replace("__ID__", INTERLUDE_ID)
                .replace("__CSS__", INTERLUDE_CSS)
            )
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
        # The one page read the failure path adds, and it goes **here**: after
        # `_stop()` has flushed whatever the medium was withholding, and before
        # the verifier below vouches for the page. Reading it after the
        # verifier would be dumping page text that nothing had checked — a
        # post-verification window, which is the class of hole this ordering
        # exists to close. Buffered in memory; it becomes a file only if the
        # verifier passes and only after `_build_failure` has masked it.
        if exc_type is not None:
            self._capture_failure_screen()
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
        # Evidence documents are assembled **after** the mask has been vouched
        # for and only when there is still a take to keep — the same treatment
        # an unverifiable mask gets, because evidence is the one artifact that
        # is plain text and a pixel control never protected it.
        #
        # It runs after `_stop()` deliberately, and that is safe rather than
        # merely convenient: the captures were buffered per beat while the page
        # was alive, and this turns them into documents in memory — it opens no
        # beat, touches no page, and writes no file. Nothing here can add
        # content to the recording after the verifier has vouched for it, which
        # is the property the ordering above exists to protect.
        #
        # It runs on the **failure** path too now, and that is issue #11 step 1
        # rather than a liberty: every beat in the timeline this take is about
        # to write carries an `evidence` path, so writing that timeline while
        # skipping this would point every beat at a file that is not there.
        # The refusal is unchanged — a document that cannot be made safe raises
        # SecretLeak here, before anything has been written, and then nothing
        # is.
        #
        # `failure/` is built in the same breath and for the same reason: a
        # crash dump of a page mid-secret is the worst leak path this package
        # has, so it is masked, checked and refused in memory rather than
        # written and regretted.
        failure: dict | None = (
            None if exc_type is None else self._failure_summary(exc_type, exc)
        )
        leaked = unmasked is not None or (
            exc_type is not None and issubclass(exc_type, SecretLeak)
        )
        if not leaked:
            try:
                self._build_evidence()
                if failure is not None:
                    self._build_failure(failure)
            except SecretLeak as leak:
                unmasked = leak
            except Exception as exc_build:  # noqa: BLE001 - same verdict
                # Not a leak that was found, but a document nobody can say is
                # clean — which is the same verdict for the same reason. The
                # message says which of the two happened, because "could not be
                # verified" and "holds a secret" send an author to different
                # places.
                unmasked = SecretLeak(
                    f"this take's evidence could not be assembled "
                    f"({type(exc_build).__name__}: {exc_build}), so the "
                    f"recorder cannot say whether it holds a registered or "
                    f"redacted value. This take wrote no mp4."
                )
        # **`keep`, not `clean`** — and that one word is issue #11 (with #32).
        # The old guard was `exc_type is None`, so a storyboard that raised
        # threw away the webm the browser already had in hand, wrote no beat
        # log for beats that were sitting in memory, and left nothing at all
        # behind. In CI, where there is no screen to look at, that means blind
        # retries — and #3 had already settled the principle in the other
        # direction: a strict take fails *after* writing every artifact,
        # because a broken take is precisely the one somebody wants to see.
        #
        # What still keeps nothing is a leak, and only a leak. That distinction
        # is the whole of `leaked` above: an unverifiable mask means the
        # recording, the stills and the beat log may each hold the value, and
        # an artifact nobody can vouch for is worse than no artifact.
        keep = not leaked and unmasked is None
        convert_error: BaseException | None = None
        video = self.page.video
        self._context.close()
        webm = Path(video.path()) if video else None
        self._browser.close()
        self._pw.stop()
        try:
            if keep and webm and webm.exists():
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
            if keep:
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
            #   unmasked        the mask could not be verified, so this take
            #                   keeps *nothing* — and what it does not touch is
            #                   what a previous run left in the same folder.
            #                   That folder is the one in #46: a watchable
            #                   demo.mp4, an emptied images/, and last week's
            #                   timeline.json. The marker is the entire defence
            #                   there, because it is the only file written.
            #   convert_error   the storyboard finished and ffmpeg did not, so
            #                   the timeline is this week's and any mp4 is not.
            #
            # A strict failure is none of these: it writes every artifact and
            # they are all current, so its marker is cleared like any success's.
            marker_failure = failure
            if marker_failure is None and unmasked is not None:
                marker_failure = {
                    "type": type(unmasked).__name__,
                    "message": str(unmasked)[:FAILURE_MESSAGE_CHARS],
                    "beat": None,
                    "verb": None,
                }
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
                    self._report_failure(failure, wrote_dump=keep)
            else:
                self._clear_failure_marker()
                self._clear_failure_dir()
            # Always, strict or not, crashed or not: the problems a take
            # recorded are the one thing nobody thinks to go looking for, so
            # they have to arrive unasked.
            self._print_issue_summary()
            # Last, so it is the line still on screen when the take ends. A
            # recording nobody can see is not something to bury above ffmpeg's
            # output (issue #97).
            print_content_summary(self._content, self._media_path().name)
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
        if self._evidence_on:
            # Written onto the beat rather than left for a reader to derive
            # from `index`, so a merge that renumbers beats (issue #7) does
            # not silently repoint every beat at somebody else's evidence.
            record["evidence"] = (
                f"{EVIDENCE_DIR}/{evidence_name(record['index'], self.segment)}"
            )
        record.update(extra)
        self._beats.append(record)
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
            # Scrubbed at record time as well as on the way out. The message is
            # not the recorder's: `wait_for_text()` quotes a thousand
            # characters of terminal screen into its timeout, and that screen
            # can hold anything the program printed.
            record["error"] = {
                "type": type(raised).__name__,
                "message": self.scrub(str(raised)),
            }
            raise
        finally:
            # Captured before `t_end` is stamped, so the round trips it costs
            # are accounted for *inside* the beat that paid for them and no
            # unexplained gap opens up between one beat and the next. Nested
            # try/finally so `t_end` is stamped even when the capture refuses
            # (a SecretLeak out of a medium's payload is fatal, on purpose).
            try:
                if self._evidence_on:
                    self._capture_evidence(record)
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

    # -- per-beat evidence (see the section at the top of this file) --------

    def _evidence_payload(self) -> dict:
        """What this medium can say about the screen right now.

        Overridden per medium (`Recorder` -> ARIA + outerHTML, `TerminalRecorder`
        -> the rendered screen). A payload of `{"omitted": reason}` is the
        medium refusing to hand over page text it cannot vouch for; the file is
        still written, and says so.
        """
        return {}

    def _capture_evidence(self, beat: dict) -> None:
        """Buffer one beat's evidence.

        Raises only SecretLeak, and that exclusion is the whole point of the
        handler below rather than an afterthought. A broad `except` here would
        swallow one — this runs in a `finally`, and everything a medium's
        payload touches (the mask, the page) is a place SecretLeak comes from.
        Catching it would turn a control that used to kill a take into one that
        prints a line and lets the mp4 be written. Every other failure is a
        diagnostic and must not lose an otherwise fine take: the beat gets a
        file saying what went wrong, which keeps the `evidence` pointer on
        every beat pointing at something real.
        """
        try:
            payload = self._evidence_payload()
        except SecretLeak:
            raise
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

    def _evidence_forbidden(self) -> tuple[str, ...]:
        """Every literal that must not appear in an evidence file, longest first.

        Two sources, and the second is the reason this exists at all:

          * `self.secrets` — text somebody registered. `scrub()` already covers
            this everywhere else, and nothing below can drop one: the author
            said explicitly that the value matters.
          * `self._evidence_masks` — the *rendered text of everything redact()
            is covering*, read out of the page as the take ran. `redact()` is a
            pixel control: it hides where a value renders and leaves the value
            in the DOM, so a text dump of that DOM is not protected by it at
            all. This is what makes evidence inherit redaction.

        **A harvested string is only used as a mask if it appears nowhere
        outside the redacted subtrees**, and without that rule this feature
        destroys the artifact it exists to produce. Harvesting *every* node of a
        redacted card also harvests its label: `redact("#revenue-card")` around
        a `<span>Revenue</span>` would otherwise register "Revenue" as a global
        forbidden literal and rewrite every unrelated paragraph in every file as
        `[redacted] for the quarter was $128,400`. Worse, a card holding
        `sk-<i>live</i>-CHLD…` harvests the text nodes "sk-" and "live" on their
        own and rewrites every other key on the page.

        The rule is not a heuristic about what a secret looks like: a string
        that also renders *in the clear* somewhere the mask does not cover is,
        by construction, not being hidden by that mask — it is in the frames, in
        the stills and in the video. Masking it in a text file buys nothing and
        costs the file its meaning. What is left is exactly what only exists
        behind the mask.

        Longest first so overlapping values (a token, and the header line
        holding it) mask the larger one whole instead of leaving its tail.
        """
        outside = "\n".join(self._evidence_outside)
        literals = set(self._secrets)
        for text in self._evidence_masks:
            flat = self._flatten(text)
            if len(flat) < EVIDENCE_MIN_MASK_LEN:
                continue
            if flat in outside:
                continue  # rendered in the clear elsewhere: not this mask's
            literals.add(text)
        return tuple(sorted(literals, key=len, reverse=True))

    def _evidence_re(self, literal: str) -> "re.Pattern[str]":
        """`literal` as a pattern whose whitespace is elastic in both directions.

        Every leak this has had is the same shape: a comparison between a value
        somebody registered and *a transformation of that value* that the code
        did not anticipate. Whitespace is where two of those transformations
        land, and they pull opposite ways:

          * **Whitespace the literal has and the text does not.** The harvest
            reads `textContent`, which carries the source's own indentation: a
            value on its own line in hand-written HTML comes back as
            `'\\n      wombatxray7714\\n    '`, while an ARIA tree renders it
            `- code: wombatxray7714`. So a run of whitespace in the literal
            matches any run in the text, and the ends are trimmed.
          * **Whitespace the text has and the literal does not.** Anything that
            reflows text inserts it. `__termText()` emits one xterm.js buffer
            row per line joined with newlines and does not consult `isWrapped`,
            so a credential crossing the last column arrives split in two —
            `"…sk-live-WRAP0000\\n00000000…"` — fully legible, trivially
            recovered with `tr -d '\\n'`, and matched by neither half of an
            exact search. So inside a token of `EVIDENCE_WRAP_MIN_TOKEN`
            characters or more, every character may be followed by whitespace.

        The token-length floor is what keeps the second rule from eating the
        page: separating the characters of a short mask by `\\s*` makes it match
        ordinary prose, and over-masking is the failure `_evidence_forbidden`'s
        whole `outside` rule exists to prevent. See `EVIDENCE_WRAP_MIN_TOKEN`.

        What this does **not** normalize is written down in SKILL.md, under
        "What it still does not cover". This is an asymptotic surface and the
        boundary is stated rather than chased.
        """
        pattern = self._evidence_res.get(literal)
        if pattern is None:
            tokens = literal.split()
            if not tokens:
                pattern = re.compile(re.escape(literal))
            else:
                parts = []
                for token in tokens:
                    if len(token) >= EVIDENCE_WRAP_MIN_TOKEN:
                        parts.append(r"\s*".join(re.escape(c) for c in token))
                    else:
                        parts.append(re.escape(token))
                pattern = re.compile(r"\s+".join(parts))
            self._evidence_res[literal] = pattern
        return pattern

    @staticmethod
    def _evidence_probe(text: str) -> str:
        """`text` with the escapes a *serializer* added resolved. Detection only.

        Never written anywhere — this exists so the two checks that ask "is a
        forbidden value still in here" can see through the encodings the writer
        itself introduces on the way to disk:

          * **HTML entity escaping.** `outerHTML` writes `&` as `&amp;`, `<` as
            `&lt;`, a non-breaking space as `&nbsp;`. A registered
            `sk-live-AMPS0000&sig=0000000000` — an ordinary shape for a
            presigned URL or a SAS token — is in the markup in full and matches
            no raw search, so the mask left it and the backstop waved it
            through, in a file whose `aria` said `[redacted]` two lines above.
          * **JSON string escaping.** The backstop runs over `json.dumps(doc)`,
            where a newline is the two characters `\\n`. Elastic whitespace in
            the pattern cannot match that, so the backstop missed every wrapped
            value the mask missed — the two failed identically, which is the
            one thing a backstop must not do.

        Resolving both, on a copy, costs one pass and removes the whole class.
        The output is deliberately not valid markup or valid JSON; nothing may
        serialize it.
        """
        probe = _JSON_STRING_ESCAPE.sub(
            lambda m: _JSON_ESCAPES.get(m.group(0), m.group(0)), text
        )
        probe = _JSON_UNICODE_ESCAPE.sub(
            lambda m: chr(int(m.group(1), 16)), probe
        )
        return html_unescape(probe)

    def _recoverable_secret(self, text: str) -> str | None:
        """The first registered secret recoverable from `text`, or None.

        The same matching an evidence file gets — whitespace elastic in both
        directions, entity and serializer escapes resolved — pointed at a
        medium's *finished output* rather than at a document, so a final
        redaction check and the evidence writer cannot disagree about whether
        a value is present.

        A terminal screen is what needs it. `__termText()` joins xterm.js
        buffer rows with newlines and does not consult `isWrapped`, so a
        credential crossing the last column is two rows with a newline through
        the middle, and `secret in screen` sees neither half — the same blind
        spot the evidence mask had, in the check that decides whether the
        frames are safe to keep.
        """
        return self._evidence_holds(text, tuple(self._secrets))

    def _evidence_holds(self, text: str, literals: "tuple[str, ...]") -> str | None:
        """The first forbidden literal still findable in `text`, or None.

        Checked against the text as written *and* against
        `_evidence_probe(text)`, because a value that only survives in an
        escaped form is exactly as readable to whoever opens the file.
        """
        probed = self._evidence_probe(text)
        for literal in literals:
            pattern = self._evidence_re(literal)
            if pattern.search(text) or pattern.search(probed):
                return literal
        return None

    def _evidence_mask(self, text: str, forbidden: tuple[str, ...]) -> str:
        for literal in forbidden:
            text = self._evidence_re(literal).sub(SECRET_MASK, text)
        return text

    def _evidence_scrub_deep(self, value: object, forbidden: tuple[str, ...]) -> object:
        """`_evidence_mask` over a whole structure, keys included.

        Keys as well as values: a payload key is a string the recorder chose
        today, but the schema is append-only and the next slice to add a field
        may not be. Masking both costs nothing and removes a hole nobody would
        think to look for.
        """
        if isinstance(value, str):
            return self._evidence_mask(value, forbidden)
        if isinstance(value, dict):
            return {
                self._evidence_mask(str(key), forbidden)
                if isinstance(key, str) else key:
                self._evidence_scrub_deep(item, forbidden)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._evidence_scrub_deep(item, forbidden) for item in value]
        return value

    def _evidence_doc(self, beat: dict, payload: dict) -> dict:
        """One evidence document: masked, then capped, then checked.

        Order matters and is not interchangeable. Masking runs *before*
        capping, because capping first can cut a secret in half and leave its
        first twenty characters as the last thing in the file — which no later
        substring search would find.
        """
        forbidden = self._evidence_forbidden()
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
        doc = self._evidence_scrub_deep(doc, forbidden)  # type: ignore[assignment]
        # Markup is the one field a substring mask cannot finish the job on, and
        # it has two ways of hiding a value from one:
        #
        #   * **structure.** A value written `harbor<b>zenith</b>7725` has a
        #     `textContent` the mask finds and an `outerHTML` it does not, and
        #     only elements the *mask* reached are elided structurally (web.py)
        #     — a `register_secret()` value split across tags in an ordinary
        #     paragraph is reached by neither. So the tags are stripped.
        #   * **entity escaping.** `outerHTML` writes `&` as `&amp;`, so a
        #     registered `…AMPS0000&sig=0000000000` is in the file whole and
        #     matches no raw search. `_evidence_holds` resolves entities before
        #     looking, which is the only reason this branch sees it at all.
        #
        # Markup that still holds a forbidden value after both is withheld
        # rather than published: the field is a convenience, and there is no
        # safe way to edit a value out of markup that interleaves it with
        # elements or spells it in character references.
        html = doc.get("html")
        if isinstance(html, str):
            bare = re.sub(r"<[^>]*>", "", html)
            if self._evidence_holds(bare, forbidden) is not None:
                doc["html"] = EVIDENCE_HTML_WITHHELD
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
        # A backstop over the *serialized bytes*, not a second opinion on the
        # masking above — run against the same list, it cannot disagree with it
        # about a plain string value, and this file does not pretend otherwise.
        # What it does reach is everything the walker structurally cannot: a
        # field added to this schema by a later slice that is built after the
        # scrub, a non-string key, a literal that only exists once serialization
        # has run. The grading that can actually fail is the byte sweep over
        # `evidence/` in tests/smoke.
        #
        # It goes through `_evidence_holds` rather than `in`, and that is the
        # difference between a backstop and a comment. `json.dumps` writes a
        # newline as the two characters `\` and `n`, so a plain substring test
        # here missed every wrapped value the mask missed — failing in the same
        # direction as the thing it backs up, which is the one thing it must
        # not do.
        blob = json.dumps(doc, ensure_ascii=False)
        held = self._evidence_holds(blob, forbidden)
        if held is not None:
            raise SecretLeak(
                f"a beat's evidence still holds a {len(held)}-character "
                f"value that is registered or redacted, after masking — so "
                f"the recorder cannot vouch for what it was about to write. "
                f"No evidence file, no mp4 and no timeline were written."
            )
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
        take that adds `redact()` (or simply has fewer beats than the last one)
        would otherwise leave the previous take's files sitting beside its own,
        holding the very value the new take was written to hide. Nothing else
        here has that shape: the mp4 is overwritten, and a still is only kept
        because it might be a committed guide. Evidence is never committed, so
        there is no such thing as one worth keeping.
        """
        for path in self._stale_evidence(keep):
            try:
                path.unlink()
            except OSError:
                print(
                    f"demo-video: WARNING — could not delete {path}, which is "
                    f"a previous take's evidence and may hold a value this "
                    f"take redacts",
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
        `_verify_redaction_final()`** — that slot is the whole design. After
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

    def _failed_beat(self) -> dict | None:
        """The beat whose verb raised, or None if the failure was between beats.

        Reads `error`, which `_beat` stamps (issue #24), rather than assuming
        the last beat is the culprit — a storyboard can raise in its own code
        between two verbs, and blaming the last beat that *worked* is exactly
        the confidently-wrong attribution `_attributed_beat` refuses to make
        for issues.
        """
        for beat in reversed(self._beats):
            if "error" in beat:
                return beat
        return None

    def _failure_summary(self, exc_type: type, exc: BaseException | None) -> dict:
        """What came out of the `with`, and which beat it came out of.

        Unscrubbed: every consumer (`_timeline_doc`, the dump, the marker)
        masks it on the way to its own file, and each has a different mask.
        """
        beat = self._failed_beat()
        message = str(exc) if exc is not None else ""
        return {
            "type": exc_type.__name__,
            "message": message[:FAILURE_MESSAGE_CHARS],
            "beat": None if beat is None else beat.get("index"),
            "verb": None if beat is None else beat.get("verb"),
        }

    def _failure_doc(self, failure: dict) -> dict:
        """The machine-readable half of `failure/`, masked and checked.

        Same order and same reasons as `_evidence_doc`: mask first, check the
        serialized bytes last, raise rather than write. Nothing in here is read
        from the page — `screen` was buffered before the verifier ran, the
        issues and the beats have been in memory since they happened, and the
        media is named rather than opened.
        """
        forbidden = self._evidence_forbidden()
        beat = self._failed_beat()
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
        doc = self._evidence_scrub_deep(self._scrub_deep(doc), forbidden)  # type: ignore[assignment]
        blob = json.dumps(doc, ensure_ascii=False)
        held = self._evidence_holds(blob, forbidden)
        if held is not None:
            raise SecretLeak(
                f"the failure dump still holds a {len(held)}-character value "
                f"that is registered or redacted, after masking — so the "
                f"recorder cannot vouch for what it was about to write. A "
                f"crash dump of a page mid-secret is the worst leak path this "
                f"package has, so it is refused whole: no failure/, no mp4, no "
                f"timeline and no evidence were written."
            )
        return doc

    def _failure_md(self, doc: dict) -> str:
        """The human half. Pure function of the document above, so it inherits
        its masking rather than re-deriving it."""
        failure = doc.get("failure") or {}
        beat = doc.get("beat") or {}
        where = (
            f"beat {failure.get('beat')} (`{_md_cell(failure.get('verb'))}`"
            + (f", target `{_md_cell(beat.get('selector'))}`" if beat.get("selector") else "")
            + ")"
            if failure.get("beat") is not None
            else "between beats — no verb was running when it happened"
        )
        out = [
            "# This take did not finish",
            "",
            f"`{doc.get('recorder')}` · {doc.get('when')} · "
            f"{doc.get('beats_recorded')} beats recorded",
            "",
            f"**{_md_cell(failure.get('type'))}** at {where}.",
            "",
            f"> {_md_cell(failure.get('message')) or '(no message)'}",
            "",
            "## What is here",
            "",
            "| file | what it is |",
            "|---|---|",
            "| `failure.json` | this, machine-readable: the failing beat in "
            "full, every issue the take recorded, and what was written |",
        ]
        if doc.get("media_written_by_this_take"):
            out.append(
                f"| `last-frame.png` | the final frame of "
                f"`{doc.get('media')}` — what was on screen when it stopped |"
            )
        if doc.get("screen_captured"):
            out.append(
                "| `screen.txt` | the page's accessibility tree (web) or the "
                "rendered terminal buffer, read at the end of the take |"
            )
        out += ["", "## What the app said", ""]
        issues = doc.get("issues") or []
        if not issues:
            out.append(
                "Nothing. No console errors, failed requests or non-zero exits "
                "were recorded, so the app did not announce this."
            )
        else:
            for issue in issues:
                seat = (
                    "before the first beat"
                    if issue.get("beat") is None
                    else f"beat {issue['beat']} (`{_md_cell(issue.get('verb'))}`)"
                )
                out.append(
                    f"- **{_md_cell(issue.get('kind'))}** — {seat} at "
                    f"{_fmt_t(issue.get('t'))}s: {_md_cell(issue.get('message'))}"
                )
            total = doc.get("issue_count", len(issues))
            if total > len(issues):
                out.append(f"- …and {total - len(issues)} more, not recorded.")
        out += [
            "",
            "## The recording",
            "",
            (
                f"`{doc.get('media')}` beside this folder is **this** take's "
                f"partial recording — the webm the browser had in hand when the "
                f"storyboard gave up, converted rather than discarded."
                if doc.get("media_written_by_this_take")
                else f"**This take encoded no mp4.** Any `{doc.get('media')}` in "
                f"the folder above is a *previous* run's and is not a recording "
                f"of this failure — see `{FAILURE_MARKER}`."
            ),
            "",
        ]
        return "\n".join(out).rstrip() + "\n"

    def _build_failure(self, failure: dict) -> None:
        """Turn the crash into documents. Writes nothing.

        Separate from writing for the reason `_build_evidence` is: a document
        that cannot be made safe raises here, before the first byte, so a
        refusal cannot leave half a `failure/` behind.

        It therefore runs **before** `_convert`, which is why the two facts
        that depend on whether the mp4 was encoded — `media_written_by_this_take`
        and the last frame — are filled in by `_write_failure` instead. Writing
        them here produced a dump that said "this take encoded no mp4" beside
        an mp4 this take had just encoded, which is the class of lie this whole
        change exists to remove. They are a boolean and a file name; deferring
        them cannot introduce a literal the masking above did not see.
        """
        out = self.out_dir / FAILURE_DIR
        self._failure_json = self._failure_doc(failure)
        docs: list[tuple[Path, str]] = []
        screen = self._failure_screen_text
        if screen is not None:
            # Its own file rather than a JSON field: a terminal buffer or an
            # ARIA tree is what somebody greps, and `\n` written as the two
            # characters `\` and `n` is not greppable. Masked and checked with
            # the same list and the same matcher as everything else.
            forbidden = self._evidence_forbidden()
            masked = self._evidence_mask(screen, forbidden)
            held = self._evidence_holds(masked, forbidden)
            if held is not None:
                raise SecretLeak(
                    f"the failure dump's page text still holds a {len(held)}-"
                    f"character value that is registered or redacted, after "
                    f"masking. No failure/, no mp4 and no timeline were written."
                )
            capped, _ = _cap_text(masked, EVIDENCE_MAX_SCREEN)
            docs.append((out / "screen.txt", capped))
        self._failure_docs = docs

    def _write_failure(self) -> None:
        """Put the built dump on disk, plus the last frame of the recording.

        The frame comes out of the mp4 with ffmpeg rather than off the page:
        it is a frame of the recording `_verify_redaction_final()` already
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
            (out / "failure.md", self._failure_md(doc)),
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

        The one artifact that is written on **every** abnormal exit, including
        the one where nothing else is: a take that could not verify its mask
        writes no mp4 and no timeline, and what it does not touch is what a
        *previous* run left in the same directory. A folder holding a watchable
        `demo.mp4`, an empty `images/`, and a `timeline.json` from the run
        before reads as a successful take with missing stills — and the video
        is a recording of different code. In a review gate that produces a
        confident approval of something that was never recorded.

        Never raises, and that is deliberate: the absence of this file means
        "the last take succeeded", so failing to write it is itself the lie it
        exists to prevent. Text that cannot be masked is dropped from it rather
        than allowed to stop it.
        """
        marker = self.out_dir / FAILURE_MARKER
        mp4 = self._media_path()
        stale = mp4.exists() and not self._converted
        try:
            forbidden = self._evidence_forbidden()
            message = self._evidence_mask(
                self.scrub(str(failure.get("message") or "")), forbidden
            )
            if self._evidence_holds(message, forbidden) is not None:
                message = (
                    "(withheld: the message still held a registered or "
                    "redacted value after masking)"
                )
        except Exception:  # noqa: BLE001 - the marker must be written regardless
            message = "(withheld: the message could not be masked)"
        when = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        beat = failure.get("beat")
        where = (
            f"beat {beat} (`{failure.get('verb')}`)"
            if beat is not None
            else "between beats"
        )
        lines = [
            "# This demo folder is not the output of a successful take",
            "",
            f"The last take run here failed at {when}, at {where}, with "
            f"**{failure.get('type')}**:",
            "",
            f"> {' '.join(str(message).split())[:600] or '(no message)'}",
            "",
        ]
        if stale:
            lines += [
                f"**`{mp4.name}` in this folder is a *previous* run's.** This "
                f"take encoded no mp4, so what is here is a recording of "
                f"different code, and so is anything derived from it — "
                f"`timeline.json`, `frames/`, `images/`. Do not review them as "
                f"though they described this take.",
                "",
            ]
        elif self._converted:
            lines += [
                f"`{mp4.name}` **is** this take's recording — a partial one, "
                f"cut off where the storyboard gave up. `{FAILURE_DIR}/` has "
                f"the last frame, the console log and the failing beat.",
                "",
            ]
        else:
            lines += [
                f"There is no `{mp4.name}` in this folder: this take wrote "
                f"none, and no previous run left one.",
                "",
            ]
        lines += [
            "This file is written by the demo-video recorder on any abnormal "
            "exit, and **deleted by the next take that succeeds** — so its "
            "presence always describes the most recent run. Do not commit it "
            "and do not delete it by hand; re-record instead.",
            "",
        ]
        try:
            marker.write_text("\n".join(lines))
        except OSError as exc:
            print(
                f"demo-video: WARNING — could not write {marker} ({exc}), so "
                f"nothing in this folder says the take failed",
                file=sys.stderr,
            )

    def _clear_failure_dir(self) -> list[str]:
        """Take a previous run's `failure/` off disk. Returns what went.

        Same reasoning as `_clear_stale_evidence`, and the same hazard: this
        directory holds a text dump of the page — an ARIA tree or a terminal
        buffer — so a stale one sitting beside a *fresh* take is both a lie
        about which run failed and a file that may hold the very value this
        take was rewritten to hide. Bounded to the names `_write_failure`
        writes, never the directory, so nothing anybody put here is touched.
        """
        directory = self.out_dir / FAILURE_DIR
        gone: list[str] = []
        if not directory.is_dir():
            return gone
        for name in ("failure.json", "failure.md", "screen.txt", "last-frame.png"):
            path = directory / name
            try:
                if path.is_file():
                    path.unlink()
                    gone.append(f"{FAILURE_DIR}/{name}")
            except OSError:  # noqa: PERF203 - report what could not be removed
                print(
                    f"demo-video: WARNING — could not delete {path}, which is "
                    f"a previous take's failure dump and may hold a value this "
                    f"take redacts",
                    file=sys.stderr,
                )
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
        except OSError:
            pass
        return gone

    def _clear_failure_marker(self) -> None:
        """Take a previous run's marker off disk once a take succeeds.

        The other half of #46 and not an optional one: a marker left beside a
        freshly-written demo.mp4 is the same lie inverted, and it is the one
        that makes people stop believing the marker at all.
        """
        marker = self.out_dir / FAILURE_MARKER
        try:
            if marker.is_file():
                marker.unlink()
                print(
                    f"demo-video: this take wrote its own artifacts, so the "
                    f"{FAILURE_MARKER} a previous run left here is gone",
                    file=sys.stderr,
                )
        except OSError as exc:
            print(
                f"demo-video: WARNING — could not delete {marker} ({exc}). It "
                f"describes a previous run, not this one.",
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
            return
        # The beat log goes in, and it is what makes the held-picture arm mean
        # anything: without it a demo narrating over a rendered screen and a
        # demo nobody can see are the same number. See CONTENT_ACTING_VERBS.
        self._content = content_report(self._media_path(), rect, self._beats)

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
        # Scrubbed again on the way out, over the whole log. `_beat` scrubs
        # what is registered *at the time the beat runs*, which is nothing at
        # all for a value registered later in the take — and registering late
        # is the ordering a hurried author actually produces. The frames from
        # before the registration keep the value (no recorder can un-paint a
        # caption), but the files this skill tells people to commit do not
        # have to.
        #
        # ...and against what redact() turned out to be covering, which
        # `scrub()` alone does not know about. The harvest exists for the
        # evidence files, but timeline.json and timeline.md are the files this
        # skill tells people to *commit* — a caption or a selector holding a
        # redacted element's text coming back `[redacted]` in evidence and in
        # the clear in the committed log is the worse half of that pair.
        #
        # Note the coupling this creates: with `evidence=False` nothing
        # harvests *on the clean path*, so this falls back to `scrub()` alone
        # there. Turning evidence off is turning off the only thing that reads
        # what redact() hides.
        #
        # The failure path is the exception, and it has to be: `_failure_screen`
        # harvests regardless of the flag, because `failure/screen.txt` is a
        # text dump of the page and `redact()` never protected text. That is
        # also why a timeline written after a crash is masked at least as well
        # as one written after a clean take, never worse.
        forbidden = self._evidence_forbidden()
        beats = [
            self._evidence_scrub_deep(self._scrub_deep(beat), forbidden)
            for beat in self._beats
        ]
        # The issue log too: it quotes console messages, request URLs and
        # process output — none of it authored, all of it capable of carrying
        # a secret the app printed, and all of it written into the same two
        # committed files.
        issues = [
            self._evidence_scrub_deep(self._scrub_deep(issue), forbidden)
            for issue in self._issues
        ]
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
            # Scrubbed like everything else in this document. It carries no
            # selector today and deliberately so (see `_content_report`), but
            # this file is committed and a field that grows a quoted string
            # later must not be the one place the mask does not reach.
            "content": self._evidence_scrub_deep(
                self._scrub_deep(self._content), forbidden
            ),
            "beats": beats,
            "strict": self._strict,
            "issues": issues,
            "issue_count": self._issue_count,
        }
        # Absent on a clean take, so a successful take's timeline.json is
        # byte-for-byte what it was before this key existed — and so that its
        # presence is the whole signal, with no `failure: null` to skim past.
        if failure is not None:
            doc["failure"] = self._evidence_scrub_deep(
                self._scrub_deep(failure), forbidden
            )
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
        # A previous take's evidence, before anything else. This take wrote
        # none — the documents never left memory — but the folder may hold the
        # last take's, and the reason this take is failing is usually that
        # somebody has just added a `redact()` for a value those files contain.
        # Unlike a still, no evidence file is ever a committed artifact, so
        # there is nothing here worth preserving.
        stale = self._stale_evidence()
        self._clear_stale_evidence()
        gone: list[str] = [f"{EVIDENCE_DIR}/{p.name}" for p in stale if not p.exists()]
        # A previous run's failure dump, for exactly the same reason: it is a
        # text dump of the page, this take wrote none (the documents never left
        # memory), and the folder may hold the last one's.
        gone += self._clear_failure_dir()
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
            "mp4, no timeline, no evidence and no failure dump, and deleted "
            + (", ".join(gone) if gone else "nothing (it had written nothing)")
            + f". The raw capture in .video/ is gone too. (Per-beat evidence "
            f"and the failure dump are held in memory until the mask has been "
            f"vouched for, precisely so there is nothing to take back here — "
            f"they are the artifacts that are plain text.) {FAILURE_MARKER} "
            f"has been written, because anything a *previous* run left in this "
            f"folder is still there and is not this take's.",
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
        # Only now. Everything that reads `duration`, extracts a review frame,
        # or pulls the last frame into `failure/` asks this flag rather than
        # `mp4.exists()`, because the file may be a previous take's and the
        # flag cannot be (issue #20).
        self._converted = True
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
                # Carried through rather than recomputed: the segment measured
                # its own `.seg.mp4` against its own rect, and a stitched demo
                # may join two media with two different geometries. See
                # `merge_content`.
                "content": doc.get("content"),
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
        "content": merge_content(records),
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
    # Again here, and that is not duplication. The segment that recorded a
    # covered stretch said so when it was recorded, minutes and several
    # thousand lines of output ago; `demo.mp4` is the file somebody watches and
    # this timeline is the file somebody commits, so the verdict has to arrive
    # with them (issue #97).
    print_content_summary(merged.get("content"), demo.name)
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
