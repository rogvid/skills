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
the demo's own story — measured at **40–120 ms** on instrumented takes, and up
to **~600 ms** on a take that loses the browser's start-up window whole (about
1 in 12). The practical consequence: for a beat comfortably longer than that,
the frame is of that beat; **for a beat shorter than the drift — a bare
`shot()`, a `wait_for()` that returned immediately — the frame can be of the
beat after it.** `tests/smoke` measures exactly this and shows it: with the
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
downstream reads it; `beat_frames(out_dir)` from `demo_recording` regenerates
it from `demo.mp4` and `timeline.json` without re-recording, and clears the
previous run's frames first.

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
| `omitted` | present *instead of* the page text when the recorder would have had to guess — see below. `timeline.json` is unaffected |

**`outerHTML` is only ever the spotlight target's, never the page's.** A whole
document's markup is an order of magnitude bigger than its ARIA tree and
carries two things nobody put on screen: the text of every inline `<script>`,
and `srcdoc` attributes — i.e. source code and whole embedded documents. The
clone that gets serialized drops both, along with `<style>`, the recorder's own
overlays, and anything `redact()` is covering.

Fields are capped (12 000 characters of ARIA or screen text, 8 000 of markup)
and truncation is **marked, never silent** — a TUI's scrollback is 5 000 lines,
and an uncapped `evidence/` outgrows the mp4 it describes.

### Evidence is plain text — what that means for secrets

**This is the artifact where a secret is cheapest to find**, and it is worth
being blunt about why: everything else this skill writes is pixels, and
`redact()` is a *pixel* control. It covers where a value renders. The value is
still in the DOM — and an evidence file is a text dump of that DOM. "It is
blurred in the video" is no protection here at all.

So evidence is masked twice over, and the second one is what makes redaction
carry across:

- every registered secret (`register_secret()`, a typed `Secret`) is replaced
  with `[redacted]`, as everywhere else;
- **the rendered text of everything `redact()` is covering** is read out of the
  page as the take runs — the matched element and every node under it, shadow
  roots at every depth, light DOM assigned into a `<slot>`, `::before`/`::after`
  content, input values, value-bearing attributes, and any element an
  `aria-labelledby` points at, however far away it is — and every occurrence of
  any of it is replaced too, in every beat's evidence, including beats recorded
  before the value first appeared. `redact()` never tells the recorder what the
  element *says*, so this is the step that turns a pixel control into a text
  one. Whitespace is elastic on both sides of the match: `textContent` carries
  the source's own indentation and an ARIA tree does not, and a value on its own
  line in hand-written HTML is otherwise the most ordinary leak there is;
- markup is elided structurally as well as by substring, because a value split
  across tags (`sk-live-<b>FAKE</b>`) has a `textContent` a string mask finds
  and an `outerHTML` it does not. Where the split value is a *registered* one
  rather than a redacted element's, the markup is **withheld** for that beat
  with a line saying so — there is no safe way to edit a value out of a
  serialization that interleaves it with elements;
- `outerHTML` also drops every value-bearing attribute — `data-*`, `title`,
  `alt`, `placeholder`, `aria-label`, `href`, `src` — from every element, not
  just redacted ones. An attribute nothing renders was in no frame, no still,
  no caption and no narration clip, so serializing it would make evidence the
  only place it exists.

**A harvested string is only used as a mask if it renders nowhere outside the
mask.** Harvesting every node of a redacted card also harvests its label, and
`redact("#revenue-card")` would otherwise register "Revenue" as a forbidden
literal and rewrite every unrelated paragraph in every file. That rule is not a
guess about what a secret looks like: a string that renders in the clear
somewhere the mask does not cover is already in the frames and the stills, so
masking it in a text file buys nothing and costs the file its meaning.

"Renders outside" means **painted**, which is narrower than it sounds, and every
relaxation of it has been a leak:

- only **text nodes and `::before`/`::after` content** count. An attribute never
  does — not `title`, `alt`, `placeholder`, `aria-label`, `data-*`, `content` or
  `srcdoc` — and neither does an input's `value`. A copy-to-clipboard button
  carrying the key it copies in `title` is ordinary UI, and it was enough to
  exempt that key from masking in every evidence file *and* in `timeline.json`.
  The same reasoning already strips those attributes out of `html`;
- **hidden means hidden by any mechanism the browser will admit to**:
  `display`, `visibility`, `opacity`, `content-visibility`, a box under 2×2 CSS
  pixels (the screen-reader-only clip), and a box entirely off the top or left
  of the document (the `-9999px` skip link). Only `display:none` was excluded
  for one round, which was the one shape the fixture happened to use;
- `<script>` text does not count — it is source, not screen;
- light DOM slotted into a redacted element counts as *inside* it;
- and **the recorder's own caption bar does not count at all** — captioning a
  redacted value would otherwise exempt it from masking everywhere, turning one
  mistake in the frames into the same mistake in `timeline.json`.

What is left uncovered is occlusion: an element painted underneath an opaque
sibling, or clipped away by a `clip-path` on an ancestor, still counts as
rendered ([issue #69](https://github.com/rogvid/skills/issues/69)).

Nothing reaches the disk until the take exits cleanly and the mask has been
verified: the documents are built in memory and written beside `timeline.json`,
so a take that dies on a `SecretLeak` has no evidence file to delete — and a
take that *succeeds* first deletes any evidence a previous recording into the
same folder left behind, since re-running `record.py` into the same directory is
the normal way to use this skill and yesterday's files would otherwise sit there
holding the value you just added a `redact()` for. If a document cannot be made
safe, the take fails.

**A page that repaints while it is being read gets no page text.** The ARIA
snapshot is a protocol call and the harvest is a page evaluation, so they cannot
be one operation: a card rewritten on a 5 ms interval — a countdown, a ticker,
a rotating token — hands the harvest one value and the snapshot the next. The
harvest is therefore taken on both sides of the snapshot and the two must agree;
if they will not settle, that beat's evidence is written as `{"omitted": …}`
with no `aria`, `scope_aria` or `html` in it. On a page where something inside a
redacted region never holds still, expect most beats to come back that way —
`timeline.json` is unaffected, and it is the safe direction.

**What it still does not cover:**

- **`TerminalRecorder` has no `redact()`** (that is
  [issue #5](https://github.com/rogvid/skills/issues/5)), so `screen` is the
  whole terminal, scrubbed for registered secrets only. A command that
  *prints* a value nobody registered writes it here verbatim — the same
  exposure the recording already has, in a form that greps.
- **`url` and `title` go through the registered-secret scrub and nothing
  else.** A token in a query string that nobody registered lands in the file —
  `redact()` cannot name it, because nothing renders it, and the harvest that
  turns redaction into text masking therefore never sees it. If your demo
  navigates through a magic link, a `?token=`, or a session id in a path,
  `register_secret()` it: that is the author's job and there is no mechanism
  here that does it for you
  ([issue #50](https://github.com/rogvid/skills/issues/50)).
- **Accessible names are still names.** `alt` and `title` become an element's
  accessible name, so they are in `aria` by design even though they are
  stripped from `html`. That is what a screen-reader user perceives; if it is a
  secret, redact the element.
- **Matching is exact, modulo a stated list of transformations — and that list
  is the boundary, not a promise to keep growing.** Every leak this feature has
  had was the same shape: a comparison between a value somebody registered and
  a transformation of that value the code did not anticipate. Three are
  handled, and they are handled by normalizing rather than by special cases:

  | Transformation | Where it comes from | How it is matched |
  |---|---|---|
  | whitespace the value has, the text does not | `textContent` keeps the source's indentation; an ARIA tree does not | a run of whitespace in the value matches any run in the text |
  | whitespace the text has, the value does not | a terminal wrapping at the last column; anything that reflows | inside a token of 8+ characters, every character may be followed by whitespace |
  | HTML entities and character references | `outerHTML` writes `&` as `&amp;`, NBSP as `&nbsp;` | entities are resolved before the check, in `html` and in the end-of-document guard |
  | JSON string escapes | the guard runs over the serialized document, where a newline is `\n` | resolved the same way, so the guard cannot miss what the mask missed |

  **Not** handled, and not planned: case differences, Unicode normalization
  forms and confusables, percent- / base64- / backslash-encoding, a value the
  app itself reformats (inserted hyphens, an ellipsis, a thousands separator),
  and a value split across two elements that are not both redacted. This is an
  asymptotic surface; a demo whose secret survives one of those is a demo whose
  author should `redact()` the element rather than rely on a string match.
- **The ARIA snapshot needs Playwright ≥ 1.49.** Older versions get a null
  `aria` and an `aria_format` saying so, rather than a fallback nobody tests.

**Evidence is not committed.** Gitignore `evidence/`. It is a byproduct
regenerated on every take, it churns completely on each re-record, and — the
reason that matters — it is greppable plaintext of a real app's DOM, which is
exactly the thing a git history should not carry permanently and cannot be
made to forget afterwards. `timeline.json` and `timeline.md` stay the
committed, diffable record of what the demo showed; evidence is for the
reviewer looking at *this* take, alongside `demo.mp4`, which is not committed
either.

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
