---
name: demo-video
description: Use when someone wants a short, polished demo video of a web app, CLI or TUI - "record a demo of X", "make a video showing this feature", "demo this PR / user story / ticket", "show this in action". Writes a small Python storyboard and produces a framed, captioned mp4 with a smooth cursor, spotlights with zoom, automatic fast-forward over waits, optional narration, plus stills and a one-image contact sheet. Needs uv, ffmpeg and Chromium.
---

# demo-video

You write a short storyboard, `record.py`, and run it.
The recorder drives the app as fast as it can, then builds the video afterwards: holds, cursor glides and title cards are inserted, waits on the app become a short fast-forward, and the window frame, captions, cursor and zoom are composited on top.
A take of a one-minute demo takes about a minute.

Paths below are relative to this skill's directory (where this file is).

## Setup, once per machine

```sh
bash <skill-dir>/ensure.sh                              # uv, and the scripts' exec bits
uv run --with playwright playwright install chromium    # add --with-deps on a fresh Linux box
```

`ffmpeg` must be on PATH.

## Workflow

1. **Decide what to show.** From the request, user story, PR description or ticket, write down 3-6 points, one sentence each, in the viewer's words. Each point becomes one caption and the action that shows it. Aim for 30-90 seconds. Two unrelated features are two demos.
2. **Know how to run the app.** Read `<project>/.demo-video/context.md` if it exists (dev server, port, seed data, login). If it doesn't, work those out once and write that file. Start the server yourself and seed state before recording.
3. **Scaffold:** `<skill-dir>/scripts/demo-new <demo-dir> --url http://localhost:3000` (or `--terminal`). `<demo-dir>` is typically `docs/demos/<yyyy-mm-dd>-<topic>`.
4. **Find selectors without reading the app's source:** `<skill-dir>/scripts/demo-inspect <url>` prints every clickable element, field, heading and repeated item with a selector. For a state deeper in the app, put `rec.inspect()` in the storyboard at that point.
5. **Write the story** (verbs below). Keep it flat: no helper functions, no comments restating the captions.
6. **Draft:** `DEMO_VIDEO_DRAFT=1 uv run <demo-dir>/record.py`. This skips the video and writes `sheet.png`, one frame per caption with its text. Look at that one image. Only open a still or `timeline.md` if the sheet shows a problem.
7. **Record:** `uv run <demo-dir>/record.py`. Run it in the foreground with a generous timeout. It blocks and prints a short summary when done. Don't background it and poll.
8. **Hand over** the path to `demo.mp4` with the summary, and ask what to change. Each change is a small edit and a re-run.

If a take fails, the recorder prints the step that failed, the page URL, and the selectors the page does offer, and saves `failure.png`. Fix the storyboard from that output.
Do not read the recorder's source to debug a storyboard.

## The storyboard

```python
with Recorder(HERE, base_url="http://localhost:3000") as rec:
    rec.goto("/orders")
    rec.caption("Every open order, newest first.")
    rec.hold()

    rec.caption("Search narrows the list as you type.")
    rec.type_into("role=textbox[name='Search']", "invoice")
    rec.spotlight(".order-row")
    rec.hold()
    rec.shot("01-search")
    rec.spotlight()
```

| Verb | What it does |
|---|---|
| `goto(path)` | Open a page (relative to `base_url`) and wait for it to load |
| `caption(text)` | The narrator line; stays up at least as long as it takes to read. `""` clears it |
| `hold(min_s=1.0)` | Let the viewer look: until the caption is read (or spoken), at least `min_s` |
| `click(sel)` / `move_to(sel)` | Glide the cursor to an element and click it / just point at it |
| `type_into(sel, text)` / `clear(sel)` / `press(key)` | Type into a field / empty it / press `"Enter"`, `"Control+K"` (shown as a key badge) |
| `scroll_to(sel)` | Smooth-scroll an element to the middle of the view |
| `spotlight(sel)` / `spotlight()` | Zoom in on an element and ring it / end it. `ring=False` zooms without the ring |
| `wait_for(sel)` / `wait_until(js_or_fn)` | Wait for something the app does on its own. Long waits become a fast-forward |
| `interlude(text)` | A full-window title card, held long enough to read |
| `shot(name)` | Save the current frame as `images/<name>.png` |
| `act(label)` | `with rec.act("import"): rec.page...` - raw Playwright work that may wait on the app |
| `inspect()` | Print what the current page offers to point at. Leaves no trace in the video |

Selectors are Playwright selectors: `#id`, `.class`, `role=button[name='Save']`, `text=Save`, or a Locator.
`rec.page` is the Playwright page.

The recorder already handles:
- **Waiting after actions:** after every action it waits until the screen has stopped changing, so debounced searches and transitions land before the next step. Don't add waits for that.
- **Long waits:** any wait on the app over about 1.5s is squeezed into 1.5-3s of video with a fast-forward badge. For a slow job, call `wait_for` on its result and let the recorder squeeze it. Never `pause()` in a loop.
- **The cursor:** it fades out when idle, so there's no need to park it.
- **Caption placement:** a caption moves to the top when a spotlight sits where it would go.

**Terminal demos** use `TerminalRecorder(HERE, cwd=...)` with these verbs:
- `run(cmd)` types a command and waits for the prompt; `run(cmd, wait=False)` is for programs that keep running.
- `send(text)` types into a REPL or prompt.
- `key("Down", "Enter", "C-c")` presses keys.
- `wait_for_text(regex)`, `wait_for_prompt()` and `wait_for_quiet()` wait on output.

A non-zero exit shows up as a warning in the summary.

## Captions

- One idea per caption, under about 12 words, in the viewer's language. Use the UI's own labels verbatim.
- Claim only what the frame shows.
- Don't hardcode values the app computes.
- Open on what the viewer is looking at. End on a one-line summary of what was shown, then `caption("")`.

## Options

`Recorder(out_dir, base_url, title=..., viewport=(1440, 810), pace=1.0, speech=None, accent="#6366f1", browser_context={...})`.
`browser_context` passes Playwright context options, for example `storage_state` for a logged-in session.
`pace` below 1 is faster.

| Environment | Effect |
|---|---|
| `DEMO_VIDEO_DRAFT=1` | Stills and `sheet.png` only, no video, no narration |
| `DEMO_VIDEO_SIZE=1280x720` | Output size (default 1920x1080) |
| `DEMO_VIDEO_BASE_URL`, `DEMO_VIDEO_PACE` | Defaults for those arguments |
| `ELEVENLABS_API_KEY` | Speak the captions. Clips are cached, so re-takes are free |
| `DEMO_VIDEO_TRACEBACK=1` | Show the full Python traceback on failure |

## Outputs

`<demo-dir>/` gets `demo.mp4`, `images/*.png` (from `shot`), `sheet.png` and `timeline.md` (each step's time in the video).
Commit `record.py` and `images/`. Regenerate the rest by re-running.
To share the video, drag `demo.mp4` into a pull request comment.

## Record fixtures only

There is no masking or redaction: whatever reaches the screen is in the video.
Never record real credentials or customer data. Use seed data and test accounts.
