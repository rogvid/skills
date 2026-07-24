# demo-video

An agent skill that records **self-explanatory demo videos of web apps**
— scripted, deterministic screen recordings with a visible cursor, burned-in
captions, and optional spoken narration. Built for agents (Claude Code and
compatible harnesses) that can't watch video: demos are storyboarded in
code, verified from stills and extracted frames, and reviewed by a
context-free agent before shipping.

## What you get

- **`demo.mp4`** — 30–60 s screen recording of a feature in use: smooth
  cursor motion, caption bar narrating every beat, spotlight rings on the
  evidence, an on-screen terminal card for off-browser actions, and
  interlude cards that bridge long waits (recorded as segments, stitched
  losslessly).
- **`images/*.png`** — stills captured at key moments, ready for a written
  guide.
- **`record.py`** — the storyboard that produced the media, committed next
  to it and re-runnable after the UI changes.
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
- Optional: an ElevenLabs API key for narration (free tier works — the
  default voice is a premade one, and rate limits are retried).

## Install

Copy this folder into a project or your user skills directory:

```sh
cp -r demo-video <project>/.claude/skills/demo-video   # one project
cp -r demo-video ~/.claude/skills/demo-video           # everywhere
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
| `DEMO_VIDEO_TERMINAL_TITLE` | on-screen terminal card title | `terminal` |
| `DEMO_VIDEO_TERMINAL_PROMPT` | terminal card prompt | `$ ` |
| `DEMO_VIDEO_VIEWPORT` | recording size, `"1280x720"` | 1280×720 |
| `DEMO_VIDEO_SPEECH` | force narration on/off (`1`/`0`) | auto by API key |
| `DEMO_VIDEO_VOICE_ID` | ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SKILL_DIR` | where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | enables narration | off |

## Layout

```
demo-video/
├── SKILL.md                    # the process — agents read this
├── README.md                   # this file — humans read this
└── helpers/demo_recording.py   # Recorder + stitch + TTS, stdlib + Playwright only
```

The helper and every generated storyboard carry PEP 723 metadata, so the
dependency declaration travels with the files. Each storyboard embeds
the skill's location as a constant written when the storyboard is
created, with `DEMO_VIDEO_SKILL_DIR` taking precedence at runtime — so
the skill works from `.claude/skills/`, `.agents/` folders, or any
global setup alike.
