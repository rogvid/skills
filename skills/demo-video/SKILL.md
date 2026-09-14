---
name: demo-video
description: Use when a web app, CLI, or TUI needs a screen-recorded demo video and/or an illustrated step-by-step guide — "record a demo of X", "make a video walkthrough", "show the feature in action", "demo my command-line tool", "document this with a recording". Records web apps (via Playwright) and terminal programs (CLIs, REPLs, full-screen TUIs, via an in-browser terminal); needs Playwright and ffmpeg.
---

# demo-video — self-explanatory recorded demos of a web app or terminal program

## What this records, and what it does not defend against

**demo-video records fixtures and example data.** Read this before pointing it
at anything.

- The tool has **no masking, no scrubbing and no redaction**. It does not hide
  anything that reaches the screen, and it does not try to.
- A value written into a storyboard, a caption or a timeline is an **example**.
  A string that would be a credential in production is not one in a fixture,
  and nothing needs to hide it.
- **If a real credential can appear in the app you are recording, do not record
  it.** That is the whole of the guidance. There is no setting, no verb and no
  flag that makes it safe.
- The corollary, stated plainly because it is a design decision and not an
  omission: **a demo that needs a real secret to be meaningful is a demo that
  cannot be made.** That is a constraint on what gets demoed. It is not a gap
  waiting to be filled, and a future version will not fill it.

This is a scope limit, not a security property. Nothing here is a control, so
nothing here can be relied on as one — which is exactly why the machinery that
used to look like one was removed rather than improved. A masking system that
works almost always is worse than none, because it is what persuades somebody
it is safe to point the recorder at production. The absence is the stronger
guarantee ([#138](https://github.com/rogvid/skills/issues/138)).

**The recorder classifies its target at construction, in CI and on your
machine, before a browser opens** — and it classifies exactly two strings.
`Recorder` classifies the `base_url` it resolved; *both* recorders classify
`DEMO_VIDEO_BASE_URL`, which is the only target a `TerminalRecorder` has and is
checked **even when a storyboard passes a loopback `base_url`** — a shell
exporting production and a storyboard saying otherwise is refused rather than
quietly resolved. Loopback passes, a private host needs `allow_private=True`, a
public one is refused and no option permits it. CI runs the same classifier
over `extra-env` and each storyboard's source ([reference/ci.md](reference/ci.md)).

**`goto()` classifies its own argument too**, before Playwright navigates:
`goto("https://app.acme.com/")` is refused, and so is a relative path that
reaches another host through userinfo, `goto("@app.acme.com/")`. **`rec.page`
is not, and never will be** — it is the escape hatch, so `rec.page.goto(...)`,
the app's own `fetch`, and any URL you compute reach the network unexamined.
This is a classifier over configuration and source, not an egress control.

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
the web recorder; the **Terminal demos** section below covers what differs,
and is **Unix-only** because it uses a PTY.

Both record into the **same framed window on a soft pastel background** (rounded
window, title bar, traffic lights): one recorder-owned chrome whose content slot
holds the web app in an iframe at true pixel size, or the terminal's xterm.js
screen, with the caption a floating pill riding the app rect's bottom edge
(`caption_overlay=False` restores the reserved band below the app). The page is
the finished picture — one encode per take, and `shot()` stills match the video.
`rec.page` is the framed page; `rec.app` is the app's document. Two edges:
an app answering `X-Frame-Options`/CSP `frame-ancestors` refuses the take
by name, and the dot is verb-driven — raw `rec.page.mouse` never moves it.

Each demo gets one folder (suggested: `docs/guides/<YYYY-MM-DD>-<slug>/`):

**Committed** — small, diffable, and between them a full account of what the
demo showed without anyone watching it:

| File | What it is |
|---|---|
| `record.py` | The storyboard that produced the media (re-runnable) |
| `images/*.png` | Stills captured at key moments |
| `timeline.json` | The beat log — every verb, when it ran, what caption was up. For a segmented demo, the merged one `stitch()` writes |
| `timeline.md` | The same log rendered for humans, stills embedded |
| `guide.md` | Optional written guide embedding the stills |

**Not committed** — every one of them describes a single run, and the next run
rewrites it: `demo.mp4` (regenerate it, or attach it to the PR),
`evidence/beat-NN.json` (what was on screen at each beat, in text — greppable
plaintext of a real app's DOM), `frames/` (the review sheet;
`beat_frames(out_dir)` regenerates it), and after a take that did not finish,
`failure/` and `demo-video-FAILED.md`
([reference/failures.md](reference/failures.md)).

The storyboard is the durable artifact, not the video
([#50](https://github.com/rogvid/skills/issues/50)).
`scripts/demo-gitignore` writes the patterns — Process step 8.

## What this does not do

The section at the top of this file is about what you must not point the
recorder at. This one is about what it will not notice once you have — stated
so you can write a storyboard around the boundary instead of discovering it in
review. Each limit below is measured, and the measurements, with the issue
behind every one, are in [reference/limits.md](reference/limits.md).

- **It will not tell you a card was left up.** A held picture is reported only
  when a verb that *acts on the app* ran while it was held — so take cards down
  explicitly, and keep captions to one line.
- **A frame is aimed at a beat, not stamped with one.** Chromium stamps frames
  with the host's wall clock and the beat log uses a monotonic one, so on a
  stepping host an event lands earlier in `demo.mp4` than the log says.
  `timeline.json`'s `capture_clock` records each step.
- **Sixty seconds buys about twenty screens.** Roughly one new screen every 3 s
  at the pacing floors below. A feature spanning two surfaces does not fit the
  30–60 s target, and the honest answers are a longer video or two demos, not
  faster captions.
- **A demo of an error path records a problem.** A non-zero exit is logged as an
  issue and is fatal under `strict=True`, with no way to say it was the point.
  Leave strict off for that demo, and say in the pull request which recorded
  issue is the demo's subject.
- **A stitched demo's issue attribution is unproven.** An issue recorded in
  segment two can name a beat of segment one, and no take exercises the
  re-pointing. Check it against the parts before handing them to a reviewer.
- **A fork's pull request gets no block, and its demo job goes red** even when
  the take succeeded. The block is printed to the job log; read it there.

## Reference — read these when you reach them, not before

This file is what you need to write and run a storyboard. Everything below is
the argued detail behind one part of it, and each is linked again at the point
where it applies. **Read a file when the work touches its subject** — do not
read them all up front, and do not skip one the text tells you to open.

| File | Read it when |
|---|---|
| [reference/verbs.md](reference/verbs.md) | When a verb's one line in the table below is not enough — the same list with every caveat attached, each one there because a take shipped wrong without it |
| [reference/configuration.md](reference/configuration.md) | When a take needs a parameter the short Configuration table does not name — window size and title, the opening and closing cards, caption placement, colours, clock and locale, the terminal's shell and font, the narration voice |
| [reference/limits.md](reference/limits.md) | Before planning a demo, when two of a take's artifacts seem to contradict each other, or before reading a green run as coverage — every limit above, with its measurement |
| [reference/determinism.md](reference/determinism.md) | Before `deterministic=True`. A frozen clock changes what an app does, and usually does it silently |
| [reference/timeline.md](reference/timeline.md) | When reading `timeline.json`/`timeline.md`, when a take warns about its `content`, or when consuming the beat log as a contract |
| [reference/review.md](reference/review.md) | At Process step 6 — handing a take to a reviewing agent or a person, reading `evidence/`, or recording against a ticket with `criteria=` |
| [reference/failures.md](reference/failures.md) | When a take raises, when `strict=True` refuses one, or when `failure/` appears beside the demo |
| [reference/terminal.md](reference/terminal.md) | When writing a `TerminalRecorder` storyboard — the full verb table, the four patterns, the gotchas |
| [reference/narration.md](reference/narration.md) | When `ELEVENLABS_API_KEY` is set and captions will be spoken |
| [reference/stills.md](reference/stills.md) | When you want the pictures now and the video later — `stills_only=True` runs the same storyboard in seconds |
| [reference/ci.md](reference/ci.md) | When wiring the recording into GitHub Actions so branches record themselves |

## Setup (once per project)

1. **Check for `uv` first**: run `uv --version`; if missing, run `bash <this
   skill's directory>/ensure.sh` — it installs uv and restores the exec bits
   on `scripts/`, and every path in this file is relative to the skill's own
   directory, not your cwd. Storyboards are single-file uv scripts and cannot
   run without uv; do not fall back to pip or a project venv.
2. **`ffmpeg`** (which includes `ffprobe`) must be on PATH. **Chromium**
   once per machine: `uv run --with playwright playwright install chromium`
   (on a fresh Linux box add `--with-deps` for system libraries). If a
   later run resolves a newer Playwright that wants a newer browser
   build, re-run this command. Playwright **1.49 or newer** for per-beat
   evidence — `locator.aria_snapshot()` arrived there, and the older
   `page.accessibility` API it replaced has since been removed.
3. **Learn how the app runs** (dev server command, port, how to build the
   frontend, how to seed data). **Read `<project root>/.demo-video/context.md`
   first** — a previous demo session may have written down exactly this, and
   re-deriving it is the heaviest part of a first demo. If it does not exist,
   inspect as usual and then **write it**: how to start the server and on
   which port, how to seed or reset data, auth quirks, selector conventions,
   anything a fresh session would otherwise have to rediscover. Keep it short
   and factual, and commit it — it is project knowledge, not session state.
   Reuse an already-running server.
4. **Set project defaults in env** (see Configuration) or pass them as
   `Recorder(...)` parameters per storyboard.

Nothing is copied into the project: storyboards import the recorder from this
skill's folder, so it must be installed wherever demos are re-recorded.

## Storyboard template

Each `record.py` is a self-contained uv script — PEP 723 metadata brings
Playwright without any project environment. You are writing this file,
and you know where this skill is installed (you are reading it) — so
**replace `_DEFAULT_SKILL_DIR` with that actual location**. What ships in
it is a guess at the commonest one, not a layout to assume: prefer a
repo-relative expression via `Path(__file__)` when the skill lives in the
same repo (survives clones), an absolute path otherwise.
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

# Replace with this skill's real location; DEMO_VIDEO_SKILL_DIR wins at
# runtime. To find it:  find . ~ -name demo-video -type d 2>/dev/null
_DEFAULT_SKILL_DIR = "~/.claude/skills/demo-video"
SKILL_DIR = Path(
    os.environ.get("DEMO_VIDEO_SKILL_DIR") or _DEFAULT_SKILL_DIR
).expanduser()
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
clean. **The Sets column names the parameter behind each variable** — for
three it is not the variable lowercased, so do not infer it; all three are in
the reference table below.

These are the ones that decide what a take *is*:

| Variable | Sets (parameter — what it does) | Default |
|---|---|---|
| `DEMO_VIDEO_OUT_DIR` | `out_dir` — where demo files land | — (required one way or the other) |
| `DEMO_VIDEO_BASE_URL` | `base_url` — app under demo. Classified before the browser opens; a public host is refused | `http://localhost:8000` |
| `DEMO_VIDEO_ALLOW_PRIVATE` | `allow_private` — permit a private/internal target (`1`/`0`). There is no equivalent for a public one | off |
| `DEMO_VIDEO_PRESET` | `preset` — quality preset, `"high"` or `"quick"`; see **Quality presets** below | `high` |
| `DEMO_VIDEO_PACE` | `pace` — multiplier over the holds the recorder computes. Durations the storyboard writes itself are never touched. See **Pacing and perception** | `1.0` |
| `DEMO_VIDEO_STILLS_ONLY` | `stills_only` — run the storyboard for its `shot()` pictures and record no video (`1`/`0`). Pacing zeroed, narration off; `timeline.json` says `mode: "stills"` so nothing reads it as a take — [reference/stills.md](reference/stills.md) | off |
| `DEMO_VIDEO_STRICT` | `strict` — fail the take on console errors / non-zero exits (`1`/`0`) | off |
| `DEMO_VIDEO_DETERMINISTIC` | `deterministic` — freeze the page clock and flatten motion (`1`/`0`) — **read [reference/determinism.md](reference/determinism.md) first** | **off** |
| `DEMO_VIDEO_SPEECH` | `speech` — force narration on/off (`1`/`0`). **`speech=False` records silently even with a key set**; forcing it *on* without a key refuses the take | auto by API key |
| `DEMO_VIDEO_EVIDENCE` | `evidence` — write `evidence/beat-NN.json` per beat (`1`/`0`) — see [reference/review.md](reference/review.md) | **on** |
| `DEMO_VIDEO_SKILL_DIR` | *no parameter* — where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | *no parameter* — enables speech narration | off |

**The other seventeen are in
[reference/configuration.md](reference/configuration.md)**, with this table
repeated in full: window size and title, the opening and closing cards, caption
placement, the accent colour, the frozen clock, timezone and locale, the
terminal's shell, prompt, title and font size, and the narration voice, model
and stability. Open it when a take needs one; the names are not guessable.

The parameters with **no** env var are per-storyboard by nature: `segment`,
`criteria` and `ticket` on both recorders, plus `TerminalRecorder`'s
`interlude`, `interlude_hold` and `type_delay_ms`.

### Quality presets

`preset` picks a named bundle of defaults so a take can say what it is for
instead of tuning knobs — explicit parameters and `DEMO_VIDEO_*` env vars
still win over whatever the preset says:

- **`high`** (the default) — the settings table above exactly: 1080p,
  narration on when a key is present, `pace` 1.0. For finished demos and
  anything shared with others. "Make a high quality demo of X" means this,
  which means it means the plain defaults.
- **`quick`** — 720p, `pace` 0.6, narration off (no TTS round trips, so it
  is also the fast and free one). For a cheap watchable proof: a code-review
  demonstration, an issue comment, "a quick demo proving B".

`Recorder(out_dir, preset="quick")` or `DEMO_VIDEO_PRESET=quick`.

## Recorder API (storyboard verbs)

`Recorder(out_dir, base_url=..., segment=None, strict=False, ...)` as a context
manager — the `...` is the Configuration table above, which names every
parameter. Exiting the `with` converts the recording to mp4 and writes the beat
log. A storyboard that *raises* gets the same treatment plus a `failure/` dump.
`strict=True` refuses a take that recorded a console error, an uncaught
exception, or a non-zero exit. Both are
[reference/failures.md](reference/failures.md).

This table is the index — every verb, and enough to write an ordinary
storyboard. **[reference/verbs.md](reference/verbs.md) is the same list with
the caveats attached**, and every caveat in it is there because a take shipped
wrong without it. Open it when a verb here needs more than its line, and
before using `spotlight`, `interlude` or `rec.page`, which carry the three that
bite hardest.

| Verb | Use |
|---|---|
| `goto(path)` | Navigate (relative to base_url); waits for networkidle, but gives up after 10 s for apps that poll. Classifies its own argument before navigating |
| `pause(s)` / `shot(name)` | Hold the frame / capture `images/<name>.png` |
| `caption(text)` | Narrator line in the caption pill over the app's bottom edge (a reserved band with `caption_overlay=False`); `""` clears. It survives navigation, which is a footgun as much as a feature — clear it before a click that navigates, and fade it before a `spotlight()` |
| `caption(text, ac="AC-3")` / `shot(name, ac="AC-3")` | Tag this beat with the acceptance criterion it demonstrates. Needs `Recorder(criteria={...})`. `shows="unmet"` points the claim the other way — evidence the clause is **not** met. Still the author's assertion: nothing read the ticket |
| `criterion("AC-3")` | Raise a card carrying **AC-3's own declared sentence**, read out of `criteria={...}` rather than retyped, so the viewer meets the clause and then watches it happen |
| `hold(min_s=1.5)` | Keep the current frame up until the current caption's narration finishes (min `min_s`). Use after a spotlight/action so the emphasis rides the whole spoken line instead of flashing. See **Pacing and perception** below |
| `move_to` / `click` / `click_fast` / `scroll_to` | Visible cursor motion; `click_fast` for elements that re-render continuously |
| `type_into(selector, text)` | Click a field and type visibly, key by key — form demos. Types at the caret, so `clear()` first to replace rather than append |
| `clear(selector)` | Empty a field, visibly. Its own beat, because emptying a field is something the viewer watches happen |
| `press(key, hold_s=0.5)` | Press one named key wherever the focus already is — `"Enter"`, `"Escape"`, `"Tab"`, `"Control+A"`. Playwright's key names; an unknown one raises. Selector-free on purpose |
| `wait_for(selector)` | Wait for something the app does on its own — and not `rec.page.wait_for_selector`, which stamps no beat |
| `spotlight(selector)` | Ring + enlarge the element the caption discusses; `spotlight()` clears. Each interval also becomes a **camera push-in** rendered after the take. Two edges in [reference/verbs.md](reference/verbs.md): transform-positioned elements get the ring only (#398), and the push-in can shave an overlay caption |
| `terminal(cmd)` / `terminal_output(text)` / `terminal_close()` | A *decorative* on-screen terminal card for off-browser actions **inside a web demo** — a prop, not a real shell. To record an actual CLI/TUI use `TerminalRecorder` (below) |
| `interlude(text, hold=2.8, style=…)` | Bridge a jump. `style="card"` (default) is a full-screen title card for real time-skips; `style="light"` a centred label over the scene, for short transitions. **`interlude("")` fades out whatever is up, whichever style raised it.** Leave one up and only stderr and `content.warnings` will say so |
| `stitch(out_dir, [segments])` | Lossless concat of segment recordings into demo.mp4, **and** merge their beat logs into one `timeline.json` / `timeline.md` beside it |
| `act(label)` | Stamp one beat around raw `rec.page` work: `with rec.act("apply the filter"): rec.page.select_option(…)`. The block gets a frame, an evidence file and a named beat, like a verb (#344) |
| `rec.page` | The live Playwright page — the escape hatch for what the verbs don't cover (iframes, drag, hover-only menus). **Bare `rec.page` work stamps no beat: no frame is aimed at it, no evidence is written, and the review cannot see it happened.** Wrap it in `rec.act(…)` |

## Pacing and perception

A demo is watched by a human, and human vision has fixed limits. Pace to
those limits, not to how fast the machine can drive the app. The defaults
below are encoded in the recorder; the point is to *not fight them*.

- **A change needs ~1.5 s to register.** Anything shown for under a second
  reads as a flicker — the viewer sees *that* something flashed, not *what*.
  So emphasis has a floor of ~1.5 s (`hold()`'s `min_s`). A spotlight you
  clear a moment after setting it is the classic mistake.
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

- **One salient change at a time.** The eye can track one moving/appearing
  thing. Don't navigate, spotlight, and type in the same instant; sequence
  them, caption first (it tells the eye where to look), then the visual.
- **Photograph the settled state.** After a multi-step interaction (three
  checkbox clicks), `pause()` before the caption so the aggregate gets a
  frame. One run shipped frames reading "1 row selected" beside a toast
  saying "Excluded 3 rows"; both reviewers flagged the jump.

**Pace to the audience.** The floors above are for a viewer seeing the
feature cold — an executive skimming a PR is not that viewer, and a dev
pausing to inspect can always rewind. `Recorder(pace=0.5)` (or
`DEMO_VIDEO_PACE`) halves every hold the recorder *computes*, so the same
storyboard serves both audiences without being rewritten; `pace > 1`
slows down for a colder one. Two limits: below ~0.5 a caption outruns
reading speed, so shorten the lines too, not just the waits — and a
duration the storyboard writes itself (`pause(2)`, `hold(min_s=…)`,
`interlude(hold=…)`) is never scaled. A take recorded off the default
records its `pace` in `timeline.json`.

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

**Read [reference/terminal.md](reference/terminal.md) before writing one.** It
carries the full verb table (`run`, `send`, `key`, `wait_for_prompt`,
`wait_for_text`), how to open a segment on a title card, the four patterns a
terminal demo takes, and the gotchas — pagers, echo, prompts that never return.

## Process

1. **Pick a demo story that is deterministic, and know where the slow
    parts are.** Prefer flows the app completes on its own in seconds. Seed
    needed state *before* recording starts — reading
    `.demo-video/context.md` first (Setup step 3), and writing back what you
    learned if it does not exist yet. The recorder pins the browser's
   timezone and locale for you, and will freeze its clock if you ask
   ([reference/determinism.md](reference/determinism.md) — read it first);
   the app's own randomness and its server data are yours to pin down. If
   the story includes minutes of real background work, don't record the
   wait — record **segments**: `Recorder(out_dir, segment="part1")`, poll
   between segments until the work is done, open the next segment with
   `rec.interlude("…a few minutes later…")` on `about:blank` before
   navigating, and `from demo_recording import stitch` to concatenate them
   into demo.mp4. A **terminal** segment takes its opening card as
   `TerminalRecorder(interlude="…")` instead — see
   [reference/terminal.md](reference/terminal.md).

    **1.5. Smoke each state transition the storyboard will wait on** —
    outside the browser (`curl` the API path), before writing any beat. In
    the run that earned this step, the check would have surfaced a real app
    bug in 20 seconds; instead it surfaced as a 25 s Playwright timeout four
    minutes into a take.
2. **Write `record.py`** in the demo folder as a short storyboard. Capture
   a still (`rec.shot("NN-name")`) at each moment a written guide would
   narrate. Make retakes idempotent — clean up state earlier takes created,
   and vary generated content if the app dedupes identical inputs.
   - **Assert every transition you will narrate.** A caption promises what
     the app *did*, so each state change a caption will narrate gets a
     `wait_for` / `wait_for_text` / `wait_for_prompt` on its outcome — the
     row exists, the flag appears, "done". A storyboard that only performs
     actions rehearses green over a feature that does nothing: these
     assertions are the gate's teeth, and they cost one line each.
   - **Show, don't assert.** An event the script triggers outside the
     browser (dropping a file, calling an API) is invisible — put it on
     screen with `rec.terminal(...)`, perform the real action right after,
     then `rec.terminal_close()` stamps ✓ and fades it.
   - **Point at the evidence.** Set the caption first, then
     `rec.spotlight(selector)` on the element it talks about, so viewers
     never see a highlight belonging to the previous line.

2.5. **Rehearse — the gate nothing downstream passes red.** Run

    ```sh
    bash <skill dir>/ensure.sh        # once per session
    <skill dir>/scripts/demo-rehearse <demo folder>/record.py
    ```

    The same storyboard end to end in seconds — pacing zeroed, no video
    encoded — under `strict=True`, so a console error, a failed request or a
    non-zero exit fails the run and names itself. **A demo of something that
    does not work is not made**: until this exits 0, do not polish captions,
    do not set spotlights, and do not record a take. A rehearsal may rewrite
    `images/`; commit only after the real take.
3. **Caption every beat.** A fresh caption before each thing the viewer
   should understand, `caption("")` to end clean. The caption lives in the
   recorder's own document and survives every navigation — full loads and SPA
   routing alike — so a line left up across one reads as narrating the next
   view too: `caption("")` before the click that navigates, fresh caption
   after. Rules (each earned in a fresh-eyes review round):
   - A caption may only claim what is visible in the frame. Don't promise
     an action the demo never performs — scope the words to what's shown,
     or show it. The prohibition alone does not hold — captions get written
     from what the author knows, not from what the frame shows, and it
     failed twice in one storyboard that way — so audit: before step 6,
     re-read every caption against its own still from a dry take.
   - When the beat is an absence, caption only the absence ("no flag
     appears") — let a later positive case supply the threshold and the
     arithmetic. Numbers on a negative beat rest on a claim, not a frame.
   - Don't hardcode values the app computes (percentages, counts) — they
     change between takes.
   - Text you put on screen must match the UI's own wording verbatim, or
     reviewers read it as two different things.
   - During waits longer than ~3 s, never leave a static screen with a
     stale caption. Best: spend the wait touring what's already on screen;
     failing that, swap in a caption saying what is being waited for.
   - End with a closing line that sums up the story, then `caption("")`.
4. **Record** (step 2.5 rehearsed green — if it did not, stop here):
   `uv run <demo folder>/record.py` (with the project's env
   loaded if it configures DEMO_VIDEO_* or the ElevenLabs key:
   `set -a; source .env; set +a`). Aim for 30–60 s. **While the storyboard
   is still wrong, run it with `DEMO_VIDEO_STILLS_ONLY=1`** — same verbs and
   the same stills in seconds, no video ([reference/stills.md](reference/stills.md));
   record the take once the pictures are right. Rehearse again whenever the
   app changed under a committed storyboard — it is the cheap half of the
   check CI runs before recording anything (#387).
5. **Verify by looking, not by exit code:** read the `images/*.png` stills
   to confirm the story is actually visible; check `ffprobe` duration. Read
   `timeline.md` too — it is the take's own account of what ran and when, so
   a beat that fired at the wrong moment or a caption that never changed
   shows up there without decoding a frame. **Read the problem summary the
   recorder prints on stderr**, and the Issues section of `timeline.md` if it
   has one — both appear only when there was something to report, so a take
   with neither is the all-clear, not a malformed file. A
   demo of an app throwing on every render looks exactly like a demo of a
   working one, and this is the only place it shows
   ([reference/failures.md](reference/failures.md)). To check what a *specific*
   frame showed without decoding it, open the beat's `evidence` file — that is
   what it is for. What every field in `timeline.json` means, and what its
   `content` warnings do and do not claim, is
   [reference/timeline.md](reference/timeline.md).

   **5.5. Run the caption lint — for free, before anyone reads frames.**

   ```sh
   <skill dir>/scripts/demo-caption-lint <demo folder>
   ```

   Each caption's numbers and quoted UI strings, checked against the evidence
   text of its beat and its neighbours (#356) — both of the field run's
   round-1 caption contradictions were findable this way, before the blind
   round spent an agent run. It prints its three states and their meanings;
   read them there. **NOT FOUND means check the app first**: a screen not
   doing what the caption says is a bug the demo caught, and softening the
   caption launders it. Advisory — exit 0 either way, and step 6 still runs.

6. **Fresh-agent review (required).** You cannot watch the video, and you
   know too much anyway — have a context-free agent watch it for you. The
   recorder has already written what they need: `frames/`, a PNG per beat
   minus the repeats (a beat whose picture repeats an earlier frame's is
   named in the sheet instead of reprinted), and `frames/frames.md`, which
   embeds them in order. **Hand them `frames/frames.md`.** Read
   [reference/review.md](reference/review.md) first — it says how accurately a
   frame is aimed at its beat, which is what decides how much weight a
   reviewer's reading of one can carry.

   Give them the pictures and nothing else — no storyboard, no feature name,
   no captions; `frames.md` is built that way on purpose. It is a working
   file, gitignored with the mp4 it came out of (step 8).

   ```sh
   <skill dir>/scripts/demo-review <demo folder>
   ```

   prints the sheet's path, the four questions **in the words they have to be
   asked in**, and who owns which half of the reply. Dispatch a subagent told
   NOTHING about the feature and paste them; do not retype the questions from
   memory, because the clauses that read as redundant are the ones a review
   round paid for.

   Two things it says that decide what you do next. **A narration that misses
   the story, or UNCLEAR, is the storyboard's fault** — re-record, with a NEW
   subagent each round. **A CONTRADICTIONS entry may not be**: check the app,
   and if the app does not do what the caption says, the demo has caught a bug
   that goes in the pull request — softening the caption launders it
   ([reference/review.md](reference/review.md)). Ship on CLEAR; cap at 3
   rounds and surface the rest.

   **6b. Locate each clause in the frames (only when the take declared
   `criteria=`).** A *second* reader, run alongside the one above and never
   instead of it: step 6 asks whether the story is clear, this asks where each
   clause of the ticket is in the frames.

   ```sh
   scripts/demo-grade brief   <demo folder>          # → review/brief.md
   scripts/demo-grade verdict <demo folder> --reading reading.json
   ```

   Between the two, **dispatch a subagent that has seen nothing else** and give
   it `review/brief.md` and the take's `frames/` — not the storyboard, not
   `record.py`, not `timeline.md`, not the diff, not your own reasoning about
   this change. The brief is blind by construction; **nothing in the tool can
   enforce what else you hand over**, and that isolation is the whole value of
   the pass. Save the reply verbatim as `reading.json`; `verdict` writes
   `review/verdict.md`, the reading against the `ac=` tags the storyboard author
   typed. The result reaches the pull request in step 8, via `pr-block`:
   disagreements and every `cannot tell` first, agreements after them, every
   clause with its text and its committed still — the first two classes are
   what a human is being pulled in for, and the agreement rows are what lets
   them confirm the rest without opening the diff.

   The reader is asked for one clause, one frame, and not for a verdict on the
   demo: that aggregate was measured unstable here
   ([#131](https://github.com/rogvid/skills/issues/131)) where per-clause
   localisation was stable. **What this check catches and what it does not** is
   printed in `brief.md` and again in `verdict.md` — read it there, not from a
   second copy here that would go stale.
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
   **To hand a person the pictures**, `scripts/demo-shots <demo folder>`
   prints one markdown block: every `shot()` in order, under the caption that
   was up, tagged with its `ac=`. It grades nothing. **When 6b graded the
   take**, commit and push, then `scripts/demo-grade pr-block <demo folder>`
   prints a second block carrying the reader's findings. Both embed committed
   stills raw off GitHub at the head commit, and both name a file they cannot
   link rather than dropping it. Nothing under `review/` is committed.
   **`demo.mp4` does not**, and neither does anything else one run wrote. A
   video is stale by the next change to the feature and bloats history
   permanently, and anyone with the skill installed can regenerate it with
   `uv run <demo folder>/record.py`.

   ```sh
   <skill dir>/scripts/demo-gitignore <demo folder>           # the lines
   <skill dir>/scripts/demo-gitignore <demo folder> --check   # ask git
   ```

   `frames/`, `review/` and `evidence/` have to be anchored to the demo folder
   — bare, they ignore every directory of that name in the repository — and
   the command does that for you. `--check` asks git, and writes nothing.
   `evidence/` has the strongest reason of the three: it is greppable
   plaintext of a real app's DOM
   ([reference/review.md](reference/review.md)).

   To put the demo in front of a reviewer, drag `demo.mp4` into a PR
   comment box — GitHub hosts it and renders a real player. That upload has
   no public API, so it stays a manual step. To stop doing it by hand
   entirely, run the recording in the pipeline instead:
   [reference/ci.md](reference/ci.md) publishes the video as a job artifact and
   the beat table as text in one comment.

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
  gives up after 10 s on apps that poll), so `wait_for` the *content*
  element, not the page chrome — `wait_for("h1")` passes while the data is
  still on its way — and hold the opening longer than feels necessary, or
  the video opens on a featureless loading flash.
- **The caption bar covers the bottom third.** Scroll the element being
  narrated to the *center* of the viewport (`scroll_to` does this) and
  never narrate something sitting at the bottom edge.
- **Scripting oversized asks to in-app agents.** If the app has chat or
  agent turns with a budget, one big scripted message can exhaust it and
  waste the take — script 1–2 steps per message.
- **Layout shifts strand the cursor.** Elements the app inserts mid-recording
  move, the cursor does not — re-`move_to` after any reflowing wait. The dot
  draws at the first pointer verb and keeps its spot across `goto()`.
- **A blind click to dismiss an overlay.** A `mouse.click(400, 400)` landed
  on a file row, opened a dialog, and its backdrop swallowed every later
  click — dead take. Dismiss via a named neutral element, never coordinates.
- **Positional selectors.** Demos sort and filter constantly.
  `input[aria-label='Select row 5']` keeps selecting the same data row
  after a sort; anything nth-child-based silently ticks whatever moved
  into that position, and the demo lies.
- **Recording real data and planning to blur it later.** There is no later,
  and there is no blur: the frame is captured the moment it paints, nothing
  here hides anything, and a published video leaks forever. Decide what must
  not appear *before* the first `goto()` — see the top of this file.
- **Reading the beat table as proof the demo showed something.** It is proof
  the storyboard *ran*. A card left up, a modal that never closed or an app
  that stopped painting produces a complete, successful timeline over a
  recording nobody can watch. Check `content` in the same file — the field
  that describes the frames ([reference/timeline.md](reference/timeline.md)).
- **Reading `content.score` or `content.static_for` as "the app was visible".**
  Neither is a verdict: a translucent overlay left over the app *raises* the
  score, and a healthy demo narrating one screen holds as still as a covering
  card does — both measured, in [reference/limits.md](reference/limits.md).
  `warnings` is the field that answers the question: an interlude *this
  recorder* raised and you did not clear is named there by element id, an
  app's own modal by nothing.
- **Embedding video in markdown.** GitHub plays only video it hosts itself,
  and `demo.mp4` isn't committed anyway — an mp4 linked from the repo or
  anywhere else renders as a bare link, not a player. Open the guide with a
  still and point at the re-record command instead.

## Sharing this skill

The skill is self-contained: this file, the `reference/` directory it links
into, the `helpers/demo_recording/` package, `ensure.sh` at the skill root,
`scripts/demo-rehearse` (the step-2.5 gate), `scripts/demo-caption-lint`
(the step-5.5 caption check), `scripts/demo-review` (step 6's questions),
`scripts/demo-grade` (step 6b), `scripts/demo-shots` (the stills block),
`scripts/demo-gitignore` (step 8) and
`scripts/demo-target-guard` (the target classifier), the vendored `helpers/assets/xterm/` terminal assets, and
`README.md`. Install it with the `skills` CLI — into the current project:

```sh
npx skills add https://github.com/rogvid/skills/tree/main/skills/demo-video
```

add `-g` to install it globally (`~/`) so it is available everywhere. Then run
Setup in the project where you record. No layout is assumed — a storyboard
embeds the skill's location as written and `DEMO_VIDEO_SKILL_DIR` overrides it,
so `.agents/`, a global install, or any other harness works the same way.
Re-recording a committed storyboard requires the skill to be installed, which
is the one setup step a fresh clone needs.
