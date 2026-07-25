# demo-video

An agent skill that records **self-explanatory demo videos of web apps and
terminal programs** — scripted, deterministic screen recordings with
burned-in captions and optional spoken narration. A web app is driven
through a browser (`Recorder`); a CLI, REPL, or full-screen TUI runs in a
real terminal (`TerminalRecorder`) — same recording engine, captions,
narration, and verification. Built for agents (Claude Code and compatible
harnesses) that can't watch video: demos are storyboarded in code, verified
from stills and extracted frames, and reviewed by a context-free agent
before shipping.

## See it in action

A demo made *with* demo-video — one narrated video spanning a live web app
and a real terminal session (voice on):

<video src="https://github.com/rogvid/skills/raw/main/skills/demo-video/examples/showcase.mp4" controls muted width="100%"></video>

<sub>If the player doesn't load in your viewer, [watch/download the mp4 directly](examples/showcase.mp4).</sub>

## What you get

- **`demo.mp4`** — 30–60 s screen recording: for web, smooth cursor motion,
  spotlight rings, and a decorative terminal card for off-browser actions;
  for terminals, a real CLI/TUI session in an in-browser terminal. Both get
  a caption bar narrating every beat and interlude cards that bridge long
  waits (recorded as segments, stitched losslessly).
- **`images/*.png`** — stills captured at key moments, ready for a written
  guide.
- **`frames/`** — one review frame per beat, plus `frames.md` embedding them
  in order. It is what you hand the fresh-agent review: aimed at what the
  storyboard did rather than at a stopwatch, so nothing is missed and a held
  frame is photographed once. A stitched demo gets them too, off the merged
  timeline. Deliberately uncaptioned, and aimed to within a beat or so rather
  than exactly — SKILL.md says how far and why.
- **`record.py`** — the storyboard that produced the media, and the thing
  that actually gets committed: re-runnable after the UI changes, so the
  video stays out of git history and is regenerated rather than archived.
- **`evidence/beat-NN.json`** — what was on screen at every beat, in text:
  the page's ARIA tree (or the terminal's rendered screen), the spotlight
  target's markup, capped and explicitly truncated. An agent reviewing the
  demo reads what the app said instead of inferring it from pixels. Plain
  text, so it is masked against registered secrets *and* against whatever
  `redact()` is covering — and it is **not committed**; `SKILL.md` says why.
- **A recording that reproduces, when you ask for it** — the browser's
  timezone and locale are always pinned, and `Recorder(deterministic=True)`
  additionally freezes the page's clock and flattens animations, so the same
  storyboard gives you the same stills rather than a new set of timestamps.
  Opt-in because a stopped clock changes what a debounce, a token check or an
  elapsed-time bar does, usually without saying so; `SKILL.md` shows the five
  shapes that break and what the recorder cannot pin at all.
- **Spoken narration (optional)** — with `ELEVENLABS_API_KEY` set, every
  caption line is synthesized via ElevenLabs and mixed onto the mp4 at the
  moment it appears. Clips are cached; pacing self-adjusts so speech is
  never cut off. No key → same storyboard records silently.

## Requirements

- [`uv`](https://docs.astral.sh/uv/) — storyboards are single-file uv
  scripts (PEP 723) that pull Playwright on demand; no project Python
  environment is needed.
- `ffmpeg` on PATH.
- Chromium for Playwright, once per machine:
  `uv run --with playwright playwright install chromium`
- Playwright **1.49 or newer** for per-beat evidence (`aria_snapshot`).
  Storyboards declare `playwright` unpinned, so a fresh resolve has it.
- Optional: an ElevenLabs API key for narration (free tier works — the
  default voice is a premade one, and rate limits are retried).
- Terminal demos (`TerminalRecorder`) are **Unix-only** (they use a PTY).
  Web demos run anywhere Playwright does.

## Install

Install with the [`skills`](https://github.com/vercel-labs/skills) CLI —
into the current project, or globally with `-g`:

```sh
npx skills add https://github.com/rogvid/skills/tree/main/skills/demo-video
npx skills add rogvid/skills --skill demo-video -g    # everywhere
```

Then ask your agent for a demo ("record a demo of the new intake page") —
`SKILL.md` carries the full process: storyboarding, caption craft,
recording, and a required fresh-eyes review where a context-free agent
retells the story from extracted frames before the demo ships.

## Configuration

Everything is configurable per project via environment variables (put them
in `.env`), and per storyboard via `Recorder(...)` parameters — parameters
win over env vars.

| Variable | Sets | Default |
|---|---|---|
| `DEMO_VIDEO_OUT_DIR` | where demo files land | — |
| `DEMO_VIDEO_BASE_URL` | app under demo | `http://localhost:8000` |
| `DEMO_VIDEO_ACCENT_RGB` | cursor/spotlight color, `"235,110,20"` | orange |
| `DEMO_VIDEO_TERMINAL_TITLE` | web terminal-card title | `terminal` |
| `DEMO_VIDEO_TERMINAL_PROMPT` | prompt (web card, and `TerminalRecorder` PS1) | `$ ` web / `❯ ` terminal |
| `DEMO_VIDEO_TERMINAL_SHELL` | shell `TerminalRecorder` launches | `/bin/bash` |
| `DEMO_VIDEO_TERMINAL_FONT_SIZE` | `TerminalRecorder` font px | `15` |
| `DEMO_VIDEO_VIEWPORT` | recording size, `"1280x720"` | 1280×720 |
| `DEMO_VIDEO_DETERMINISTIC` | freeze the page clock and flatten motion (`1`/`0`) | **off** |
| `DEMO_VIDEO_CLOCK` | instant the clock is frozen at, when it is (ISO 8601) | `2025-01-01T09:00:00Z` |
| `DEMO_VIDEO_TIMEZONE` | browser timezone (always applied) | `UTC` |
| `DEMO_VIDEO_LOCALE` | browser locale (always applied) | `en-US` |
| `DEMO_VIDEO_SPEECH` | force narration on/off (`1`/`0`) | auto by API key |
| `DEMO_VIDEO_EVIDENCE` | write `evidence/beat-NN.json` per beat (`1`/`0`) | **on** |
| `DEMO_VIDEO_VOICE_ID` | ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SKILL_DIR` | where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | enables narration | off |

## Layout

```
demo-video/
├── SKILL.md                       # the process — agents read this
├── README.md                      # this file — humans read this
└── helpers/
    ├── demo_recording/            # package: core + web + terminal recorders
    │   ├── __init__.py            #   exports Recorder, TerminalRecorder, stitch
    │   ├── core.py                #   shared recording + narration + ffmpeg
    │   ├── web.py                 #   Recorder (Playwright web apps)
    │   └── terminal.py            #   TerminalRecorder (PTY + xterm.js)
    └── assets/xterm/              # vendored xterm.js (terminal rendering)
```

The package and every generated storyboard carry PEP 723 metadata, so the
dependency declaration travels with the files. Each storyboard embeds
the skill's location as a constant written when the storyboard is
created, with `DEMO_VIDEO_SKILL_DIR` taking precedence at runtime — so
the skill works from `.claude/skills/`, `.agents/` folders, or any
global setup alike.
