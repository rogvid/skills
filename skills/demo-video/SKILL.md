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
| `timeline.json` | The beat log — every verb, when it ran, what caption was up | yes |
| `timeline.md` | The same log rendered for humans, stills embedded | yes |
| `guide.md` | Optional written guide embedding the stills | yes |
| `demo.mp4` | The recording (mp4 only — gifs get too big) | **no** — regenerate it, or attach it to the PR |

The storyboard is the durable artifact, not the video. See **Commit the
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
   build, re-run this command.
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
| `DEMO_VIDEO_SPEECH` | force narration on/off (`1`/`0`) | auto by API key |
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

## Recorder API (storyboard verbs)

`Recorder(out_dir, base_url=..., segment=None, ...)` as a context manager;
mp4 conversion happens on clean exit.

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
| `interlude(text, style=…)` | Bridge a jump. `style="card"` (default) is a full-screen title card, for real time-skips; `style="light"` is a centered label over a soft scrim with the scene still visible, for short transitions. `""` fades it out. |
| `stitch(out_dir, [segments])` | Lossless concat of segment recordings into demo.mp4 |
| `rec.page` | The live Playwright page — the escape hatch for anything the verbs don't cover (iframes, keyboard shortcuts, drag) |

## The beat timeline (`timeline.json` / `timeline.md`)

Every storyboard verb is logged as a **beat** — what was done, when, and what
caption was on screen while it happened — and a clean exit writes the log next
to the media. No storyboard changes are needed; it is a byproduct of recording.

`timeline.md` is the readable version: a table of every beat, then each still
embedded under the caption it was taken during. **Commit both.** They are
small, diffable, and unlike `demo.mp4` they survive as a record of what the
demo showed after the video has been regenerated or thrown away — which is
what makes them worth reviewing in a PR. Segments write
`<segment>.seg.timeline.json` alongside `<segment>.seg.mp4`; gitignore those
with the segment media.

`timeline.json` is the machine-readable one, and a stable contract — adding a
key is fine, renaming one is not:

```json
{ "schema": 1, "generated_by": "demo-video", "recorder": "Recorder",
  "segment": null, "media": "demo.mp4", "duration": 18.04,
  "beats": [
    { "index": 4, "t_start": 3.02, "t_end": 3.06, "caption": "A small dashboard.",
      "verb": "shot", "selector": "01-dashboard",
      "still": "images/01-dashboard.png", "segment": null }
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
| `send(text, enter=True)` | Type a response to the running program (answer a prompt, a REPL expression). |
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
   needed state *before* recording starts. If the story includes minutes
   of real background work, don't record the wait — record **segments**:
   `Recorder(out_dir, segment="part1")`, poll between segments until the
   work is done, open the next segment with `rec.interlude("…a few minutes
   later…")` on `about:blank` before navigating, and `stitch()` into
   demo.mp4.
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
   shows up there without decoding a frame.
6. **Fresh-agent review (required).** You cannot watch the video, and you
   know too much anyway — have a context-free agent watch it for you:

   ```sh
   ffmpeg -y -i demo.mp4 -vf fps=1/3 <tmpdir>/frame-%02d.png
   ```

   Dispatch a subagent told NOTHING about the feature (any context-free
   reviewer works: a fresh session or process fed only the frames, if the
   harness has no subagents): read the frames in
   order; reply with (1) NARRATION — the story as understood purely from
   the frames, (2) CONFUSIONS — anything unclear, unreadable, or
   contradictory, (3) VERDICT — CLEAR or UNCLEAR with the reason, plus
   whether the demo is CONVINCING: did they see evidence of the claims on
   screen, or take the captions' word for it. If the narration misses the
   intended story or the verdict is UNCLEAR, fix the storyboard and
   re-record. Each round needs a NEW subagent — the previous one is no
   longer fresh. Ship only on CLEAR with the headline claim evidenced on
   screen. Reviewers converge in ~2 rounds; cap at 3 and surface remaining
   findings to the user instead of looping. Findings that need a different
   feature demoed are future demos, not blockers.
7. **Write `guide.md`** (when a written guide is wanted): what the feature
   is, how to use it step by step — each step referencing a still —
   opening with the strongest still. Don't link `demo.mp4` from it: the
   video is not committed (step 8), so a repo-relative link to it is dead
   in a fresh clone. End with a "Re-recording this demo" section giving the
   exact command — that is how a reader gets the video.
8. **Commit the storyboard, not the media.** `record.py`, `guide.md`, the
   `images/*.png` stills, and `timeline.json` / `timeline.md` go into git —
   they are small, diffable, and between them they say what the demo showed
   without anyone having to watch it. **`demo.mp4` does not.** A video is
   stale by the next change to the feature and bloats history permanently,
   and anyone with the skill installed can regenerate it with
   `uv run <demo folder>/record.py`. Gitignore `demo.mp4`, `*.seg.mp4`
   segment parts, `*.seg.timeline.*`, and `.tts/` narration caches.

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
