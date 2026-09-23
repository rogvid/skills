---
name: status
description: Handoff for the demo-video v2 work - where it stands, how it is built, and the prioritized next steps to make it polished. Read after GOAL.md when starting a session on demo-video.
---

# demo-video v2 - status

Last updated: 2026-09-23 (output polish).

## Where it stands

v2 is merged to `main`.
The v1 code is tagged `demo-video-v1`.
All open GitHub issues were v1-specific and are closed.

The reason for v2: the Koyr session that made eight guide demos on 2026-09-22 (`~/.claude-personal/projects/-home-kvist-personal-projects-koyr/e487eecf-*.jsonl`) ran 709 turns, re-read about 250M cached tokens, and peaked at 632k of context.
Where it went:
- 133 turns polling real-time takes with `sleep`/`tail` (about 61M tokens replayed)
- 130 turns grepping the app's source for selectors (about 36M)
- 44 full-size stills viewed
- 200-290 line storyboards with hand-written helpers

Koyr's `part1-the-build-loop` video sat on a near-frozen screen for 15s and then 53s while the AI worked.

## How v2 works

- `record.py` drives the app through Playwright as fast as the app allows.
- `capture.py`: a CDP screencast writes every painted frame with its wall-clock time. No frames arrive while the screen is still.
- `clock.py`: an edit list maps wall-clock time onto video time.
  - Holds, cursor glides and title cards are inserted as frozen frames, so they cost no wall-clock time.
  - Waits on the app over 1.5s are retimed to 1.5-3s and get a fast-forward badge.
  - Recorder overhead (overlay rendering, TTS) is retimed to zero.
- `recorder.py` (`_Take` base plus the web `Recorder`) and `terminal.py` (`TerminalRecorder`, PTY plus xterm.js) hold the verbs. After each action, `_settle()` waits for about 350ms of screen stillness, then cuts that still tail.
- `overlays.py` renders the window, caption pills, cards, badges and cursor as PNGs through Chromium. The app renders at a device scale factor that makes its frames exactly the content size, so the app pixels are never resampled at rest.
- `render.py` runs in its own uv env (`scripts/demo-render`, Pillow) from `.take/take.json`. Each output frame is a pure function of its time, and identical consecutive frames are drawn once. It pipes rgb24 to ffmpeg with threaded colour conversion and x264 superfast. It writes `demo.mp4`, `images/`, `sheet.png` and `timeline.md`.
- `inspect_page.py` powers `scripts/demo-inspect` and the failure report.
- `DEMO_VIDEO_KEEP_TAKE=1` keeps `.take/` so the renderer can be re-run or profiled by itself.

Measured so far:

| Demo | Video | Take | Render |
|---|---|---|---|
| `examples/ticket-queue/demo` | 17s | 6s | 9s |
| Koyr part 2, v1 storyboard with mechanical edits | 77s | 11s | 41s |

A simulated 12s wait became 1.8s of video, and a `sleep 8` in the terminal became 1.6s.

## Next steps, in priority order

### 1. Prove it on real use (blocks everything else)

- [ ] Use `examples/ticket-queue/demo` as the working example for everything below. Koyr part 1 does not need re-recording; ticket-queue can show a long wait by adding one (the recorder squeezed a simulated 12s wait into 1.8s).
- [ ] Have the user make one new demo in a fresh session with the v2 skill installed. Record turns, peak context, and wall-clock to the accepted video. Compare with the baseline above; GOAL.md's target is well under 100k context.
- [ ] Only after v2 is done: update Koyr's vendored `.claude/skills/demo-video` (an old single-file v1 from 2026-09-13) and port the eight `docs/guides/2026-09-22-*` storyboards. The user asked to wait for this.

### 2. Output polish (what a viewer sees)

- [x] Click ripple is a swelling disc plus ring; the cursor dips to 80% on press.
- [x] Cursor glides bow upward slightly (12% of the distance, capped) with minimum-jerk easing.
- [x] `goto` holds the old page until the new one has painted (two rAFs), then crossfades 0.3s. Checked with a JSON page and back: no white flash.
- [x] A spotlight re-measures its element on every recorder tick, so ring and camera follow scrolls and reflows.
- [x] Zoom keeps the element's row (outermost box on the same line) in view. The requester spotlight now shows the whole row and the heading. `spotlight(sel, ring=False)` already is a plain zoom, so no `rec.zoom`.
- [x] Title cards follow the window theme (light card on the web recorder, dark in the terminal).
- [x] Long captions wrap to two balanced lines. Placement now compares how much of the spotlit rect each position covers.
- [x] Contact sheet merges tiles that look the same (ticket-queue: 6 tiles to 5), and uses 5 columns at 384px past 12 tiles.
- [ ] Record a new showcase video for the README (the v1 `examples/showcase.mp4` was removed).

### 3. Speed

- [ ] Rendering runs at about 0.5x real time. The bottleneck is ffmpeg ingesting 6MB rgb24 frames, duplicates included. Options, in order:
  - send yuv420p (half the bytes)
  - draw unique frames in a process pool
  - encode only unique frames with timestamps (PyAV, VFR)
- [ ] `DEMO_VIDEO_DRAFT=1` still starts a full take. Check that it is fast enough to be the default iteration loop.

### 4. Robustness

- [ ] Popups and new tabs are not captured; only the first page is. Decide whether to follow them.
- [ ] Full-screen TUIs (`top`, `vim`, alternate screen) are untested in v2. Test one.
- [x] Narration: a real ElevenLabs take of the ticket-queue demo works. Each line starts within 0.2s of its caption and ends before the next, peak -1.6dB. The key is in this repo's `.env` (`set -a; . ./.env; set +a`). Clips are cached in `~/.cache/demo-video/tts`.
- [ ] `_settle()` caps at 2.5s for pages that never go still (spinners). Check that this reads well and doesn't stack up.
- [ ] Removed v1 constructor options are ignored with a warning. Decide whether to keep that shim once Koyr is ported.

### 5. Housekeeping

- [x] `mise.toml` is trusted again and the git hooks run. `/graft/` and `/.ignore` (graft's local files) are gitignored.
- [ ] `ensure.sh` and `skills/script-conventions` are unchanged from v1. Confirm `ensure.sh` still fits (it chmods `scripts/*`).
- [ ] When v2 is done, delete this file and move anything left into GitHub issues.

## How to check a change

- Unit tests and lint: `mise run check` (or `tests/lint` and `uv run --no-project --with pytest --with pillow pytest -q tests`).
- Visual changes: `mise run example` records `examples/ticket-queue/demo`. Look at `sheet.png`, and pull frames around motion with `ffmpeg -ss <t> -i demo.mp4 -frames:v 4 -vf fps=6,tile=4x1 out.png`.
- A test storyboard for any app lives best in the session scratchpad, importing `skills/demo-video/helpers` directly.
