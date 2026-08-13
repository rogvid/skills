<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# The boundary: what this does not do

> Read when planning a demo the 60-second budget will not hold, when a take's artifacts seem to disagree with each other, or before reading a green suite as coverage. SKILL.md's **What this does not do** is the summary; this is each limit with the measurement behind it.

Everything here was measured and then left in place. That is a decision, not a
backlog: recording a real application faithfully is an asymptotic property, and
a project that tracks every gap in one as an open defect implies a swarm of
latent bugs and converges on nothing. Declaring the boundary instead means a
newly found gap outside it is a line in this file, and an author who knows the
boundary can work around it. Each section names the issue it supersedes, and
carries that issue's numbers, so the evidence outlives the issue.

Some limits live elsewhere and are not repeated. The recorder hides nothing that
reaches the screen — the top of [SKILL.md](../SKILL.md), and the reason there
is no masking verb. A frozen clock changes what an app does and usually does it
silently, and every boundary about the recorder's own cursor sits beside it —
when the dot is drawn at all, why a verb landing on exactly `(0, 0)` draws
nothing, and when a move can be dropped outright — [determinism.md](determinism.md).

## What the recorder will not notice about your app

### A demo of an error path always records a problem, and `strict=True` cannot be told it was wanted

Demonstrating that a program rejects bad input is an ordinary thing to demo,
and the recorder logs it as a fault. Measured on this repo's
`examples/ticket-queue`, a 48-beat take on 2026-07-26:

```
demo-video: 1 problem(s) recorded during this take (nonzero_exit x1)
  [19.01s] nonzero_exit in beat 13 (run): './tickets list --status frozen' exited 2
```

`timeline.md` gets an Issues section saying the same. Two consequences. First,
`strict=True` is unusable for such a demo — `nonzero_exit` is fatal under
strict, and there is no per-call way to say "this exit is the point", so the
choice is between checking the app and demoing the error. Second, and worse, an
Issues section carrying an expected entry teaches its reader to skim, and **a
real regression would arrive in the same slot**. Both reviewers of that demo
remarked on it unprompted.

What to do: record error-path demos with strict off, and say in the pull
request which recorded issue is the demo's subject, so a reader knows which
line is not supposed to be there. There is no `expect_exit=` today
([#93](https://github.com/rogvid/skills/issues/93)).

### The evidence file and the beat log describe the same element differently

`evidence/beat-NN.json`'s `html` strips every value-bearing attribute —
`data-*`, `title`, `alt`, `placeholder`, `aria-label`, `href`, `src` — from
every element, deliberately: an attribute nothing renders was in no frame, no
still, no caption and no narration clip, and treating it as evidence of
rendering is how a demo comes to claim something it never showed. But
`timeline.json` records the beat's `selector` verbatim, so a reviewer handed
both sees `button[data-status='open']` in one file and, in the other, that same
button carrying only `type` and `aria-pressed`.

Measured from a reviewing agent's own words on that 48-beat take of this repo's
`examples/ticket-queue`: it spent a paragraph on the discrepancy, called
it an "unresolved inconsistency in the artifacts themselves", and could not
settle it — the three resolutions available to it were "the app is wrong", "the
log is wrong", "the dump is wrong", and all three are false. Nothing in the
file says the attributes were removed; only this skill's documentation does
([review.md](review.md) states it).

What to do: when handing `evidence/` to a conformance reviewer, tell it the
attributes are stripped, in the same message that hands it the files
([#92](https://github.com/rogvid/skills/issues/92)).

## What the timing guarantees are worth

### A frame is aimed at a beat; it is not stamped with one

Chromium stamps every screencast frame with
`Page.screencastFrame.metadata.timestamp` — a `Network.TimeSinceEpoch`, which is
the **host's wall clock** — and Playwright turns that straight into the frame's
position in the webm. The beat log uses `time.monotonic()`. So when the host
steps its clock, the video and the log disagree by the size of the step, and
every frame after it sits that much earlier in `demo.mp4` than
`timeline.json` says. It is a discrete step because a clock step is one.

**The earlier explanation here was wrong, and it is worth saying why.** This
section used to blame idle stretches: a screencast emits a frame when the page
paints, so a still page was thought to cost wall time that never reached the
webm. Measured directly, it does not — 30 s of a take with nothing painting
produced seven frames and came back the full 30 s. The evidence that looked
like idle loss was six samples of the clock step, and the ticker both
storyboards inject was credited with preventing something it does not affect.

Measured on one WSL2 host in April: **−0.75 to −0.81 s every 32.2 s**,
confirmed by a sampler that opens no browser and by a patched Playwright driver
that caught two consecutive frames 84 ms apart on the monotonic clock and
711 ms backwards on Chromium's. Seven takes of one storyboard: the four whose
window contained a step encoded 0.78 s less video than the three that did not,
to within 12 ms. A 19 s take against a 32.2 s interval is a coin flip, which is
exactly the bimodality
[#209](https://github.com/rogvid/skills/issues/209) measured.

**Do not read those two numbers as constants.** The same host, re-measured on
2026-08-08 with a 1 ms sampler over 300 s, was doing something else entirely
([#247](https://github.com/rogvid/skills/issues/247)): a **+10.03 to +10.10 s
rectangular pulse, 40–230 ms wide, every 5.509 s**, each one leaving the offset
0.43–0.56 s lower than it found it. `CLOCK_REALTIME_COARSE` moved with it, so
the kernel's timekeeper was being written, not a clock read glitching. The
permanent part of it is a **rate error, not a metronome**: against NTP over
90 s, `CLOCK_MONOTONIC` ran **+10.01 % fast** while `CLOCK_REALTIME` kept true
time to −0.40 %, and `adjtimex` reported `tick = 11000` — the kernel's +10 %
clamp. Something on the host (Hyper-V / `systemd-timesyncd` under WSL2) was
re-stepping the wall clock every 5.5 s to undo a monotonic clock running fast.
Same shape as April's, different size and period. **The recorder is not tuned
to either, and nothing you build on top of it should be.**

**The correction is exact when the record is.** Six takes, seven caption
transitions each, transitions located by luma straight off `demo.mp4` and
compared with the beat log: uncorrected, the video was up to **−1.50 s** from
the log by 13.5 s into the take; corrected by the wall-clock offset before each
beat, all 38 landed within **101 ms**, and within 40 ms at the caption-on edges
(a caption fade takes two frames to cross, which is the rest).

The suite's bars are asymmetric because the two directions have different
causes: `MAX_LOG_EARLY_S = 0.25` for the log running ahead of the frame and
`MAX_CAPTURE_LOSS_S = 0.75` for the video running ahead of the log. That first
direction is the beat log's own error **on a take whose host clock held
still**, and only then — this file used to say that nothing about capture can
move an event later, full stop, and
[#255](https://github.com/rogvid/skills/issues/255) measured +906, +540 and
+970 ms of it on takes whose clock stepped. The cause is an instant inside the
window a backward step deletes: it has no frame of its own, so a reading that
subtracts the whole step instead of clamping to the hole's edge is left with up
to a whole step of log-ahead
([#256](https://github.com/rogvid/skills/issues/256)). On a stitched demo there
is a second cause, and it is the merge rather than the capture — see the seam
below ([#263](https://github.com/rogvid/skills/issues/263)). On a stepping take
the suite now names the step first
([#257](https://github.com/rogvid/skills/issues/257)).

**What this file said between #257 and #255's retraction, which was wrong.** It
explained the same skew as a capture losing a *fraction* of the step it
recorded, over-shot by the difference. There is no such fraction. Playwright
1.62.0 stamps `frameNumber = floor((wall_ts − first_wall_ts) · 25)` into the
matroska clusters and CFR conversion drops everything until the wall clock
climbs back, so the video's clock is the wall clock's high-water mark and the
muxer cannot produce a partial shift — measured at **97.0–100.2 %** of the
recorded step across 10 steps in 9 takes, at 2–60 Hz paint, through plain
Playwright and through the real `Recorder`. The three figures above were
in-hole instants read as though they were shifts, which reads as
`(t − hole_start)/Δ` and is uniform on [0,1]. Do not correct by a proportion;
there is nothing to take a proportion of.

Both storyboards inject a small animated element for their whole length,
which gives the capture frames to measure with — **not**, as this file
previously claimed, protection from idle loss, which does not exist. `MAX_CAPTURE_LOSS_S`
now bounds only the gap before the first frame: 20–140 ms idle, 500–540 ms at
load 3.1. The suite corrects for the clock step by measuring it independently
rather than by widening a bar, which is why `MAX_SKEW_DRIFT_S` could be
restored at 250 ms after being deleted in
[#217](https://github.com/rogvid/skills/issues/217).

The recorder already applies this for you wherever it publishes an instant on
the video's clock, and reading one of those as uncorrected is the way to get it
wrong twice ([#229](https://github.com/rogvid/skills/issues/229)). Each place
is named below rather than counted, because a count went wrong here at three
commits running — "Two", then "Three", then "Three" with a fourth added
underneath it — and a reader who trusts one stops looking once they have found
that many: **the review frames
under `frames/` are cut on the video's clock**, midpoint plus that beat's own
capture's steps before *that midpoint* (the rule is indexed by the instant you
are converting, not by the beat — a step inside a beat's first half moves its
frame; and a beat a backward step deleted from the file is cut at the last
instant before the gap and marked `no_video`, see below), and
`frames/frames.md` says which of the three cases the take was;
**every narration clip is mixed on the video's clock too**
([#226](https://github.com/rogvid/skills/issues/226)) — `timeline.json`'s
`narration.lines` gives each spoken line's `t` (the beat log's instant) beside
its `at` (where the clip really is in `media`, which is `t` corrected by the
same rule and never below zero), with `narration.clock_correction` saying which
of the three cases applied — a line may also carry `clamped`, the seconds a
correction lost to the start of the file, but **no record the recorder can
emit produces one any more**: since
[#256](https://github.com/rogvid/skills/issues/256) an instant is never placed
earlier than the step that moved it, and the recorder's sampler starts at frame
zero, so `at` cannot come out negative. The floor and the field stay because
`adelay` refuses a negative delay outright and would cost the take its whole
audio track; read `clamped` as a guard against a malformed record, not as
something to expect; and **a stitched take's `overlaps` are graded on the
video's clock**, which is what `video_overlap` is and why it answers a
different question from the raw difference beside it (described under *A
stitched beat log can run backwards at a seam* below).

`timeline.md` says above its beat table when the clock stepped and by how much,
and what that meant for the audio — but it *reports* the correction rather than
applying one: every timestamp in that table is the raw beat log. `timeline.json`'s beat
timestamps are untouched — they are the log, and the log is `time.monotonic()`.

**A backward step is not a slide, and correcting one as though it were puts an
instant up to a whole step early.** A step of −Δ at `T` deletes the monotonic
window `(T, T+Δ)` from the file outright: the encoder stamps frames with the
wall clock and will not write a stamp it has already written, so the file
stalls for the width of the step instead of rewinding. Measured one video
frame wide — `video 31.560 → 31.600 shows mono 31.644 → 32.644`. An instant
inside that window has **no video at all**, and `t + (the steps before t)`
lands it in content that predates the step; that is how a review frame came
out showing the previous caption
([#256](https://github.com/rogvid/skills/issues/256)). The rule that holds
everywhere is that the video's clock is the wall clock's **high-water mark**:
an instant sits at the greatest of `t + (the steps before t)` and every
`T + (the steps before T)` for a step at `T ≤ t`. Outside a hole that is the
same sum; inside one it is the last instant the file has, and whatever you
build on it has to be able to say *this beat has no frame* rather than print a
timestamp as though it did. The recorder's own consumers do: a `no_video` on a
review frame and on a narration line, and a paragraph in `frames.md` and
`timeline.md` naming them.

What to do everywhere else: prefer `timeline.json`'s `capture_clock`, which
records every step with its offset and size, and correct with it — **after
checking `capture_clock.measured`**. That flag is false when the recorder's sampler
could not keep its interval, and then `steps` is empty and `total` is `null`
on purpose: a record that says "I did not watch this" is the one thing worth
more than a number that might be wrong. `max_gap` and `max_gap_limit` are the
measurement behind the flag. This exists because the sampler *was* wrong once,
silently, for a whole issue: it slept on `threading.Event.wait`, whose deadline
on the interpreter `uv` installs is an absolute `CLOCK_REALTIME` instant, so a
sampler that read the clock during one of those +10 s pulses set a deadline
10 s ahead, slept until the wall clock climbed back, and from then on only ever
sampled *inside* the pulses. It reported `total: +9.09 s` on takes whose clock
had moved −2.00 s. Nothing downstream could tell.

On a **stitched** demo the same
field carries every part's steps, each naming the `segment` it was measured in:
correct a beat with the steps of *its own* segment up to its `t_start`, never
with `total` and never with an earlier part's — that part's lost wall time is
already in the offset `stitch()` laid it out by, and applying it twice moves the
beat by a whole extra step ([#225](https://github.com/rogvid/skills/issues/225)).
Failing all that, read a review
frame as *around* its beat, do not build anything that needs a beat timestamp
to be exact to the frame, and when a frame and its caption disagree by a
fraction of a second, suspect the capture before the
storyboard ([#18](https://github.com/rogvid/skills/issues/18)).

### A stitched beat log can run backwards at a seam, and says so

`stitch()` moves each part's beats by that part's real **ffprobe duration**
while the beats keep their own `time.monotonic()` timestamps. Those are two
clocks. A part whose host clock stepped backwards has a video shorter than its
own beat log by the size of the step, so its last beats run past where the next
part begins and the merged log goes non-monotonic at the seam — reproduced at
−1.4684 s as `beat 21 t_end 37.451` against `beat 22 t_start 37.441` — a
**10 ms** overlap out of a 1.4684 s step, which is 0.7% of it
([#263](https://github.com/rogvid/skills/issues/263)). That is the only
measurement there is. What sets the size is not known from one point, so do not
work out an expected overlap from the size of the step; read the number the
take published.

Nothing is clamped: a beat's merged timestamp is exactly its own part's log
plus that part's `offset`, and the whole per-segment correction rule above
depends on that identity. The overlap is published instead, as `overlaps` in
`timeline.json` and as a paragraph above the beat table in `timeline.md`. Empty
on a healthy merge, and only reported past 5 ms, which is the same slack this
repo's suite grades a merged log's beat order against — a report tighter than
the bar it is checked by would call a healthy take broken.

Read `video_overlap` first — the same difference with both instants put on the
video's clock by the rule above. At or below zero the frames really are in
order and only the log's column runs backwards, which is the mechanism in this
section; above zero the recorded steps do not account for it; `null` means no
correction was possible at all, which is not the same answer as zero. Then read
`no_video` and `previous_no_video`, which are each endpoint's `lost`:
**"in order" is not "the frames are all there"**, because an endpoint the step
deleted has no frame at all and its place on the video's clock is the last
instant before the gap.

### Sixty seconds buys about twenty screens

SKILL.md says to aim for 30–60 s. That holds for a feature on one surface and
does not hold for one that spans two, and the difference is arithmetic rather
than discipline. Measured on the first real feature this skill was pointed at
(this repo's `examples/ticket-queue`, PR #94, four acceptance criteria across a
web UI and a CLI): **61.2 s**, with every caption already shortened once; the first-pass
storyboard was 60.2 s. Neither is padded — they are one beat per criterion plus
the two the skill's own pacing rules require around each.

| | seconds | share |
|---|---:|---:|
| web segment | 37.8 | 62% |
| terminal segment | 23.4 | 38% |
| a picture already shown | 41.9 | 69% |
| a picture not shown before | 19.3 | 31% |

20 of 48 review frames are a new picture; 28 are the previous picture with a
different line under it. That is not waste — it is the ~1.5 s a change needs to
register and the `0.6 + 0.34·words` a caption needs to be read. It is also the
ceiling: **about one new screen every 3 seconds**, so a minute buys roughly
twenty screens, and both fresh-eyes reviewers of that demo still asked for
more.

What to do: budget by the rate before writing the storyboard. A two-surface
feature does not fit, and the honest answers are a longer video or two demos —
not faster captions, which only makes the reviewers unable to read
([#96](https://github.com/rogvid/skills/issues/96)).

### A terminal segment's opening card can still miss the first frame

`TerminalRecorder(interlude="…")` raises the card before capture starts, which
is why SKILL.md tells you to open a terminal segment that way. Two residues.

Nothing stops the old shape. `interlude()` as a take's **first statement** is
~290 ms too late, so the segment opens on an empty terminal with a lone prompt
and no warning is printed — the guidance is documented in two places and
enforced in none ([#114](https://github.com/rogvid/skills/issues/114)).

And the constructor argument is not proof against a loaded runner. The smoke
check reads the mean luma of a corner strip outside the terminal window on the
recording's first frame: 26 with the card up, 226 bare. Across three `main` CI
runs and six local runs it read **26**, with the card covering 2.65–2.85 s. One
CI run read **128** and 0.00 s of cover — neither state, which is what a card
still becoming opaque looks like. One failure in four observed CI runs, none in
six local ones ([#128](https://github.com/rogvid/skills/issues/128)).

Neither residue is closed, but the second one is now *visible without
watching*: every terminal take reads that same strip off its own first frame
and writes the answer into `content.opening.card` in `timeline.json` —
`state: "card"`, `"bare"` or `"between"`, beside the luma it was read from and
whether the take asked for a card at all. It is reported and not enforced,
precisely because of the 128 above: a take that lands in the empty band says so
rather than failing ([#235](https://github.com/rogvid/skills/issues/235)). It
also covers the *first* residue from the side nothing else does — a segment
that opened with `interlude()` as its first statement records
`raised: false` and `state: "bare"`, which is the flash, in the one file a demo
directory commits.

What to do: use the constructor argument, and read `content.opening.card` in
the timeline of a terminal segment before shipping it. If it does not say
`card`, look at `frames/beat-00.png`.

## Where the picture measurement goes quiet

The `content` report exists so that a take whose beats all succeeded over a
recording nobody can watch does not read as healthy. [timeline.md](timeline.md)
explains what it measures and lists five limits of the held-picture arm. Three
of those five can hide a real occlusion; two of the three are worth an author's
attention before recording, and both are here with their numbers.

The third limit below is the *score* arm's rather than the held-picture arm's,
and it is the sharpest measured thing in this group: an overlay does not merely
hide from the score, it can push the score **up**.

### An occluder that spans only narration is never reported

A held stretch warns only when a verb that *acts on the app* began inside it —
without that correlation a healthy touring demo (22.0 s held) is
indistinguishable from a card over the app (23.0 s held), and the check warned
on both. So a card raised and never taken down, with only captions, holds and
stills behind it, is silent however long it stays up.

Measured, by adding one line to a healthy fixture storyboard: an `interlude()`
raised after the command and never cleared covered **31.5 s of a 34 s take**.
`static_for: 31.5` against `static_limit: 15.0`, every entry in `static_beats`
marked `"acting": false`, `warnings: []`. The still captured during it is the
card. There is no third answer available from the frames — the measured region
excludes the caption bar on purpose, so an honest narrated tour and a card left
up are byte-identical, and warning on the pair reinstates the false positive.

Note one rough edge that follows from it: the stderr line for a non-warning
over-limit stretch still ends "…which is what a still screen is supposed to
look like". On this shape it is not. Read the clause as a statement of which
beats were inside the stretch, not as a certificate.

What to do: take cards down explicitly. Do not rely on this check to notice one
you forgot ([#123](https://github.com/rogvid/skills/issues/123)).

### A wrapping caption can split a real occlusion into short stretches

The measured rect drops its bottom fifth so the recorder's own caption bar
cannot supply the contrast — `CONTENT_CAPTION_TRIM = 0.2`, a fixed fraction. A
caption long enough to wrap grows *upward*, past the trim and into the measured
region: **266 changed pixels per wrap**, against a `CONTENT_MOVED_PIXELS`
threshold of 4. Every caption swap then reads as the picture moving.

Against the recorder's own `interlude()` card this cannot matter: the card is
opaque at `z-index: 2147483647` and the caption bar sits at 2147483646, so with
the card up no caption is drawn at all. Browser top-layer content — a
`<dialog>.showModal()`, a popover — behaves the same way. But an **app-level**
overlay or modal is ordinary app DOM, and the caption bar paints over it, so
the swaps keep registering and a genuinely occluded stretch is split into
pieces that each sit under the limit. Measured: 25 s becoming 11 s + 8 s + 6 s,
and the warning goes silent.

The trim is still a fixed fraction rather than the caption's measured box, and
no fixture records a wrapping caption over a covered take, so this shape is
documented rather than graded
([#124](https://github.com/rogvid/skills/issues/124)).

What to do: keep captions to one line if you want `static_for` to mean what it
says.

### A full-viewport overlay can raise the content score, not lower it

The score arm is the median luma standard deviation over the app rect, so it
answers "is there variance here" and nothing more. A translucent overlay with
internal variance — the `style="light"` scrim is a radial gradient — **adds**
variance across the whole measured region. Three takes of one storyboard
against one app, from a clean standalone install:

| take | state | `content.score` |
|---|---|---:|
| 1 | scrim over the app for the last ~17 s of 48 s | 32.94 |
| 2 | "cleared" per the docs, still covered ([#162](https://github.com/rogvid/skills/issues/162)) | 32.95 |
| 3 | clean, nothing covering the app | **26.74** |

The two broken takes scored **23% higher** than the correct one, and stderr
printed `demo.mp4 shows a picture` for all three. An overlay pair recorded
against a fixture app reproduces it harder: **28.07** with the scrim up
against **17.02** without, 65% the wrong way round. There is no threshold that
separates those numbers in the right direction, and restricting the rect cannot
help — the overlay is exactly where the app is. This is the same
anti-correlation issue #17 found at whole-frame level, one level in.

What was added instead is narrow and exact rather than a better metric: at the
end of every take, before teardown, the recorder asks the **page** whether
`#__demo_interlude` or `#__demo_bridge` is still visible. It built those
elements and knows their ids, so the answer is a fact rather than an inference.
A take that ends with one up gets a `content.warnings` entry naming it, a
`WARNING` on stderr, and — because a non-empty warning list suppresses the
healthy line — no `shows a picture` claim.

**What it does not cover**, and this is the boundary rather than a to-do:

- **Only the recorder's own two overlays.** An app's own modal, a cookie
  banner, a `<dialog>.showModal()`, a stuck loading veil: all invisible to it,
  and to everything else here. General occlusion detection is unbounded and is
  declared out of scope alongside
  [#123](https://github.com/rogvid/skills/issues/123) and
  [#124](https://github.com/rogvid/skills/issues/124).
- **Only the end of the take.** An overlay raised at 10 s and cleared at 40 s of
  a 45 s take covered two thirds of the recording and reports nothing here. The
  held-picture arm is what might see that, with the limits above.
- **Only a take that encoded an mp4.** The finding rides in `content`, which is
  null when no mp4 was written, so a take whose ffmpeg conversion failed loses
  it. Such a take already carries `failure/` and `demo-video-FAILED.md`.
- **The score is left alone.** It still reads high on an occluded take. The two
  answers sit side by side in `timeline.json` on purpose; the warning says why
  they disagree ([#163](https://github.com/rogvid/skills/issues/163)).

What to do: nothing, if you use `interlude("")`. If you build your own overlay
in page script, take it down yourself — no check here will notice it.

### If your app paints slowly, you are the first to run that path

A web take's recording begins while the page is still `about:blank`, so the
recorder covers the blank opening with the first frame that painted — unless
the gap is longer than `OPENING_HOLD_LIMIT_S = 1.5`, past which it holds
nothing and warns instead, on the argument that an app taking that long to
paint is telling the viewer something true about itself.

**Nothing exercises the declining branch.** The fixture app paints in
0.30–0.50 s on this machine, so every recorded take in the suite takes the
cover path; set the constant to 100 and the whole suite still passes. It is a
config-hidden path in the exact sense the reviewer's catalogue means — the
fixture cannot reach it, so the constant guarding it is graded by nothing.

The branch is warn-only and fails safe: over the limit the recorder does
*nothing* to the picture, says so on stderr, and the `gap` measured afterwards
off the encoded file warns on its own. So the failure mode is a demo that opens
blank, which is the state that existed before the hold was added
([#126](https://github.com/rogvid/skills/issues/126)).

What to do: if your app's first paint is slower than 1.5 s, watch the opening
seconds of the first take rather than assuming they were repaired.

## What a stitched demo's artifacts promise

### A problem recorded in segment two can be attributed to segment one's beat

`stitch()` merges each segment's `issues` as well as its beats: every issue's
`t` is offset by the cumulative duration of the parts before it, and its `beat`
is re-pointed from that segment's own beat list at the merged one. Neither line
is exercised. The suite's segmented take records the healthy fixture under
`strict=True` — deliberately, since that is the only assertion that can fail on
*over*-reporting — so it records no issues at all.

What that leaves open is a confidently wrong attribution in the one file a
reviewer opens to find out what broke: an issue from segment two named against
whatever beat of segment one happens to sit at that index
([#51](https://github.com/rogvid/skills/issues/51)).

What to do: on a stitched demo, check a reported issue against its own
segment's `.seg.timeline.json` before believing the beat it names — pass
`keep_parts=True` to `stitch()` if you need those files to survive.

### A coverage row losing its segment — closed, and now graded

`coverage_report` copies each claimed beat's `segment` into the coverage table
(`coverage.py:117`), and `timeline.md` renders a claim as ``beat 5 (`part2`)``.
Nothing used to pin it: this skill's own suite graded a claimed beat's `index`,
`t_start` and `still` against the beat list, and its merge case *constructed*
beats carrying `part1` and `part2` and then asserted only on `index`. Replacing
that line with `"segment": None` left the coverage arm green — one of six
injections against that arm, and the only survivor
([#137](https://github.com/rogvid/skills/issues/137)).

Beat indices are per-segment before merging, so a reviewer of a stitched demo
handed "beat 5" with no segment has no way to know which beat 5. Pointing a
conformance reviewer at the right frame is the coverage table's whole job.

That merge case now asserts the segment of each claimed beat as well as its
index, and that exact injection is registered in the nightly manifest, so it
runs nightly rather than having been performed once.

## What CI will and will not do for you

### A pull request from a fork gets no comment

The workflow posts its comment with `github.token` on a `pull_request` event.
For a pull request from a fork that token is read-only whatever the
`permissions:` block says, so the `POST /issues/{n}/comments` call fails and
the contributor gets no beat table and no artifact link where an internal
contributor gets both.

The information is not lost: `demo-comment` also writes the body to
`$GITHUB_STEP_SUMMARY`, which does work on a fork run. It is one click deeper
than the pull request and invisible to anyone reading the conversation.

The obvious fix is the one that must not be taken. `pull_request_target` runs
the workflow from the base branch with a writable token and the fork's code
checked out — and this workflow's job is precisely to run arbitrary code from
the branch (`uv run record.py`, plus the caller's `app-command`). That would
hand a fork a writable token and the repository's secrets, which is worse than
no comment ([#118](https://github.com/rogvid/skills/issues/118)).

What to do: for a fork's pull request, point the reviewer at the workflow run's
summary page.

### How much a green suite is worth on a third encoder

The suite's content axis compares a take with a moving picture against a take
with a covered one by PSNR, and asserts the **gap** — a relative form that
replaced an absolute `>= 40 dB` bar which went red on CI at 39.8 dB after
measuring 47.5 dB locally. Only one of the two readings is stable:

| | this box | CI runner |
|---|---:|---:|
| moved | 25.5 dB | 25.9 dB |
| held | 47.5 dB | 39.8 dB |
| **gap** | **22.0 dB** | **13.9 dB** |

The moved reading is content-determined and barely travels. The held one is a
still frame, so it is entirely at the mercy of how a given x264 build
re-quantises — 7.7 dB of spread across two machines. The gate the suite applies,
`CONTENT_PSNR_GAP_DB = 8.0`, therefore has 5.9 dB of margin on the worse of the
two encoders anyone has run it on, which is fine today and is not obviously fine
on a third ([#122](https://github.com/rogvid/skills/issues/122)).

## Paths that only your recording takes

These branches of the recorder run nowhere in the test suite, so the first
program to exercise either is yours. They are stated here rather than left to a
maintainer's notes because they are reached by an ordinary storyboard.

**Nothing has ever called the ElevenLabs API.** The narration take grades
everything a cache *hit* reaches — the key, the pacing, whether the mix carries
audio — and by construction never takes the miss path, which is what makes it
fast and offline. So `tts_clip`'s HTTP request, its 429/5xx retry ladder with
backoff, the `.part`-then-rename that keeps a truncated download out of the
cache, and every error message it raises are unexercised. A regression there
costs a take at record time with a legible exception, which is the mildest
failure shape available — but it is your take that pays it.

**A narration-enabled segment that speaks no lines is ungraded.** Conversion
gives such a segment a track of `anullsrc` silence so that `stitch()`'s
`-c copy` concat sees uniform streams across the parts. Every take in the suite
either narrates or disables speech, so that branch runs nowhere. If you record
a segmented demo with narration on and one segment carries no captions, listen
to the stitched audio before shipping it: a mismatched stream is what makes
`concat` drop every later part's narration, and it does that silently.
