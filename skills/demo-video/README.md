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
- **`frames/`** — a review frame per beat, at most 1024 px wide, plus
  `frames.md` embedding them in order. It is what you hand the fresh-agent
  review: aimed at what the storyboard did rather than at a stopwatch, so
  nothing is missed. A beat whose picture repeats an earlier frame's is not
  reprinted — `frames.md` names it and says which kept frame holds its
  picture. A stitched demo gets them too, off the merged timeline.
  Deliberately uncaptioned, and aimed to within a beat or so rather than
  exactly — `reference/review.md` says how far and why.
- **`record.py`** — the storyboard that produced the media, and the thing
  that actually gets committed: re-runnable after the UI changes, so the
  video stays out of git history and is regenerated rather than archived.
- **`evidence/beat-NN.json`** — what was on screen at every beat, in text:
  the page's ARIA tree (or the terminal's rendered screen), the spotlight
  target's markup, capped and explicitly truncated. An agent reviewing the
  demo reads what the app said instead of inferring it from pixels. The
  serializer drops what was never **painted** — inline `<script>` text, a
  `srcdoc` document, an attribute nothing renders, an input's `value` — because
  a string that reached none of the frames should not have evidence as the one
  place it exists. It clears what a previous take left behind. It is **not
  committed**; `reference/review.md` explains those decisions and where they
  stop.
- **A statement about the frames, not only the storyboard** — `content` in
  `timeline.json`, plus a line on stderr, saying whether the recording shows
  anything at all: how much picture there is where the app sits, and the
  longest stretch in which nothing there changed. Every other artifact here
  describes what the storyboard *did*, and all of them can be exactly right
  over a recording that is blank or covered — a title card over a terminal
  once cost this project 24.3 s of a 60.2 s demo with every beat, exit code
  and evidence file reporting success. It warns; it never fails a take.
- **A recording that reproduces, when you ask for it** — the browser's
  timezone and locale are always pinned, and `Recorder(deterministic=True)`
  additionally freezes the page's clock and flattens animations, so the same
  storyboard gives you the same stills rather than a new set of timestamps.
  Opt-in because a stopped clock changes what a debounce, a token check or an
  elapsed-time bar does, usually without saying so; `reference/determinism.md`
  shows the five shapes that break and what the recorder cannot pin at all.
- **A refusal to record against production** — the host a take is pointed at
  is classified at construction, before a browser opens: loopback passes, a
  private or internal host needs `allow_private=True`, and a public one is
  refused with no option that permits it. It is a target classifier and
  nothing more — there is no masking, no scrubbing and no redaction anywhere
  in this skill, deliberately, and `SKILL.md` opens with why. The same rules
  run as `scripts/demo-target-guard` in CI, over the workflow's configuration
  and each storyboard's source text.
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
| `DEMO_VIDEO_BASE_URL` | app under demo — classified before the browser opens | `http://localhost:8000` |
| `DEMO_VIDEO_ALLOW_PRIVATE` | permit a private/internal target (`1`/`0`); no public equivalent exists | **off** |
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
| `DEMO_VIDEO_STRICT` | raise `StrictTakeFailed` if the take recorded a fatal issue (`1`/`0`) | **off** |
| `DEMO_VIDEO_EVIDENCE` | write `evidence/beat-NN.json` per beat (`1`/`0`) | **on** |
| `DEMO_VIDEO_VOICE_ID` | ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SKILL_DIR` | where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | enables narration | off |

## Layout

```
demo-video/
├── SKILL.md                       # the process — agents read this, in full, every time
├── reference/                     # the argued detail — read at the point of use
│   ├── determinism.md             #   the frozen clock, and why it is opt-in
│   ├── timeline.md                #   the beat log, and whether the picture showed anything
│   ├── review.md                  #   frames, per-beat evidence, acceptance criteria
│   ├── failures.md                #   strict takes, and takes that do not finish
│   ├── terminal.md                #   TerminalRecorder verbs, patterns, gotchas
│   ├── narration.md               #   ElevenLabs speech
│   └── ci.md                      #   recording on a pull request
├── README.md                      # this file — humans read this
├── ensure.sh                      # installs uv, restores exec bits — run once
├── scripts/
│   ├── demo-grade                 # the blind reader's brief, and the verdict
│   │                              #   comparing it with the ac= tags (step 6b)
│   ├── demo-shots                 # the take's stills as one pasteable block,
│   │                              #   captions and ac= tags, grading nothing
│   └── demo-target-guard          # the target classifier, on the command line
└── helpers/
    ├── demo_recording/            # package: the recorders, and what reads their output
    │   ├── __init__.py            #   exports Recorder, TerminalRecorder, stitch,
    │   │                          #   beat_frames, content_report, StrictTakeFailed
    │   ├── core.py                #   _DemoBase: the browser, narration, ffmpeg
    │   ├── web.py                 #   Recorder (Playwright web apps)
    │   ├── terminal.py            #   TerminalRecorder (PTY + xterm.js)
    │   │                          #   ── everything below this line is browser-free:
    │   │                          #      no Playwright, no ffmpeg import, importable
    │   │                          #      and unit-testable on its own. tests/unit
    │   │                          #      grades it in ~3 s; tests/smoke the rest.
    │   ├── target.py              #   what host a take may be pointed at
    │   ├── timeline.py            #   the beat log: schema and its two renderings
    │   ├── coverage.py            #   acceptance criteria, and what claimed them
    │   ├── content.py             #   whether the picture showed anything
    │   ├── frames.py              #   review frames, off a demo already recorded
    │   ├── failure.py             #   the dump a take that did not finish leaves
    │   ├── narration.py           #   ElevenLabs synthesis and its content cache
    │   ├── markdown.py            #   escaping a value into a markdown table
    │   ├── links.py               #   a committed still's path, caption, and URL
    │   └── stitching.py           #   joining segments into one demo, losslessly
    └── assets/xterm/              # vendored xterm.js (terminal rendering)
```

**SKILL.md is loaded whole into an agent's context whenever the skill triggers;
`reference/` is read on demand.** That is why the split exists and why it is
worth keeping: the always-loaded entry point is the smaller part of the skill's
prose by a wide margin — `reference/` is the larger — and nothing was deleted to
get there. No figure is quoted here because it goes stale on every edit;
`wc -c SKILL.md reference/*.md` in the installed skill directory is the current
one.

The package and every generated storyboard carry PEP 723 metadata, so the
dependency declaration travels with the files. Each storyboard embeds
the skill's location as a constant written when the storyboard is
created, with `DEMO_VIDEO_SKILL_DIR` taking precedence at runtime — so
the skill works from `.claude/skills/`, `.agents/` folders, or any
global setup alike.
