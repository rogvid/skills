---
name: demo-video
description: Use when a web app, CLI, or TUI needs a screen-recorded demo video and/or an illustrated step-by-step guide — "record a demo of X", "make a video walkthrough", "show the feature in action", "demo my command-line tool", "document this with a recording". Records web apps (via Playwright) and terminal programs (CLIs, REPLs, full-screen TUIs, via an in-browser terminal); needs Playwright and ffmpeg.
---

# demo-video — self-explanatory recorded demos of a web app or terminal program

## Overview

A demo is a short mp4 that explains itself to someone with zero context —
no narration track, no insider knowledge. You never watch the video; you
*script* it as a deterministic storyboard (`record.py`), *read* the stills
it captures, and have a context-free agent *read* extracted frames to
verify the story lands. The storyboard is committed next to the media, so
anyone can re-record after the UI changes.

Two subjects, one engine. **`Recorder`** drives a **web app** through a
Playwright page. **`TerminalRecorder`** runs a **CLI or TUI** in a real PTY
rendered by an in-browser terminal — so captions, narration, stills,
segments, and verification all work identically. This document leads with
the web recorder; the **Terminal demos** section below covers what differs.
Terminal recording is **Unix-only** (it uses a PTY).

Both record into a **framed window on a soft pastel background** (rounded
window, title bar, traffic-light buttons) so the eye has an obvious focus —
the caption sits as a lower-third. The terminal frames itself in-page; the
web recording is composited into the window by ffmpeg on exit, which scales
it down (hence the larger web caption). One consequence: web `shot()` stills
are captured full-bleed (no window frame) — good for embedding in a guide,
but they will not match the windowed video exactly.

Each demo gets one folder (suggested: `docs/guides/<YYYY-MM-DD>-<slug>/`):

| File | What it is | In git? |
|---|---|---|
| `record.py` | The storyboard that produced the media (re-runnable) | yes |
| `images/*.png` | Stills captured at key moments | yes |
| `timeline.json` | The beat log — every verb, when it ran, what caption was up. For a segmented demo, the merged one `stitch()` writes | yes |
| `timeline.md` | The same log rendered for humans, stills embedded | yes |
| `guide.md` | Optional written guide embedding the stills | yes |
| `demo.mp4` | The recording (mp4 only — gifs get too big) | **no** — regenerate it, or attach it to the PR |
| `evidence/beat-NN.json` | **A working file, not an artifact.** What was on screen at each beat, in text — read by the reviewing agent in the same run that produced it, then thrown away. Greppable plaintext of a real app's DOM | **no** — gitignore it |
| `frames/` | Review frames pulled out of `demo.mp4`, plus the sheet you hand a reviewer | **no** — a working file of a review; `beat_frames(out_dir)` regenerates it |

The storyboard is the durable artifact, not the video. The last two rows are
neither: they are inputs to a review that happens once, derived from a video
that is itself not committed, and both are in this repo's `.gitignore`
([#50](https://github.com/rogvid/skills/issues/50)). See **Commit the
storyboard, not the media** in the Process section.

## Setup (once per project)

1. **Check for `uv` first**: run `uv --version`. If it is missing, STOP
   and tell the user to install it (https://docs.astral.sh/uv/) —
   storyboards are single-file uv scripts and cannot run without it. Do
   not fall back to pip or a project venv.
2. **`ffmpeg`** (which includes `ffprobe`) must be on PATH. **Chromium**
   once per machine: `uv run --with playwright playwright install chromium`
   (on a fresh Linux box add `--with-deps` for system libraries). If a
   later run resolves a newer Playwright that wants a newer browser
   build, re-run this command. Playwright **1.49 or newer** for per-beat
   evidence — `locator.aria_snapshot()` arrived there, and the older
   `page.accessibility` API it replaced has since been removed.
3. **Learn how the app runs** (dev server command, port, how to build the
   frontend, how to seed data). If the project documents this, follow it;
   otherwise ask. Reuse an already-running server.
4. **Set project defaults in env** (see Configuration) or pass them as
   `Recorder(...)` parameters per storyboard.

Nothing is copied into the project: storyboards import the recorder from
this skill's folder, so the skill must be installed (project-level
`.claude/skills/` or user-level `~/.claude/skills/`) wherever demos are
re-recorded.

## Storyboard template

Each `record.py` is a self-contained uv script — PEP 723 metadata brings
Playwright without any project environment. You are writing this file,
and you know where this skill is installed (you are reading it) — so
**fill `_DEFAULT_SKILL_DIR` with that actual location**. Prefer a
repo-relative expression via `Path(__file__)` when the skill lives in
the same repo (survives clones), an absolute path otherwise. Do not
assume any particular layout — `.claude/skills/`, `.agents/`, a global
directory are all just whatever path happens to be true.
`DEMO_VIDEO_SKILL_DIR` overrides the constant at runtime, covering moves
and unusual setups.

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""<one line: the demo story>"""
import os, sys
from pathlib import Path

# Filled in by the writing agent with the skill's real location;
# DEMO_VIDEO_SKILL_DIR takes precedence.
_DEFAULT_SKILL_DIR = <the demo-video skill folder, as known when writing this file>
SKILL_DIR = Path(os.environ.get("DEMO_VIDEO_SKILL_DIR") or _DEFAULT_SKILL_DIR)
if not (SKILL_DIR / "helpers" / "demo_recording" / "__init__.py").exists():
    sys.exit(f"demo-video skill not found at {SKILL_DIR} — set DEMO_VIDEO_SKILL_DIR")
sys.path.insert(0, str(SKILL_DIR / "helpers"))
from demo_recording import Recorder  # noqa: E402   (or TerminalRecorder)

with Recorder(Path(__file__).parent) as rec:
    rec.goto("/")
    ...
```

Run it with `uv run <demo folder>/record.py`. For a terminal demo, the only
change is `from demo_recording import TerminalRecorder` and the verbs you
call — see **Terminal demos** below.

## Configuration

Every `Recorder` parameter resolves **explicit parameter → `DEMO_VIDEO_*`
env var → built-in default**, so projects can put defaults in their
`.env` (load with `set -a; source .env; set +a`) and storyboards stay
clean:

| Variable | Sets | Default |
|---|---|---|
| `DEMO_VIDEO_OUT_DIR` | where demo files land (`out_dir`) | — (required one way or the other) |
| `DEMO_VIDEO_BASE_URL` | app under demo | `http://localhost:8000` |
| `DEMO_VIDEO_ACCENT_RGB` | cursor/spotlight color, `"235,110,20"` | orange |
| `DEMO_VIDEO_TERMINAL_TITLE` | web `terminal()` card title | `terminal` |
| `DEMO_VIDEO_TERMINAL_PROMPT` | prompt string — web card, and `TerminalRecorder`'s shell PS1 | `$ ` (web card); `❯ ` (`TerminalRecorder`) |
| `DEMO_VIDEO_TERMINAL_SHELL` | shell `TerminalRecorder` launches | `/bin/bash` |
| `DEMO_VIDEO_TERMINAL_FONT_SIZE` | `TerminalRecorder` font px | `15` |
| `DEMO_VIDEO_VIEWPORT` | recording size, `"1280x720"` | 1280×720 |
| `DEMO_VIDEO_DETERMINISTIC` | freeze the page clock and flatten motion (`1`/`0`) — see **Determinism** | **off** |
| `DEMO_VIDEO_CLOCK` | the instant the page's clock is frozen at, when it is (ISO 8601) | `2025-01-01T09:00:00Z` |
| `DEMO_VIDEO_TIMEZONE` | browser timezone (`timezone_id`), always applied | `UTC` |
| `DEMO_VIDEO_LOCALE` | browser locale (`locale`), always applied | `en-US` |
| `DEMO_VIDEO_SPEECH` | force narration on/off (`1`/`0`) | auto by API key |
| `DEMO_VIDEO_STRICT` | fail the take on console errors / non-zero exits (`1`/`0`) | off |
| `DEMO_VIDEO_EVIDENCE` | write `evidence/beat-NN.json` per beat (`1`/`0`) — see **Per-beat evidence** | **on** |
| `DEMO_VIDEO_VOICE_ID` | ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SKILL_DIR` | where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | enables speech narration | off |

`DEMO_VIDEO_BASE_URL` applies to the web `Recorder` only; the terminal
`*` variables to `TerminalRecorder`. All the rest apply to both.

## Speech narration (optional)

When the `ELEVENLABS_API_KEY` environment variable is set (e.g.
`set -a; source .env; set +a` before recording), every `caption` and
`interlude` line is also spoken — synthesized with ElevenLabs and mixed
onto demo.mp4 at the moment the line appeared. No storyboard changes
needed; captions are the narration script.

- `Recorder(..., speech=True)` demands narration (fails fast if the key
  is missing); `speech=False` forces it off; default is auto by env var.
  `voice_id` / `speech_model` override the voice (default is a premade
  voice that works on free-tier keys; library voices need a paid plan).
- Clips are cached in `<out_dir>/.tts/` keyed by voice+model+text —
  retakes and crashed takes only synthesize lines they haven't seen.
  Transient 429/5xx responses and network blips retry with backoff (free
  keys get deprioritized under load).
- The first take synthesizes each new line mid-recording, which shows as
  a brief hold before the caption appears. Treat take 1 as a
  cache-warming rehearsal and judge pacing from take 2, which plays
  entirely from cache.
- Pacing self-adjusts: a caption call first waits for the previous line
  to finish speaking. Storyboard pauses are minimums, never cut-offs, and
  the recording holds at the end until the last line lands. Because of
  that wait, the caption-before-spotlight rule matters doubly with speech
  on — visuals set *before* a caption sit on screen through the tail of
  the previous spoken line.
- Write captions for the ear as well as the eye: short sentences, no
  markup, nothing you wouldn't say aloud.
- Verify audio like you verify frames: `ffprobe` shows the aac stream;
  `ffmpeg -af silencedetect` should show speech blocks spanning the video;
  if the key has STT permission, transcribe the extracted track with
  ElevenLabs Scribe and compare against the caption lines.
- Segments all get an audio track (silence if a segment has no lines), so
  `stitch()` still concatenates losslessly.

## Determinism

Re-recording a storyboard should produce the same video. That is what makes a
still diffable against the one committed last month, and what makes "did the UI
actually change?" answerable instead of "the video is different, they always
are". But the controls that get you there are not equally safe, so they are not
switched on together.

**Always on, in every recording:**

| Control | What it does |
|---|---|
| **Fixed timezone and locale** | The context is pinned to `UTC` / `en-US`, so every date, number and currency the app formats reads the same on your laptop as in CI. |
| **`prefers-reduced-motion: reduce`** | Requested on the context. An app that honours it was built to. |

**Opt-in, with `deterministic=True`:**

| Control | What it does |
|---|---|
| **Frozen wall clock** | `Date.now()`, `new Date()`, `Intl.DateTimeFormat().format()`, `performance.timeOrigin`, `document.lastModified` and a `Worker`'s clock all answer one fixed instant — `2025-01-01T09:00:00Z` by default. Explicit arguments (`new Date(iso)`), `Date.parse` and `Date.UTC` are untouched. |
| **Flattened motion** | Animations and transitions are compressed to 1 ms, so they land on their finished state within the first frame. Authored delays and fill-modes are left alone. |

```python
with Recorder(out_dir, deterministic=True) as rec:   # or DEMO_VIDEO_DETERMINISTIC=1
```

### Why the clock is opt-in — read this before turning it on

**A frozen clock breaks apps, and it usually breaks them silently.** Five
ordinary patterns, each recorded both ways against a real page:

| Pattern | With the clock frozen | Actually |
|---|---|---|
| lodash-shaped debounce (`now - last >= wait`) | never fires; the timer reschedules forever | fires |
| elapsed-time progress bar | sticks at `0%` | reaches `100%` |
| token gate (`nbf`/`exp` around now) | "not yet valid (clock skew)" | "signed in" |
| "last 7 days" chart | draws **0** bars | draws 7 |
| `while (Date.now() - t0 < ms)` spin | never exits — the take dies on a navigation timeout with **no mp4 written**, and nothing in the error mentions the clock | exits |

Four of the five produce **a plausible wrong screen**: no exception, nothing on
the console, nothing in `timeline.json` — just a demo that confidently shows a
reviewer something the app never does. That is a worse outcome than a fresh
timestamp in every take, which is why you have to ask for it.

So: turn it on deliberately, and **check the stills against the real app the
first time you do**. If something looks wrong, try moving the frozen instant
first (`clock="2026-03-01T12:00:00Z"`, so tokens minted at record time are
still valid), and drop back to the default if the app needs a moving clock.

Every take records what it was given, in `timeline.json`:

```json
"determinism": { "deterministic": true, "clock": "2025-01-01T09:00:00Z",
                 "timezone_id": "UTC", "locale": "en-US" }
```

`"clock": null` means the page's clock was live. Commit it with the stills: a
year from now it is the only thing that says whether a diff is the UI changing
or the frozen instant changing.

### Keeping something animated

Motion is flattened to 1 ms rather than to zero on purpose — a transition of
zero duration never starts, so it never fires `transitionend`, and every
accordion, modal, carousel and wizard that advances on that event would stall.
An element that must keep *moving* opts out by name:

```html
<div class="pulse" data-demo-video-animate>…</div>
```

The recorder's own overlays (`#__demo…`, `#__term…`) are exempt already, so
captions still fade. And note what is *not* frozen: `performance.now()`,
`requestAnimationFrame`, and the document animation timeline. Only the wall
clock stops. Freezing monotonic time would stop the compositor, and Chromium's
screencast only emits a frame when the page paints — a still page loses wall
time out of the recording ([#18](https://github.com/rogvid/skills/issues/18)).

One shape has no right answer and gets a deliberate one: an **infinite**
animation has no finished state, so it is stopped after a single 1 ms iteration
and the element shows the style it was declared with. A finite animation —
including `alternate` — ends where the browser would have left it.

### What it cannot control

The recorder drives a browser. Everything below is upstream of it and is the
**storyboard author's** job — a demo that ignores them re-records differently
no matter what this section does:

- **The app's own randomness.** `Math.random()`, `crypto.randomUUID()`,
  generated ids, shuffled lists, faker-seeded fixtures. Nothing here seeds
  them. Seed the app yourself (most frameworks and fixture libraries take a
  seed), or pick a screen that has none.
- **Server data.** Rows a backend returns, "5 minutes ago" rendered
  server-side, anything a background job wrote since the last take. Seed the
  state *before* recording and reset it between takes; storyboards are meant
  to be idempotent (see Process, step 2).
- **Network timing.** Which of two requests lands first, whether a spinner is
  on screen long enough to be photographed, a chart that draws before or after
  its data arrives. `wait_for` a concrete element rather than a delay, and
  never assert on a frame that only exists while something is in flight.
- **The terminal recorder's program.** `TerminalRecorder` runs a real PTY
  child; it does not see the frozen clock, so `date` in a terminal demo prints
  the real time. Tracked in [#26](https://github.com/rogvid/skills/issues/26).
- **Animation the browser does not drive with CSS.** `element.animate()` (Web
  Animations), `requestAnimationFrame` loops, canvas and WebGL keep running —
  no stylesheet can reach them
  ([#35](https://github.com/rogvid/skills/issues/35)). Nor can one reach into
  a shadow root, or outrank an app's own `!important`
  ([#36](https://github.com/rogvid/skills/issues/36)).
- **A module worker's clock.** A classic `Worker` gets the freeze re-injected;
  `{type: "module"}` workers, shared workers and service workers do not
  ([#38](https://github.com/rogvid/skills/issues/38)).
- **The bytes of `demo.mp4`.** H.264 is not byte-reproducible and the
  screencast's frame timing is not either. Two takes match in what they *show*,
  not in their checksums — compare the stills, which are lossless PNGs and do
  reproduce exactly.


## Recorder API (storyboard verbs)

`Recorder(out_dir, base_url=..., segment=None, strict=False, ...)` as a context
manager; mp4 conversion happens on clean exit. `strict=True` refuses a take
that recorded a console error, an uncaught exception, or a non-zero exit — see
**Failing the take on a broken app**.

| Verb | Use |
|---|---|
| `goto(path)` | Navigate (relative to base_url); waits for networkidle, but gives up after 10 s for apps that poll |
| `pause(s)` / `shot(name)` | Hold the frame / capture `images/<name>.png` |
| `caption(text)` | Narrator line at the bottom; `""` clears; dies on full page loads, survives SPA routing — clear before navigating either way |
| `hold(min_s=1.5)` | Keep the current frame up until the current caption's narration finishes (min `min_s`). Use after a spotlight/action so the emphasis rides the whole spoken line instead of flashing. See **Pacing and perception**. |
| `move_to` / `click` / `click_fast` / `scroll_to` | Visible cursor motion; `click_fast` for elements that re-render continuously |
| `type_into(selector, text)` | Click a field and type visibly, key by key — form demos (checkout, login, search) |
| `wait_for(selector)` | Wait for something the app does on its own |
| `spotlight(selector)` | Ring + enlarge the element the caption discusses; `spotlight()` clears |
| `terminal(cmd)` / `terminal_output(text)` / `terminal_close()` | A *decorative* on-screen terminal card for off-browser actions **inside a web demo** — a prop, not a real shell. To record an actual CLI/TUI use `TerminalRecorder` (below). |
| `redact(*selectors)` | Blur these elements for the whole take — frames and stills. **Plain CSS selectors only.** Call it **before** the first `goto()`. See **Redacting secrets**. |
| `register_secret(*values)` | Register literal text that must never be captioned, spoken, or logged. A caption containing it raises `SecretLeak`. |
| `interlude(text, style=…)` | Bridge a jump. `style="card"` (default) is a full-screen title card, for real time-skips; `style="light"` is a centered label over a soft scrim with the scene still visible, for short transitions. `""` fades it out. |
| `stitch(out_dir, [segments])` | Lossless concat of segment recordings into demo.mp4, **and** merge their beat logs into one `timeline.json` / `timeline.md` beside it. `keep_parts=True` leaves each `.seg.mp4` and its `.seg.timeline.*` on disk for a re-stitch |
| `rec.page` | The live Playwright page — the escape hatch for anything the verbs don't cover (iframes, keyboard shortcuts, drag) |

## Redacting secrets

A published video leaks permanently, and demos run against seeded-but-realistic
data. Two registrations, at the top of the storyboard, before the first
`goto()`:

```python
from demo_recording import Recorder, Secret

with Recorder(Path(__file__).parent) as rec:
    rec.redact("#api-key", ".customer-email")   # blur where it renders
    rec.register_secret(os.environ["DEMO_TOKEN"])  # keep the text out of narration
    rec.goto("/settings")
    rec.type_into("#token", Secret("sk-live-…"))   # both, automatically
```

- **`redact(*selectors)`** paints an **opaque cover** over matching elements,
  in the page — not with an ffmpeg box in post, which needs fixed coordinates
  while elements scroll, reflow and re-render.

  It covers rather than blurs because a blur is a *how much is enough*
  question, and every answer to it is a guess about how the ink was produced.
  Five ways of rendering text larger than its `font-size` says — a
  `::after`, a `transform: scale()`, `zoom`, an SVG `viewBox`, a value two
  shadow roots down — each defeated a radius derived from CSS, and there was
  no reason to think the fifth was the last. A cover is sized from rendered
  geometry (client rects, which include transforms and zoom by construction)
  and asks no question about the text at all. `redact(..., style="blur")`
  keeps the old look; it is an aesthetic choice, and a weaker one. It is installed as a context init
  script, so it is in place before the page's own scripts run and before the
  first frame; elements are masked from the instant they enter the DOM, and a
  `MutationObserver` re-asserts the mask if the app rewrites the element's
  `style` attribute or replaces the document's stylesheets. Stills inherit it,
  because the mask is in the page rather than in the video pipeline.
  - **Plain CSS selectors only** — an id, a class, an attribute. This is the
    one verb that does not take `text=`, `xpath=`, `>>` or `nth=`, and it
    refuses them with an error rather than accepting them. Continuous cover
    comes from a stylesheet injected into the page, and a stylesheet can only
    express CSS; a Playwright-engine selector can only be re-resolved out of
    process at whatever moments the recorder happens to check, which measured
    as four unmasked seconds of a ten-second take on an ordinary
    fetch-then-render page. Name the element with CSS, or keep the value off
    the screen and register the text.
  - **It reaches an open shadow root** — which `document.querySelectorAll`
    cannot see at all — because the mask is also applied from Python through
    Playwright's engine, and because it wraps `attachShadow` at document start
    to hold every root the app opens.
  - **Sized from what the element paints**, not from what its CSS says: the
    union of the client rects of everything in its subtree, shadow roots at
    every depth included, grown by any pseudo-element's font size (generated
    content has no rect to measure and can paint outside its parent's box).
    Redacting a wrapper is the ordinary call — `redact("#card")` where the
    value is an 80px child — and every measurement here is of the child's
    rendered box, not the wrapper's font.
  - **A blur stays underneath the cover** as a floor, sized the same way. It
    is what a stylesheet can do with no JS at all, and `filter` applies to
    everything an element renders — so it reaches ink the cover's rectangle
    can miss.
  - **It fails rather than misses.** At every checkpoint — after a navigation,
    before every still, around every verb that spends time, and before the mp4
    is written — the recorder asks Playwright, across every frame, how many
    elements each selector matches, and then asks the *browser's own hit
    testing* whether anything is painting over each cover. A cover that
    something paints above, or a selector that never matched anything, raises
    `SecretLeak`: the take writes no mp4, no timeline, and deletes the stills
    it had already taken. A redacted take also withholds the first paint of
    each navigation until that check has passed.
- **`register_secret(*values)`** is about *text*, not pixels. A `caption()`,
  `interlude()`, `terminal()`, `terminal_close()`, `run()` or `send()` line
  containing a registered value raises `SecretLeak` and **fails the take** — deliberately,
  rather than masking the line: captions are burned in *and* spoken *and*
  cached as audio in `.tts/`, and a secret in one is an authoring bug that
  wants rewording, not blurring. Text you did not author is scrubbed to
  `[redacted]` instead: `terminal_output()` (a program's output), every string
  on a beat (`selector`, `still`, `caption`), and `shot()`'s name, which is
  scrubbed before it becomes a filename so the log and the disk agree.
- **`Secret("…")`** is a value the demo types but must never show:
  `type_into(sel, Secret(v))` registers the text, blurs the field before the
  first keystroke, and types the real value. It is not a `str` — printing one
  yields `[redacted]`, and it can never be logged as a beat's target by
  accident.

### Redaction in a terminal demo

`TerminalRecorder` has no `redact()`, and that is not an omission: a CSS
selector means nothing to a PTY. What it has instead is a **scrubber on the
output path**, between `os.read()` and the terminal, so a secret a program
prints never reaches the buffer the frames are drawn from.

```python
from demo_recording import TerminalRecorder, Secret

with TerminalRecorder(Path(__file__).parent) as rec:
    rec.register_secret(os.environ["DEMO_TOKEN"])   # exact text: the guarantee
    rec.run("./deploy --show-config")               # its output comes back masked
    rec.run("ssh-add -l")                           # wait_for_prompt() sees the mask too
    rec.send(Secret(os.environ["DEMO_PW"]))         # a password, at a prompt
```

- **Registered values are the guarantee.** Every occurrence in a program's
  output becomes `[redacted]` — in the video, in the stills, and in the screen
  text `wait_for_text()` and `wait_for_prompt()` match against. It holds when
  the value is chopped across `os.read()` boundaries (the recorder holds back
  any trailing fragment that could still complete one, with no time limit) and
  when one of a **listed set** of escape sequences is printed *inside* it —
  colour and style, cursor show/hide, erase-to-end-of-line, window-title OSC,
  charset and keypad selection. Not "any sequence that does not move the
  cursor": that is the shape of the rule, not its reach, and sequences outside
  the list are where it stops. See below for both halves.
- **…and what the stream cannot express, the recorder refuses.** Before it
  writes anything, the take reads the finished terminal — visible screen and
  scrollback — and raises `SecretLeak` if a registered value is in it: no mp4,
  no timeline, no stills. That is the backstop for the case the scrubber
  cannot see (a value written in two pieces at two cursor positions), and it
  is why "not covered" below means "the take dies", not "it records the key".

  "Finished" and "no stills" both mean it. The check runs after the narration
  tail and after the recorder has flushed whatever it was still holding, so
  it reads the screen the recording actually ends on — and it runs on every
  way out of the `with`, including a storyboard that raised. A
  `wait_for_text()` that timed out still gets its stills taken back, because
  a still is written long before a take ends and a terminal still is the raw
  screen. When that happens the timeout is what gets raised, not the leak:
  the leak is printed, and the message that says what to fix is the one you
  wanted.
- **Shape detection is a safety net under that, not a substitute for it.**
  Four patterns are masked whether or not anyone registered them:

  | | what it matches |
  |---|---|
  | `sk-…` | `sk-` + 16 or more of `A-Za-z0-9_-` |
  | `ghp_…` | `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` + 16 or more alphanumerics |
  | `AKIA…` | `AKIA` or `ASIA` + 12 or more of `0-9A-Z` |
  | JWT | `eyJ` + base64url, a `.`, base64url, optionally `.` and more |

  They are deliberately narrow. Anything looser starts masking ordinary
  output, and a demo with holes punched in it at random is worse than one that
  shows a fake key. **Do not plan a demo around them**: a value that does not
  match one of those four shapes — a database URL with a password in it, a
  session cookie, an internal token format, a licence key — is not touched
  unless you register it. They are also the *only* thing the final screen
  check ignores: a registered value on screen kills the take, a shape-matched
  one does not, because failing a recording on a heuristic is worse than the
  heuristic missing.
- **`run()` and `send()` refuse authored secrets.** A command line is text the
  storyboard wrote and the PTY echoes on camera, so it is treated like a
  caption: `run("curl -H 'x-api-key: sk-live-…'")` raises `SecretLeak` and
  fails the take rather than typing a command the viewer cannot read. Pass the
  value through the environment instead (`run('curl -H "x-api-key: $KEY"')`),
  or type it with `send(Secret(...))`.
- **`send(Secret(v))` is the password case.** It registers the value, types
  the real thing, and the terminal's own echo of it comes back masked — one
  character per read, which is exactly the split the carry buffer exists for.
  Programs that turn echo off (a real `getpass`) show nothing either way.
- **`key()` refuses one too.** `key(*value)` spells a value out one keystroke
  at a time, and the beat it records is those keys joined by spaces — which no
  scrub of the value can match, in a file this skill tells you to commit. So
  the call raises rather than the log leaking.
- **A held fragment can make the screen lag.** The recorder cannot know that
  `sk-live-de` is the start of a registered value until the rest arrives, so
  it withholds it. If the program then goes quiet — a prompt waiting for
  input — those characters stay off screen, and a `wait_for_text()` looking
  for them waits with them. After two seconds the recorder says so on stderr,
  naming the count. Shape fragments are not held indefinitely: they go out
  after three seconds, or immediately if they sit in the middle of a word
  rather than where a token would start.

### What redaction does NOT cover

Read this before trusting a recording to it. It closes a specific, countable
set of paths — four on the web, one in the terminal — and nothing else:

- **The cover is erasure; `style="blur"` is not.** An opaque rectangle
  removes the pixels. A blur destroys legibility, not information — a
  determined attacker with the font and the radius can attempt deconvolution —
  and it is sized by a rule that has been wrong five times. If you opt into
  blur, treat it as a visual convention rather than a control. For a real
  credential, do not render it at all: demo against a fake value.
- **What the cover is sized from, it can miss.** It is the union of the client
  rects the recorder can find. Generated content is allowed for by growing the
  box by the pseudo's font size, but an absolutely positioned pseudo far from
  its parent, or ink painted outside every rect in the subtree, is outside it —
  the blur underneath is what covers those, and the blur is the weaker
  mechanism. Look at the stills.
- **`redact()` takes plain CSS and nothing else**, unlike every other verb
  here. `text=`, `xpath=`, `>>` and `nth=` raise. See above for why.
- **Nothing is registered for you.** `redact()` does not read the element's
  text, so the value stays *unregistered* — write it into a caption yourself
  and it will be captioned, spoken and cached without complaint. Register the
  text separately, or type it as a `Secret`.
- **Only exact substrings match, on every path but one.** No normalisation —
  a secret rendered with different whitespace, a soft hyphen, or split across
  two elements is not caught, and a caption or a beat field is checked
  literally. The single exception is the terminal recorder's PTY output, which
  also runs four shape patterns over what a program prints; those are listed
  under **Redaction in a terminal demo**, they apply nowhere else, and they
  are a net rather than a promise.
- **Registering late does not un-record anything.** A caption set before its
  value was registered is already burned into the frames and already spoken;
  what registration afterwards buys is only that the files the recorder writes
  (`timeline.json`, `timeline.md`, still filenames) come back masked. Register
  before you caption.
- **Frames recorded before the call are already on disk.** `redact()` after a
  `goto()` warns for exactly this reason: masking late cannot un-capture a
  frame.
- **A *closed* shadow root cannot be masked by anything** — not by an injected
  stylesheet, not by Playwright, not by `document.querySelector`. A take told
  to redact something inside one fails loudly and records nothing, which is the
  only honest outcome; there is no way to record that app with that value on
  screen.
- **Iframes: same-origin only, in practice.** The in-page mask is injected
  into every frame, and masking and verification now run across all of them —
  but a *cross-origin* frame's contents are a separate document the recorder
  cannot always reach, and nothing here can mask what it cannot see. A key in
  a third-party iframe is not covered.
- **Canvas: the picture is covered, the bitmap is not.** The cover is over
  the canvas element's rect, so nothing it draws is visible. Anything reading
  the bitmap back (`toDataURL`, `getImageData`) still sees the original.
- **The terminal scrubber has its own list, and it is not short.** Everything
  under **Redaction in a terminal demo** above holds; here is what it does not
  reach.
  - **A value split by an escape the scrubber does not know is not masked —
    and it can be perfectly legible.** Matching runs against a copy with the
    *inert* sequences removed, and that is a **fixed list**: colour and style
    (SGR), mode set/reset (`\x1b[?25l`, which every spinner emits),
    erase-to-end-of-line, window-title OSC, charset and keypad selection. A
    token broken by one of those is contiguous on screen and is caught.

    A token broken by a non-cursor-moving sequence that is *not* on the list
    is not. Measured, each of these renders the value as one word on screen
    while the scrubber writes it in the clear: a CSI with an intermediate byte
    (`\x1b[1 q`, the cursor-style escape), a DCS string (`\x1bPxx\x1b\\`), and
    an OSC aborted by an ESC rather than a BEL (`\x1b]0;t\x1b[0m`). For a
    *registered* value the final screen check below still kills the take, so
    the guarantee holds — the recording is refused rather than leaked. For a
    value that only shape detection was hiding, nothing catches it and it is
    in the frames.

    Cursor movement is different. `\x1b[3;1Hsk-live-` followed by
    `\x1b[3;15HKEY…` puts the value on screen as one word while no substring
    of the stream contains it, and masking across the jump would delete the
    movement and corrupt the redraw. **Do not read this as "the secret comes
    out scrambled anyway" — it comes out readable.** What saves the recording
    is the final screen check: the take raises `SecretLeak` and keeps nothing.
    A recording you wanted, refused. Keep such values off the screen.

    (A line the *terminal* wraps at the right margin is not this case and is
    caught: wrapping puts no escape in the stream.)
  - **The final screen check covers registered values only.** A shape-matched
    token written the same way is not refused and not masked. Register.
  - **Half a secret still renders.** The recorder cannot know a run of
    characters is the start of a key until the rest arrives, so a program
    killed part-way through printing one leaves what it printed on screen.
    (At teardown a dangling fragment of a registered value, or one that had
    reached a credential anchor, is masked; up to that point it is on screen
    because it might have been anything.)
  - **Shape detection has a clock, and a registered value does not.** A
    fragment that could still grow into a shape match is held across quiet
    moments — measured, a token written at 5, 20, 100 or 400 ms per character
    is masked — but not forever: three seconds where a token would start,
    and not at all in the middle of a word, because a screen permanently
    missing its last character is a `wait_for_text()` that never returns. So a
    program that pauses **longer than three seconds inside a token** defeats
    shape matching. Registered values have no such limit.
  - **A shape-matched token longer than 4096 characters may have its head
    rendered** — the fragment ceiling. A *registered* value of any length is
    held whole.
  - **Registering late is worse here than on the web.** The scrubber runs as
    output arrives, so anything already on screen when you call
    `register_secret()` stays on screen. Register before the command runs.
  - **Scrollback is the recording.** A secret masked on screen was never in
    the buffer at all, so scrollback holds the mask too — but anything the
    *program* writes elsewhere (a log file, a `tee`, its own history) is
    untouched. This hides values from the recording, not from the machine.
  - **The PTY child is a real process.** It sees your real environment; the
    recorder does not sanitize it. A screen recording of a shell is a
    recording of a shell.
- **What CSS cannot reach, the mask cannot hide**: a cross-origin iframe's
  contents, an OS-level dialog, anything drawn outside the page. A `<canvas>`
  *is* covered — `filter` on the element blurs its rendered pixels like any
  other element (verified) — but only what is *displayed*; the bitmap behind it
  is unchanged, so anything reading it back (`toDataURL`, `getImageData`) still
  sees the original.
- **Non-visual channels are untouched.** The value still exists in the DOM
  (`page.content()`), in the app's network traffic, and in whatever the app
  logs. Redaction hides it from the *recording*, not from the machine.
  - The one place this skill *does* dump the DOM is `evidence/beat-NN.json`,
    and it is plain text, so it cannot inherit a pixel control for free: the
    recorder reads what each redacted element renders and masks that text out
    of every evidence file. Read **Per-beat evidence** before trusting it, and
    do not commit `evidence/`.
  - What that harvest reads is also masked out of `timeline.json` and
    `timeline.md`, which *are* committed. Without it a caption or a selector
    holding a redacted element's text would come back `[redacted]` in the
    evidence and in the clear in the file you are asked to check in.
- **A screenshot the storyboard takes itself** — `rec.page.screenshot(...)`
  rather than `rec.shot(...)` — still goes through the page, so the CSS mask
  applies; but any artifact your storyboard writes by hand (a `page.content()`
  dump, a downloaded file) is yours to clean.
- **`register_secret()` takes any non-empty string, including a short one.**
  Registering `"1234"` masks every occurrence of those four characters in beat
  selectors and terminal output. Register whole values.
- **A failed take deletes its own stills, and only its own.** When the mask
  cannot be verified the recorder removes the stills *this* take wrote and
  names each one it removed. Stills a previous take left in the same folder
  are not touched — and anything your storyboard wrote by hand is yours.

## The beat timeline (`timeline.json` / `timeline.md`)

Every storyboard verb is logged as a **beat** — what was done, when, and what
caption was on screen while it happened — and a clean exit writes the log next
to the media. No storyboard changes are needed; it is a byproduct of recording.

`timeline.md` is the readable version: a table of every beat, then each still
embedded under the caption it was taken during. **Commit both.** They are
small, diffable, and unlike `demo.mp4` they survive as a record of what the
demo showed after the video has been regenerated or thrown away — which is
what makes them worth reviewing in a PR.

**A segmented demo gets exactly the same pair, written by `stitch()`.** Each
segment records `<segment>.seg.timeline.json` beside its `<segment>.seg.mp4`,
with timestamps relative to that segment's own start; `stitch()` merges them
into one `timeline.json` / `timeline.md` next to `demo.mp4`, moving each
segment's beats by the **real duration** (ffprobe) of the parts before it.
Commit the merged pair; gitignore the `*.seg.timeline.*` parts with the
segment media, exactly as you gitignore `*.seg.mp4`. `stitch()` deletes them
along with the `.seg.mp4` files unless you pass `keep_parts=True`, which keeps
both so one expensive segment can be re-recorded and re-stitched.

`timeline.json` is the machine-readable one, and a stable contract — adding a
key is fine, renaming one is not:

```json
{ "schema": 1, "generated_by": "demo-video", "recorder": "Recorder",
  "segment": null, "media": "demo.mp4", "duration": 18.04,
  "strict": false, "issue_count": 1,
  "beats": [
    { "index": 4, "t_start": 3.02, "t_end": 3.06, "caption": "A small dashboard.",
      "verb": "shot", "selector": "01-dashboard",
      "still": "images/01-dashboard.png", "segment": null, "segment_index": 4 }
  ],
  "issues": [
    { "kind": "console_error", "t": 0.47, "beat": 0, "verb": "goto",
      "caption": "", "message": "Cannot read properties of undefined",
      "url": "http://localhost:3000/app.js", "line": 412 }
  ] }
```

- `t_start` / `t_end` are seconds from the start of `media` — the verb
  starting and returning. A verb built out of other verbs (`click` glides
  first, `type_into` clicks first) is one beat, not one per internal step.
- `caption` is the line on screen during the beat: the new text for a
  `caption` beat, the line shown for an `interlude`, `""` when none is up.
- `selector` is what the verb acted on, as a string — a CSS selector for the
  web verbs, the command / keys / pattern for the terminal ones, the name for
  `shot`. `null` for verbs with no target (`pause`, `hold`, a cleared
  `spotlight`).
- `still` is a path relative to the timeline file, so `timeline.md`'s embeds
  and any tooling resolve the same way.
- `evidence` is a path, the same way — the beat's own account of what was on
  screen. See **Per-beat evidence** below.
- `exit_code` appears on `TerminalRecorder` `run` beats — see **Failing the
  take** below.
- `issues` is what the recorder saw *behind* the pixels; `issue_count` is how
  many it saw, and is larger than `len(issues)` only when a take blew past the
  200-issue cap.
- `index` is the beat's position **in this file**, so `stitch()` renumbers it
  across a merged demo. `segment` and `segment_index` (its position within its
  own segment) survive the merge untouched — use that pair, not `index`, to
  name a beat in anything that has to line up across a re-stitch.

A merged timeline says so, and says what it was built from:

```json
{ "segment": null, "media": "demo.mp4", "duration": 15.2,
  "recorder": "Recorder",
  "segments": [
    { "segment": "part1", "media": "part1.seg.mp4", "duration": 6.6,
      "offset": 0.0, "beats": 6, "recorder": "Recorder", "determinism": {…} },
    { "segment": "part2", "media": "part2.seg.mp4", "duration": 8.6,
      "offset": 6.6, "beats": 9, "recorder": "Recorder", "determinism": {…} }
  ] }
```

`offset` is where each part starts inside `demo.mp4`, which is what maps a
merged timestamp back to the file it came from. `recorder` and `determinism`
at the top level carry the value every segment agrees on — `"mixed"`, and
`null` per key, where they do not; the per-segment truth is in `segments`. A
timeline a single take wrote has no `segments` key at all.

`stitch()` refuses before it encodes anything if the parts cannot honestly be
joined: a missing or unreadable `.seg.mp4`, a beat log of the wrong schema or
one written for a *different recording* of that segment, or parts that
disagree on codec, resolution, frame rate or having an audio track.
`concat -c copy` accepts all of those and exits 0, and the damage is invisible
afterwards — a frame-rate mismatch moves every later beat away from its frame,
a resolution mismatch keeps the first part's dimensions, and one silent part
makes concat drop every later part's narration. Recording every segment with
the same `Recorder` settings is what keeps you clear of it.

## Review frames (`frames/`)

Nobody reviewing a demo through this skill can watch a video, so every review
is a review of frames pulled out of it. A clean exit writes them: one PNG per
beat under `frames/`, named `beat-NN.png` for the beat's index in
`timeline.json`, plus `frames/frames.md` — the sheet to hand a reviewer, which
embeds them in order — and `frames/frames.json` for anything reading them by
machine.

They are aligned to **beats, not to a clock**. The old advice was
`ffmpeg -vf fps=1/3`, which misses a short beat entirely and photographs a long
static one twice. Each frame is taken at its beat's **midpoint** — `t_start` is
0% into the caption bar's fade and before the verb has done anything.

**How accurate that aim is, honestly.** The beat log is wall-clock; the video
is whatever Chromium's screencast managed to record, and it drops wall time
during idle stretches ([#18](https://github.com/rogvid/skills/issues/18)). So a
frame cut at a beat's midpoint shows a moment slightly *ahead* of that beat in
the demo's own story — measured at **40–120 ms** on instrumented takes, and up
to **~600 ms** on a take that loses the browser's start-up window whole (about
1 in 12). The practical consequence: for a beat comfortably longer than that,
the frame is of that beat; **for a beat shorter than the drift — a bare
`shot()`, a `wait_for()` that returned immediately — the frame can be of the
beat after it.** `tests/smoke` measures exactly this and shows it: with the
drift allowance removed, the frame for a 50 ms `shot()` beat that sits against
a caption change is already showing the next beat's screen.

Read the frames as *"roughly here in the demo"*, not as *"exactly this beat"*.
When a specific short moment matters, use `shot()` — `images/*.png` are
Playwright screenshots taken synchronously at the beat, with no video clock
between the moment and the file. `frames/frames.md` reports the take's own
lower bound on how much wall time the capture lost, when it lost any.

**They carry no caption, and that is deliberate.** Printing the line that was
on screen during a frame's beat under that frame is the obvious next step and
it is not sound: the beat log and the video run on different clocks
([#18](https://github.com/rogvid/skills/issues/18)), so the caption under a
frame can belong to the frame next to it — and a confident wrong caption is
worse review material than no caption at all. An earlier version tried to
recover the mapping by finding caption transitions in the video; it mislabelled
frames on ordinary storyboards (two captions of the same length give it no
signal, an app that repaints under the bar gives it a stronger edge than the
caption does, and a mid-take `goto()` destroys the bar while logging no caption
change at all). [#60](https://github.com/rogvid/skills/issues/60) is how the
pairing gets earned back: have the recorder render the beat index into the
frame so extraction reads it rather than infers it.

`frames.md` also carries **no verb and no selector**, for the same reason step
6 tells you to give the reviewer nothing else: it is the document a
context-free reviewer reads before answering what story the pictures tell.

Inside a beat long enough to hide something the storyboard never scripted (3 s
and up) the recorder also runs scene-change detection and adds
`beat-NN-scene-1.png` for each transition it finds. Beat alignment sees what
the storyboard wrote down; a redirect, a toast or a load finishing mid-hold is
invisible to it.

**A stitched demo gets frames; a single segment does not.** Each segment
numbers its beats from zero and its timeline names a `.seg.mp4` that `stitch()`
deletes, so two segments writing into one directory would collide on
`beat-00.png` and the sheet would embed a file that is gone — a segment take
therefore writes no frames and says why. `stitch()` writes them instead, off
the **merged** timeline, at the first moment a whole demo exists. Nothing extra
to run, and it is the case that needs a sheet most: a demo long enough to
record in parts is a demo nobody wants to review by scrubbing.

`frames/` is a review artifact, not documentation: **gitignore it** along with
`demo.mp4` — it is in the file table at the top for the same reason. Nothing
downstream reads it; `beat_frames(out_dir)` from `demo_recording` regenerates
it from `demo.mp4` and `timeline.json` without re-recording, and clears the
previous run's frames first.

## Per-beat evidence (`evidence/beat-NN.json`)

A reviewing agent handed frames has to infer what the page said from pixels.
The recorder is *driving* the page, so at the end of every beat it also writes
down what was on screen, in text, next to the frame that beat's timestamps
point at. No storyboard changes; it is a byproduct of recording, like the
timeline. `Recorder(..., evidence=False)` or `DEMO_VIDEO_EVIDENCE=0` turns it
off.

```json
{ "schema": 1, "generated_by": "demo-video", "recorder": "Recorder",
  "segment": null, "media": "demo.mp4",
  "beat": { "index": 6, "t_start": 5.31, "t_end": 5.44, "verb": "shot",
            "selector": "01-dashboard", "caption": "A small dashboard.",
            "still": "images/01-dashboard.png",
            "evidence": "evidence/beat-06.json" },
  "scope": "#kpi-rev",
  "url": "http://localhost:3000/", "title": "Northwind Ops",
  "aria_format": "aria-yaml",
  "aria": "- banner:\n  - heading \"Northwind Ops\" [level=1]\n- text: Revenue $128,400 …",
  "scope_aria": "- text: $128,400",
  "html": "<div id=\"kpi-rev\">$128,400</div>",
  "truncated": [], "limits": { "aria": 12000, "html": 8000 } }
```

| Field | What it is |
|---|---|
| `aria` | **`Recorder`**: the page's ARIA snapshot — a compact YAML tree of roles and accessible names, the same thing `expect(...).toMatchAriaSnapshot` compares. Semantic, ~10× smaller than the markup, and stable across restyling, which is why it is preferred over raw HTML |
| `scope` / `scope_aria` / `html` | the current `spotlight()` target: its selector, its own ARIA tree, and its `outerHTML` with every value-bearing attribute stripped. All three are null when no spotlight is up |
| `screen` | **`TerminalRecorder`**: the rendered screen, ANSI resolved by xterm.js, scrollback included — the same text `wait_for_text()` matches against |
| `truncated` / `limits` | which fields were cut, and at what budget. A cut field also says so inline where it stops |
| `omitted` | present *instead of* the page text when the recorder would have had to guess — see below. `timeline.json` is unaffected |

**`outerHTML` is only ever the spotlight target's, never the page's.** A whole
document's markup is an order of magnitude bigger than its ARIA tree and
carries two things nobody put on screen: the text of every inline `<script>`,
and `srcdoc` attributes — i.e. source code and whole embedded documents. The
clone that gets serialized drops both, along with `<style>`, the recorder's own
overlays, and anything `redact()` is covering.

Fields are capped (12 000 characters of ARIA or screen text, 8 000 of markup)
and truncation is **marked, never silent** — a TUI's scrollback is 5 000 lines,
and an uncapped `evidence/` outgrows the mp4 it describes.

### Evidence is plain text — what that means for secrets

**This is the artifact where a secret is cheapest to find**, and it is worth
being blunt about why: everything else this skill writes is pixels, and
`redact()` is a *pixel* control. It covers where a value renders. The value is
still in the DOM — and an evidence file is a text dump of that DOM. "It is
blurred in the video" is no protection here at all.

So evidence is masked twice over, and the second one is what makes redaction
carry across:

- every registered secret (`register_secret()`, a typed `Secret`) is replaced
  with `[redacted]`, as everywhere else;
- **the rendered text of everything `redact()` is covering** is read out of the
  page as the take runs — the matched element and every node under it, shadow
  roots at every depth, light DOM assigned into a `<slot>`, `::before`/`::after`
  content, input values, value-bearing attributes, and any element an
  `aria-labelledby` points at, however far away it is — and every occurrence of
  any of it is replaced too, in every beat's evidence, including beats recorded
  before the value first appeared. `redact()` never tells the recorder what the
  element *says*, so this is the step that turns a pixel control into a text
  one. Whitespace is elastic on both sides of the match: `textContent` carries
  the source's own indentation and an ARIA tree does not, and a value on its own
  line in hand-written HTML is otherwise the most ordinary leak there is;
- markup is elided structurally as well as by substring, because a value split
  across tags (`sk-live-<b>FAKE</b>`) has a `textContent` a string mask finds
  and an `outerHTML` it does not. Where the split value is a *registered* one
  rather than a redacted element's, the markup is **withheld** for that beat
  with a line saying so — there is no safe way to edit a value out of a
  serialization that interleaves it with elements;
- `outerHTML` also drops every value-bearing attribute — `data-*`, `title`,
  `alt`, `placeholder`, `aria-label`, `href`, `src` — from every element, not
  just redacted ones. An attribute nothing renders was in no frame, no still,
  no caption and no narration clip, so serializing it would make evidence the
  only place it exists.

**A harvested string is only used as a mask if it renders nowhere outside the
mask.** Harvesting every node of a redacted card also harvests its label, and
`redact("#revenue-card")` would otherwise register "Revenue" as a forbidden
literal and rewrite every unrelated paragraph in every file. That rule is not a
guess about what a secret looks like: a string that renders in the clear
somewhere the mask does not cover is already in the frames and the stills, so
masking it in a text file buys nothing and costs the file its meaning.

"Renders outside" is narrower than it sounds, and each exclusion was a leak:
hidden elements do not count (an `aria-labelledby` source can be `display:none`
and still name a redacted element), `<script>` text does not count (it is
source, not screen), light DOM slotted into a redacted element counts as
*inside* it, and **the recorder's own caption bar does not count at all** —
captioning a redacted value would otherwise exempt it from masking everywhere,
turning one mistake in the frames into the same mistake in `timeline.json`.

Nothing reaches the disk until the take exits cleanly and the mask has been
verified: the documents are built in memory and written beside `timeline.json`,
so a take that dies on a `SecretLeak` has no evidence file to delete — and a
take that *succeeds* first deletes any evidence a previous recording into the
same folder left behind, since re-running `record.py` into the same directory is
the normal way to use this skill and yesterday's files would otherwise sit there
holding the value you just added a `redact()` for. If a document cannot be made
safe, the take fails.

**A page that repaints while it is being read gets no page text.** The ARIA
snapshot is a protocol call and the harvest is a page evaluation, so they cannot
be one operation: a card rewritten on a 25 ms interval — a countdown, a ticker,
a rotating token — hands the harvest one value and the snapshot the next. The
harvest is therefore taken on both sides of the snapshot and the two must agree;
if they will not settle, that beat's evidence is written as `{"omitted": …}`
with no `aria`, `scope_aria` or `html` in it. On a page where something inside a
redacted region never holds still, expect most beats to come back that way —
`timeline.json` is unaffected, and it is the safe direction.

**What it still does not cover:**

- **`TerminalRecorder` has no `redact()`** (that is
  [issue #5](https://github.com/rogvid/skills/issues/5)), so `screen` is the
  whole terminal, scrubbed for registered secrets only. A command that
  *prints* a value nobody registered writes it here verbatim — the same
  exposure the recording already has, in a form that greps.
- **`url` and `title` go through the registered-secret scrub and nothing
  else.** A token in a query string that nobody registered lands in the file —
  `redact()` cannot name it, because nothing renders it, and the harvest that
  turns redaction into text masking therefore never sees it. If your demo
  navigates through a magic link, a `?token=`, or a session id in a path,
  `register_secret()` it: that is the author's job and there is no mechanism
  here that does it for you
  ([issue #50](https://github.com/rogvid/skills/issues/50)).
- **Accessible names are still names.** `alt` and `title` become an element's
  accessible name, so they are in `aria` by design even though they are
  stripped from `html`. That is what a screen-reader user perceives; if it is a
  secret, redact the element.
- **Only exact substrings match**, modulo whitespace — the same limit
  `register_secret()` has. A value rendered with a soft hyphen, or split across
  two elements that are not both redacted, is a different string.
- **The ARIA snapshot needs Playwright ≥ 1.49.** Older versions get a null
  `aria` and an `aria_format` saying so, rather than a fallback nobody tests.

**Evidence is not committed.** Gitignore `evidence/`. It is a byproduct
regenerated on every take, it churns completely on each re-record, and — the
reason that matters — it is greppable plaintext of a real app's DOM, which is
exactly the thing a git history should not carry permanently and cannot be
made to forget afterwards. `timeline.json` and `timeline.md` stay the
committed, diffable record of what the demo showed; evidence is for the
reviewer looking at *this* take, alongside `demo.mp4`, which is not committed
either.

### Naming, and merged segments

A beat's `index` is its position in **its own take**, so two segments of one
demo both start at 0. Two things make that a non-event: a segment's evidence
carries the segment in its filename
(`evidence/part1.seg.beat-03.json`, mirroring `<segment>.seg.timeline.json`),
and the path is written **onto the beat** as `evidence` rather than derived
from `index` by whoever reads the log. Read the pointer, never rebuild it —
then a merge that renumbers beats has only to carry the string across, and
every evidence file names its own `segment` and `index` internally anyway.

## Failing the take on a broken app

**A demo that looks perfect while the app throws `TypeError` on every render
passes any review that only watches pixels.** This is the failure mode with no
visual signature at all: the captions are right, the stills are pretty, the
video is convincing, and the feature is broken. So every take also watches the
app itself and writes what it saw into `timeline.json` as `issues`:

| `kind` | What it is | Fatal under `strict=True`? |
|---|---|---|
| `console_error` | `console.error(…)` from the page | yes |
| `console_warning` | `console.warn(…)` from the page | no |
| `page_error` | an uncaught exception or unhandled rejection | yes |
| `request_failed` | a request that never got a response | no |
| `http_error` | a response with status ≥ 400 (3xx redirects are normal) | no |
| `nonzero_exit` | a `TerminalRecorder` `run()` whose command failed | yes |

Each issue is **attributed to the beat that was running when it fired** —
`beat` (an index into `beats`), plus the beat's `verb` and `caption` copied
alongside so the list reads on its own. "The take broke" is not a bug report;
"the take broke during `click('#refresh')`, under the caption *Refresh reloads
it*" is. `timeline.md` gets an **Issues** section saying the same thing in
prose, so a reviewer reading the PR sees it without opening the JSON.

**`beat` is `null` when no beat can honestly claim the problem**, and that is a
real answer rather than a gap. Playwright hands the recorder page events only
while it is being called, so the naive reading — blame the most recently
started beat — invents attributions in both directions: an error thrown during
a three-second `hold()` would be blamed on the beat *after* the hold and quoted
under a caption that had not appeared yet. Holds therefore pump events as they
wait, and anything still ambiguous — a problem surfacing between two verbs,
or after a long stretch where nothing reached Playwright — records `beat: null`
instead of a confident guess. Trust `beat`; `t` is when the problem was
*observed*, which can lag when it happened.

Nothing has to be asked for: **a summary prints on stderr at the end of every
take**, listing each problem and its beat, or saying plainly that there were
none.

`TerminalRecorder.run()` additionally records `exit_code` on its beat, and
`timeline.md` gets an `exit` column when any beat has one. The shell reports
the status through an invisible escape in its own prompt, carrying `$?` and
bash's command number, which the recorder strips before the terminal ever
renders it — so the status is known without typing `echo $?` into the demo.

The command number is what makes it trustworthy. The shell prints a prompt at
startup before any command, and reprints one for an empty Enter or a Ctrl-C, and
each of those reports a status belonging to no command; the number is what tells
them apart. Two `run()`s with no wait between them queue, and each status
reaches the beat that typed it, because the shell still runs them in order.

An `exit_code` is either right or `null`, never wrong. It is `null` when the
status never arrived: a `run()` the storyboard never waited on and the take
ended, a program still running at the end, or a shell that does not expand `$?`
in its prompt (zsh needs `PROMPT_SUBST`; only bash is exercised). Pair every
`run()` with `wait_for_prompt()` and it is always there.

### `strict=True`

```python
with Recorder(Path(__file__).parent, strict=True) as rec:
    ...
```

`Recorder(..., strict=True)` / `TerminalRecorder(..., strict=True)` (or
`DEMO_VIDEO_STRICT=1`) makes the take **raise `StrictTakeFailed` on exit** if it
recorded any fatal issue, naming the kind, the beat and the message for each.
Default is off, so a take that would otherwise have shipped silently still
records everything and still succeeds.

It fails *after* writing demo.mp4, the stills and the timeline. A broken take
is exactly the one somebody wants to look at, so failing it must not also
destroy the evidence.

Strict means strict. Chromium writes its own `Failed to load resource: …` to
the console for anything that 404s or refuses a connection, and that is a real
console error — so a missing favicon fails a strict take too. Use it when you
want the demo to be a check that the app works, not when you want it to be
lenient.

**Timestamps are wall-clock offsets, and the video can drift under them.**
Chromium's screencast emits a frame when the page paints and nothing pads the
gap when it does not, so an idle stretch costs the recording ~0.6 s of wall
time and every frame after it lands that much earlier than the timestamps say.
The beat log itself is good to ~100–200 ms of the frame it describes; the drift
is the capture's, and it shows up as `duration` being shorter than the take
really was. Tracked in [issue #18](https://github.com/rogvid/skills/issues/18)
— read it before relying on a beat timestamp to extract a frame.

## Pacing and perception

A demo is watched by a human, and human vision has fixed limits. Pace to
those limits, not to how fast the machine can drive the app. The defaults
below are encoded in the recorder; the point is to *not fight them*.

- **A change needs ~1.5 s to register.** After something appears (a spotlight,
  a new panel), the eye takes a saccade (~200 ms) plus a fixation to notice and
  recognise it. Anything shown for under a second reads as a flicker — the
  viewer sees *that* something flashed, not *what*. So emphasis has a floor of
  ~1.5 s (`hold()`'s `min_s`). A spotlight you clear a moment after setting it
  is the classic mistake.
- **Reading takes time too.** People read burned-in captions at roughly
  3–4 words per second, plus ~0.5 s to start. A caption must stay up long
  enough to read *and* watch at once — with narration off, captions hold for
  about `0.6 + 0.34·words` seconds automatically.
- **Sync emphasis to the sentence.** With narration on, the spoken clause is
  already paced for comprehension — so keep the highlight up for the whole
  line. The pattern:

  ```python
  rec.caption("It points the eye at exactly what matters,")
  rec.spotlight("#kpi")
  rec.hold()          # stays highlighted until the line finishes speaking
  rec.spotlight()     # then clear
  ```

  `hold()` waits for the current narration line to finish (or `min_s` when
  silent). Without it, a short `pause()` can clear the highlight while the
  narrator is still talking about it — exactly the flicker above.
- **One salient change at a time.** The eye can track one moving/appearing
  thing. Don't navigate, spotlight, and type in the same instant; sequence
  them, caption first (it tells the eye where to look), then the visual.
- **Never dwell on a static frame with a stale caption** (see Common mistakes)
  — during unavoidable waits, tour what's on screen or swap the caption.

## Terminal demos (CLI / TUI)

`TerminalRecorder` records a **real terminal program** — a CLI, an
interactive prompt/REPL, or a full-screen TUI. It launches the program
under a PTY and renders it with an in-browser terminal (vendored xterm.js),
so it records to demo.mp4 through the same headless Chromium the web
recorder uses. **Everything shared works identically**: `caption`,
`interlude`, `pause`, `shot`, speech/narration, segments + `stitch`. Only
the interaction verbs differ. **Unix-only** (PTY). No new install
prerequisites beyond the web path (`uv` + `ffmpeg` + Chromium).

The recorder launches an interactive shell whose prompt (`PS1`) it sets to
`terminal_prompt` (default `❯ `), giving `wait_for_prompt()` a reliable
marker. The recording size drives the terminal grid; the resulting
cols/rows are pushed to the PTY so TUIs lay out correctly (`font_size`
tunes how much fits — default 15 px).

Storyboard — identical template as above, swapping the import and verbs:

```python
from demo_recording import TerminalRecorder  # noqa: E402

with TerminalRecorder(Path(__file__).parent) as rec:
    rec.caption("Scaffold a project in one command.")
    rec.run("mytool init my-app")       # types visibly, presses Enter
    rec.wait_for_prompt()               # waits for the command to finish
    rec.shot("01-done")

    rec.caption("Answer the prompts it asks.")
    rec.run("mytool config")
    rec.wait_for_text(r"Environment\?")  # a regex, matched per screen line
    rec.send("production")               # types a response + Enter

    rec.caption("Drive a full-screen TUI with keys.")
    rec.run("mytool dashboard")
    rec.wait_for_text(r"CPU|MEM")
    rec.key("Down", "Down", "Enter")     # arrows, Enter, Tab, "q", "C-c", …
    rec.shot("02-dashboard")
    rec.key("q")
    rec.wait_for_prompt()
```

### TerminalRecorder verbs (plus the shared ones above)

| Verb | Use |
|---|---|
| `run(command)` | Type a shell command visibly, press Enter. Pair with `wait_for_prompt()`. |
| `send(text, enter=True)` | Type a response to the running program (answer a prompt, a REPL expression). Takes a `Secret(v)` for a password: the value is registered, typed for real, and the terminal's echo of it comes back masked. |
| `key(*names)` | Send keys: `"Up" "Down" "Left" "Right" "Enter" "Tab" "Escape" "Home" "End" "PageUp" "PageDown" "Backspace" "Delete" "Space"`, `"C-<letter>"` (e.g. `"C-c"`), or any single literal char (`"q"`, `"/"`). |
| `wait_for_prompt(timeout_s=60)` | Wait until the shell prompt returns — i.e. the command finished. |
| `wait_for_text(pattern, timeout_s=60)` | **The universal sync.** Wait until the rendered screen (visible text + scrollback, ANSI-stripped) matches `pattern`; `^`/`$` anchor to screen lines. |
| `rec.page` | The live Playwright page (escape hatch). `rec._write(str)` sends raw bytes to the PTY. |

### Driving the four patterns

- **Non-interactive CLI:** `run(cmd)` → `wait_for_prompt()`.
- **Interactive prompt / REPL:** `run(cmd)` → `wait_for_text(prompt)` →
  `send(answer)` → repeat.
- **Full-screen TUI:** `key(...)` → `wait_for_text(a marker on the new
  screen)` or `pause(...)` → `shot(...)`; quit, then `wait_for_prompt()`.
- **Long-running / streaming:** `run(server)` → `wait_for_text("Listening…")`,
  tour the output; skip big waits with the same `segment=` + `interlude` +
  `stitch` machinery the web path uses. Output streams into the recording
  live, so you see it scroll.

### Terminal gotchas

- **Sync on the *rendered screen*, not a guessed delay.** `wait_for_text`
  reads what xterm.js actually displays (scrollback included), so it
  survives TUIs that repaint continuously and never print a clean "done".
- **`wait_for_prompt` keys on an *idle* prompt** — the last screen line
  being exactly the prompt marker. Programs that clear the screen (`top`,
  `clear`, most TUIs) erase earlier prompt lines, which is why counting
  prompts does not work and this does.
- **Typing is real echo.** `run`/`send` write to the PTY; the terminal
  echoes each key, so it appears typed. Programs that turn echo off
  (password prompts, raw-mode TUIs) correctly show nothing.
- **A secret a command prints is masked on the way in.** `register_secret()`
  before the command runs, and its output — plus the screen text
  `wait_for_text()` reads — comes back `[redacted]`. `run()` and `send()`
  refuse a command line holding a registered value outright. Read
  **Redacting secrets → Redaction in a terminal demo**, and the list of what
  it does not cover, before trusting it.
- **Keep the prompt distinctive.** The default `❯ ` rarely collides with
  output. If you theme it via `terminal_prompt`, keep it a string unlikely
  to appear as the last line of a command's output.
- **A program that never returns** (a server) needs `wait_for_text`, not
  `wait_for_prompt` — there is no prompt until it exits.
- **Pagers are disabled by default.** A real PTY makes `git`, `man`,
  `systemctl`, etc. pipe through `less`, which holds the terminal and hangs
  `wait_for_prompt`. The recorder sets `PAGER`/`GIT_PAGER`/`SYSTEMD_PAGER` to
  `cat` so commands print inline. To demo a pager on purpose, launch it and
  drive it with `key` (`"Space"`, `"q"`).

## Process

1. **Pick a demo story that is deterministic, and know where the slow
   parts are.** Prefer flows the app completes on its own in seconds. Seed
   needed state *before* recording starts. The recorder pins the browser's
   timezone and locale for you, and will freeze its clock if you ask (see
   **Determinism**); the app's own randomness and its server data are yours to
   pin down. If the story includes minutes
   of real background work, don't record the wait — record **segments**:
   `Recorder(out_dir, segment="part1")`, poll between segments until the
   work is done, open the next segment with `rec.interlude("…a few minutes
   later…")` on `about:blank` before navigating, and `stitch()` into
   demo.mp4. `stitch()` also merges the segments' beat logs into one
   `timeline.json` / `timeline.md`, so a segmented demo commits the same two
   files as any other — you do not have to do anything for that.
2. **Write `record.py`** in the demo folder as a short storyboard. Capture
   a still (`rec.shot("NN-name")`) at each moment a written guide would
   narrate. Make retakes idempotent — clean up state earlier takes created,
   and vary generated content if the app dedupes identical inputs.
   - **Show, don't assert.** An event the script triggers outside the
     browser (dropping a file, calling an API) is invisible — put it on
     screen with `rec.terminal(...)`, perform the real action right after,
     then `rec.terminal_close()` stamps ✓ and fades it.
   - **Point at the evidence.** Set the caption first, then
     `rec.spotlight(selector)` on the element it talks about, so viewers
     never see a highlight belonging to the previous line.
3. **Caption every beat.** A fresh caption before each thing the viewer
   should understand, a new one after any navigation, `caption("")` to end
   clean. On a full page load the caption dies with the DOM; in an SPA
   (hash routing) it *survives* into the next view and reads as a mistimed
   line — so `caption("")` before the click that navigates, fresh caption
   after, in both cases. Rules (each earned in a fresh-eyes review round):
   - A caption may only claim what is visible in the frame. Don't promise
     an action the demo never performs — scope the words to what's shown,
     or show it.
   - Don't hardcode values the app computes (percentages, counts) — they
     change between takes.
   - Text you put on screen must match the UI's own wording verbatim, or
     reviewers read it as two different things.
   - During waits longer than ~3 s, never leave a static screen with a
     stale caption. Best: spend the wait touring what's already on screen;
     failing that, swap in a caption saying what is being waited for.
   - End with a closing line that sums up the story, then `caption("")`.
4. **Record:** `uv run <demo folder>/record.py` (with the project's env
   loaded if it configures DEMO_VIDEO_* or the ElevenLabs key:
   `set -a; source .env; set +a`). Aim for 30–60 s.
5. **Verify by looking, not by exit code:** read the `images/*.png` stills
   to confirm the story is actually visible; check `ffprobe` duration. Read
   `timeline.md` too — it is the take's own account of what ran and when, so
   a beat that fired at the wrong moment or a caption that never changed
   shows up there without decoding a frame. **Read the problem summary the
   recorder prints on stderr**, and the Issues section of `timeline.md`: a
   demo of an app throwing on every render looks exactly like a demo of a
   working one, and this is the only place it shows (see **Failing the take
   on a broken app**). To check what a *specific* frame showed without
   decoding it, open the beat's `evidence` file — that is what it is for.
6. **Fresh-agent review (required).** You cannot watch the video, and you
   know too much anyway — have a context-free agent watch it for you. The
   recorder has already written what they need: `frames/`, one PNG per
   beat, and `frames/frames.md`, which embeds them in order. **Hand them
   `frames/frames.md`.**

   Give them the pictures and nothing else — no storyboard, no feature
   name, no captions. `frames.md` is built that way on purpose (see
   **Review frames** above): a `click('#refresh')` in the margin answers
   the question you are asking before they look at anything.

   A tmpdir, or `frames/` beside `demo.mp4` if the reviewer needs a stable
   path. Either way they are working files — `frames/` is gitignored for the
   same reason `evidence/` is, and for the same reason the mp4 they came out
   of is.

   Dispatch a subagent told NOTHING about the feature (any context-free
   reviewer works: a fresh session or process fed only `frames/`, if the
   harness has no subagents): read the frames in order; reply with
   (1) NARRATION — the story as understood purely from the frames,
   (2) CONFUSIONS — anything unclear, unreadable, or contradictory, and
   (3) VERDICT — CLEAR or UNCLEAR with the reason, plus whether the demo
   is CONVINCING: did they see evidence of the claims on screen, or take
   the captions' word for it. If the narration misses the intended story
   or the verdict is UNCLEAR, fix the storyboard and re-record. Each round
   needs a NEW subagent — the previous one is no longer fresh. Ship only
   on CLEAR with the headline claim evidenced on screen. Reviewers
   converge in ~2 rounds; cap at 3 and surface remaining findings to the
   user instead of looping. Findings that need a different feature demoed
   are future demos, not blockers.
7. **Write `guide.md`** (when a written guide is wanted): what the feature
   is, how to use it step by step — each step referencing a still —
   opening with the strongest still. Don't link `demo.mp4` from it: the
   video is not committed (step 8), so a repo-relative link to it is dead
   in a fresh clone. End with a "Re-recording this demo" section giving the
   exact command — that is how a reader gets the video.
8. **Commit the storyboard, not the media.** `record.py`, `guide.md`, the
   `images/*.png` stills, and `timeline.json` / `timeline.md` go into git —
   they are small, diffable, and between them they say what the demo showed
   without anyone having to watch it. For a **segmented** demo those two are
   the merged pair `stitch()` wrote next to `demo.mp4`; the per-segment
   `*.seg.timeline.*` are working files that go with `*.seg.mp4`, and
   `stitch()` removes them for you unless you asked to keep the parts.
   **`demo.mp4` does not.** A video is
   stale by the next change to the feature and bloats history permanently,
   and anyone with the skill installed can regenerate it with
   `uv run <demo folder>/record.py`. Gitignore `demo.mp4`, `*.seg.mp4`
   segment parts, `*.seg.timeline.*`, `<demo folder>/frames/` (regenerated
   from the two by `beat_frames(out_dir)` — anchor the pattern to the demo
   folder rather than writing a bare `frames/`, which matches a directory
   of that name anywhere in the repo), `.tts/` narration caches, and
   `<demo folder>/evidence/` — the last two are **working files**, inputs to
   a review that happens once, and the file table at the top of this skill
   says so in the same column that says the mp4 is not committed.

   **`evidence/` is not committed either, and for a stronger reason than the
   mp4.** It is regenerated wholesale on every take, so it would churn
   completely on each re-record and diff as noise — but the deciding argument
   is that it is greppable plaintext of a real app's DOM and terminal, which
   is precisely what a git history should not carry permanently and cannot be
   made to forget afterwards. It is a per-take artifact for the reviewer
   looking at *this* recording, like the mp4. `timeline.md` is what a reader
   six months from now gets.

   To put the demo in front of a reviewer, drag `demo.mp4` into a PR
   comment box — GitHub hosts it and renders a real player. That upload has
   no public API, so it stays a manual step.

   The exception is a video that is itself permanent documentation: a
   hand-authored showcase for a stable feature, recorded once and not
   per-change. Commit that one deliberately, knowing the repo carries it
   forever.

## Common mistakes

- **Dead air.** A demo waiting on the app with a static screen and a stale
  caption reads as a pre-loaded screenshot. Swap captions during the wait.
- **An ending that contradicts the story.** If the final frame shows
  something that needs insider context (an empty state, a prompt asking
  what to do next), caption it away or end elsewhere.
- **Waiting on mechanism internals.** Don't `wait_for` text that depends
  on *which* internal path produced the result — wait on stable outcomes:
  the row exists, the link appears, "done".
- **Recording against a cold page.** `goto` waits for networkidle (and
  gives up after 10 s on apps that poll), so `wait_for` a concrete
  element and `pause` before the first shot, or the video opens on a
  loading flash.
- **The caption bar covers the bottom third.** Scroll the element being
  narrated to the *center* of the viewport (`scroll_to` does this) and
  never narrate something sitting at the bottom edge.
- **Scripting oversized asks to in-app agents.** If the app has chat or
  agent turns with a budget, one big scripted message can exhaust it and
  waste the take — script 1–2 steps per message.
- **Layout shifts strand the cursor.** When the app inserts rows/cards
  mid-recording, elements move but the cursor doesn't — re-`move_to` the
  target after any wait that can reflow the page.
- **Recording real data and planning to blur it later.** There is no later: the
  frame is captured the moment it paints, and a published video leaks forever.
  Decide what must not appear *before* the first `goto()` — see **Redacting
  secrets**, and read what it does not cover.
- **Embedding video in markdown.** Repo-relative mp4s don't play inline in
  rendered markdown, and `demo.mp4` isn't committed anyway — open the guide
  with a still and point at the re-record command instead. GitHub plays only
  video it hosts itself, so an mp4 linked from anywhere else renders as a
  bare link, not a player.

## Sharing this skill

The skill is self-contained: this file, the `helpers/demo_recording/`
package, the vendored `helpers/assets/xterm/` terminal assets, and
`README.md`. Install it with the `skills` CLI — into the current project:

```sh
npx skills add https://github.com/rogvid/skills/tree/main/skills/demo-video
```

add `-g` to install it globally (`~/`) so it is available everywhere. Then run
Setup in the project where you record. The skill is not tied to
the `.claude/skills/` convention: each storyboard embeds the skill's
location as written at creation time, and `DEMO_VIDEO_SKILL_DIR`
overrides it — so `.agents/` folders, global installs, or any other
harness layout work the same way. Re-recording a committed storyboard
requires the skill to be installed — that is the one setup step a fresh
clone needs.
