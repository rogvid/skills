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

import functools
import hashlib
import json
import os
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
#   recorder      str    — "Recorder" | "TerminalRecorder" (which medium)
#   segment       str?   — the segment name, or null for a whole demo
#   media         str    — the mp4 this timeline describes, e.g. "demo.mp4"
#   duration      float? — that mp4's real duration (ffprobe), null if absent
#   beats         list   — the beats, in the order they ran
#   strict        bool   — whether strict mode was on for this take
#   issues        list   — the problems the take recorded (see "take issues")
#   issue_count   int    — how many were seen; > len(issues) only if capped
#
# Beat
#   index     int    — position in `beats`, 0-based
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
    out = [
        "# Demo timeline",
        "",
        " · ".join(head),
        "",
        "Written by the demo-video recorder on every clean exit — do not edit "
        "it by hand, re-record instead.",
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

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "_DemoBase":
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._video_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch()
            self._context = self._browser.new_context(
                viewport=self._size,
                record_video_dir=str(self._video_dir),
                record_video_size=self._size,
            )
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
        if exc_type is None:
            self._finish_line(tail=0.5)  # don't end mid-sentence
        self._stop()
        video = self.page.video
        self._context.close()
        webm = Path(video.path()) if video else None
        self._browser.close()
        self._pw.stop()
        try:
            if exc_type is None and webm and webm.exists():
                self._convert(webm)
            if exc_type is None:
                # The beat log is the durable, diffable record of the take — it
                # outlives the mp4, which is not committed. Written after
                # conversion so `duration` is the encoder's answer, not a guess.
                json_path, _ = write_timeline(self.out_dir, self._timeline_doc())
                print(f"wrote {json_path} ({len(self._beats)} beats)")
        finally:
            # Whatever went wrong above, don't leave .video/ behind — the
            # next take into this directory would trip over it.
            for leftover in self._video_dir.glob("*"):
                leftover.unlink()
            self._video_dir.rmdir()
            # Always, strict or not, crashed or not: the problems a take
            # recorded are the one thing nobody thinks to go looking for, so
            # they have to arrive unasked.
            self._print_issue_summary()
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
        record: dict = {
            "index": len(self._beats),
            "t_start": round(time.monotonic() - self._t0, 3),
            "t_end": None,
            "caption": self._caption if caption is None else caption,
            "verb": verb,
            "selector": selector,
            "still": still,
            "segment": self.segment,
        }
        record.update(extra)
        self._beats.append(record)
        try:
            yield record
        finally:
            record["t_end"] = round(time.monotonic() - self._t0, 3)
            self._in_beat = False

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
        return {
            "schema": TIMELINE_SCHEMA,
            "generated_by": "demo-video",
            "recorder": type(self).__name__,
            "segment": self.segment,
            "media": mp4.name,
            "duration": duration,
            "beats": self._beats,
            "strict": self._strict,
            "issues": self._issues,
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

    def shot(self, name: str) -> Path:
        """Still for the written guide -> images/<name>.png."""
        path = self.images_dir / f"{name}.png"
        rel = path.relative_to(self.out_dir).as_posix()
        with self._beat("shot", selector=name, still=rel):
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


def stitch(out_dir: Path, segments: list[str], keep_parts: bool = False) -> None:
    """Concatenate segment recordings into demo.mp4.

    keep_parts=True leaves the .seg.mp4 files on disk so a single segment
    can be re-recorded and re-stitched without redoing the expensive ones
    (segments are untracked; only demo.mp4 is committed).

    Note: each segment writes its own <segment>.seg.timeline.json, with
    timestamps relative to that segment's own start. Merging them into one
    timeline.json next to demo.mp4 — offsetting each by the real duration of
    the segments before it — is issue #7, and belongs here.
    """
    out_dir = Path(out_dir)
    parts = [out_dir / f"{s}.seg.mp4" for s in segments]
    for p in parts:
        if not p.exists():
            raise FileNotFoundError(p)
    listing = out_dir / ".concat.txt"
    listing.write_text(
        "".join(
            # concat-demuxer quoting: a literal ' inside single quotes
            # is written as '\'' (paths like ".../Rógvi's Mac/..." occur).
            "file '{}'\n".format(str(p.resolve()).replace("'", "'\\''"))
            for p in parts
        )
    )
    demo = out_dir / "demo.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(demo)],
        check=True,
    )
    listing.unlink()
    if not keep_parts:
        for p in parts:
            p.unlink()
