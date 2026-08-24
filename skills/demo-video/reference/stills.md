# Stills without a video

A stills-only run drives the storyboard from end to end and writes its
pictures, and records no video. Same verbs, same app, same `shot()` calls,
same `images/*.png`. What it skips is the pacing — the holds, the reading
time, the per-keystroke delay — because pacing exists for a viewer's eyes and
a still does not have any.

    rec = Recorder(out_dir, base_url=..., stills_only=True)
    DEMO_VIDEO_STILLS_ONLY=1 uv run demos/my-demo/record.py

Measured on a 13-beat storyboard against the reference fixture: **19.0 s as a
take, 2.1 s as a stills run**, both writing the same two stills. The field
notes this came from measured 68% of a 124 s take as pure pacing — 48 s of
caption, 19 s of hold, 17 s of pause — and none of it is anything a picture
records.

## Use it while you are still working

The loop it is for is: change the app, run the storyboard, look at the
pictures. A wrong selector, a dialog that never opened, a page that renders
empty — all of it surfaces in seconds instead of after a full paced take plus
an encode. Record the take once the story is right.

It is also the cheap way to answer "does this branch do what the ticket
said": the `criteria=` map, the `ac=` tags and the coverage table all work
exactly as they do in a take, and `timeline.md` comes out with the same
acceptance section.

**As a gate, run it through `scripts/demo-rehearse`.** That is this mode plus
`strict=True` — console errors, failed requests and non-zero exits become a
failing verdict instead of a note in the timeline — under one command that
refuses an environment variable set to route around it. Nothing is polished
and no take is recorded until it exits 0 (SKILL.md Process step 2.5); CI runs
the same command before spending encoder minutes on a take.

## What it writes, and what it does not

| Written | Not written |
|---|---|
| `images/<name>.png` — every `shot()` | `demo.mp4` — no screencast is attached |
| `timeline.json` / `timeline.md` | `frames/` — there is no video to cut frames from |
| `evidence/beat-NN.json` | narration — there is no audio track to mix onto |
| `failure/` and the failure marker, if it raises | `content` — nothing measured a picture |

`timeline.json` says which of the two it was, and says it in three places
that agree:

    "mode": "stills",   "media": null,   "duration": null

`mode` is **absent on a take**, so a take's timeline is byte-for-byte what it
was before this mode existed and nothing has to interpret `mode: "take"`.
`content` is absent rather than null, because null on a take means an mp4 was
expected and the picture could not be measured — a different statement.

## Three things refuse a stills folder, by name

None of them can do their job without a recording, and each says so rather
than failing for an adjacent reason:

- **`beat_frames()`** returns a manifest whose `skipped` names the mode and
  writes no `frames/`. Without the refusal it would fall back to `demo.mp4`
  and cut a sheet out of whatever video the folder already held — a previous
  take's — under this run's beat names.
- **`scripts/demo-grade`** refuses both `brief` and `verdict` at exit 2. It
  would have refused anyway, on the missing frame sheet, but "there is no
  frames/frames.json" reads as a sheet somebody forgot to generate.
- **`stitch()`** refuses a stills run offered as a segment.

## What it changes about the picture, and what it does not

**Every animation is landed on its end state before each still is taken.**
This is not cosmetic and it is not optional. The determinism rule deliberately
*spares* the recorder's own overlays — the spotlight, the caption, the
interlude card — so they animate on camera; in a take the hold after the verb
is what lets them finish. Take the hold away and nothing does. The first
stills run of the reference storyboard photographed its criterion card mid-fade
and its spotlight's scrim half-faded — dimming the whole app instead of picking
out the tile its caption named — at **12.0 dB and 21.7 dB PSNR** from the
take's own stills, with nothing wrong in the beat log, the filenames or the
timeline. This repository's own `tests/pixel` grades it: it records the
reference storyboard both ways and holds the stills against each other. Today
they come back byte-identical.

An animation with no end — a spinner, a blinking caret — is left running,
which is what a take would have shown too. Nothing settles on a beat that
takes no picture: everything else a stills run leaves behind is a document,
and a document does not care what a transition was halfway through.

**Wait timeouts are unchanged.** `wait_for`, `wait_for_text` and
`wait_for_prompt` keep their full deadlines. Shortening them would make a
stills run fail where the take passes, and a fast wrong answer is worse than
a slow right one.

## Two things that are exactly as they are in a take

- **It drives the real app and mutates real state.** A stills run submits the
  forms, writes the rows and sends the requests a take does. Re-run the seed
  between runs, same as between takes.
- **The target guard applies unchanged.** The URL is classified before the
  browser opens, and a public host is refused. There is no fast path around
  it, because there is nothing about a picture that makes a target safer.

## Not a substitute for the take

The video is what a person watches to follow the story and catch the nuance
a still cannot hold — the order things happened in, how long something took,
what moved. A stills run answers "is this right yet". Record the take when
the answer is yes.
