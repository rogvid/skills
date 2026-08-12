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
static one twice. Each frame is taken at its beat's **midpoint**, moved onto
the video's own clock (below) — `t_start` is 0% into the caption bar's fade and
before the verb has done anything.

**How accurate that aim is, honestly.** The beat log is `time.monotonic()`;
the video is on the host's **wall** clock, because that is what Chromium
stamps every screencast frame with
([#18](https://github.com/rogvid/skills/issues/18),
[#215](https://github.com/rogvid/skills/issues/215)). (It is *not* dropped
idle time — that explanation was measured and retracted; see
`limits.md`.) So a frame cut at a beat's midpoint shows a moment slightly
*ahead* of that beat in the demo's own story — measured at **80–200 ms** on
instrumented takes with a steady host clock, and by however much the host's
wall clock moved during the take on one that does not: **1.50 s** by 13.5 s
into a take on the WSL2 box of
[#247](https://github.com/rogvid/skills/issues/247), with no fixed bound.

**The second of those two is corrected, and the first is not**
([#229](https://github.com/rogvid/skills/issues/229)). Each frame is cut at
its beat's midpoint **plus the wall-clock steps its own capture recorded
before that midpoint** — the instant being converted, not the beat's start, so
a step landing inside a beat's first half moves that beat's frame — read out of
`timeline.json`'s `capture_clock`; corrected that way,
38 caption transitions over six takes landed within 101 ms of the log where the
uncorrected cut was out by up to 1.50 s. The timestamps in `frames.json` and
`frames.md` are **already on the video's clock** — do not apply
`capture_clock` to them a second time.

**A beat can have no frame at all, and the sheet says which**
([#256](https://github.com/rogvid/skills/issues/256)). A backward step of Δ
does not slide the video: it takes a Δ-wide window of wall time *out of the
file*, because the encoder will not write a frame stamp it has already
written. A beat inside that window was never encoded, so its frame is the last
one before the gap — `frames.json` gives it a `no_video` (how many seconds
later the video resumes) and `frames.md` names it, above the table and beside
the picture. Read such a frame as the moment the demo had reached when the
clock moved, not as the beat. Without the clamp the cut lands up to a whole
step early, which is how `seg-run1`'s `beat-05.png` came out showing the
previous caption.

`frames.md` says which of the three cases the take was, because a corrected
sheet and an uncorrected one are otherwise the same document: the clock
stepped and the frames were moved, the clock was watched and held still, or
**nothing could be corrected** — no record, or a sampler that says it could
not watch (`capture_clock.measured` false). In that last case the frames are
cut on the raw beat log and the sheet says so; treat their aim as unbounded.

The practical consequence, for what is left: for a beat comfortably longer
than that, the frame is of that beat; **for a beat shorter than the drift — a
bare `shot()`, a `wait_for()` that returned immediately — the frame can be of
the beat after it.** This was measured directly, by this repo's `tests/smoke`
rather than by anything shipped with the skill: with the drift allowance
removed, the frame for a 50 ms `shot()` beat that sits against a caption change
is already showing the next beat's screen.

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
caption does, and a mid-take `goto()` destroys the bar a beat before the log
says so — see [#134](https://github.com/rogvid/skills/issues/134)). [#60](https://github.com/rogvid/skills/issues/60) is how the
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

## Why the comprehension review reports contradictions separately

Step 6's reviewer answers four questions, not three, and the fourth — the
CLEAR/UNCLEAR verdict — is deliberately narrowed to *could you follow the
story*. Two failures made that necessary, and both are worth knowing about
before you write the prompt differently.

### A caption leads its evidence, by design

The pacing rules tell a storyboard author to set the caption **first** and then
perform the action it introduces, so the eye is already pointed where the change
will happen. That is right for a viewer, who experiences the caption as a
sentence spanning several seconds with the click as an event inside it. It is
wrong for a frame reviewer, who sees one instant per beat and finds the caption
asserting something the pixels under it do not yet show.

Asked "name any caption that asserts something the picture does not show", a
reviewer given no warning can answer *"all of the ones written the way the skill
prescribes"* — and a gate whose output is mostly artifact gets skimmed, taking
the real entry with it ([#95](https://github.com/rogvid/skills/issues/95)
measured a list of four, of which three were this).

So the prompt states the lead. It does **not** tell the reviewer to ignore
caption/picture mismatches, which would remove the finding the section exists
for. The discriminator is *does the evidence ever arrive*: a caption still
waiting for its picture is the house style; a caption whose claim no later frame
shows, or that a later frame shows the opposite of, is a finding. That is a
question about the whole sheet rather than one frame, which is exactly why the
reviewer is asked to name the frames it checked.

### A caption the app contradicts is not a recording defect

The verdict used to carry this too, and it was unstable. On the reference take
kept in this repository at `examples/ticket-queue/demos/2026-07-28-queue-search/`
— recorded against a
ticket one of whose criteria the app does not satisfy, with the beat claiming it
kept and captioned in the ticket's own words — two independent reviewers given
the same frames and the same instructions returned **UNCLEAR** and **CLEAR**.
Both named the same beat, correctly, in the same terms. The finding was stable;
the ship/no-ship field was a coin flip
([#131](https://github.com/rogvid/skills/issues/131)).

The reason is that one verdict was being asked to carry two different faults:

- **"I could not follow this."** The storyboard is at fault, and re-recording is
  the fix.
- **"I followed it, and the screen disagrees with the words."** The *app* is at
  fault. Re-recording cannot help, and the three things that would make the
  contradiction go away — delete the beat, editorialise the caption, choose an
  input that does not look like the unimplemented case — all hide the finding
  the demo exists to deliver. Followed honestly, the old rule launders the
  result.

Splitting them means the verdict now grades the thing re-recording can repair,
and the contradiction is routed where it can be acted on: the pull request, and
the conformance pass below when the take declared `criteria=`. On a take with
`criteria=` this is sharper still — a caption/picture contradiction on a tagged
beat is 6b's call by construction, and 6b answers it with citations.

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

Both are statements about what belongs in a text dump of an element, and this
repo's `tests/smoke` grades them directly: its evidence take injects an element
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

### What a take that died renders instead

A verb that raises is recorded on its beat (`error`), and the claim that beat
made carries it too. So on a crashed take the acceptance section **leads with
the failure**, before the table — the same ordering `timeline.md` already uses
for "## This take did not finish" — and the row reads:

```
| **AC-3** — The CLI prints the same… | beat 17 **raised TimeoutError** | 31.80 | *not written* |
```

The still is withheld rather than printed. `shot()` stamps the path on the beat
before it takes the picture, so on a take that died there the path names a file
nothing wrote, and printing it sends a reviewer looking for last week's picture.
A clause claimed by a beat that **returned** is untouched, even when the take
died later somewhere else: that claim is as good as any other claim that take
made.

**The `## Stills` gallery at the foot of the same file drops that beat too**
([#305](https://github.com/rogvid/skills/issues/305)). Withholding the path in
the table above and embedding it as a picture twenty lines lower is the same
lie twice, and the picture is the worse half: `images/` is committed, so on a
re-record after a crash the *previous* take's file of that name is already on
disk, and the embed puts a real photograph under this take's heading, this
take's timestamp and this take's caption. The beat table is where that beat
still appears, marked **raised**.

### Put the clause on screen: `criterion()`

Everything above lives in files a viewer never opens. The video — the artifact
this skill exists to produce — never says which clause it is demonstrating, so a
reviewer watching it has to hold the ticket in their head and map what they see
onto it. That mapping is the work the coverage table exists to remove.

`rec.criterion("AC-2")` raises a full-screen card carrying **AC-2's declared
text**, read out of the `criteria=` map:

```python
rec.criterion("AC-1")          # the clause, on screen, in the ticket's words
rec.caption("Typing invoice in lower case narrows the list.", ac="AC-1")
rec.type_into(SEARCH, "invoice")
rec.wait_for(".ticket")
rec.shot("02-invoice", ac="AC-1")
rec.interlude("")              # take the card down before the next scene
```

The point is that the sentence is **not a string the storyboard retyped**. There
is one string, and the card, the coverage table and the quote a drift check
compares against the ticket are all reading it — so a storyboard cannot show a
viewer one requirement while claiming another.

- **The card claims its own criterion** (`ac=["AC-1"]`) and appears in
  `coverage` like any other claim. It is the cheapest claim to make and the
  weakest evidence there is: it proves the clause was *said*, not shown. Tag a
  `shot()` as well, or the reviewer has a sentence and no picture.
- **It tags nothing after it.** The beats that follow are untouched. An implicit
  claim is a label nobody typed, and in `coverage` it is indistinguishable from
  one somebody did.
- **One id, not a list.** A card shows one sentence; handed two it would have to
  drop one silently. `caption(ac=[...])` is where a screen claims several.
- **Refused** when the id was never declared, and when the take declared no
  `criteria=` — the same two refusals `ac=` makes, at the line that made them.
- **It is the `interlude()` card.** `interlude("")` takes it down, and the "card
  left up" warning applies unchanged: take it down explicitly, because a card
  over the rest of the demo is the one thing no check reliably notices
  ([limits.md](limits.md)).
- **`hold` defaults to reading speed** over the words in the clause (floored at
  2.8 s, capped at 9 s), and to the whole spoken line when narration is on. A
  clause too long to read inside the cap is a clause too long for a card: quote
  the sentence rather than the paragraph, or pass `hold=` and accept the cost.

**What nothing here grades: whether the clause is legible in the frame.** "The
text reached the page" is not "a human can read it" — a card that renders
off-frame, clipped, or under an app overlay satisfies every assertion this
skill's own suites make (they live in this repository, in `tests/`). That is a
judgement about pixels, and it is answered the way this skill answers every
such question: somebody watches the video (Process step 6).

That is not a theoretical gap. This card was painted the same near-black on a
web demo as on a terminal one from the day the recorder had two media until
[#291](https://github.com/rogvid/skills/issues/291), so inside the web
recorder's own dark window frame — title bar, traffic lights — a viewer read it
as *a terminal window* rather than as a card over the app. The element, the
beat, the coverage row, the snapshot and the frames were all correct
throughout, and the person who found it was watching. Note what the defect
was *not*: the card had always stopped at the app rect, with the frame drawn
around it. It was 1.3 luma levels from that frame, so the boundary existed and
nobody could see it. A web card is now the window's own body colour, which is
what that same person asked for after seeing three rounds of alternatives —
and "the same colour" turned out to mean *in the encoded video*, not in the
stylesheet. The window frame reaches `demo.mp4` as a screenshot and the card
reaches it through the page recording, so one declared colour arrives as two
([#301](https://github.com/rogvid/skills/issues/301)); the card is declared a
couple of levels off the window so that the two land together, and what
`tests/` grades is where they land. **Nothing grades whether a viewer reads
the result as a card** rather than as one flat surface; watching is the only
thing covering that.

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

### What a take is evidence about, and what stays the diff's to answer

Everything above defends against one failure: the artifact **claiming** more
than it earned. This is the other one, and it is the likelier way this skill
hurts somebody — the artifact **implying** more than it covers.

A demo can show that a ticket's clauses were met. It cannot show that the
change does *only* that. Every criterion can be declared, claimed, illustrated
and watched, and the same pull request can delete a rate limiter, widen a
permission, drop an authorisation check or add a dependency: the recording is
silent about all four. Not because the recorder missed them — because they are
not things a screen does. There is no frame in which a removed guard is
visible, and no storyboard that could film one.

So watching a take replaces reading the diff for exactly one question: *were
the declared clauses shown?* It is a real substitution and a narrow one, and
the danger is a reviewer who has generalised it — "the demo is green, so the
ticket is done" is half of a review being skipped by somebody who was never
told which half. The pull-request comment this repository's workflow renders
therefore says so above the clause table, in a sentence, on every take recorded
against a ticket.

**There is deliberately no number beside it.** Files changed against paths the
take exercised, criteria against lines of diff, a percentage of anything — each
is a count standing in for content, and each would be read as a bound on what
got past. A demo that touched 90 % of the changed files is not 90 % reviewed.
Worse, the number is the part people remember: it would manufacture exactly the
confidence the sentence exists to withhold, and it would do it with a figure
nobody could argue with. The honest artifact here is a sentence, not a
measurement.

Stated the way the security absence at the top of [SKILL.md](../SKILL.md) is
stated, and for the same reason: this is a scope limit, not a gap waiting to be
filled. A demo that graded the whole change would have to be trusted. This one
only has to be watched.

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
