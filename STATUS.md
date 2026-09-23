---
name: status
description: Handoff for the demo-video v2 work - where it stands, how it is built, and the prioritized next steps to make it polished. Read after GOAL.md when starting a session on demo-video.
---

# demo-video v2 - status

Last updated: 2026-09-23 (after the first real-use test).

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
- `capture.py`: a CDP screencast writes every painted frame with its wall-clock time. No frames arrive while the screen is still. The frames are CSS-pixel size, so every hold also takes a full-resolution screenshot (`snapshot()`), which is what holds and zooms show.
- `clock.py`: an edit list maps wall-clock time onto video time.
  - Holds, cursor glides and title cards are inserted as frozen frames, so they cost no wall-clock time.
  - Waits on the app over 1.5s are retimed to 1.5-3s and get a fast-forward badge.
  - Recorder overhead (overlay rendering, TTS) is retimed to zero.
- `recorder.py` (`_Take` base plus the web `Recorder`) and `terminal.py` (`TerminalRecorder`, PTY plus xterm.js) hold the verbs. After each action, `_settle()` waits for about 350ms of screen stillness, then cuts that still tail.
- `overlays.py` renders the window, caption pills, cards, badges and cursor as PNGs through Chromium. The app renders at twice the content's density; the renderer downsamples it.
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

### 1. Prove it on real use

- [x] First real-use test, 2026-09-23: Koyr "row lineage" demo, session `e82da7c1` (`~/.claude-personal/projects/-home-kvist-personal-projects-koyr/`). 45 turns, 115k peak context (36k at session start), 3.3M cached tokens re-read, 9.5 min to an accepted 52s video, versus 709 turns and 632k before. No polling.
- User's verdict: good flow and a big speed-up, but it zoomed too often, a caption jumped from bottom to top, and image quality was low. All three are fixed below.
- [ ] Only after v2 is done: update Koyr's vendored `.claude/skills/demo-video` and port the eight `docs/guides/2026-09-22-*` storyboards. The user asked to wait for this. (Koyr now has the v2 skill installed through `skills-lock.json`.)

### 1b. From the real-use test

- [x] Quality: Chromium's screencast sends CSS-pixel frames whatever the device scale factor, so every frame was upscaled about 1.17x, with broken letter spacing. Each hold now starts with a Playwright screenshot at 2x the video's density, downsampled at rest and cropped from real pixels when zoomed. Raw CDP `captureScreenshot` with a clip must not be used: it resets the page's device scale factor, which changed how Koyr's canvas zoomed.
- [x] Zoom only when the spotlit text is under 17px at 1080p (measured as drawn, transforms included), and only as far as needed. `spotlight(zoom=True/False)` overrides. The render summary notes when most spotlights zoom.
- [x] Captions sit in a band below the window, with an even margin on all sides. The default viewport is 1440 wide, shaped to the window.
- [x] `demo-new` failed on uv 0.11, which reads the template's embedded PEP 723 block as a second one (0.9 did not). The template's metadata now sits in a one-line string.
- [x] Pages that never go still (Koyr's pinned lineage runs React Flow's infinite `dashdraw` animation at 59fps) made every `_settle()` run to its 2.5s cap. Settle now also asks the page: when the only things moving are infinite animations already running before the step, and the DOM and scroll have been quiet for 0.35s, it is settled. A spinner the step started is still waited for. Koyr: take 31s to 18s, video 51.5s to 35.7s, same content.
- [x] Render time grew with the full-resolution holds (Koyr 66s for 51s of video); fixed under Speed.
- [x] `act()` now settles like every verb, so a still right after it is not stale. `shot()` takes a full-resolution snapshot, and stills and the sheet show everything on screen fully arrived (captions and rings faded in, zoom pushed in, no ripple).

### 2. Output polish (what a viewer sees)

- [x] Click ripple is a swelling disc plus ring; the cursor dips to 80% on press.
- [x] Cursor glides bow upward slightly (12% of the distance, capped) with minimum-jerk easing.
- [x] `goto` holds the old page until the new one has painted (two rAFs), then crossfades 0.3s. Checked with a JSON page and back: no white flash.
- [x] A spotlight re-measures its element on every recorder tick, so ring and camera follow scrolls and reflows.
- [x] Zoom keeps the element's row (outermost box on the same line) in view. The requester spotlight now shows the whole row and the heading. `spotlight(sel, ring=False)` already is a plain zoom, so no `rec.zoom`.
- [x] Title cards follow the window theme (light card on the web recorder, dark in the terminal).
- [x] Long captions wrap to two balanced lines. Placement now compares how much of the spotlit rect each position covers.
- [x] Contact sheet merges tiles that look the same (ticket-queue: 6 tiles to 5), and uses 5 columns at 384px past 12 tiles.
- [x] New narrated showcase in the README (`examples/showcase`, `mise run showcase`): a web take and a terminal take joined. GitHub strips `<video>` tags, so the README shows a poster still linked to the mp4; an inline player needs the mp4 uploaded once through the github.com editor (a `user-attachments` URL). Found on the way: the audio track ended before the video, which put a joined part's narration about 1s early (now padded), and zooms under 1.25x cropped more than they helped (now skipped). Fixed a `ticket-queue` layout bug where the Copy button ran past the detail card.

### 3. Speed

- [x] Rendering is now faster than real time: Koyr 66s to 23s for 36s of video, ticket-queue 10s for 17s. Profiling showed two thirds in LANCZOS resizes and one third blocked on ffmpeg, in series. Snapshots (exactly 2x) downsample with `reduce(2)`, zoom and motion frames use bicubic (50.8dB PSNR against the old render), unique frames are drawn in a thread pool while ffmpeg takes the last one, and PNGs use default compression (`optimize` was 5x slower for 5% smaller files). If more is needed, the next step is encoding only unique frames (PyAV, VFR).
- [x] `DEMO_VIDEO_DRAFT=1`: the render part is now about 2s. The take is the app's own time (Koyr 20s), which a draft cannot skip.

### 4. Robustness

- [x] New tabs and popups are followed: the old page holds until the new one paints, then crossfades, and closing it returns to the page before. A popup is resized to the recording viewport and shown like a tab. `rec.page` is always the page on screen.
- [ ] Full-screen TUIs (`top`, `vim`, alternate screen) are untested in v2. Test one.
- [x] Narration: a real ElevenLabs take of the ticket-queue demo works. Each line starts within 0.2s of its caption and ends before the next, peak -1.6dB. The key is in this repo's `.env` (`set -a; . ./.env; set +a`). Clips are cached in `~/.cache/demo-video/tts`.
- [x] The v1 constructor options are pruned: each was either covered under another name (`title=`, `prompt=`, `browser_context=`, `interlude()`, `rec.page.clock`) or belonged to a removed v1 feature. An old option now raises `TypeError`.

### 5. Housekeeping

- [x] `mise.toml` is trusted again and the git hooks run. `/graft/` and `/.ignore` (graft's local files) are gitignored.
- [ ] `ensure.sh` and `skills/script-conventions` are unchanged from v1. Confirm `ensure.sh` still fits (it chmods `scripts/*`).
- [ ] When v2 is done, delete this file and move anything left into GitHub issues.

## How to check a change

- Unit tests and lint: `mise run check` (or `tests/lint` and `uv run --no-project --with pytest --with pillow pytest -q tests`).
- Visual changes: `mise run example` records `examples/ticket-queue/demo`. Look at `sheet.png`, and pull frames around motion with `ffmpeg -ss <t> -i demo.mp4 -frames:v 4 -vf fps=6,tile=4x1 out.png`.
- A test storyboard for any app lives best in the session scratchpad, importing `skills/demo-video/helpers` directly.
