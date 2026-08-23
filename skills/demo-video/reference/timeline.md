<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# The beat timeline, and whether the recording showed anything

> Read when interpreting `timeline.json` / `timeline.md`, when a take warns about its content, or when writing anything that consumes the beat log as a contract.

## The beat timeline (`timeline.json` / `timeline.md`)

Every storyboard verb is logged as a **beat** — what was done, when, and what
caption was on screen while it happened — and exiting the `with` writes the log
next to the media, whether or not the storyboard finished. No storyboard
changes are needed; it is a byproduct of recording.

`timeline.md` is the readable version: a table of every beat, then each still
**the take actually wrote** embedded under the caption it was taken during — a
`shot()` whose screenshot raised stamped its path on the beat before it took
the picture, so that beat contributes no gallery entry at all
([#305](https://github.com/rogvid/skills/issues/305)); the beat table above
still carries its row, marked **raised**. Directly above that table it
says when the host's wall clock **stepped** during the take, and by how much —
the times in the table are `time.monotonic()` and `demo.mp4` is on the wall
clock, so a step parts the two (`timeline.json`'s `capture_clock` carries every
step; [limits.md](limits.md) has the measurement, and
[#229](https://github.com/rogvid/skills/issues/229) is why this is printed).
When nothing could watch
that clock it says *that* instead, which is a different answer from silence.
**Commit both.** They are
small, diffable, and unlike `demo.mp4` they survive as a record of what the
demo showed after the video has been regenerated or thrown away — which is
what makes them worth reviewing in a PR.

**A segmented demo gets exactly the same pair, written by `stitch()`.** Each
segment records `<segment>.seg.timeline.json` beside its `<segment>.seg.mp4`,
with timestamps relative to that segment's own start; `stitch()` merges them
into one `timeline.json` / `timeline.md` next to `demo.mp4`, moving each
segment's beats by the **real duration** (ffprobe) of the parts before it.
Commit the merged pair; gitignore the `*.seg.timeline.*` parts with the
segment media, exactly as you gitignore `*.seg.mp4`. `stitch()` deletes them
along with the `.seg.mp4` files unless you pass `keep_parts=True`, which keeps
both so one expensive segment can be re-recorded and re-stitched.

`timeline.json` is the machine-readable one, and a stable contract — adding a
key is fine, renaming one is not:

```json
{ "schema": 1, "generated_by": "demo-video", "recorder": "Recorder",
  "segment": null, "media": "demo.mp4", "duration": 18.04,
  "strict": false, "issue_count": 1,
  "beats": [
    { "index": 4, "t_start": 3.02, "t_end": 3.06, "caption": "A small dashboard.",
      "verb": "shot", "selector": "01-dashboard",
      "still": "images/01-dashboard.png", "segment": null, "segment_index": 4 }
  ],
  "issues": [
    { "kind": "console_error", "t": 0.47, "beat": 0, "verb": "goto",
      "caption": "", "message": "Cannot read properties of undefined",
      "url": "http://localhost:3000/app.js", "line": 412 }
  ] }
```

- `t_start` / `t_end` are seconds from the start of `media` — the verb
  starting and returning. A verb built out of other verbs (`click` glides
  first, `type_into` clicks first) is one beat, not one per internal step.
- `caption` is the line on screen during the beat: the new text for a
  `caption` beat, the line shown for an `interlude`, the declared clause a
  `criterion` card carries, `""` when none is up.
- `selector` is what the verb acted on, as a string — a CSS selector for the
  web verbs, the command / keys / pattern for the terminal ones, the name for
  `shot`. `null` for verbs with no target (`pause`, `hold`, a cleared
  `spotlight`).
- `still` is a path relative to the timeline file, so `timeline.md`'s embeds
  and any tooling resolve the same way.
- `evidence` is a path, the same way — the beat's own account of what was on
  screen. See [review.md](review.md).
- `exit_code` appears on `TerminalRecorder` `run` beats — see **Failing the
  take** below.
- `error` appears **only on a beat whose verb raised**, carrying the
  exception's `type` and its `message` verbatim — `wait_for_text()` quotes a
  thousand characters of terminal screen into a timeout, and nothing filters
  that; it is absent from every beat
  that returned. `t_start` and `t_end` are stamped either way, so this is the
  only thing that tells the two apart — do not read a beat as evidence that
  something was demonstrated without checking it. The envelope gains a
  `failure` key on the same terms: absent when the take finished, present with
  `type`, `message`, `beat` and `verb` when it did not (`beat` is `null` when
  the failure happened between verbs and no beat may honestly be blamed).
- `duration` is the length of the mp4 **this take encoded**, and is `null`
  when it encoded none — even if a `demo.mp4` from an earlier run is sitting
  right there. A null is the honest answer; the previous take's number is not.
- `issues` is what the recorder saw *behind* the pixels; `issue_count` is how
  many it saw, and is larger than `len(issues)` only when a take blew past the
  200-issue cap.
- `index` is the beat's position **in this file**, so `stitch()` renumbers it
  across a merged demo. `segment` and `segment_index` (its position within its
  own segment) survive the merge untouched — use that pair, not `index`, to
  name a beat in anything that has to line up across a re-stitch.
- `content` is the only key here that describes the **frames** rather than the
  storyboard. See the next section.

### `content` — did the recording show anything?

Every other field above is a statement about what the storyboard *did*, and all
of them can be exactly right while the recording shows nothing: a title card
left up, a modal that never closed, an app that stopped painting. That happened
here, on this skill's own reference demo — a card covered the terminal for 24.3s
of a 60.2s take, and the beat table, the exit codes, the evidence files and the
stills all read like a healthy demo.

So the recorder also measures the picture, over the region the app occupies in
the encoded frame, and writes down what it found:

```json
"content": { "measured": true, "note": null,
             "rect": [74, 110, 1132, 432], "sample_fps": 2, "frames": 47,
             "score": 14.1, "floor": 1.0,
             "static_for": 21.5, "static_from": 3.5, "static_limit": 15.0,
             "static_beats": [{ "index": 6, "verb": "caption", "acting": false },
                              { "index": 7, "verb": "hold", "acting": false }],
             "opening": { "gap": 0.7, "held": null, "limit": 1.5, "note": null,
                          "card": null },
             "warnings": [] }
```

- `score` is the median luma standard deviation over `rect`. Under `floor` the
  frames are featureless — a page that never painted, a take recorded black.
- `static_for` is the longest stretch, in seconds, where **nothing inside
  `rect` changed**, and `static_from` is when it started. Both are reported
  always, whatever they are.
- `static_beats` is what the storyboard was doing during that stretch, and it
  is what decides whether the stretch is worth a warning. See below.
- `warnings` is empty on a healthy take, and each entry is one sentence saying
  what to go and look at. They are also printed on stderr as the take ends, so
  an author who never opens this file is still told. One entry does not come
  from the frames at all — see *An overlay the recorder left up* below.
- `measured` is `false`, with `note` saying why, when the check could not run.
  `content` itself is `null` only when the take encoded no mp4.
- `opening` says what the take opened on. Read the next section: on a web
  take a short featureless `gap` is the wrapper's own opening hold, which is
  deliberate. On a terminal take `opening.card` says whether the segment's
  first frame was its title card or a bare terminal.

**What the take says out loud, and on which stream.** Which line the take
prints decides the stream: **anything wrong — a warning, or the note that the
check could not run — goes to stderr; the healthy `shows a picture` line goes
to stdout.** A take takes at most one of those branches and never both: a take
that warned prints no `shows a picture` line, a take that printed one recorded
no warnings, and a take that encoded no mp4 has no `content` to report and says
nothing here at all. So capturing one stream in a script never gives you half a
summary; it gives you the whole summary of one kind of take and silence for
the other, which is the thing to know before redirecting either.

### `opening` — a web take opens on the wrapper hold, on purpose

Chromium starts recording when the page is created, before your first
`goto()` has an app to show. A recorder that did nothing about that would
open every demo on a flat white app rect inside a correct-looking window —
which reads as *the app loaded blank*, and is the most plausible-looking way
a demo can misrepresent an app.

So a web take's frame 0 is the **opening hold**: an opaque field in the
window's own colour over the app rect, up before anything else paints and
faded out by the first `goto()` — the moment there is an app to reveal. It
is chrome the recording really captured, not a composited still, so nothing
about the video is retouched: the duration, the audio and every beat
timestamp are exactly what they were. The review sheet names the frames
that were cut inside it (`frames.md`), so a flat dark window under a `goto`
heading is documented as the hold rather than left to read as a failed
load.

`gap` is measured afterwards, off the encoded mp4: on a healthy web take it
is the hold's own featureless stretch (a few hundred milliseconds to a
second), and it is a description, not a warning. `held` is how many seconds
a take's *encode* covered with a composited still; no current recorder does
that (the exit-time composite that did went with #361), so `held` is `null`
on every take and `limit` keeps the scale the numbers were tuned against.
Only a recorder that claims to cover can warn about a gap it failed to
cover.

On a terminal take the equivalent is the opening card; open a terminal
segment on one if you want its first frame to be deliberate (see *Opening a
terminal segment on a title card*).

### `opening.card` — what a terminal segment's first frame showed

A terminal take reads its own frame zero after the encode and writes down what
was there:

```json
"card": { "luma": 25.8, "state": "card", "raised": true,
          "rect": [1214, 0, 58, 50],
          "card_max": 60.0, "bare_min": 150.0, "note": null }
```

- `luma` is the mean luma of a strip of background **beside** the terminal
  window on the segment's first frame. Outside the window on purpose: inside
  it a title card and a terminal are both dark and telling them apart means
  reading text. Outside it the card (`#1c1a17`, full bleed) reads ~26 and the
  recorder's pastel background reads ~226.
- `state` is that number as a word: `"card"`, `"bare"`, or `"between"`. The gap
  between the two bars is wide and deliberately empty — a frame that lands in
  it is a card still becoming opaque, and calling that either thing would be
  this file claiming something nobody measured.
- `raised` says whether the take asked for an opening card
  (`TerminalRecorder(interlude=…)`). It is what makes `"bare"` readable: on a
  take that asked, `"bare"` is the flash issue #110 is about; on a take that
  did not, it is simply what the segment opens on.
- `note` says why when there is no reading. `luma` and `state` are then `null`
  rather than a guess.
- `card` itself is `null` on a web take — there is no window to read beside.

**Nothing enforces it.** No warning, no refusal, no failed take: one CI run in
nine has read a value in the empty band on a loaded runner, and a bar that
refused there would be unreliable exactly where it would be trusted most. This
is a number to read, and the reason it exists is that the mp4 is the one
artifact a demo directory does not commit — so without it, "does part 2 open on
its card" can only be answered by watching.

### An overlay the recorder left up is reported exactly

Every other number in `content` is measured off the encoded mp4. One warning is
not: at the end of a take, while the page is still alive, the recorder asks it
whether `#__demo_interlude` or `#__demo_bridge` — the two elements `interlude()`
creates — is still visible. It built them, so this is a fact rather than an
inference, and the warning names the id.

It exists because the score arm gets this case *backwards*. A `style="light"`
scrim is a radial gradient, and a gradient across the measured rect adds
variance — which is what `score` is. Measured on three takes of one storyboard:
**32.94** and **32.95** with the scrim over the app against **26.74** clean.
The covered takes scored 23% higher, and all three printed
`demo.mp4 shows a picture`.

A take that ends with an overlay up now gets the warning, on stderr and in this
file, and no `shows a picture` line. What it does **not** cover: an app's own
modal (it only knows its own two elements), an overlay raised and cleared in the
middle of a take (only the end is checked), and a take that encoded no mp4
(`content` is null there). See [limits.md](limits.md).

### A long held stretch is not a problem, and this is the part to understand

The example above holds one picture for **21.5s** — well past `static_limit` —
and produces no warning at all. That is correct, and it is not a special case:

> `static_for` on its own cannot tell a healthy demo from a broken one.

Measured on real takes: a demo touring a rendered screen with three captions
holds the measured region for **20–22s**. The title card that covered this
skill's own reference demo held it for **23s**. There is no threshold between
those two numbers, because the region measured excludes the recorder's caption
bar — and swapping captions over a still screen is exactly what this guide tells
you to do during a wait.

So the warning needs a second condition: **did a verb that acts on the app run
inside the stretch?**

| beats inside the held stretch | verdict |
|---|---|
| `caption`, `criterion`, `hold`, `interlude`, `pause`, `shot`, `wait_for`, `wait_for_prompt`, `wait_for_text` | narrated hold — silent |
| `clear`, `click`, `click_fast`, `goto`, `key`, `move_to`, `press`, `run`, `scroll_to`, `send`, `spotlight`, `terminal`, `terminal_close`, `terminal_output`, `type_into` | worth looking at — warns |

Both rows are the whole of `content.py`'s `CONTENT_PASSIVE_VERBS` and
`CONTENT_ACTING_VERBS`, written out name by name rather than summarised. This
skill's own repository holds a `tests/unit` that compares the two rows to those
two sets, so a verb that drifts out of either one fails there rather than
shipping as a table nobody grades (#289).

Both interlude styles log as the verb `interlude`, with `selector` carrying the
style (`"card"` or `"light"`) — there is no separate verb for the light one.

A `run()` that printed nothing visible, a `click()` that moved nothing: those
are the shapes worth a human's two minutes. A caption change over a screen
nobody touched is not.

**What the warning does and does not claim.** It states what was measured — the
stretch, the acting beats inside it, and the region — and then says plainly that
an overlay left up, an app that stopped painting, and a demo that legitimately
holds still through those verbs all look identical from here. It does **not**
name a cause. It cannot know one, and an artifact that confidently attributes
something to the wrong place is the failure this whole field exists to remove.

**It warns; it never fails a take.** Treat a warning as "watch the video at this
timestamp before believing the beats", not as a verdict.

**It does not judge whether the demo shows the _right_ thing** — only whether
it captured anything at all. `rect` deliberately excludes the recorder's own
window chrome and its caption bar: a whole-frame score is dominated by them, to
the point where a recording with the app painted flat scores *higher* than a
working one.

**Five limits worth knowing before you rely on it:**

- **A held stretch containing only narration is never reported.** This is the
  verb correlation doing its job, and it is also the one blind spot that can
  hide a real fault: a demo that raises a card (`interlude()`, `criterion()`)
  and then only captions, holds and takes stills behind it is silent, however
  long the card stays up. Measured: a card over 31.5s of a 34s take, no
  warning. There is no third answer available from the frames — with the
  caption band excluded, an honest tour of a still screen and a card left up
  are byte-identical. If your storyboard raises a card, take it down
  explicitly; do not rely on this check to notice.

- **A caption change is invisible to the held-picture arm, by design.** The
  caption bar is the recorder's own drawing and it renders over an interlude
  card as readily as over the app, so counting it would defeat the detector on
  the exact occlusion it exists for. The verb correlation above is what makes
  that survivable.
- **The bottom fifth of the app is not measured at all** — that is where the
  caption bar sits, and there is no room to shrink the exclusion. On a terminal
  demo that is the last few rows *before the screen starts scrolling*. Once it
  scrolls, every new line moves the whole picture and the blind window closes.
- **A caption long enough to wrap reaches back into the measured region.** The
  bar grows upward, so a two- or three-line caption crosses the exclusion and a
  caption change then does count as the picture changing. Measured at 266 pixels
  per wrap. The effect is to make a held stretch read *shorter* than it is. It
  cannot touch a take occluded by the recorder's **own** interlude card, which
  is opaque and paints above the caption — but an app-level overlay or modal is
  app DOM, the caption paints *over* it, so a wrapping caption can split a real
  occlusion into stretches that each sit under the limit. Measured: 25s becomes
  11s + 8s + 6s, and goes silent. Keep captions to one line if you want
  `static_for` to mean what it says.
- **A run of held frames is measured per segment.** Two parts of a stitched
  demo that each hold still for 8s across the cut are reported as 8s, not 16s.

Three of the five can hide a real occlusion — the first, the fourth and the
fifth. A card behind narration only, a wrapping caption splitting an app-level
overlay into short stretches, and a hold that straddles a segment cut each
produce a clean report on a take that shows nothing.

The second and third cannot: excluding the caption bar, and not measuring the
bottom fifth, both mean *less* of the picture counts as moving, so a stretch
grows rather than shrinks. They push toward reporting a hold that is not there,
not toward missing one.

**A silent content report is not a guarantee that the demo shows your app.** It
rules out the two loud failures — a recording that never rises above blank, and
a screen that never moved while a verb was acting on it — and nothing more.

On a stitched demo each part measures its own `.seg.mp4` — two segments can be
two media with two geometries — so the envelope's `content` is the worst of the
parts on each arm with `rect: null`, every warning tagged with the segment it
came from, and each part's own report under `segments`.

You can re-run it on a demo you already have, without re-recording. Pass the
beat log too — without it the held-picture arm still measures and reports, but
never warns, because there is nothing to correlate the stretch against:

```python
import json
from pathlib import Path
from demo_recording import content_report

d = Path("demos/2026-07-26-x")
doc = json.loads((d / "timeline.json").read_text())
print(content_report(d / "demo.mp4", tuple(doc["content"]["rect"]), doc["beats"]))
```

A merged timeline says so, and says what it was built from:

```json
{ "segment": null, "media": "demo.mp4", "duration": 15.2,
  "recorder": "Recorder",
  "segments": [
    { "segment": "part1", "media": "part1.seg.mp4", "duration": 6.6,
      "offset": 0.0, "beats": 6, "recorder": "Recorder",
      "determinism": {…}, "content": {…} },
    { "segment": "part2", "media": "part2.seg.mp4", "duration": 8.6,
      "offset": 6.6, "beats": 9, "recorder": "Recorder",
      "determinism": {…}, "content": {…} }
  ] }
```

`offset` is where each part starts inside `demo.mp4`, which is what maps a
merged timestamp back to the file it came from. `recorder` and `determinism`
at the top level carry the value every segment agrees on — `"mixed"`, and
`null` per key, where they do not; the per-segment truth is in `segments`. A
timeline a single take wrote has no `segments` key at all.

`ticket` is the exception to that pattern, and deliberately: parts that agree
carry it at the top level, and parts that **disagree** produce
`ticket_conflicts` naming every one of them with no top-level `ticket` at all.
A demo half of which demonstrates another ticket has no single honest answer,
so this one is named rather than resolved — the treatment a disagreement about
a clause's wording already gets ([review.md](review.md)).

`stitch()` refuses before it encodes anything if the parts cannot honestly be
joined: a missing or unreadable `.seg.mp4`, a beat log of the wrong schema or
one written for a *different recording* of that segment, or parts that
disagree on codec, resolution, frame rate or having an audio track.
`concat -c copy` accepts all of those and exits 0, and the damage is invisible
afterwards — a frame-rate mismatch moves every later beat away from its frame,
a resolution mismatch keeps the first part's dimensions, and one silent part
makes concat drop every later part's narration. Recording every segment with
the same `Recorder` settings is what keeps you clear of it.
