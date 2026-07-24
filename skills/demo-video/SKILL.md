---
name: demo-video
description: Use when a web app feature or flow needs a screen-recorded demo video and/or an illustrated step-by-step guide — "record a demo of X", "make a video walkthrough", "show the feature in action", "document this with a recording". Works on any web app reachable at a URL; needs Playwright and ffmpeg.
---

# demo-video — self-explanatory recorded demos of a web app

## Overview

A demo is a short mp4 that explains itself to someone with zero context —
no narration track, no insider knowledge. You never watch the video; you
*script* it as a deterministic storyboard (`record.py`), *read* the stills
it captures, and have a context-free agent *read* extracted frames to
verify the story lands. The storyboard is committed next to the media, so
anyone can re-record after the UI changes.

Each demo gets one folder (suggested: `docs/guides/<YYYY-MM-DD>-<slug>/`):

| File | What it is |
|---|---|
| `record.py` | The storyboard that produced the media (re-runnable) |
| `demo.mp4` | The recording (mp4 only — gifs get too big) |
| `images/*.png` | Stills captured at key moments |
| `guide.md` | Optional written guide embedding the stills, linking the video |

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
if not (SKILL_DIR / "helpers" / "demo_recording.py").exists():
    sys.exit(f"demo-video skill not found at {SKILL_DIR} — set DEMO_VIDEO_SKILL_DIR")
sys.path.insert(0, str(SKILL_DIR / "helpers"))
from demo_recording import Recorder  # noqa: E402

with Recorder(Path(__file__).parent) as rec:
    rec.goto("/")
    ...
```

Run it with `uv run <demo folder>/record.py`.

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
| `DEMO_VIDEO_TERMINAL_TITLE` | terminal card title | `terminal` |
| `DEMO_VIDEO_TERMINAL_PROMPT` | terminal card prompt | `$ ` |
| `DEMO_VIDEO_VIEWPORT` | recording size, `"1280x720"` | 1280×720 |
| `DEMO_VIDEO_SPEECH` | force narration on/off (`1`/`0`) | auto by API key |
| `DEMO_VIDEO_VOICE_ID` | ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SKILL_DIR` | where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | enables speech narration | off |

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
| `move_to` / `click` / `click_fast` / `scroll_to` | Visible cursor motion; `click_fast` for elements that re-render continuously |
| `type_into(selector, text)` | Click a field and type visibly, key by key — form demos (checkout, login, search) |
| `wait_for(selector)` | Wait for something the app does on its own |
| `spotlight(selector)` | Ring + enlarge the element the caption discusses; `spotlight()` clears |
| `terminal(cmd)` / `terminal_output(text)` / `terminal_close()` | On-screen terminal card for off-browser actions |
| `interlude(text)` | Full-screen card bridging skipped real-world time |
| `stitch(out_dir, [segments])` | Lossless concat of segment recordings into demo.mp4 |
| `rec.page` | The live Playwright page — the escape hatch for anything the verbs don't cover (iframes, keyboard shortcuts, drag) |

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
   to confirm the story is actually visible; check `ffprobe` duration.
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
   opening with a still that links to the video
   (`[![Watch the demo](images/01-home.png)](demo.mp4)`). End with a
   "Re-recording this demo" section giving the exact command.
8. **Commit** the whole folder including the mp4 — it is the point of the
   exercise. Gitignore the working files: `.tts/` narration caches and
   `*.seg.mp4` segment parts (only demo.mp4 belongs in history).

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
  rendered markdown — embed a still that links to `demo.mp4` instead.

## Sharing this skill

The skill is self-contained: this file, `helpers/demo_recording.py`, and
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
