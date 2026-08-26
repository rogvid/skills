"""Constants and configuration for the smoke test suite."""

from __future__ import annotations

import re
from pathlib import Path

# Repository paths
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixture"
HELPERS_DIR = REPO_ROOT / "skills" / "demo-video" / "helpers"

# Size floors
MIN_MP4_BYTES = 20_000
MIN_PNG_BYTES = 5_000

# Content scoring
MIN_CONTENT_STDDEV = {
    "web": 6.0,
    "terminal": 2.0,
    "segments": 6.0,
    "spotlight": 6.0,
    "terminal-opening": 2.0,
}

MIN_CAPTION_BAND_DIFF = {"web": 2.0, "terminal": 2.0, "segments": 2.0}
MIN_STILL_DIFF = 0.25
CONTENT_SAMPLE_FPS = 1
CONTENT_KEEP = 0.8

# Content check (issue #97)
CONTENT_TAKES = ("content-shown", "content-covered")
CONTENT_TOURED = "content-toured"
CONTENT_CARD = "Everything after this is covered."
CONTENT_TOUR_COMMAND = ("Four tickets, oldest first.", "seq 1 4")
CONTENT_TOUR_CAPTIONS = (
    "Each line is one ticket.",
    "The left column is the id.",
    "Nothing is filtered here.",
)
CONTENT_TOUR_HOLD_S = 6.0

CONTENT_COMMANDS = (
    ("The first command.", "seq 1 3"),
    ("The second, printing something else.", "printf 'alpha\\nbravo\\n'"),
    ("A listing, cut short.", "ls -1 | head -2"),
    ("Two more words.", "printf 'charlie\\ndelta\\n'"),
    ("And one that says where it is.", "basename $PWD"),
)

CONTENT_STATIC_HEADROOM = 1.6
CONTENT_STATIC_MARGIN = 0.7
CONTENT_SCORE_HEADROOM = 3.0
CONTENT_COVERED_FRACTION = 0.75
CONTENT_PSNR_GAP_DB = 8.0

# Overlay check (issues #162, #163)
OVERLAY_TAKES = ("overlay-cleared", "overlay-left-up")
OVERLAY_LABEL = "Ten minutes later…"
OVERLAY_HOLD_S = 3.2
OVERLAY_QUIET_S = 3.0
OVERLAY_SCRIM_MIN_DIFF = 6.0
OVERLAY_CLEARED_MAX_RATIO = 0.2

# Duration windows
WEB_DURATION_S = (6.0, 45.0)
TERMINAL_DURATION_S = (4.0, 32.0)

WEB_SHOTS = ["01-dashboard", "02-filtered", "03-refreshed", "04-cleared"]
TERMINAL_SHOTS = ["01-echo", "02-listing"]
CAPTION_PROBE = ("90-caption-off", "91-caption-on")

PROBE_CAPTION = "Recorded end to end."
PROBE_QUIET_S = 2.0

# Determinism (issue #10)
ENTROPY_SHOTS = ("01-entropy", "02-entropy")
ENTROPY_SETTLE_S = 1.0
ENTROPY_GAP_S = 1.0

_CURSOR_BOX_JS = """() => {
  const d = document.getElementById('__demo_cursor');
  if (!d) return null;
  const r = d.getBoundingClientRect();
  return {x: r.x, y: r.y, width: r.width, height: r.height};
}"""

MAX_TAKE_VIDEO_DELTA = 1.5
MIN_LIVE_VIDEO_DELTA = 2.5
MIN_LIVE_STILL_DELTA = 4.0

SERVER_START_TIMEOUT_S = 15.0

# Problems (issue #197)
MISSING_PATH = "/definitely-missing.json"

LATE_BOOM = "fixture: late boom"
LATE_BOOM_CAPTION = "Errors during a hold belong to the hold."
LATE_BOOM_JS = ("() => setTimeout(() => { throw new Error('__M__'); }, 1000)").replace(
    "__M__", LATE_BOOM
)
LATE_BOOM_HOLD_S = 3.0

BETWEEN_BEATS = "fixture: between beats"
BETWEEN_BEATS_JS = "() => console.error('__M__')".replace("__M__", BETWEEN_BEATS)

TERMINAL_FAILING_COMMAND = "(exit 3)"
TERMINAL_UNWAITED = ("sleep 1", "(exit 9)")
TERMINAL_RACE_COMMAND = "(exit 5)"
TERMINAL_RACE_EXIT = 5
TERMINAL_RACE_DELAY_S = 1.2
TERMINAL_RACE_SHELL = '#!/bin/sh\nsleep __DELAY__\nexec /bin/bash "$@"\n'

TERMINAL_PROBLEM_EXIT_CODES = {
    "echo ok": 0,
    TERMINAL_FAILING_COMMAND: 3,
    TERMINAL_UNWAITED[0]: 0,
    TERMINAL_UNWAITED[1]: 9,
}

WEB_PROBLEM_ISSUES = [
    {
        "kind": "console_error",
        "needle": "fixture: deliberate console error",
        "verb": "goto",
    },
    {
        "kind": "page_error",
        "needle": "fixture: deliberate uncaught error",
        "verb": "goto",
    },
    {"kind": "http_error", "needle": MISSING_PATH, "verb": "goto"},
    {"kind": "request_failed", "needle": "ERR_CONNECTION_REFUSED", "verb": "goto"},
    {
        "kind": "page_error",
        "needle": LATE_BOOM,
        "verb": "pause",
        "caption": LATE_BOOM_CAPTION,
    },
    {"kind": "console_error", "needle": BETWEEN_BEATS, "verb": None},
]
TERMINAL_PROBLEM_ISSUES = [
    {
        "kind": "nonzero_exit",
        "needle": f"{TERMINAL_FAILING_COMMAND!r} exited 3",
        "verb": "run",
    },
    {
        "kind": "nonzero_exit",
        "needle": f"{TERMINAL_UNWAITED[1]!r} exited 9",
        "verb": "run",
    },
]

STRICT_CAPTION = "A broken page."
STRICT_BEAT_RE = re.compile(r"beat \d+ \((\w+)\)")

# Timeline
WEB_BEATS = [
    ("goto", "/"),
    ("wait_for", "#kpi-rev"),
    ("pause", None),
    ("caption", None),
    ("shot", "01-dashboard"),
    ("spotlight", "#kpi-rev"),
    ("hold", None),
    ("spotlight", None),
    ("caption", None),
    ("type_into", "#search"),
    ("pause", None),
    ("shot", "02-filtered"),
    ("caption", None),
    ("move_to", "#refresh"),
    ("click", "#refresh"),
    ("pause", None),
    ("shot", "03-refreshed"),
    ("caption", None),
    ("clear", "#search"),
    ("shot", "04-cleared"),
    ("press", "Enter"),
    ("press", "Tab"),
    ("type_into", "#search"),
    ("pause", None),
    ("press", "Escape"),
    ("caption", None),
    ("shot", "90-caption-off"),
    ("pause", None),
    ("caption", None),
    ("shot", "91-caption-on"),
    ("caption", None),
]

WEB_PRESS_KEYS = ["Enter", "Tab", "Escape"]

TERMINAL_BEATS = [
    ("pause", None),
    ("caption", None),
    ("run", "echo hello from demo-video"),
    ("wait_for_prompt", None),
    ("wait_for_text", r"^hello from demo-video$"),
    ("shot", "01-echo"),
    ("caption", None),
    ("run", "ls -1"),
    ("wait_for_prompt", None),
    ("wait_for_text", r"^skills$"),
    ("pause", None),
    ("shot", "02-listing"),
    ("caption", None),
    ("shot", "90-caption-off"),
    ("pause", None),
    ("caption", None),
    ("shot", "91-caption-on"),
    ("caption", None),
]

WEB_CAPTIONS = [
    "A small dashboard.",
    "Filter by city.",
    "Refresh reloads it.",
    "Keys, not just clicks.",
    "",
    PROBE_CAPTION,
    "",
]
TERMINAL_CAPTIONS = [
    "A real shell, recorded.",
    "Any command works.",
    "",
    PROBE_CAPTION,
    "",
]

BEAT_ORDER_SLACK_S = 0.005
MIN_HELD_BEAT_SPAN_S = 1.0
MIN_BEAT_TIME_COVERAGE = 0.80
_MD_ROW = re.compile(r"^\|\s*\d+\s*\|")
DURATION_TOLERANCE_S = 0.2

MAX_LOG_EARLY_S = 0.25
MAX_CAPTURE_LOSS_S = 0.75
MAX_SKEW_DRIFT_S = 0.25
MAX_CLOCK_RECORD_DISAGREEMENT_S = 0.06
MAX_CLOCK_STEP_TIME_DISAGREEMENT_S = 0.25
HOST_CLOCK_MIN_STEP_S = 0.005
HOST_CLOCK_MAX_GAP_S = 0.25

# Clock probe (issue #370)
CLOCK_PROBE_S = 40.0
CLOCK_PROBE_POLL_S = 0.1
CLOCK_PROBE_ARMS = ("--web-only", "--terminal-only")
CLOCK_SAFE_ARMS = (
    "--determinism-only",
    "--evidence-only",
    "--narration-only",
    "--failure-only",
    "--polish-only",
    "--content-only",
    "--overlay-only",
    "--coverage-only",
    "--strict-only",
    "--wrapper-only",
    "--stills-only",
    "--issues-only",
    "--lock-only",
)

ALIGN_POST_S, ALIGN_FPS = 0.8, 25
MAX_BASELINE_NOISE_FRACTION = 0.15
CAPTION_FADE_FRAMES = int(ALIGN_FPS * 0.35)
MIN_BASELINE_FRAMES = 4

ALIGN_OVERSHOOT_S = 0.27
ALIGN_PRE_S = (
    MAX_CAPTURE_LOSS_S
    + ALIGN_OVERSHOOT_S
    + (CAPTION_FADE_FRAMES + MIN_BASELINE_FRAMES) / ALIGN_FPS
)
ALIGN_RESCUE_S = 5.0
ALIGN_ARRIVAL_FRACTION = 0.25
MIN_ALIGN_BAND_DELTA = {"web": 2.0, "terminal": 2.0, "segments": 2.0}

MAX_FRAME_PLACEMENT_S = 0.02

FRAME_CAPTION_GUARD_S = MAX_CAPTURE_LOSS_S
MIN_GRADED_CAPTION_FRAMES = 5

SCENE_WINDOW_PAD_S = 0.1

MARKER_NAME = ".demo-video-smoke"

# Segments (issue #7)
SEGMENT_NAMES = ["part1", "part2"]
SEGMENT_OPENING = "One demo, in two parts."
SEGMENT_INTERLUDE = "A few minutes later."
SEGMENT_INTERLUDE_HOLD_S = 1.2
SEGMENT_SHOTS = ["01-part1"]
SEGMENT_DURATION_S = (10.0, 45.0)

SEGMENT_BEATS_FULL = [
    ("goto", "/", "part1"),
    ("wait_for", "#kpi-rev", "part1"),
    ("pause", None, "part1"),
    ("caption", None, "part1"),
    ("shot", "01-part1", "part1"),
    ("caption", None, "part1"),
    ("interlude", "card", "part2"),
    ("goto", "/", "part2"),
    ("wait_for", "#kpi-rev", "part2"),
    ("caption", None, "part2"),
    ("shot", "90-caption-off", "part2"),
    ("pause", None, "part2"),
    ("caption", None, "part2"),
    ("shot", "91-caption-on", "part2"),
    ("caption", None, "part2"),
]
SEGMENT_BEATS = [(verb, target) for verb, target, _ in SEGMENT_BEATS_FULL]
SEGMENT_BEAT_SEGMENTS = [segment for _, _, segment in SEGMENT_BEATS_FULL]
SEGMENT_CAPTIONS = [SEGMENT_OPENING, "", "", PROBE_CAPTION, ""]
SEGMENT_INTERLUDES = [SEGMENT_INTERLUDE]
SEGMENT_PROBES = [SEGMENT_OPENING, PROBE_CAPTION]
SEGMENT_OFFSET_TOLERANCE_S = 0.2
MAX_UNMERGED_FIRST_BEAT_S = 3.0
MAX_MERGE_OFFSET_ERROR_S = 0.1
MAX_CROSS_SEGMENT_DRIFT_S = MAX_CAPTURE_LOSS_S

# Polish (issues #110, #111)
SPOTLIGHT_TARGET = "#kpi-rev"
SPOTLIGHT_PAD_PX = 14
SPOTLIGHT_MID_BAND = (0.12, 0.88)
MIN_SPOTLIGHT_MID_FRAMES = 2
SPOTLIGHT_MIN_TOTAL = 5.0
SPOTLIGHT_WINDOW_S = (0.5, 1.0)
SPOTLIGHT_HOLD_S = 1.5
SPOTLIGHT_DURATION_S = (5.0, 30.0)
MIN_SPOTLIGHT_CLEAR_S = 0.45

CAMERA_PUSH_MIN = 8.0
CAMERA_STILL_MAX = 1.5
CAMERA_STRIP_MIN_H = 24
CAMERA_MIN_EVENT_S = 1.2
CAMERA_AFTER_S = 0.4
CAMERA_CENTRE_BAR_PX = 20.0

OPENING_CARD = "…and the same thing, on the command line."
OPENING_HOLD_S = 2.5
OPENING_SAMPLE_FPS = 20
OPENING_CARD_MAX_LUMA = 60.0
OPENING_BARE_MIN_LUMA = 150.0
OPENING_STRIP_FRACTIONS = (0.01, 0.04, 0.90, 0.16)
TERMINAL_REVEAL_MIN_STDDEV = 1.2
MIN_OPENING_CARD_S = 1.0
MIN_OPENING_FRAMES = 40
OPENING_CARD_AGREEMENT = 1.0
OPENING_DURATION_S = (5.0, 30.0)

# Evidence (issue #9)
EVIDENCE_DIR_NAME = "evidence"
EVIDENCE_SCHEMA_EXPECTED = 1
EVIDENCE_RICH_TEXT = "zz-rich-00000000"
EVIDENCE_HIDDEN_TEXT = "zz-painted-00000000"
EVIDENCE_UNPAINTED_TEXT = "zz-unpainted-00000000"
EVIDENCE_CLIPPED_TEXT = "zz-clipped-00000000"
EVIDENCE_INVISIBLE_TEXT = "zz-invisible-00000000"

EVIDENCE_LIMITS_EXPECTED = {
    "aria": 12_000,
    "scope_aria": 12_000,
    "html": 8_000,
    "screen": 12_000,
    "chrome": 8_000,
    "aria_omits": 12_000,
}
EVIDENCE_MARKER = "[demo-video: truncated here,"
EVIDENCE_TRUNCATED_MAX = len(
    "\n…[demo-video: truncated here, 999999999 more characters]"
)
MAX_EVIDENCE_FILE_BYTES = 4 * 32_000 + 8_000
MAX_EVIDENCE_DIR_BYTES = 512_000

WEB_EVIDENCE = [
    (
        "shot",
        "01-dashboard",
        [
            "$128,400",
            "snapshot 1 of 3",
            "Refresh",
            "Harbor Supply Co.",
            "Ferrari Logistics",
            "A small dashboard.",
        ],
        ["$134,950", "snapshot 2 of 3"],
    ),
    (
        "shot",
        "02-filtered",
        ["Harbor Supply Co.", "Seattle", "Filter by city."],
        ["Ferrari Logistics", "Cascade Outfitters", "Pine & Poplar"],
    ),
    (
        "shot",
        "03-refreshed",
        ["$134,950", "snapshot 2 of 3", "Refresh reloads it."],
        ["$128,400", "snapshot 1 of 3"],
    ),
    (
        "clear",
        "#search",
        [
            "Harbor Supply Co.",
            "Ferrari Logistics",
            "Redwood Kitchens",
            "Blue Ridge Foods",
            "Keys, not just clicks.",
        ],
        ["Pine & Poplar", "Cascade Outfitters"],
    ),
    (
        "press",
        "Enter",
        ["snapshot 3 of 3", "$119,180", "Pine & Poplar", "Cascade Outfitters"],
        ["snapshot 2 of 3", "$134,950"],
    ),
]

WEB_EVIDENCE_SCOPE = ("#kpi-rev", "$128,400", 'id="kpi-rev"')

TERMINAL_EVIDENCE = [
    (
        "shot",
        "01-echo",
        ["echo hello from demo-video", "hello from demo-video"],
        ["ls -1", "AGENTS.md"],
    ),
    (
        "shot",
        "02-listing",
        ["ls -1", "skills", "tests", "hello from demo-video"],
        [],
    ),
]

# Narration (issue #157)
NARRATION_KEY = "not-a-real-key-and-must-never-be-used"
NARRATION_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
NARRATION_MODEL_ID = "eleven_multilingual_v2"
NARRATION_KEY_CHARS = 20
NARRATION_STABILITY = "0.75"

NARRATION_LONG_LINE = "This line runs longer than the beat that carries it."
NARRATION_LONG_S = 1.6
NARRATION_SHORT_LINE = "This one is over quickly."
NARRATION_SHORT_S = 0.3
NARRATION_HOLD_S = 0.5
NARRATION_LINES = (
    (NARRATION_LONG_LINE, NARRATION_LONG_S),
    (NARRATION_SHORT_LINE, NARRATION_SHORT_S),
)

NARRATION_LOUD_DBFS = -60.0
NARRATION_QUIET_DBFS = -80.0
NARRATION_WINDOW_S = 0.4
NARRATION_SILENCE_DBFS = -50.0
NARRATION_SILENCE_MIN_S = 0.08
NARRATION_ONSET_TOLERANCE_S = 0.12
NARRATION_SPAN_TOLERANCE_S = 0.15
NARRATION_CODEC = "aac"
NARRATION_CHANNELS = 2
NARRATION_SAMPLE_RATE = 44100

# Evidence take (issue #9)
EVIDENCE_SEGMENT = "shapes"
EVIDENCE_RENDERED_TEXT = "nothing rendered here"
EVIDENCE_ATTR_RENDERED = "nothing rendered here"
EVIDENCE_MIN_ARIA_CHARS = 400
EVIDENCE_ATTR_TARGET = "#ev-spot-attrs"
EVIDENCE_STALE_MARK = "a previous take's evidence"
EVIDENCE_SOURCE_ID = "smoke-source"
EVIDENCE_SOURCE_RENDERED = "this element renders one line"
EVIDENCE_SOURCE_SCRIPT = "SOURCE_ONLY_NEVER_ON_SCREEN"
EVIDENCE_SOURCE_SRCDOC = "SRCDOC_ONLY_NEVER_ON_SCREEN"

EVIDENCE_SOURCE_JS = (
    """(id) => {
  const el = document.createElement('div');
  el.id = id;
  el.textContent = '__RENDERED__';
  const script = document.createElement('script');
  script.textContent = 'var x = "__SCRIPT__";';
  el.appendChild(script);
  const frame = document.createElement('iframe');
  frame.setAttribute('srcdoc', '<p>__SRCDOC__</p>');
  el.appendChild(frame);
  document.body.appendChild(el);
}""".replace("__RENDERED__", EVIDENCE_SOURCE_RENDERED)
    .replace("__SCRIPT__", EVIDENCE_SOURCE_SCRIPT)
    .replace("__SRCDOC__", EVIDENCE_SOURCE_SRCDOC)
)

EVIDENCE_BLOAT_ID = "smoke-bloat"
EVIDENCE_BLOAT_ITEMS = 900
EVIDENCE_BLOAT_JS = """(n) => {
  const box = document.createElement('ul');
  box.id = '__ID__';
  for (let i = 0; i < n; i++) {
    const li = document.createElement('li');
    li.textContent = 'bloat row ' + i + ' — filler so the evidence cap has '
      + 'something to cut';
    box.appendChild(li);
  }
  document.body.appendChild(box);
}""".replace("__ID__", EVIDENCE_BLOAT_ID)

EVIDENCE_TAKE_FACTS = [
    ("wait_for", EVIDENCE_ATTR_TARGET, [EVIDENCE_RENDERED_TEXT], []),
    ("spotlight", f"#{EVIDENCE_SOURCE_ID}", [EVIDENCE_SOURCE_RENDERED], []),
    ("spotlight", f"#{EVIDENCE_BLOAT_ID}", ["bloat row 0"], []),
]

# Determinism
FROZEN_CLOCK = "2025-01-01T09:00:00Z"
FROZEN_EPOCH_MS = 1735722000000
FROZEN_ISO = "2025-01-01T09:00:00.000Z"
FROZEN_TIMEZONE = "UTC"
FROZEN_LOCALE = "en-US"

PROBE_ANIMATION_S = "2s"
PROBE_TRANSITION_S = "5s"
FLATTENED_S = "0.001s"
MAX_LIVE_CLOCK_SKEW_MS = 5 * 60 * 1000
MIN_MONOTONIC_ADVANCE_MS = 5000.0

# Clock demo
TICKER_JS = """() => {
  if (document.getElementById('__smoke_ticker')) return;
  const style = document.createElement('style');
  style.textContent =
    '@keyframes __smoke_ticker{0%{opacity:.02}100%{opacity:.06}}';
  document.head.appendChild(style);
  const el = document.createElement('div');
  el.id = '__smoke_ticker';
  el.style.cssText = 'position:fixed;top:0;left:0;width:8px;height:8px;'
    + 'background:#808080;z-index:2147483647;pointer-events:none;'
    + 'animation:__smoke_ticker .18s steps(2) infinite';
  el.setAttribute('data-demo-video-animate', '');
  document.body.appendChild(el);
}"""

_TICKER_STATE_JS = """() => {
  const el = document.getElementById('__smoke_ticker');
  if (!el) return null;
  const style = getComputedStyle(el);
  const control = document.createElement('div');
  control.style.cssText = 'position:fixed;top:-99px;left:-99px;width:1px;'
    + 'height:1px;animation:__smoke_ticker .18s steps(2) infinite';
  document.body.appendChild(control);
  const controlDuration = getComputedStyle(control).animationDuration;
  control.remove();
  return {name: style.animationName, duration: style.animationDuration,
          state: style.animationPlayState, control: controlDuration};
}"""

_CAPTION_JS = """() => {
  const ids = ['__demo_caption', '__demo_caption2'];
  const el = document.getElementById(ids[window.__demoCapLayer || 0]);
  if (!el) return null;
  return [el.textContent, getComputedStyle(el).opacity];
}"""

# Housekeeping
KEEP_OUT_ROOTS = 5
REAP_MIN_AGE_S = 3600.0

# Arm selection
EXPENSIVE_ARMS = ("--web-only", "--content-only", "--terminal-only")

# Lock (issue #105)
SMOKE_LOCK = "/tmp/demo-video-smoke.lock"
LOCK_CHILD_TIMEOUT_S = 30.0

# Capture clock
MAX_UNWATCHED_CAPTURE_LOSS_S = MAX_CAPTURE_LOSS_S

# Video
FLATTENED_S = "0.001s"

# Narration placement
NARRATION_WINDOW_S = 0.4

# For pytype
CAPTION_PROBE_BAND = {"web": 2.0, "terminal": 2.0, "segments": 2.0}

# Re-export from _pixels (these are imported at module level in smoke.py)
# FRAME_BAND, Rect, card_run, card_strip, channels_apart, contrast,
# frame_difference, gray_frames, psnr_db, strip_rgb