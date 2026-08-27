"""Every constant the smoke suite grades with, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixture"
HELPERS_DIR = REPO_ROOT / "skills" / "demo-video" / "helpers"

# The pixel toolkit, lifted to a plain module beside the entry script so the
# pixel loop can grade with the same primitives this suite does (#349).
# Running `tests/smoke` puts its own directory on sys.path already; loading
# this package *as a module* — which `tests/unit` does — does not, hence the
# insert. The path is this package's parent, not REPO_ROOT: the
# fault-injection drivers stage a copy from a temp directory, with
# `_pixels.py` copied in beside it.
_HERE = str(Path(__file__).resolve().parent.parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


MIN_MP4_BYTES = 20_000


MIN_PNG_BYTES = 5_000


MIN_CONTENT_STDDEV = {
    "web": 6.0,
    "terminal": 2.0,
    "segments": 6.0,
    # The two takes that grade how a recording *looks* (issues #110/#111) are
    # the same two media against the same fixture, so they take the same
    # numbers. They are here only as a floor under the frame-shape assertions
    # that follow: neither of those can tell a black take from a working one,
    # because "nothing changed" is what a black take also reports.
    "spotlight": 6.0,
    "terminal-opening": 2.0,
}


MIN_CAPTION_BAND_DIFF = {"web": 2.0, "terminal": 2.0, "segments": 2.0}


MIN_STILL_DIFF = 0.25


CONTENT_SAMPLE_FPS = 1


CONTENT_KEEP = 0.8


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


CONTENT_STATIC_HEADROOM = 1.6  # x above the healthy take's longest still run


CONTENT_STATIC_MARGIN = 0.7  # x below the covered take's still run


CONTENT_SCORE_HEADROOM = 3.0


CONTENT_COVERED_FRACTION = 0.75


CONTENT_PSNR_GAP_DB = 8.0


OVERLAY_TAKES = ("overlay-cleared", "overlay-left-up")


OVERLAY_LABEL = "Ten minutes later…"


OVERLAY_HOLD_S = 3.2


OVERLAY_QUIET_S = 3.0


OVERLAY_SCRIM_MIN_DIFF = 6.0


OVERLAY_CLEARED_MAX_RATIO = 0.2


WEB_DURATION_S = (6.0, 45.0)


TERMINAL_DURATION_S = (4.0, 32.0)


WEB_SHOTS = ["01-dashboard", "02-filtered", "03-refreshed", "04-cleared"]


TERMINAL_SHOTS = ["01-echo", "02-listing"]


CAPTION_PROBE = ("90-caption-off", "91-caption-on")


PROBE_CAPTION = "Recorded end to end."


PROBE_QUIET_S = 2.0


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
    # The form verbs (issue #130). `press` records the key it pressed in the
    # beat's target field, which is the issue's acceptance criterion: before
    # this, the keystrokes that emptied a field happened in the gap between two
    # beats and appeared in no artifact at all.
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
    # `interlude`'s target is its style, not its text — see core.interlude().
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
    # The chrome's own on-screen text (#361): the caption line and any card,
    # read out of the wrapper document — see reference/review.md.
    "chrome": 8_000,
    # On-screen text the ARIA snapshot structurally cannot carry (#353).
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
        # The filter really filtered: one row left, and the four it dropped are
        # gone from the account of the screen as well as from the screen.
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
    # The two form verbs, graded in the artifact issue #130 is actually about.
    # `find()` above locates these by (verb, target), so each entry asserts
    # three things at once: the beat exists, its target is the selector the
    # storyboard cleared or the key it pressed by name, and the evidence file
    # written for *that beat* describes the screen the verb produced. A verb
    # that drove the page through `rec.page.keyboard` would fail at the first.
    (
        "clear",
        "#search",
        # The filter came off: the three rows "harbor" had hidden are back in
        # the account of the screen, not merely on it.
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
        # The command as typed *and* its output, which is the pair that says
        # the PTY ran what run() sent rather than echoing it.
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


_CAPTION_JS = """() => {
  // Two stacked layers crossfade (chrome.py). The one the recorder just set
  // is `__demoCapLayer`'s — reading the visible layer instead would grade
  // the previous line for the ~0.3 s the fade is running.
  const ids = ['__demo_caption', '__demo_caption2'];
  const el = document.getElementById(ids[window.__demoCapLayer || 0]);
  if (!el) return null;
  return [el.textContent, getComputedStyle(el).opacity];
}"""


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


FROZEN_CLOCK = "2025-01-01T09:00:00Z"  # core.py's DEFAULT_CLOCK, as it logs it


FROZEN_EPOCH_MS = 1735722000000  # ...the same instant, as the page reads it


FROZEN_ISO = "2025-01-01T09:00:00.000Z"


FROZEN_TIMEZONE = "UTC"


FROZEN_LOCALE = "en-US"


PROBE_ANIMATION_S = "2s"


PROBE_TRANSITION_S = "5s"


FLATTENED_S = "0.001s"


MAX_LIVE_CLOCK_SKEW_MS = 5 * 60 * 1000


MIN_MONOTONIC_ADVANCE_MS = 5000.0


_PAGE_STATE_JS = """() => {
  // A probe element and a ::after on it, because an animated pseudo-element is
  // the most common spinner on the web and a rule that forgets `::after` looks
  // exactly like one that does not on a plain <div>.
  let sheet = document.getElementById('__smoke_probe_css');
  if (!sheet) {
    sheet = document.createElement('style');
    sheet.id = '__smoke_probe_css';
    sheet.textContent =
      '#__smoke_probe::after{content:"";animation:__smoke_probe 3s linear infinite}'
      + '#__smoke_probe::before{content:"";animation:__smoke_probe 4s linear infinite}';
    document.head.appendChild(sheet);
  }
  const probe = document.createElement('div');
  probe.id = '__smoke_probe';
  probe.style.cssText = 'position:fixed;top:-99px;left:-99px;width:1px;'
    + 'height:1px;animation:__smoke_probe 2s linear infinite;'
    + 'transition:opacity 5s linear';
  document.body.appendChild(probe);
  const style = getComputedStyle(probe);
  const animation = style.animationDuration;
  const transition = style.transitionDuration;
  const after = getComputedStyle(probe, '::after').animationDuration;
  const before = getComputedStyle(probe, '::before').animationDuration;
  probe.remove();
  return {
    now: Date.now(),
    iso: new Date().toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
    language: navigator.language,
    offset: new Date().getTimezoneOffset(),
    reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
    animation: animation,
    transition: transition,
    after: after,
    before: before,
    // Four more clocks, each of which was found running while `Date.now()`
    // was frozen. Intl formats from its own internal clock; `constructor`
    // walked past the proxied global to the real one; timeOrigin and
    // lastModified are wall-clock readings of their own.
    intl: new Intl.DateTimeFormat('en-US', {year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'UTC'}).format(),
    constructorNow: new Date().constructor.now(),
    constructorIsDate: Date.prototype.constructor === Date,
    descriptorNow: Object.getOwnPropertyDescriptor(Date, 'now').value(),
    nowIsStable: Date.now === Date.now,
    nowName: Date.now.name,
    timeOrigin: Math.round(performance.timeOrigin),
    // The clock a CSS animation actually runs on — not performance.now(),
    // which merely correlates with it. This is the one TICKER_JS depends on.
    monotonic: typeof document.timeline.currentTime === 'number'
      ? document.timeline.currentTime : performance.now(),
  };
}"""


_FOCUSED_JS = """() => {
  const el = document.activeElement;
  if (!el) return '(none)';
  return el.id || el.tagName.toLowerCase();
}"""


_TRAIL_JS = """() => {
  window.__smokeTrail = [];
  window.addEventListener(
    'mousemove', (e) => window.__smokeTrail.push([e.clientX, e.clientY]), true);
}"""


OPENING_FIRST_FRAME_S = 0.03


SYNTHETIC_PAINT_AT = 0.6


SYNTHETIC_SLACK_S = 0.12


COVERAGE_CRITERIA = {
    "AC-1": "The dashboard lists the current figures.",
    "AC-2": "The list can be filtered.",
    "AC-3": "A filter that matches nothing says so.",
}


COVERAGE_UNCLAIMED = "AC-3"


COVERAGE_CARD = "AC-1"


COVERAGE_APP_MARKER = "Northwind Ops"


CONTENT_RECT_SLACK_PX = 1


MIN_PRESS_BEAT_SPAN_S = 0.35


MIN_CLEAR_OVER_CLICK_S = 0.40


WRAPPER_CAPTION = "The caption sits in its own band below the app."


WRAPPER_UNREACHED = "this caption must never be recorded"


WRAPPER_CLAUSE = "The caption band survives a full page navigation."


WRAPPER_SURVIVES = "This line must outlive the document below it."


WRAPPER_LONG_CAPTION = (
    "This caption is deliberately far too long for the reserved caption "
    "band below the app rect, so the band's edges shave its first and its "
    "last line instead of covering the app."
)


WRAPPER_BAND_SWEEP_FPS = 10


WRAPPER_BAND_LIT = 12.0


WRAPPER_BAND_UNLIT = 6.0


WRAPPER_BAND_MIN_S = 1.0


WRAPPER_APP_MAX_DELTA = 3.0


WRAPPER_APP_CONTROL_S = 0.3


WRAPPER_APP_SAMPLE_S = 0.5


WRAPPER_HOLD_MAX_LUMA = 60.0


WRAPPER_BARE_MIN_LUMA = 150.0


WRAPPER_FIRST_FRAME_S = 0.05


WRAPPER_CARD_WINDOW_TOLERANCE = 5.0


WRAPPER_CARD_SWEEP_FPS = 10


WRAPPER_CARD_LOCATE_MAX_LUMA = 60.0


WRAPPER_CARD_EDGE_TRIM = 2


WRAPPER_CARD_FRACTIONS = (0.3, 0.6)


WRAPPER_CARD_MIN_STRETCH_S = 1.0


WRAPPER_CARD_MIN_DOWN_S = 0.8


WRAPPER_CARD_CONTROL_MIN_GAP = 12.0


WRAPPER_SECOND_MIN_LUMA = 75.0


WRAPPER_SECOND_MAX_LUMA = 140.0


WRAPPER_SECOND_MIN_FRAMES = 4


WRAPPER_SURVIVES_SAMPLES_S = (0.2, 0.5, 0.8)


STILLS_DECLARED_HOLD_S = 4.0 + 4.0 + 3.0


STILLS_PACING_BUDGET_S = 8.0


STILLS_CAPTION = "The same storyboard, without the waiting."


STILLS_CLAUSE = "The dashboard shows the current figures."


CRASH_SELECTOR = "#this-selector-matches-nothing"


CRASH_CAPTION = "This take is about to give up."


CRASH_SCREEN_WEB = "Northwind Ops"


CRASH_SCREEN_TERMINAL = "crash-arm-was-here"


STALE_MARK = "stale-from-a-previous-run-0000"


SMOKE_LOCK = Path(tempfile.gettempdir()) / "demo-video-smoke.lock"


LOCK_CHILD_TIMEOUT_S = 120.0


KEEP_OUT_ROOTS = 5


REAP_MIN_AGE_S = 3600.0


EXPENSIVE_ARMS = ("--web-only", "--content-only", "--terminal-only")


# The per-pull-request selection, and the one list in this file that is
# enumerated rather than derived.
#
# `--cheap` (#61) is a *complement* — every phase an arm outside
# EXPENSIVE_ARMS reaches — which is why it grew to 22 takes and 300 s on a
# runner without anybody choosing that. A complement cannot be scaled down;
# only a list can. So this is a list, and the cost of each entry is written
# beside it, measured one arm at a time on a 16-core box:
#
#     --lock-only        0.2 s   a refused run leaves no directory to send
#                                anybody to (#105)
#     --stills-only      2.1 s   pictures with no video, nothing readable as
#                                a take (#372)
#     --strict-only     11.6 s   the two takes strict=True must refuse, web
#                                and terminal (#3)
#     --coverage-only   15.5 s   every acceptance clause is answered by a
#                                beat (#12)
#     --evidence-only    7.3 s   the per-beat evidence a reviewer reads (#9)
#     --failure-only    46.8 s   six takes that crash, and what each leaves
#                                behind (#11/#20/#24/#46)
#                       ------
#                       83.5 s   ~97 s on a runner at the measured 1.16x
#
# The class each entry buys is the reason it is here: a take that did not
# finish must not leave something that reads as a success, and a take that
# should have been refused must be refused. Those are the two ways a
# recording lies to its reader, which is what GOAL.md measures.
#
# **What a pull request therefore no longer sees**, written out rather than
# implied, because the last split's unstated half became #233: the wrapper
# pair and its geometry (#358), the console/exit-code reporting both media do
# (#197), the spotlight and terminal-opening polish takes (#110/#111), the
# light-interlude pair (#162/#163), the stitch (#7), narration (#157) and
# determinism. Every one of them runs on merge to `main`, where `smoke-full`
# records the whole suite. Rendered-frame geometry has a second, faster
# reader in `tests/pixel`, which is 4.7 s warm and is the loop CLAUDE.md
# already sends a chrome change through first.
CORE_ARMS = (
    "--lock-only",
    "--stills-only",
    "--strict-only",
    "--coverage-only",
    "--evidence-only",
    "--failure-only",
)
