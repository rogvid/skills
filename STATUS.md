---
name: status
description: Handoff for the demo-video v2 work - where it stands, how it is built, and the prioritized next steps to make it polished. Read after GOAL.md when starting a session on demo-video.
---

# demo-video v2 - status

Last updated: 2026-09-23.

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

- [ ] Re-record Koyr `part1-the-build-loop` with v2. It calls Koyr's AI, so ask the user first because it costs API money. This is the demo with the frozen minute; the fast-forward should turn about 68s of waiting into about 5s.
- [ ] Have the user make one new demo in a fresh session with the v2 skill installed. Record turns, peak context, and wall-clock to the accepted video. Compare with the baseline above; GOAL.md's target is well under 100k context.
- [ ] Only after v2 is done: update Koyr's vendored `.claude/skills/demo-video` (an old single-file v1 from 2026-09-13) and port the eight `docs/guides/2026-09-22-*` storyboards. The user asked to wait for this.

### 2. Output polish (what a viewer sees)

- [ ] The click ripple is faint. Make it clearly visible and add a small cursor press (scale down) on click.
- [ ] Cursor glides are straight lines. A slight arc and ease reads more like a hand.
- [ ] Page navigations cut hard, and a full navigation can flash white. Add a short crossfade on `goto`, and hold the last frame until the new page first paints.
- [ ] A spotlight measures its element once. If the page scrolls or reflows during it, the ring drifts. Re-measure on each verb, or refuse to scroll while spotlit.
- [ ] Zoom tuning: small elements hit the 1.6 zoom cap and crop headings (the requester spotlight in the example). Consider fitting a little context around the element, and an optional `rec.zoom(sel)` for typing into a field.
- [ ] The title card is always dark (`#15151f`), which jars on a light app. Match the window theme or the app's background.
- [ ] Check that long captions wrap to two balanced lines and never cover the spotlit element (caption placement only checks the bottom band).
- [ ] Contact sheet: merge a still with its caption tile when they show the same frame (Koyr tiles 1 and 2 were duplicates). Consider 5 columns at 384px to cut image tokens on long demos.
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
- [ ] Narration was only tested with a stand-in tone clip. Run one real ElevenLabs take.
- [ ] `_settle()` caps at 2.5s for pages that never go still (spinners). Check that this reads well and doesn't stack up.
- [ ] Removed v1 constructor options are ignored with a warning. Decide whether to keep that shim once Koyr is ported.

### 5. Housekeeping

- [ ] `mise.toml` was edited, so run `mise trust` before `mise run ...` and before the gitleaks hook will work. The v2 commit used `--no-verify` after ruff and gitleaks were run by hand.
- [ ] `ensure.sh` and `skills/script-conventions` are unchanged from v1. Confirm `ensure.sh` still fits (it chmods `scripts/*`).
- [ ] When v2 is done, delete this file and move anything left into GitHub issues.

## How to check a change

- Unit tests and lint: `mise run check` (or `tests/lint` and `uv run --no-project --with pytest --with pillow pytest -q tests`).
- Visual changes: `mise run example` records `examples/ticket-queue/demo`. Look at `sheet.png`, and pull frames around motion with `ffmpeg -ss <t> -i demo.mp4 -frames:v 4 -vf fps=6,tile=4x1 out.png`.
- A test storyboard for any app lives best in the session scratchpad, importing `skills/demo-video/helpers` directly.
