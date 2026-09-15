---
name: demo-video
description: Use when someone wants a polished demo video of a web app, CLI or TUI to show a feature to people - "record a demo of X", "make a walkthrough video", "show this feature in action", "demo my command-line tool". Produces a framed, captioned mp4 with a visible cursor, spotlights and optional narration, plus stills for a written guide, from a short `record.py` storyboard that re-records whenever the UI changes. Not needed for a raw capture of a browser session with no captions or framing - plain browser recording does that. Needs uv, ffmpeg and Chromium.
---

# demo-video

You write a short storyboard, `record.py`.
The recorder drives the app and produces a finished video that explains itself to someone with no context: the app in a framed window, a caption for each step, a visible cursor, spotlights with a camera push-in, and optional spoken narration.
Web apps run through Playwright.
Terminal programs (CLIs, REPLs, full-screen TUIs) run in a real PTY, rendered in the same window.
The storyboard is committed, so anyone can re-record the demo after the UI changes.

A demo folder ends up holding:

| File | What it is |
|---|---|
| `record.py` | The storyboard. Committed |
| `images/*.png` | The stills `shot()` captured. Committed |
| `timeline.md` / `timeline.json` | What ran, when, and which caption was up. Committed |
| `demo.mp4` | The video. Not committed - regenerate it, or attach it to the pull request |
| `frames/`, `evidence/` | One frame and one screen-text file per beat, for checking a take without watching it. Not committed |

## Quick start

All paths below are relative to this skill's own directory - the directory this SKILL.md was read from, not the current working directory.

```sh
bash <skill-dir>/ensure.sh                     # once per session: uv, and the scripts' exec bits
<skill-dir>/scripts/demo-new docs/demos/2026-09-15-search --url http://localhost:3000
#   ...edit record.py: the story, one caption per step...
<skill-dir>/scripts/demo-rehearse docs/demos/2026-09-15-search/record.py   # seconds: does the feature work?
uv run docs/demos/2026-09-15-search/record.py  # the real take: writes demo.mp4
```

`demo-new` writes a `record.py` that already runs: it knows where this skill is and opens on the app with a caption and a still.
Add `--terminal` for a CLI or TUI instead of a web app.
The file is a plain uv script: a few lines that find this skill, `from demo_recording import Recorder` (or `from demo_recording import TerminalRecorder`), and one `with Recorder(HERE) as rec:` block holding the story.
Then look at `images/*.png` and `timeline.md` before calling the demo done - an exit code of 0 says the storyboard ran, not that the picture is right.

Once per machine: `ffmpeg` on PATH, and Chromium via `uv run --with playwright playwright install chromium` (add `--with-deps` on a fresh Linux box).
If a script fails with `env: 'uv': No such file or directory`, re-run `ensure.sh` and follow what it prints; do not fall back to `python3`.

## What this records, and what it does not defend against

**Record fixtures and example data only.**

- The tool has **no masking, no scrubbing and no redaction**. Whatever reaches the screen is in the video, and a published video leaks forever.
- If a real credential can appear in the app, do not record it. No setting makes that safe ([#138](https://github.com/rogvid/skills/issues/138)).
- The recorder refuses a public target before a browser opens: the `base_url`, `DEMO_VIDEO_BASE_URL`, and every `goto()` argument. A private host needs `allow_private=True`.
- **`rec.page` is not checked**, and neither is the app's own `fetch`. This is a classifier over configuration and source, not an egress control.

## Writing the storyboard

1. **One story, 30-60 seconds.** That buys about twenty screens. A feature spanning two surfaces is two demos, not faster captions.
2. **Know how the app runs.** Read `<project root>/.demo-video/context.md` if it exists: the dev server and port, how to seed data, selector conventions. If it does not, write it once you have worked those out, and commit it. Seed state before the first `goto()`, and reuse a server that is already running.
3. **One beat at a time: caption, action, wait.** Set the caption first (it tells the eye where to look), then act, then `wait_for` the outcome the caption promises. The wait is what makes a broken feature fail the rehearsal instead of recording green.
4. **`shot("NN-name")`** at each moment a written guide would narrate.
5. **End on a closing caption** that sums up the story, then `caption("")`.

```python
rec.caption("Type a name and the list narrows to match.")
rec.type_into("#search", "invoice")
rec.wait_for(".ticket")          # the outcome, not the page shell
rec.spotlight(".ticket")
rec.hold()                       # keep the ring up for the whole line
rec.shot("02-filtered")
rec.spotlight()
```

| Verb | Use |
|---|---|
| `goto(path)` | Navigate, relative to `base_url`. Waits for network idle, up to 10 s |
| `caption(text)` | The narrator line over the bottom of the app; `""` clears it. It survives navigation, so clear it before a click that navigates |
| `hold(min_s=1.5)` | Keep the frame until the caption's narration finishes, at least `min_s` |
| `pause(s)` / `shot(name)` | Hold for `s` seconds / capture `images/<name>.png` |
| `move_to` / `click` / `click_fast` / `scroll_to` | Visible cursor motion. `click_fast` for elements that re-render continuously |
| `type_into(selector, text)` / `clear(selector)` / `press(key)` | Type visibly, key by key / empty a field / press a named key like `"Enter"` |
| `wait_for(selector)` | Wait for something the app does on its own, and stamp it as a beat |
| `spotlight(selector)` | Ring the element the caption is about, with a camera push-in; `spotlight()` clears |
| `interlude(text)` | A title card to bridge a jump in time; `interlude("")` takes it down |
| `terminal(cmd)` / `terminal_output(text)` / `terminal_close()` | A decorative terminal card inside a web demo, to show an off-browser step |
| `act(label)` | `with rec.act("drag the card"): rec.page...` - raw Playwright work, stamped as a beat |
| `stitch(out_dir, [segments])` | `from demo_recording import stitch` - join segment recordings into one `demo.mp4` and one timeline |

[reference/verbs.md](reference/verbs.md) has every verb with its caveats - read it before using `spotlight`, `interlude` or `rec.page`.
A terminal demo uses `run`, `send`, `key`, `wait_for_prompt` and `wait_for_text` instead of the pointer verbs: read [reference/terminal.md](reference/terminal.md) before writing one.

**Captions:**

- Claim only what is visible in the frame. Re-read each caption against its own still.
- Use the UI's own wording, verbatim.
- Do not hardcode values the app computes; they change between takes.
- Never leave a static screen with a stale caption for more than about 3 seconds. Tour what is on screen, or say what is being waited for.

## Pacing and perception

The recorder's defaults are set to human limits; the point is not to fight them.

- **A change needs about 1.5 s to register.** A spotlight cleared a moment after it was set reads as a flicker.
- **Captions hold for reading time automatically** (about `0.6 + 0.34 x words` seconds without narration). With narration on, `hold()` waits for the spoken line.
- **One salient change at a time.** Do not navigate, spotlight and type in the same instant.
- **Photograph the settled state.** After a multi-step interaction, `pause()` before the caption so the result gets a frame.
- **Pace to the audience** with `pace=0.6` (or `preset="quick"`) for a skimming reviewer. Below about 0.5, captions outrun reading.

## Record, then look

- **While the storyboard is still wrong**, run it with `DEMO_VIDEO_STILLS_ONLY=1`: the same stills in seconds, no video ([reference/stills.md](reference/stills.md)).
- **Rehearse before every take**, and again whenever the app changed under a committed storyboard. `demo-rehearse` runs the storyboard strict and fast, and fails on a console error, a failed request or a non-zero exit. Do not polish a demo of something that does not work.
- **After the take**, read the stills, `timeline.md`, and the problem summary the recorder prints on stderr. A take with no summary is the all-clear ([reference/failures.md](reference/failures.md), [reference/timeline.md](reference/timeline.md)).
- **`<skill-dir>/scripts/demo-caption-lint <folder>`** checks each caption's numbers and quoted strings against the screen text of its beat. When it reports NOT FOUND, check the app before softening the caption.
- **For a demo other people will watch, get fresh eyes.** You wrote the story, so you cannot tell whether it lands. `<skill-dir>/scripts/demo-review <folder>` prints the frame sheet and the questions for a subagent told nothing about the feature ([reference/review.md](reference/review.md)).

## Configuration

Every parameter resolves as explicit argument, then `DEMO_VIDEO_*` environment variable, then default - so project defaults can live in `.env` (`set -a; source .env; set +a`).

| Variable | Parameter - what it does | Default |
|---|---|---|
| `DEMO_VIDEO_BASE_URL` | `base_url` - the app under demo | `http://localhost:8000` |
| `DEMO_VIDEO_PRESET` | `preset` - `"high"` (1080p, narration when a key is set) or `"quick"` (720p, pace 0.6, silent) | `high` |
| `DEMO_VIDEO_PACE` | `pace` - multiplier over the holds the recorder computes | `1.0` |
| `DEMO_VIDEO_STILLS_ONLY` | `stills_only` - stills, no video | off |
| `DEMO_VIDEO_STRICT` | `strict` - fail the take on console errors or non-zero exits | off |
| `DEMO_VIDEO_ALLOW_PRIVATE` | `allow_private` - permit a private-network target | off |
| `DEMO_VIDEO_DETERMINISTIC` | `deterministic` - freeze the page clock; read [reference/determinism.md](reference/determinism.md) first | off |
| `ELEVENLABS_API_KEY` | *no parameter* - speak the captions ([reference/narration.md](reference/narration.md)) | off |

Window size and title, cards, caption placement, colours, locale, and the terminal's shell and font are in [reference/configuration.md](reference/configuration.md).

## Commit the storyboard, not the video

Commit `record.py`, `images/`, `timeline.json` and `timeline.md` - small, diffable, and enough to see what the demo showed without watching it.
Do not commit `demo.mp4` or the other working files: `<skill-dir>/scripts/demo-gitignore <folder>` prints the ignore lines, anchored to the demo folder.
To share the video, drag `demo.mp4` into a pull request comment; GitHub hosts it and renders a player.
For a written guide, `<skill-dir>/scripts/demo-shots <folder>` prints every still under its caption as one markdown block.

## Common mistakes

- **Positional selectors.** Demos sort and filter; `nth-child` ticks whatever moved into that slot. Use ids, labels or text.
- **Waiting on the page shell.** `wait_for("h1")` passes while the data is still loading. Wait for the content.
- **Layout shifts strand the cursor.** Re-`move_to` after anything that reflows.
- **A blind click to dismiss an overlay.** Dismiss through a named element, never coordinates.
- **Narrating something at the bottom edge.** The caption covers it; `scroll_to` centres the element.
- **An ending that needs insider context** - an empty state, a prompt asking what next. Caption it or end elsewhere.

## Going further

| Read | When |
|---|---|
| [reference/limits.md](reference/limits.md) | Before reading a green take as proof, or when two artifacts seem to disagree - every known limit, measured |
| [reference/verbs.md](reference/verbs.md) | A verb needs more than its line above; segments and `stitch` for stories with long waits |
| [reference/terminal.md](reference/terminal.md) | Writing a `TerminalRecorder` storyboard |
| [reference/configuration.md](reference/configuration.md) | Any parameter the table above does not name |
| [reference/stills.md](reference/stills.md) | Iterating on the pictures before recording the video |
| [reference/determinism.md](reference/determinism.md) | Before `deterministic=True` |
| [reference/narration.md](reference/narration.md) | Spoken captions |
| [reference/timeline.md](reference/timeline.md) | Reading `timeline.json` or its `content` warnings |
| [reference/failures.md](reference/failures.md) | A take raised, `strict` refused it, or `failure/` appeared |
| [reference/review.md](reference/review.md) | Handing a take to a reviewer, reading `evidence/`, or recording against a ticket's acceptance criteria |
| [reference/ci.md](reference/ci.md) | Recording demos automatically on pull requests |

Proving a ticket's acceptance criteria with a demo - `criteria=`, `ac=` tags and a blind grader - is a separate workflow built on this recorder, described in the `demo-verify` skill.
