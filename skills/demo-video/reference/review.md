<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Reviewing a take: frames, evidence, and acceptance criteria

> Read at step 6 of the Process — when handing a take to a reviewing agent, when reading `evidence/beat-NN.json`, or when recording against a ticket with `criteria=`.

## Review frames (`frames/`)

Nobody reviewing a demo through this skill can watch a video, so every review
is a review of frames pulled out of it. A clean exit writes them: one PNG per
beat under `frames/`, named `beat-NN.png` for the beat's index in
`timeline.json`, plus `frames/frames.md` — the sheet to hand a reviewer, which
embeds them in order — and `frames/frames.json` for anything reading them by
machine.

They are aligned to **beats, not to a clock**. The old advice was
`ffmpeg -vf fps=1/3`, which misses a short beat entirely and photographs a long
static one twice. Each frame is taken at its beat's **midpoint** — `t_start` is
0% into the caption bar's fade and before the verb has done anything.

**How accurate that aim is, honestly.** The beat log is wall-clock; the video
is whatever Chromium's screencast managed to record, and it drops wall time
during idle stretches ([#18](https://github.com/rogvid/skills/issues/18)). So a
frame cut at a beat's midpoint shows a moment slightly *ahead* of that beat in
the demo's own story — measured at **80–200 ms** on instrumented takes, and up
to the **~0.7 s** of browser start-up no test code can cover, on a take that
loses that window whole (about 1 in 12, which is why `tests/smoke` bounds this
direction at 750 ms). The practical consequence: for a beat comfortably longer
than that, the frame is of that beat; **for a beat shorter than the drift — a
bare `shot()`, a `wait_for()` that returned immediately — the frame can be of
the beat after it.** `tests/smoke` measures exactly this and shows it: with the
drift allowance removed, the frame for a 50 ms `shot()` beat that sits against
a caption change is already showing the next beat's screen.

Read the frames as *"roughly here in the demo"*, not as *"exactly this beat"*.
When a specific short moment matters, use `shot()` — `images/*.png` are
Playwright screenshots taken synchronously at the beat, with no video clock
between the moment and the file. `frames/frames.md` reports the take's own
lower bound on how much wall time the capture lost, when it lost any.

**They carry no caption, and that is deliberate.** Printing the line that was
on screen during a frame's beat under that frame is the obvious next step and
it is not sound: the beat log and the video run on different clocks
([#18](https://github.com/rogvid/skills/issues/18)), so the caption under a
frame can belong to the frame next to it — and a confident wrong caption is
worse review material than no caption at all. An earlier version tried to
recover the mapping by finding caption transitions in the video; it mislabelled
frames on ordinary storyboards (two captions of the same length give it no
signal, an app that repaints under the bar gives it a stronger edge than the
caption does, and a mid-take `goto()` destroys the bar while logging no caption
change at all). [#60](https://github.com/rogvid/skills/issues/60) is how the
pairing gets earned back: have the recorder render the beat index into the
frame so extraction reads it rather than infers it.

`frames.md` also carries **no verb and no selector**, for the same reason step
6 tells you to give the reviewer nothing else: it is the document a
context-free reviewer reads before answering what story the pictures tell.

Inside a beat long enough to hide something the storyboard never scripted (3 s
and up) the recorder also runs scene-change detection and adds
`beat-NN-scene-1.png` for each transition it finds. Beat alignment sees what
the storyboard wrote down; a redirect, a toast or a load finishing mid-hold is
invisible to it.

**A stitched demo gets frames; a single segment does not.** Each segment
numbers its beats from zero and its timeline names a `.seg.mp4` that `stitch()`
deletes, so two segments writing into one directory would collide on
`beat-00.png` and the sheet would embed a file that is gone — a segment take
therefore writes no frames and says why. `stitch()` writes them instead, off
the **merged** timeline, at the first moment a whole demo exists. Nothing extra
to run, and it is the case that needs a sheet most: a demo long enough to
record in parts is a demo nobody wants to review by scrubbing.

`frames/` is a review artifact, not documentation: **gitignore it** along with
`demo.mp4` — it is in the file table at the top for the same reason. Nothing
downstream reads it; `beat_frames(out_dir)` regenerates it from `demo.mp4` and
`timeline.json` without re-recording, and clears the previous run's frames
first:

```python
from demo_recording import beat_frames

beat_frames(Path("demos/2026-07-26-x"))
```

## Per-beat evidence (`evidence/beat-NN.json`)

A reviewing agent handed frames has to infer what the page said from pixels.
The recorder is *driving* the page, so at the end of every beat it also writes
down what was on screen, in text, next to the frame that beat's timestamps
point at. No storyboard changes; it is a byproduct of recording, like the
timeline. `Recorder(..., evidence=False)` or `DEMO_VIDEO_EVIDENCE=0` turns it
off.

```json
{ "schema": 1, "generated_by": "demo-video", "recorder": "Recorder",
  "segment": null, "media": "demo.mp4",
  "beat": { "index": 6, "t_start": 5.31, "t_end": 5.44, "verb": "shot",
            "selector": "01-dashboard", "caption": "A small dashboard.",
            "still": "images/01-dashboard.png",
            "evidence": "evidence/beat-06.json" },
  "scope": "#kpi-rev",
  "url": "http://localhost:3000/", "title": "Northwind Ops",
  "aria_format": "aria-yaml",
  "aria": "- banner:\n  - heading \"Northwind Ops\" [level=1]\n- text: Revenue $128,400 …",
  "scope_aria": "- text: $128,400",
  "html": "<div id=\"kpi-rev\">$128,400</div>",
  "truncated": [], "limits": { "aria": 12000, "html": 8000 } }
```

| Field | What it is |
|---|---|
| `aria` | **`Recorder`**: the page's ARIA snapshot — a compact YAML tree of roles and accessible names, the same thing `expect(...).toMatchAriaSnapshot` compares. Semantic, ~10× smaller than the markup, and stable across restyling, which is why it is preferred over raw HTML |
| `scope` / `scope_aria` / `html` | the current `spotlight()` target: its selector, its own ARIA tree, and its `outerHTML` with every value-bearing attribute stripped. All three are null when no spotlight is up |
| `screen` | **`TerminalRecorder`**: the rendered screen, ANSI resolved by xterm.js, scrollback included — the same text `wait_for_text()` matches against |
| `truncated` / `limits` | which fields were cut, and at what budget. A cut field also says so inline where it stops |
| `error` | present *instead of* the page text when reading the screen raised. Capturing evidence is a diagnostic and must not cost an otherwise fine take, so the file is written anyway, saying what went wrong — which keeps every beat's `evidence` pointer resolving. `timeline.json` is unaffected |

### What evidence does and does not carry

**Nothing here is hidden.** This recorder has no masking, no scrubbing and no
redaction (see the top of [SKILL.md](../SKILL.md)), and an evidence file is a
text dump of the DOM or the terminal buffer — so a value the app renders is in
it verbatim, in a form that greps. That is the same exposure the recording
already has; it is worth stating because pixels feel private and plaintext
does not.

Two things are dropped, and neither is a security control:

- **`outerHTML` is only ever the spotlight target's, never the page's.** A
  whole document's markup is an order of magnitude bigger than its ARIA tree
  and carries two things nobody put on screen: the text of every inline
  `<script>`, and `srcdoc` attributes — source code and whole embedded
  documents. The clone that gets serialized drops both, along with `<style>`
  and the recorder's own overlays.
- **Every value-bearing attribute is stripped** — `data-*`, `title`, `alt`,
  `placeholder`, `aria-label`, `href`, `src` — from every element. An
  attribute nothing renders was in no frame, no still, no caption and no
  narration clip, so serializing it would make evidence the only place it
  exists.

Both are statements about what belongs in a text dump of an element, and
`tests/smoke` grades them directly: the evidence take injects an element
holding a `<script>` and a `srcdoc` and requires neither in the markup.

**Fields are capped** — 12 000 characters of ARIA or screen text, 8 000 of
markup — and truncation is **marked, never silent**. A TUI's scrollback is
5 000 lines, and an uncapped `evidence/` outgrows the mp4 it describes.

**Evidence is not committed.** Gitignore `evidence/`. It is a byproduct
regenerated on every take, it churns completely on each re-record, and — the
reason that matters — it is greppable plaintext of a real app's DOM, which is
exactly the thing a git history should not carry permanently and cannot be
made to forget afterwards. `timeline.json` and `timeline.md` stay the
committed, diffable record of what the demo showed.

### Naming, and merged segments

A beat's `index` is its position in **its own take**, so two segments of one
demo both start at 0. Two things make that a non-event: a segment's evidence
carries the segment in its filename
(`evidence/part1.seg.beat-03.json`, mirroring `<segment>.seg.timeline.json`),
and the path is written **onto the beat** as `evidence` rather than derived
from `index` by whoever reads the log. Read the pointer, never rebuild it —
then a merge that renumbers beats has only to carry the string across, and
every evidence file names its own `segment` and `index` internally anyway.

## Recording against a ticket (`coverage`)

A demo can be perfectly clear and demonstrate the wrong thing. The fresh-agent
review in step 6 answers *"is this story clear?"*; a review gate has to answer
*"does this show what the ticket asked for?"*, which is a different question
with a different answer.

Declare the criteria on the recorder and tag the beats that demonstrate them:

```python
with Recorder(OUT, criteria={
    "AC-1": "The queue can be filtered to one status.",
    "AC-2": "A filter that matches nothing explains itself.",
    "AC-3": "The CLI prints the same filtered list.",
}) as rec:
    rec.goto("/")
    rec.caption("Filtering to one status.", ac="AC-1")
    rec.shot("01-filtered", ac="AC-1")
    rec.caption("Nothing matches, and the queue says why.", ac="AC-2")
    rec.shot("02-empty", ac="AC-2")
```

`timeline.md` then carries a table above the beats, and `timeline.json` a
`coverage` object:

```
| criterion                                   | claimed by | at   | still                 |
| **AC-1** — The queue can be filtered…       | beat 1     | 3.20 |                       |
|                                             | beat 2     | 5.46 | `images/01-filtered…` |
| **AC-2** — A filter that matches nothing…   | beat 3     | 7.10 | `images/02-empty.png` |
| **AC-3** — The CLI prints the same…         | *nothing claims this* |    |            |

**1 of 3 criteria have no beat claiming them: `AC-3`.**
```

### What this does and does not tell you

**The report is what the storyboard *claimed*, never what it proved**, and every
name in it says so — `claimed` and `unclaimed`, not "demonstrated" and
"missing". An `ac=` tag is a string you typed. A beat tagged `AC-3` whose frames
show an error page is still tagged `AC-3`.

That is not pedantry about naming. The failure this feature exists to catch is
the **tautology**: a storyboard derived from the diff rather than from the
ticket produces a polished, convincing demo of a misread requirement. If this
file said "AC-3 demonstrated", the conformance reviewer below would be taking
your word for the exact thing it was convened to check.

So there is one machine-checkable finding here, and it is `unclaimed` — safe to
automate precisely because it takes no judgement: nobody even asserted those.
Everything else is the reviewer's call, and the artifact's job is to put them in
front of the right frames.

### Rules that follow

- **Derive the storyboard from the ticket, the ADR or the RFC — not from the
  diff.** A scenario generated from the implementation cannot fail to match it.
  Write the criteria down first, then work out how to show each one.
- **Criteria are declared up front**, not accumulated from the tags. The useful
  half of the report is the criteria *nothing* claimed, and that cannot be
  derived from the tags alone.
- **A tag naming an undeclared criterion raises.** Left through, the criterion
  you meant comes back unclaimed while the storyboard looks complete — wrong in
  the one direction nobody checks. Fix the typo at the line that made it.
- **Most beats claim nothing**, and that is ordinary: navigation, waits and
  scene-setting captions are not demonstrating anything in particular. Tag the
  moment a reviewer should look at, not every beat.
- One beat may claim several criteria (`ac=["AC-1", "AC-2"]`) when one screen is
  the evidence for both.
- Without `criteria=`, `coverage` is `null` and `ac=` is refused. A take
  recorded outside a ticket has no coverage to report, and an empty report would
  read as a take that covered nothing.
- On a **segmented** demo, `stitch()` recomputes coverage over the merged beats
  against the union of the segments' criteria — so the joined timeline can name
  a criterion *no* segment claimed, which neither segment's own report could.
  Segments declaring different text for one id are reported as a conflict rather
  than silently resolved.
