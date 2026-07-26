# tests

One smoke test and one fixture app. Together they answer four questions:
**does the demo-video recorder still produce a real video, does it still notice
when the thing it recorded was broken, does a registered secret stay out of
everything it produces, and can a reader say what each frame showed without
decoding one?**

They are not unit tests. The recorders' interesting behaviour is "shell out to
ffmpeg, drive a headless browser, come back with an mp4", which nothing short
of running it can check. So the smoke test runs it, end to end, and asserts on
what lands on disk.

```
tests/
├── smoke              # the runner (a PEP 723 uv script — no venv, no install)
└── fixture/
    └── index.html     # the app it records: static, dependency-free, deterministic
```

Takes: `web/` and `terminal/` (the two media), the determinism pair, the
problem takes, `redaction/` — the web recorder against a page that renders
a secret, plus a second few-second take that must *fail* — `segments/`,
one demo recorded in two parts and joined with `stitch()`,
`terminal-redaction/`, the redaction question asked of the PTY output path,
and `evidence/`, a few seconds against the shapes that leak into text and into
nothing else.

## Running it

```sh
tests/smoke                       # every take, output to a temp dir
tests/smoke --web-only            # just the Playwright takes
tests/smoke --terminal-only       # just the PTY/xterm.js takes
tests/smoke --determinism-only    # just the three re-recording takes
tests/smoke --redaction-only      # just the secret-redaction takes
tests/smoke --segments-only       # just the two-segment take and its stitch
tests/smoke --evidence-only       # just the per-beat evidence takes
tests/smoke --out-dir /tmp/smoke  # keep the recordings at a known path
tests/smoke --keep                # keep the temp dir even when it passes
```

Prerequisites: `uv`, `ffmpeg`/`ffprobe` on PATH, and Chromium for Playwright
(`uv run --with playwright playwright install chromium`; add `--with-deps` on a
fresh Linux box). The script's PEP 723 header pins **Playwright ≥ 1.49**:
per-beat evidence uses `locator.aria_snapshot()`, which arrived there, and the
`page.accessibility` API it replaced has since been removed outright. A pass
looks like this, and takes about half a minute:

```
smoke: serving …/tests/fixture at http://127.0.0.1:36321
smoke: web demo.mp4 ok (20.2s, 279 kB, content 16.0)
smoke: web still 01-dashboard.png ok (77 kB, content 16.9)
smoke: web caption is visible on screen (delta 25.6)
smoke: web first caption 'A small dashboard.' logged at 3.03s, on screen at 2.95s (-80 ms)
smoke: web closing caption 'Recorded end to end.' logged at 17.03s, on screen at 16.99s (-40 ms)
smoke: web beat clock holds across the take (+40 ms)
smoke: web timeline.json ok (23 beats)
smoke: web each review frame shows its own beat's caption state (10 captioned frames from 11.2, 4 bare ones to 3.3; 9 within 0.75s of a caption change and not graded)
smoke: web frames/ ok (23 beat frames, each byte-identical to the demo.mp4 frame it claims to be)
smoke: web evidence ok (23 beats, 39 kB, largest 2468 bytes)
smoke: web healthy app under strict=True records no problems
smoke: redaction #api-key is blurred in every frame of demo.mp4 (worst 1.5 vs control 52.0, 3%)
smoke: redaction all 9 masked elements are blurred in the review frames (18 gradable of 31; worst #a4-card 0.2 vs control 21.8 in beat-23.png, 1%, bar 7%)
smoke: redaction still 01-key-blurred.png ok (key 1.0, token 2.9, control 39.3)
smoke: redaction .tts/ holds 2 clips — the narrated lines, and nothing for the refused one
smoke: redaction evidence ok (34 beats, 90 kB, largest 3369 bytes)
smoke: redaction none of the 13 secrets appears verbatim in any of the 48 files the take wrote (34 of them per-beat evidence, which the controls prove is not empty)
smoke: segments recorded 2 parts, each with its own beat log (part1 6.8s, part2 7.8s)
smoke: segments part1's probe caption is +0 ms from where its own segment puts it (-120 ms in part1.seg.mp4, -120 ms in demo.mp4)
smoke: segments part2's probe caption is +0 ms from where its own segment puts it (-80 ms in part2.seg.mp4, -80 ms in demo.mp4)
smoke: segments stitched 2 parts into a 14.6s demo.mp4 and merged their beat logs (15 beats); keep_parts=True kept every part and its log, the default removed them
smoke: segments closing caption 'Recorded end to end.' logged at 11.43s, on screen at 11.35s (-80 ms)
smoke: segments timeline.json ok (15 beats)
…
smoke: web-problems timeline.json records 8 problem(s), 6 of them fatal under strict — take still passed
smoke: web-strict strict=True refused the take, naming beat 0 (goto) (4 fatal issues, artifacts kept)
smoke: evidence a SecretLeak raised while capturing a beat kills the take and keeps nothing
smoke: evidence a registered secret spans the markup budget (chars 7984-8016 of 72716, budget 8000)
smoke: evidence ok (18 beats as shapes.seg.beat-NN.json, 12 leak shapes clean, 4 controls intact, 2 beat(s) refused a moving target)
smoke: terminal-problems timeline.json records 2 problem(s), 2 of them fatal under strict — take still passed
smoke: terminal-race exit status survives a shell that starts 1.2s late (logged 5)
smoke: terminal-problems a printed secret is masked out of the screen dump, and the line around it survives
smoke: terminal-wrap a registered secret split by a line wrap at column 120 (chars 112-140) is masked in both halves
smoke: terminal-strict strict=True refused the take, naming beat 1 (run) (1 fatal issues, artifacts kept)
smoke: determinism froze all four clocks identically in both takes
smoke:   frozen  1/1/2025, 9:00:00 AM · 1735722000000
smoke:   frozen  intl 01/01/2025, 09:00:00 AM
smoke:   frozen  ctor 1735722000000 · same true
smoke:   frozen  worker 1735722000000
smoke:   default 7/25/2026, 6:23:51 PM · 1785003831823
smoke:   default intl 07/25/2026, 06:23:51 PM
smoke:   default ctor 1785003831823 · same true
smoke:   default worker 1785003831865
smoke: determinism stills reproduce byte for byte across takes (the same two stills move 28.6 over the spinner with the recorder's default settings)
smoke: determinism demo.mp4 reproduces (takes differ by 0.44, against 6.85 with the default settings)
smoke: determinism ok (3 takes)
smoke: PASSED
```

Re-running into the same `--out-dir` is safe: the take subdirectories
(`web/`, `terminal/`, `segments/`, `redaction/`, `terminal-redaction/`,
`terminal-cursor-leak-clean/`, `terminal-cursor-leak-crash/`,
`terminal-cursor-leak-tail/`, `web-problems/`, `terminal-problems/`,
`terminal-race/`, `terminal-wrap/`, `web-strict/`, `terminal-strict/`,
`evidence/`, `evidence-leak-fatal/`, `determinism-a/`, `determinism-b/`,
`determinism-off/`) are deleted before each take. Only the first two are graded
on their video; the rest are short and exist to break, or to reproduce, in one
specific way each. That is not tidiness — every artifact assertion works by
path, so without it a leftover `demo.mp4` from the previous run would grade a
recorder that produced nothing at all as a pass, and recording repeatedly into
one directory is exactly how a change to the recorder gets verified.

Deleting is bounded. Only those named subdirectories are ever
removed, and only when each is absent, empty, or carries the
`.demo-video-smoke` marker file a previous run wrote there. `--out-dir .` in a
project that has its own `web/` directory gets a refusal naming the path, not a
deleted source tree.

Unix only — `demo_recording/__init__.py` imports the PTY-backed terminal
recorder unconditionally, so the whole package needs a Unix platform. The
terminal *take* additionally skips itself with a message if `os.name` is not
`posix`.

The runner deletes every `DEMO_VIDEO_*` variable plus `ELEVENLABS_API_KEY` from
its own environment before recording, so a sourced project `.env` cannot change
what the test measures. The web and terminal takes then force narration off
(`speech=False`).

The **redaction take is the exception, and deliberately so**: it records with
`speech=True` against a stubbed synthesizer (`stub_narration`), which writes a
short silent mp3 under the same cache key `tts_clip` computes. The `.tts/`
cache is one of the four leak paths, and with narration off it does not exist —
"no cache entry holds the secret" would then be a statement about an empty
directory. Only the network call is replaced; the guard that refuses to speak a
secret, the cache path, the pacing and the ffmpeg audio mix are the recorder's
own code. That also makes this the one take that exercises the speech path at
all (see Known gaps).

## What it asserts

Eight independent axes, because a recorder can fail on any one of them while
looking perfect on the other seven.

**Artifacts** — `demo.mp4` and every still the storyboard asked for exist, were
modified by *this* run rather than a previous one, clear a size floor
(20 kB / 5 kB), and no two consecutive stills are the same picture. Duration,
via the `media_duration` helper, falls inside a wide window (6–32 s): the low
bound catches a take that died early, the high bound catches a hang, everything
between is normal variation between a laptop and a cold CI runner.

**Content** — the frames contain a picture. This is measured, not inferred from
file size: **no byte count can separate a blank recording from a real one.** A
flat white 14-second 720p H.264 is about 20 kB, comfortably over any floor that
a real 117 kB terminal take also clears. `gray_frames()` has ffmpeg decode
frames to raw 8-bit grayscale at 160×90 and the luma standard deviation is
computed in pure Python — no image library, no extra dependency.

**Where** it measures is the whole trick. Scoring the full frame does not work
and is worse than not scoring at all: a fifth to a third of every frame is the
recorder's own chrome — a pastel gradient at ~230 luma against a ~35 luma
window — and that bimodal spread alone scores 60–79. A fully blank web
recording scores **61.8** that way and a healthy one **60.2**, so the metric is
anti-correlated and no floor can work. Instead, the app's own rect is measured:

- **web video** — `Recorder._geom`, the composited window position, read off the
  live recorder rather than re-derived, so a change to the window geometry
  carries the measurement with it
- **web stills** — the full frame, since `shot()` captures the page full-bleed
  before compositing
- **terminal** — the bounding box of `#__term_host`, the xterm.js host div

The bottom 20% of each rect is dropped so the recorder's caption bar cannot
supply the contrast for an otherwise blank app. Video is sampled at 1 fps and
scored by the **median** frame, so one good frame cannot excuse a blank video.

| | healthy | blank | floor |
|---|---|---|---|
| web video | 16.0 | 0.0 | 6.0 |
| web stills | 15.5–16.9 | 0.1–1.1 | 6.0 |
| terminal video | 8.0 | 0.2 | 2.0 |
| terminal stills | 5.1–7.9 | 0.4 | 2.0 |

The floors differ per medium because the media do: a web page fills its rect
with light and dark, a terminal is mostly empty dark background with a few
lines of text on it.

**Behaviour** — the verbs actually did something. Byte sizes cannot tell a
filtered table from an unfiltered one, so each verb is followed by the
observable post-condition it must have caused:

| Verb | Post-condition checked |
|---|---|
| `goto` | `#rows` has 5 rows, `#status` reads `snapshot 1 of 3`, and `#refresh`'s computed background is the accent orange — the last one resolves a total stylesheet failure, which the luma metric cannot (see Known gaps) |
| `caption(text)` | `#__demo_caption` exists, holds exactly `text`, and has computed opacity > 0.5 (or ≤ 0.5 after `caption("")`) — checked after *every* caption in both takes |
| `caption`, on screen | two stills taken back to back with the page frozen and only the caption changing must differ in the caption band. Self-calibrating: no absolute threshold tied to whatever the fixture renders near the bottom. Healthy 25.6 (web) / 2.7 (terminal); not drawn 0.00 |
| `spotlight(sel)` / `spotlight()` | `#kpi-rev` computed `outline-style` is `solid`, then `none` |
| `type_into("#search", …)` | the field holds `seattle` and `#rows` is down to 1 row |
| `click("#refresh")` | `#status` reads `snapshot 2 of 3`, `#kpi-rev` reads `$134,950` |
| `move_to` | the page saw ≥ 10 `mousemove` events during the call. **Not** where the cursor ended up: Playwright's own `locator.click()` dispatches a `mousemove` to the target, so a final-position check passes with `move_to` stubbed out entirely — it measures Playwright, not the recorder. The 30-step glide is the only thing that produces a trail |
| `run` (terminal) | the shell prompt returns, and the command's *output* appears on a whole screen line (`^hello from demo-video$`, `^skills$`) — anchored so the echoed command line cannot satisfy it |

All post-condition failures are collected, never raised, in both takes. A take
that aborts writes no mp4, and CI's failure-only artifact upload then has
nothing to upload at exactly the moment somebody wants to look at it.

**Timeline** — the beat log the recorder writes as `timeline.json` and
`timeline.md` says what actually happened, and points at the right frames.

The beats are checked against `WEB_BEATS` / `TERMINAL_BEATS`, a hand-written
`(verb, target)` sequence per storyboard. That duplication is the point: a
count or a sequence derived from the log being graded agrees with that log no
matter what it says, which is how a dropped beat would pass. `WEB_CAPTIONS` /
`TERMINAL_CAPTIONS` do the same for the caption text, separately, so a
missing beat and a wrong caption fail independently.

Three of the checks exist because an earlier round of this file had them
missing and did not notice:

- **Every beat carries the caption it ran under**, not just the `caption`
  beats. That context is what makes a `shot` or a `click` beat mean anything,
  and it is what `timeline.md` quotes over each still — but checking only
  `verb == "caption"` beats is blind to losing it. The expected per-beat
  caption is derived from the two hand-written lists, never from the log.
- **`t_end` has to carry information.** Setting it equal to `t_start` satisfies
  every ordering check. So: a `caption(text)` or `hold()` beat must span at
  least a second (the recorder enforces 1.4 s and 1.5 s floors itself), and the
  beats together must account for ≥ 80% of the time from the first starting to
  the last ending. #8 wants the beat *midpoint* for frame extraction precisely
  because `t_start` is 0% into the caption's fade, so this is load-bearing for
  the next PR, not decoration.
- **`timeline.md`'s beat table specifically**, one row per beat. Checking that
  each caption "appears in the file" is satisfied by the Stills section alone,
  so the entire table could vanish and the run would pass — and the table is
  the only place a beat *without* a still (every click, every spotlight, the
  shape of the take) shows up at all.

Alongside them: `schema` matches the `TIMELINE_SCHEMA` the package exports,
indices match positions, timestamps are monotonic and inside the mp4's
duration, the recorder's own `duration` matches ffprobe, and every `still` a
beat names is a file on disk *and* every file in `images/` is named by a beat.

**Where the timestamps point** is the assertion worth having, and it is
measured rather than computed. Both takes set a caption after two seconds of
caption-band quiet; the band is then sampled every frame around what
`timeline.json` claims, and the first frame that has travelled a quarter of the
way to the caption's final state is taken as when it appeared. A quarter, not
"any change at all", because the bar fades in over 0.3 s and those two
definitions are a third of a second apart. The run-up is validated too — but on
frames well before the crossing, never the ones just before it, which *are* the
fade partway up and would read as a busy run-up on any take whose fade got
captured as a ramp.

Both the take's first caption and its last are timed, and the skew is graded
three ways, because the two directions have different causes and only one of
them is the beat log's:

| | bound | why |
|---|---|---|
| log **ahead** of the frame | 250 ms | nothing about the capture can move an event *later*, so a positive skew is the log's own error |
| video **ahead** of the log | 750 ms | a screencast that drops frames only ever makes events land early; capped at one lost setup window |
| the two probes **drifting apart** | 250 ms | whatever the capture loses, it loses for every later frame equally, so a stall cancels here and only a bad clock survives |

Observed across eight consecutive `--web-only` runs and six full runs, both
media: first caption **-80 to -200 ms**, closing caption **-160 to 0 ms**,
drift **0 to 80 ms**. Nothing came near the 250 ms *ahead* bound — no run has
ever produced a positive skew — which is the point of splitting by direction:
the tight bound guards a failure mode with no natural variation near it.
`_t0` set after `_start()` instead of at page creation measures **+320 ms** and
fails it; a beat clock running 3% fast drifts **-360 ms** and fails the third.

That split, and the tightness, only work because of `TICKER_JS` — the part to
understand before trusting this axis. Chromium's screencast emits a frame when
the page paints and nothing pads the gap when it does not, so an idle stretch
silently costs the recording ~0.6 s of wall time and everything after it sits
that much early. Measured, three runs each: 3/3 idle takes stalled, 3/3 takes
with a small animated element running did not. Both storyboards inject one for
their whole length. It cannot cover the ~0.7 s between the page being created
and the first line of storyboard running — the recorder's own setup, which no
test code can reach — and roughly 1 web take in 12 loses that window whole,
which is what the 750 ms bound is for. **A real demo has no ticker at all**;
see Known gaps and [#18](https://github.com/rogvid/skills/issues/18).

The recorder's determinism controls ([#10](https://github.com/rogvid/skills/issues/10))
land an animation on its final frame — which is exactly what the ticker must
not do, and how a green harness could quietly stop being one. Two things keep
them apart, and both are asserted rather than assumed:

- **The freeze is of the wall clock only.** `Date.now()` and `new Date()` stop;
  `performance.now()`, the document animation timeline, and
  `requestAnimationFrame` do not, and CSS animations run on the second of
  those. The web take samples the page at its start and at its end and fails
  unless the wall clock moved **0 ms** while the monotonic clock moved seconds.
- **The motion rule cannot match an opt-out.** It is written
  `*:not([data-demo-video-animate])…`, and the ticker carries that attribute.
  `start_ticker()` reads the ticker's computed `animation-duration` *and*
  plants a control element with the same animation and no attribute: the take
  fails unless the rule flattened the control to `0.001s` and left the ticker
  at `0.18s`. Checking only the ticker would pass just as happily on a
  recorder that had stopped injecting the rule at all. Both takes pass
  `deterministic=True` for this reason — under the recorder's default the rule
  is not injected and the control assertion would have nothing to say.

When the measurement cannot be made the run says which reason it was: a caption
that was never drawn, a video that slid further than the search window can see,
or a run-up that was not quiet. They look identical from inside the window, and
only the first is the recorder losing a caption.

**Review frames** — the `frames/` a reviewer is actually handed: one PNG per
beat, and `frames.md` embedding them in order. What is graded is what the
recorder claims, and it deliberately claims very little:

- **One frame per beat, named for it.** Counted against the hand-written
  `WEB_BEATS`/`TERMINAL_BEATS`, so a dropped frame, a doubled one or an
  off-by-one name fails without a pixel being read. Every file on disk is named
  by the manifest and vice versa.
- **Each frame is the moment it says it is.** Two halves, and only together.
  Its timestamp must be its beat's midpoint, computed *here* from
  `timeline.json` — not imported from the recorder, because a check that
  re-derives its expectation from the constants it is grading moves whenever
  they do. And the PNG must be that frame: the harness **cuts the same second
  out of `demo.mp4` again and compares the bytes**. 56 of 56 identical across
  the three graded takes — 23 web, 18 terminal, and 15 off the stitched
  `segments/` demo; one frame away (40 ms) is already a different file.

  Exact rather than approximate, because approximate does not work here. A PNG
  and a decoded video frame reach a luma reduction through different colour
  conversions and sit ~1.0 mean luma apart *when they are the same frame*,
  while two moments three seconds apart in this fixture differ by 0.87 (a
  filtered table and a refreshed one are mostly the same white page). A
  threshold loose enough to absorb the first cannot see the second — measured,
  by injecting exactly that and watching it pass.
- **The sheet leaks no storyboard.** `frames.md` goes to a *context-free*
  reviewer who is asked what story the pictures tell. It is searched for every
  caption in `WEB_CAPTIONS`/`TERMINAL_CAPTIONS` and every selector in the beat
  list, and finding any of them is a failure; `frames.json` must carry no
  `caption`, `verb` or `selector` key, because a manifest that duplicates the
  storyboard is how it ends up back on the sheet.
- **A re-run clears the previous run's frames**, and only those. `beat_frames()`
  is called a second time with a planted `beat-99.png` and a planted file it did
  not write: the first must be gone, the second must survive, and the frame list
  must be identical. SKILL.md advertises the re-run and step 6 tells a reviewer
  to read the whole directory, so a storyboard that lost beats between runs
  must not leave plausible-looking frames from a demo that no longer exists.
- **A single segment's timeline gets no frames — and only that.** Graded by
  handing `beat_frames()` this take's own timeline with a segment name on it:
  it must write nothing and say why. Both reasons are properties of that
  document, not of the world around it: its beats are numbered from zero, so
  two segments collide on `beat-00.png`, and its `media` is a `.seg.mp4` that
  `stitch()` deletes on its way to `demo.mp4`. Neither survives the merge, so
  the **stitched** demo gets frames like any other take — the `segments/` take
  runs the whole of this axis, `_check_frame_captions()` included, against the
  15-beat merged timeline `stitch()` writes.
- **Frame N shows beat N** — issue #8's acceptance criterion, and the only
  claim here about a frame's *content*. For every beat the hand-written
  storyboard says had a caption bar up, the frame must show one; for every beat
  it says had none, the frame must not. Decided by ranking rather than by a
  threshold: each frame's caption band is reduced and measured against the
  take's own first caption-off frame, and every captioned frame must sit
  further from that baseline than every uncaptioned one, by at least
  `MIN_ALIGN_BAND_DELTA`. Observed margins: web 8.1, terminal 2.3, segments
  16.6. A recorder that stopped drawing the bar, or extraction that returned
  one picture for every beat, collapses the two groups together and the margin
  goes to zero — there is nothing to tune past it.

  **One bit per frame, deliberately.** *Which* caption is a stronger claim and
  this band cannot carry it: two of the fixture's own terminal captions sit 1.5
  mean luma apart against a 1.0 floor, so a check that named them would be
  reporting noise. That is [#60](https://github.com/rogvid/skills/issues/60).

  **And a stated tolerance, which is the honest part.** The video runs ahead of
  the beat log ([#18](https://github.com/rogvid/skills/issues/18)), so a frame
  cut at a beat's midpoint shows a moment slightly later in the story than that
  beat. Frames within `FRAME_CAPTION_GUARD_S` — the same `MAX_CAPTURE_LOSS_S`
  the skew bars use, 750 ms — of a caption *change* are therefore not graded:
  that close, the log and the video genuinely disagree about which side of the
  change a frame is on. This is not theoretical. Set the guard to zero and the
  suite fails on `segments/beat-13.png`, the frame for a 50 ms `shot()` beat
  that ends 25 ms before a caption clears: the video is ~80 ms ahead, so the
  entire beat is already past the change and the frame shows the *next* beat's
  screen. `MIN_GRADED_CAPTION_FRAMES` and a one-of-each-class rule keep the
  guard from turning the check off — set it to 3 s instead and the suite fails
  with "only 0 of 23 review frames … were graded".

**What is still not graded: which caption a frame shows.** The recorder makes
no such claim, and neither does this file. An earlier round graded a caption
printed under each frame by reading the caption bar back out of the pixels;
that measurement worked, and the thing it was measuring did not. The recorder
inferred which caption a frame showed by locating caption transitions in the
video, and review found the inference mislabelling frames on ordinary
storyboards: two captions of the same length change under 0.25 mean luma in the
band against a 1.5 floor, an app repainting under the bar supplies a stronger
and earlier edge than the caption does, and a mid-take `goto()` destroys the
bar while logging no caption change to measure. The claim was withdrawn rather
than tuned — see [#60](https://github.com/rogvid/skills/issues/60), which is
what earning it back would take.

**Scene-change detection**, the fallback for what the storyboard did not
script, is graded directly against `demo.mp4` rather than through a take: no
beat in either storyboard runs the 3 s the recorder needs before it reaches for
it, and stretching one to provoke it would cost every run the seconds. It must
see the largest change a take contains and stay quiet where nothing moves.

The positive half — at least one cut somewhere in the video — is **web only**,
and that is about the medium rather than a convenience. The biggest thing that
happens to the web frame is the caption bar arriving, at 0.023–0.026 against
the recorder's 0.02 threshold, while *nothing* in the terminal take reaches it:
its largest change is two lines of shell output on a dark background at 0.011,
against an idle 0.004. At a threshold separating those, an ordinary terminal
repaint would be reported as a cut. Tracked in
[#57](https://github.com/rogvid/skills/issues/57), which proposes scoring the
app's rect instead of the whole composited frame.

The quiet half runs on both, over the stretch after the **last beat's logged
end** — where the recording holds its closing frame until it stops. Anchored
there rather than in the middle of the take because the video only ever runs
*ahead* of the beat log (#18), so the real end of that beat is at or before
this; a first version picked "the middle of the longest pause beat" and a take
that stalled 540 ms slid a caption change into it on the first run.

**Problems** — what the recorder saw *behind* the pixels. This is the axis the
other four are structurally blind to: a demo of an app throwing `TypeError` on
every render is pixel-for-pixel a demo of a working one, scores the same luma,
logs the same beats, and satisfies every post-condition the storyboard checks.

It splits four ways, and no single take answers more than one of them — which
is why there are seven takes and not two.

**A healthy app must record nothing.** The two graded takes record the plain
fixture, with `strict=True`, and `check_healthy()` demands an empty `issues`
list. This is the only assertion here that can fail on **over**-reporting, and
without it the axis is one-directional: every check below is "at least one
issue matches", which a recorder that flagged every healthy 2xx as a fatal
console error satisfies perfectly — while refusing every strict take of every
working app ever recorded. That is not hypothetical; it was measured passing
the entire suite before this existed. Recording them strict is the second half:
over-reporting does not merely get noticed, it aborts the take.

Keeping the graded takes healthy also matters for what they *are*. They are the
reference demo a reader watches; the fixture hooks belong in takes of their
own, the way `?secret=1` does.

**A broken app must record what broke, where.** `web-problems/` loads
`?console-error=1&bad-fetch=<url>`: the fixture logs a `console.error`, throws
an uncaught error, and fires two doomed requests — a 404 and a connection
refused on a port nothing is listening on. All four fire **during page load**,
on purpose, so the recorder's `goto` beat is open and there is a real
attribution to check. `terminal-problems/` runs `(exit 3)` — a subshell, so the
recorder's own shell survives, and 3 rather than 1 so the assertion proves the
*status* was read and not "something failed" inferred from elsewhere.

Two cases in `web-problems/` exist because the obvious implementation of
attribution — blame `self._beats[-1]` — is wrong in both directions:

- an error thrown **one second into a three-second hold** must land on the
  `pause`, under the caption that was on screen, not on the caption beat that
  follows the hold. Without the recorder pumping events as it waits, it lands
  on the later beat and gets stamped with a line that did not exist when it
  fired. Both the beat *and* the caption are asserted.
- an error logged **between two verbs**, where no beat is open, must come back
  `beat: null`. A confidently wrong index is worse than no answer.

These takes are graded on `timeline.json` alone — nothing about their video is
checked. They also carry the other half of the strict assertion: the **default**
recorder tolerates every one of these problems and still writes every artifact.

| Checked | Why |
|---|---|
| each deliberate problem appears, by kind and message | the whole axis |
| …attributed to the beat it fired during — `beat` indexes a real beat *and* that beat's `verb` is the expected one | `verb` alone is a string the recorder could copy from anywhere; `beat` alone is an integer that means nothing. Together they say the attribution is real and right |
| …or to no beat at all, when none was open | the null case above |
| …under the caption that was up when it fired | the field a reviewer reads as context; quoting a later line is the failure a wrong beat index produces |
| `run` beats carry the exit status of their command | hand-written like the beat lists, `{echo ok: 0, (exit 3): 3, sleep 1: 0, (exit 9): 9}` |
| `nonzero_exit` is in the package's `STRICT_KINDS` | links the recorded data to the policy: recording a failing command that strict would ignore is not catching it |
| `issue_count` equals `len(issues)` | nothing here comes near the 200 cap, so the two disagreeing means one is wrong |
| every `kind` is in `ISSUE_KINDS` | the published contract, not whatever the recorder felt like emitting |
| `timeline.md` has an Issues section naming each, and an exit column | the human-readable half of the log must not say the take was fine |

**An exit status must be right or absent, never wrong.** Two shapes of that,
both found by review after the first round shipped them silently wrong:

- `terminal-problems/` types `sleep 1` and `(exit 9)` with **no wait between
  them**. The shell buffers the second and runs it after the first, so both
  statuses arrive in order and must reach different beats. A single pending
  slot gave `sleep`'s 0 to `(exit 9)` and dropped the 9 — a *wrong* exit code,
  which strict passes, rather than a missing one.
- `terminal-race/` runs against a shell that **sleeps 1.2 s before exec'ing
  bash**, with typing instant, so `run()` finishes before the shell has printed
  its first prompt. That prompt reports the shell's own 0, and a recorder that
  takes the next marker it sees writes that 0 onto the command. Its own take
  because the condition has to be manufactured: on a normal box the startup
  prompt always wins, and removing the guard passes every other take here.

**Strict mode must refuse what the default tolerates.** `web-strict/` and
`terminal-strict/`, deliberately tiny. Each must raise `StrictTakeFailed`, the
message must **name the beat** (issue #3's acceptance criterion verbatim,
matched as `beat N (verb)`), it must name the kind the storyboard caused, and
**demo.mp4 and timeline.json must still be on disk** — a broken take is
precisely the one somebody wants to look at, so failing it by destroying the
evidence would be worse than not failing it.

**Determinism** — recording the same storyboard twice produces the same
recording. Three extra takes, each about six seconds, against `?entropy=1`: a
page rendering what a re-record is otherwise free to differ by — four
*different* clocks, and a spinning shape.

Four, because they are four clocks under the hood and patching the `Date`
global reaches only the first. `Intl.DateTimeFormat().format()` formats from
its own internal clock, a `Worker` has its own global that page init scripts
never run in, and `new Date().constructor` walked straight past a proxied
global to the real constructor. All three were found running behind a frozen
`Date.now()`, by two takes that differed while every assertion passed.

| Take | `deterministic` | What it is for |
|---|---|---|
| `determinism-a` | `True` | the reference |
| `determinism-b` | `True` | must match `determinism-a` |
| `determinism-off` | *not passed* | must **not** match — grades the default |

The third take passes no `deterministic` argument at all, deliberately. The
frozen clock is opt-in (it changes what a debounce, a token check or an
elapsed-time bar does, usually silently), so the default is the setting every
user gets and the one worth grading. The web and terminal takes above go the
other way and pass `deterministic=True` explicitly, because that is where the
frozen clock and the motion rule have to be shown coexisting with
`TICKER_JS`.

What is compared, and why each comparison is not free:

- **The stills, byte for byte.** They are lossless PNGs of a frozen page, so
  there is no threshold to argue about and no encoder noise to tolerate:
  `sha256(a/01-entropy.png) == sha256(b/01-entropy.png)`, or the take failed.
  This is the sensitive one — it catches a four-digit change in a timestamp,
  which nothing measuring luma will. The same two stills are also compared
  *within* `determinism-a`, a second apart on a page nobody touched, and that
  is the comparison that catches a running animation: headless Chromium turns
  out to reproduce animation phase across two takes of an identically-paced
  storyboard remarkably well (a spinner exempted from the motion rule produced
  byte-identical stills in both takes and was caught only within one).
- **…and the same two stills inside `determinism-off`, which must differ.**
  This is the assertion that keeps the ones above honest. Two blank screenshots
  are byte-identical too, and so are two files a comparison forgot to read. The
  same storyboard, the same page, nothing pinned: 28.6-30.0 mean luma over the
  spinner, against a 4.0 floor.
- **The video, where bytes cannot be compared.** H.264 at crf 20 is not
  byte-reproducible and the screencast's frame timing is not either, so the
  closing frame of each take is sampled over the entropy panel instead: two
  deterministic takes score 0.00-0.59 mean luma apart, a deterministic take
  against `determinism-off` scores 6.85-7.22. Both bars (1.5 and 2.5) sit in
  that gap, and **both directions are asserted** — the second is what says the
  comparison can see a difference at all. Know what it cannot see: a *coarse*
  measure over a 160x90 reduction, it caught a whole panel changing colour
  (24.14) and did not notice four digits of a timestamp changing (0.22). The
  stills are what make the fine claim; this makes the claim about the artifact
  people actually watch.
- **The clock the page printed.** Frozen takes must agree on it, and
  `determinism-off` must disagree with them. Printed on every run, so a reader
  sees which instant was frozen and what the live clock said.
- **What the page reports about itself**, in every take including the web and
  terminal ones: `Date.now()`, `new Date().toISOString()`, the resolved
  timezone and locale, `navigator.language`, `prefers-reduced-motion`, and the
  computed `animation-duration` / `transition-duration` of a probe element
  planted for the purpose. Read from *inside the page*, never off the
  recorder's own attributes — a constructor that stored `deterministic=True`
  and forgot to wire it to the context satisfies any check made in Python.
  With determinism unasked-for, every clock-related one is asserted the other
  way, including that the page's clock is within five minutes of this
  process's — while timezone, locale and reduced motion are asserted *pinned*
  in both, because those three are not gated on `deterministic`.

  Four of those checks are not clock readings at all and hold in both modes:
  `Date.prototype.constructor === Date`, `Date.now === Date.now`,
  `Date.now.name === "now"`, and the flattened durations being **1 ms rather
  than 0s**. The proxy that freezes the clock is exactly what breaks the first
  three, and a transition of zero duration never starts — so it never fires
  `transitionend`, and every accordion, modal and wizard that advances on that
  event stalls. Both were live regressions, caught by review rather than by
  this harness, which is why they are asserted by value and not by "not the
  original".

Before any of that, each still has to have a picture in it at all, on the same
whole-frame luma floor the web take uses (6.0, healthy 15-17). Two blank
recordings reproduce beautifully.

And one reading is checked in the DOM rather than left to the pixels: the
worker's. The fixture falls back to rendering `worker unavailable` if the
`Worker` constructor throws, and that reproduces byte for byte across takes
exactly as happily as a frozen timestamp does — so a wrapper that broke every
worker on the page would pass this whole phase on the strength of failing
consistently. The take reads the line and requires `worker <frozen epoch>`.
All three takes also run `strict=True` (issue #3's machinery), which is what
would catch the blob shim breaking worker *loading* rather than its clock.

**Redaction** — a third take, `redaction/`, records `?secret=1` with
`rec.redact("#api-key")` and `rec.type_into("#token", Secret(...))`, and grades
the four leak paths of [#4](https://github.com/rogvid/skills/issues/4)
separately. Its acceptance criterion is *no frame, still, caption or TTS cache
entry containing the secret*, so it is graded on pixels and bytes, never on the
recorder agreeing that it did the right thing.

Six elements are masked and graded, each reached a different way, because
each is a different way for a mask to miss:

| element | why it is there |
|---|---|
| `#api-key` | the ordinary case: a leaf with the value in it |
| `#hero-key` | 44px text inside a **12px wrapper**, and the wrapper is what `redact()` is given — a radius scaled from the matched element leaves the value readable |
| `#sd-key` | inside an **open shadow root**: `page.locator` sees it, `document.querySelectorAll` does not, and a document stylesheet does not apply to it |
| `#if-key` | inside an **iframe**: `frame.evaluate` reaches it, `page.locator` does not descend into it |
| `#token`, `#sd-token` | typed into as `Secret(...)`, one of them across the shadow boundary |
| `#a1-card` … `#a5-card` | the **sufficiency shapes**: a wrapper with a small font-size holding a value rendered four to five times larger by a `::after`, a `transform: scale(4)`, `zoom: 4`, an SVG `viewBox`, and two nested shadow roots. Each is redacted by the wrapper, and each reported 12–13 px to a mask that asked CSS how big its text was |

The sufficiency axis tests *shapes*, plural, on purpose. For two rounds it was
exercised by exactly one — a wrapper with a plain 44 px descendant — and five
constructions walked straight through it. A single shape tests the shape, not
the property.

`redact()` takes **plain CSS only**, and the take asserts that the dialects
every other verb accepts — `text=`, `xpath=`, `>>`, `:has-text()` — are
*refused*. That is the honest trade rather than a limitation: continuous cover
is a stylesheet, a stylesheet is CSS, and a Playwright-engine selector can only
be re-resolved at checkpoints. Measured before the change, a `text=` selector
sat unmasked for four seconds of a ten-second take on an ordinary
fetch-then-render page while its CSS sibling holding the same value was covered
throughout — and the end-of-take check then found it masked and passed.

**The mask is an opaque cover, not a blur**, and that is a decision this
harness forced. A blur has to answer "how much is enough", and the answer is a
guess about how the ink was produced; five separate ways of rendering text
larger than its `font-size` says — a `::after`, `transform: scale()`, `zoom`,
an SVG `viewBox`, a value two shadow roots down — each defeated a radius
derived from CSS, and nothing suggested the fifth was the last. A cover is
sized from client rects, which include transforms and zoom by construction, and
asks nothing about the text.

**What the in-page check can and cannot prove.** For two rounds it compared the
filter it had just applied against the value it had just computed —
`applied < needed` was unreachable by construction, so it read as a check and
could not fail. It now asks the *browser's hit testing* whether anything paints
over each cover, at nine points per element, which is a fact the recorder does
not decide. That covers **stacking** — z-index, the top layer, paint order.
It does **not** cover **extent**: whether the cover is over the right pixels is
geometry, and the only independent grading of that is the pixel measurement
below. Nothing in the page can grade it, because the same walk that positions
the cover would be the one grading it.

The pixel measurement is **sharpness**, not contrast: `edge_energy()` is the
mean absolute difference between neighbouring pixels of a crop. A gaussian blur
is precisely the operation that removes glyph edges, so it separates a masked
key from a legible one by more than an order of magnitude — where luma stddev
would happily score a blurred-but-colourful smear as "content".

**The crop is normalised to a fixed text height first, and that is what makes
the number mean "legible" rather than "small".** Sharpness is scale-dependent:
bigger text has fewer glyph edges per pixel, so a *sharp* 44 px key scores
lower than a *blurred* 15 px one. Measured with only the font size varied and a
constant 8 px blur:

| font | control | blurred | ratio | legible to a human? |
|---|---|---|---|---|
| 15px | 37.7 | 1.0 | 2.7% | no |
| 40px | 16.4 | 1.6 | 10.0% | borderline |
| 52px | 12.3 | 1.6 | 13.4% | **yes** |
| 68px | 9.4 | 1.7 | 17.7% | **yes** |

The denominator collapses while the numerator stays flat, so a raw ratio passes
text anyone can read — and at 68px the control is about to trip its own floor,
three sizes after the secret became readable. Scaling every crop to the same
text height removes that: a blur proportional to the text survives the rescale
as a blur, while a constant 8 px blur on 44 px text rescales into a ~3 px blur
on 15 px text and scores like the legible thing it is.

**What it is measured against is the whole trick again.** Every masked element
has a control of the same kind and size in the same frame, never registered:
`#api-key-control` for the body-size keys, `#hero-key-control` for the hero
one, and a control *field* beside each secret field. Fields need their own
control because a field is not comparable with text — its border blurs along
with its contents and smears a gradient across the crop — and the control
fields are **typed into**, not pre-filled, because a freshly re-coded region
carries ringing that a static one does not.

| | control | masked | mask off | constant 8px radius, hero | radius 8→3 | whole page blurred |
|---|---|---|---|---|---|---|
| stills, text | 26 – 30 | 0.8 – 0.9 | 40.6 | 3.5 (12%) | 3.0 (11%) | 0.4 |
| video, text | 30 – 36 | 0.8 – 1.2 | 53.6 | 3.4 (11%) | 3.7 (10%) | 0.7 |
| video, fields | 27 – 28 | 2.5 – 3.6 | ~100% | — | 7.7 (28%) | — |

So the bar is per kind: **7%** for text, where the interesting faults (a blur
that does not scale, a radius cut to 3px) land at 10–12%, and **25%** for
fields, whose floor is structurally higher (9–13% while being, on inspection of
the extracted crop, a featureless smear — the same crop in the lossless still
reads 3%). The looser field bar still catches the failure that matters there,
a field not masked at all, by 4x.

With covers, a masked element reads **0.0–0.2** where a blurred one read
0.7–1.4, against controls at 25–35. The bars below are unchanged and are now
a long way from anything healthy.

**Bar headroom, stated because it is thinner than the rest of this file.**
Injecting a radius cut from 8px to 3px puts `#sd-token` at 28% against a 25%
field bar and `#token` at 22% — two near-identical fields either side of the
line. The 7% text bar catches a 44px hero under a 15px-calibrated radius at
11–12%, but a 28–30px hero would likely slip under it. Both bars are backstops
now rather than the primary check: a radius too small for the text fails
*verification*, in the page, deterministically, before any pixel is measured —
which is where that class of bug is actually caught.

The control also carries an absolute floor (8.0 stills / 6.0 video), and that
floor is the anti-vacuity guard: without it a black recording, a blank page, or
a mask that blurred *everything* — all of which score near zero everywhere —
would pass the ratio trivially. Injecting exactly that (mask every element)
trips the floor in all four artifacts.

Video is sampled at 2 fps and graded on the **worst** frame, not the median:
one frame showing the key is a leak, because a paused video is a screenshot.
Rects come from the recorder's own `_geom` mapped through `to_video_rect()`,
never a hardcoded scale factor. The two fields are graded only from the moment
they were typed into — before that they hold a placeholder, and grading a
placeholder would force the bar up for everything else.

**A control that cannot be measured is a failure, not a skip.** For one round
the field controls were missing from the dict the loop reads, both fields went
ungraded, and the run printed PASSED. It now says which element was not graded
and why.

**Two axes exist only because a mask can succeed by hiding everything.**

*Blankness*: the recorder withholds the first paint of each navigation until
the mask is verified, which means a gate that never comes down records a blank
window — and every leak assertion above passes on a blank frame. The take
measures the longest run of blank frames in the app rect (bar 1.5s, observed
0.6s) after clicking an ordinary link, because for one round the gate was
lowered from `goto()` alone and a link click left four of ten seconds white
with the take reporting success.

*Gate integrity*: the gate is raised again deliberately, mid-take, and attacked
the way an ordinary page does it by accident — a descendant declaring
`visibility: visible`, and a script stripping `<style>` elements it does not
recognise. A still taken while it is up must show **nothing**, including the
controls, which are never redacted. This is the only assertion that can fail
when the gate is weakened: with CSS-only redaction the in-page stylesheet
already masks from the first paint, so no *leak* assertion depends on the gate
— it is defence in depth, and the honest way to test defence in depth is to
test the mechanism directly rather than to claim a leak it no longer prevents.

Two things that line does **not** cover, and the phrasing should not be read as
covering: content in the browser's **top layer** (`<dialog>.showModal()`, a
popover, fullscreen) ignores z-index entirely. The gate and the covers ask for
the top layer when the browser offers it, and a cover that something paints
over is caught by the hit test — but a *dialog opened after* a cover is
ordered above it in the top layer, and only the hit test at the next checkpoint
notices. And the attack the fixture runs is the two ordinary ones, not an
adversary.

The **review frames** (`frames/`, issue #8) are a fifth artifact on disk and
are graded on pixels like the rest. They are frames of `demo.mp4`, so they
inherit its mask by construction — which is a reason to expect them clean, not
a reason to skip measuring them, and this file's whole premise is that
"inherits it by construction" is a claim rather than evidence. **Every element
the video is graded over** is scored in the frames too, each against its own
control **in the same frame**, worst frame wins by *ratio*, same 7% text bar as
the video — and `#if-key` carries the video's window with it, since it holds
its secret only until the take navigates and an emptied iframe is not a masked
one.

For one round this graded `#api-key` alone, which was the wrong single element
to pick: `#api-key` is clean in every run, and `#if-key` is the one measured
leaking into `demo.mp4` intermittently ([#68](https://github.com/rogvid/skills/issues/68)).
The frames are the artifact a reviewer is *handed*, so the element most likely
to leak was the one they were least protected from.

Only frames where the *control* is legible are graded, and the count of those
is asserted (≥ 10 of ~31, per element). That skip is not a loophole while the
control is what decides it: this take opens on `about:blank` for five
`redact()` beats, raises the paint gate on purpose mid-take, and navigates
once, so a handful of its frames legitimately show nothing at all — and a mask
that blanked the whole recording takes the gradable count to zero and fails.

And the take that *cannot* verify its mask must leave none of them behind:
`check_unmatched_redaction` requires an empty `frames/` alongside the absent
stills and the absent `.video/`.

That assertion needs a **planted `demo.mp4`** to mean anything, and for one
round it did not have one. `beat_frames()` returns "there is no demo.mp4 to
extract frames from" *before* it creates `frames/`, and a refused take never
converts its webm — so "no review frames survived" was true whatever the exit
path did, and the `if clean:` guard that is supposed to keep frames off a
refused take could be deleted without a single assertion moving. It now writes
a real two-second mp4 into the directory first, which makes that guard the only
thing standing between the refusal and a `frames/` directory. The mp4 check
changes with it, from "the file does not exist" to "the file is still the one
we planted" — the same claim, since conversion writes over it, and equally
sharp.

The two text paths are checked by searching bytes, not by asking the recorder:

- every file the take wrote — `timeline.json`, `timeline.md`, the stills, the
  mp4, the narration clips, `frames/` and its two manifests — is read and
  searched for both literals, with no exemptions, so a leak path nobody
  anticipated still shows up. It is an `rglob`, not a list, which is why the
  review frames were covered by it the moment they existed;
- `.tts/` must hold **exactly** the clips for the lines that were narrated —
  not merely "nothing for the refused line", which is also true of an empty
  directory. The innocent line's clip existing is what makes the refused line's
  absence mean anything;
- the refused caption must leave **no beat** behind, and exactly one beat must
  carry a `[redacted]` selector — the `terminal()` call whose command held the
  key. Asserted positively, because "no beat contains the secret" is equally
  true of a log that dropped the beat.

The storyboard also tears the mask out mid-take the way a real app does —
rewriting the element's `style` attribute wholesale and removing the injected
stylesheet, which is what a framework re-render and this recorder's own
`spotlight()` clear both do — and requires that the next frame is masked again.
That is the assertion the `MutationObserver` exists for; with the observer
stubbed out, the video check fails on the frames between the tamper and the
next `shot()`.

**A mask that cannot be applied must kill the take, not quietly cover
nothing.** A second, few-second recording (`check_unmatched_redaction`) points
`redact()` at a key inside a *closed* shadow root — reachable by neither
Playwright nor an injected script, so there is no way to mask it — and requires
`SecretLeak`, no `demo.mp4`, no `.frame.png`, no raw capture in `.video/`, and
**no stills**. It takes one first, on purpose: web stills are full-bleed, and
for one round a failed take left them on disk holding the value it had refused
to write an mp4 for, while reporting that it had written nothing. The same
path covers the plain typo, `redact("#api-ky")`, which is the same failure with
a friendlier cause.

Two premises of the shadow-DOM case are asserted rather than assumed, because
if the fixture ever stopped putting those elements behind a real boundary the
take would go on passing while proving nothing: `page.locator("#sd-key")` must
find exactly one, and `document.querySelectorAll("#sd-key")` exactly none.

**Segments and the merge** — a demo recorded in two parts and joined by
`stitch()` ([#7](https://github.com/rogvid/skills/issues/7)). `segments/`
records the storyboard `SKILL.md` prescribes for a real time-skip: part one,
then a second `Recorder(segment=…)` that opens with an `interlude()` on the
blank page before navigating back. Each part writes its own `.seg.mp4` and its
own beat log; the demo-wide `timeline.json` is assembled from them.

**The merged timeline is graded by `check_timeline()` — the same function, and
the same assertions, that grade a single take.** That is the point rather than
an economy: the beats, the captions, the per-beat caption context, the
monotonicity and coverage of the timestamps, `timeline.md`'s table, the stills
on disk, and the measured "does this timestamp point at that frame" check all
apply unchanged. A segmented demo graded more softly than a recorded one is a
segmented demo nobody can trust. What the merge adds is a hand-written
*segment* column — a stitch that merged part one twice produces a perfectly
monotonic timeline of the right length, and only that column notices.

The offsets are the parts' **ffprobe durations**, never the storyboard's
nominal timing, and that distinction is load-bearing: the screencast drops
wall time during idle stretches, so a segment's video routinely runs ~0.9 s
shorter than its beats say it took. Injecting nominal timing here moves the
second segment's beats 2.1 s off their frames.

**How the acceptance criterion is measured, and why it can be stated at
100 ms.** Every segment carries a probe caption with a quiet run-up, and each
is timed *twice* — once in that segment's own `.seg.mp4` against that
segment's own beat log, and once in the stitched `demo.mp4` against the merged
one. `stitch()` copies the streams, so those are literally the same frames
carrying the same capture loss, and the **difference** between the two skews
is that segment's offset error with issue #18 cancelled out. Measured across
several takes: **+0 ms** for both segments, against a 100 ms bar; the absolute
skews behind them ranged -200 to +0 ms. A bar on the absolute skew could not
be set anywhere near that, because a segment whose capture stalled shows every
caption early in its own video too.

**One probe per segment, and that is load-bearing rather than thorough.** The
differential at segment *k* measures `offset_true - offset_recorded` for that
segment and nothing else. Timing only the last segment therefore checks only
the last cumulative offset: a constant shift applied to segment one's beats
leaves it exact, and with three or more segments every intermediate offset
would have no pixel measurement at all. That is not hypothetical — an earlier
round of this file timed one beat, and injecting +350 ms onto segment one
passed, printing `beat clock holds across the take (+400 ms)`.

The other half is each segment's *own* skew, graded against the same
directional bars a single take gets (250 ms log-ahead, 750 ms video-ahead) but
read out of that segment's own mp4. The differential cancels capture loss on
purpose, so it is blind by construction to a segment whose own video has slid
away from its own beat log; this is where that shows up, per capture.

Between them, `MAX_SKEW_DRIFT_S` across a boundary has nothing left to say,
and it is explicitly **a flake guard rather than a check**: the take's two
probes sit in different segments, so they rode different screencasts, each
with its own ~0.7 s of untickerable recorder setup, and a stall in the second
moves only the second. Measured across four takes: -80, +80, +80, and one at
**-520** — a real segment-two capture stall, not a merge error, which a 250 ms
bar here would fail on about one run in four. It is widened to one capture-loss
window for that reason alone, and the file says so where the number is set. A
constant shift of any segment's beats is caught by the two measurements above,
at 100 ms, not by this one at any width.

The rest is what is true of a merge and of nothing else:

| Checked | Why |
|---|---|
| before any stitch, each part has an `.seg.mp4` *and* an `.seg.timeline.json`/`.md`, and no `demo.mp4`/`timeline.json` exists yet | the cleanup assertion below is otherwise satisfied by a recorder that never wrote them, and every path assertion by a leftover |
| each part's own log starts within `MAX_UNMERGED_FIRST_BEAT_S` of zero | "the merged timestamps are large" proves nothing if they were large before the merge |
| `stitch(keep_parts=True)` leaves every part **and its beat log** | re-recording one expensive segment and re-stitching is the whole reason that flag exists, and it needs the logs as much as the mp4s |
| stitching twice produces the same beats | the merge has to be a function of what is on disk |
| the default `stitch()` leaves **no** `*.seg.*` at all | [#21](https://github.com/rogvid/skills/issues/21): a `.seg.timeline.json` outliving its `.seg.mp4` names a file that is gone, and the next stitch cannot tell it from a fresh one |
| the merged envelope's `segments` records, **all six fields**: `segment` / `media` in order, `duration` / `offset` against ffprobe and tiling `demo.mp4`, and `beats` / `recorder` / `determinism` against the segment's own log | it is what maps a merged timestamp back to the file it came from, and `SKILL.md` points a reader at the last three for the per-segment truth the envelope cannot carry once segments disagree. Checking only the first four was measured passing with `beats` hardcoded to 0 and `recorder` to `"Bogus"` |
| `segments[].beats` also equals how many merged beats carry that segment | the two can only differ if the merge dropped or duplicated some |
| `stitch()` refuses parts that disagree on codec, geometry, frame rate, or having an audio track | `concat -c copy` joins them and exits 0. A frame-rate mismatch was measured putting a beat **1.92 s** from its frame; a geometry mismatch silently keeps part one's dimensions; a silent part followed by a narrated one makes concat drop the narration entirely. None is reachable through the shipped recorders — nothing enforced it at the join |
| `stitch()` refuses a segment log written for a different recording of that segment | the `media`-name check cannot see it: both sides derive from the same segment string. Re-recording one part and merging it against the previous take's log is the ordinary way to get here, and it was accepted silently (6.6 s log against a 2.0 s part) |
| every part is probed *before* ffmpeg runs, and `.concat.txt` is removed even when it fails | a truncated part makes concat exit 0 and `media_duration` raise afterwards, leaving `demo.mp4` with no `timeline.json` — the one state a reader cannot tell from a demo that never had beats |
| `index` is renumbered to the position in the merged file, `segment_index` is **not** | [#22](https://github.com/rogvid/skills/issues/22): `(segment, segment_index)` names a beat the same way before and after a merge, which `index` alone cannot. Asserted in every take, not just this one — for a single take it is 0, 1, 2, … |
| a take recorded in one piece carries no `segments` key | that key means "assembled by stitch()", and a reader would otherwise be told a single recording has parts |


**Terminal redaction** — `terminal-redaction/`, the PTY half
([#5](https://github.com/rogvid/skills/issues/5)). Different mechanism,
different failure mode: there is no DOM to cover, so the only intervention is
a scrubber between `os.read()` and `term.write()`, and everything downstream —
the frames, the stills, and the xterm buffer `wait_for_text()` matches
against — is drawn from what that scrubber let through.

A shell script prints one tagged value per line, all 28 characters wide so
they share a column, and the take is graded on the pixels of those rows:

| row | what it is | what hides it |
|---|---|---|
| `key` | a registered value printed by a command | the registry |
| `ans` | a registered value with a **colour escape inside it** | matching an escape-stripped copy |
| `hid` | the same, cut by `ESC[?25l` — what every spinner emits mid-line | the same, once "inert" means more than SGR |
| `osc` | the same, cut by a window-title OSC | the same |
| `shp` | a `ghp_`-shaped token **nobody registered**, printed in one burst | shape detection alone |
| `str` | a `ghp_`-shaped token written **one character at a time** | shape detection *across quiet boundaries* |
| `pau` | an `sk-`-shaped token **paused 0.4 s mid-value** | the same |
| `anc` | a `ghp_`-shaped token paused after its **first character** | the same, plus the token-boundary rule |
| `slw` | a `ghp_`-shaped token paused **past** the hold window | nothing — it is the documented limit, graded as one |
| `aws` | an `AKIA`-shaped token nobody registered | shape detection alone |
| `jwt` | a JWT nobody registered | shape detection alone |
| `pwd` | `send(Secret(...))`, echoed back by the PTY | the registry, one character per read |
| `ctl` | never registered, matches no shape | nothing — it is the reference |
| `ref` | the literal string `[redacted]` | nothing — it is the reference |

The `str`, `pau`, `anc` and `slw` rows are the ones a scrubber that flushes on
an idle poll gets wrong, and they are why the printer is a shell script rather
than a `printf`.
Capping `os.read()` cannot manufacture a *time* boundary: capped reads come
back-to-back off a full buffer and the scrubber never sees the PTY go idle
mid-value. `str` writes at 5 ms per character, which is slower than the
recorder drains, so `select()` reports nothing ready between every character.
`pau` and `anc` stop dead in the middle of a token — `anc` after one
character, where nothing yet says "credential" and only *where it sits* does.

`slw` stops for longer than the recorder will hold, and is the only row that
must come out **legible**. That is not a gap in the take, it is the take
grading a gap: `SKILL.md` says shape detection has a clock, and the clock has
to be measurable from outside as well as inside. `pau` pauses 2.0 s and must be
masked, `slw` pauses 4.0 s and must not; together they pin `_ANCHORED_HOLD_S`
(3.0 s) from both sides, with a second of margin either way because the
quantity the recorder measures is wall-clock idle time on a loaded CI box.
Injected at 5.0 s, `slw` comes out masked and the take says the documented
limit moved; injected at 1.0 s, `pau` and `anc` come out legible at 41-45
against the mask. Before this pair, `_ANCHORED_HOLD_S` could be set to any
value above ~0.45 s and the whole suite still passed.

**The split across `os.read()` boundaries is forced, not hoped for**, and that
is the assertion the acceptance criterion turns on. `capped_pty_reads()`
replaces the `os` module *in `demo_recording.terminal` only* with one whose
`read()` returns at most 7 bytes and keeps every fragment. The take then
asserts, from those fragments, that the printed key was reassembled from more
than one of them — measured 5 — and prints the number. Without the cap this
box hands the whole value over in a single read: injected, the assertion fires
and says so, which is the difference between testing a carry buffer and
hoping one was needed. The `pwd` row needs no help; the PTY echoes a typed
character as it is typed, so it arrives in 28 fragments on any box.

The ANSI case is asserted at the byte level too, over the printer's output
only: the raw stream must contain `value-head`, `ESC[32m`, `value-tail` and
must **not** contain the value whole — otherwise a literal substring match
would have found it and the row proves nothing.

**The pixels are graded three ways, and the second is what makes the first
mean anything.** Every crop is the same 28 cells of one row at native
resolution:

- a masked row against the `ref` row must be **the same picture** — mean
  absolute luma difference 0.0 in the stills, 1.2-2.4 in the mp4 (codec noise
  on identical glyphs), bar 3.0 / 6.0;
- the `ctl` row against the same `ref` row must **not** be: 40.6 in the
  stills, 42.7 in the mp4, bar 12.0. That row is a 28-character key in the
  same font at the same size in the same frame — exactly what a leak looks
  like — so this says the comparison can tell a key from `[redacted]` at all.
  With the scrubber taught to swallow the control too, it collapses to 0.0-1.4
  and the take says every reading below it is vacuous;
- the `ctl` row must be **sharp** (edge energy 28-31, floor 6.0 / 5.0). With
  the terminal's foreground colour set to its background it scores 0.0-0.2 and
  the take refuses to grade anything, which is the answer a blank recording
  needs: every "these two crops match" reading is also true of two crops of
  nothing.

Not OCR, and not a claim to be. It says the pixels at that row are the mask
and not a key; it cannot say *which* mask, and no assertion here reads text
back out of a frame (the same gap the web half has).

**Two more paths, checked without pixels.** The rendered screen — what
`wait_for_text()` and `wait_for_prompt()` read, and the buffer every frame is
drawn from — must hold none of the thirteen values and must hold the control
intact. And every byte the take writes is swept for all thirteen, with no
exemptions; the printer script lives in a temp directory of its own precisely
so the sweep grades what the *recorder* wrote.

**Two values are longer than the recorder's 4096-character fragment ceiling**,
and they pull in opposite directions. A 4208-character JWT says a hold clamped
mid-match must not write the head of a credential and mask the tail; a
4208-character *registered* value says the ceiling must not bound the registry
at all, whose hold is already bounded by the value's own length. Neither is
graded on pixels — 4 kB of base64 wraps over fifty rows and scrolls every
measured row away — so they go last, the video is graded only up to that
point, and both are checked on the screen text and the byte sweep against a
64-character witness. The whole value is the wrong needle: a clamped hold
leaks a *prefix*, and a take rendering the first 111 characters in the clear
was measured passing a check for the token itself.

**`key()` must refuse too.** It is the one verb whose beat log a scrub cannot
clean: the beat records the keys joined by spaces, and no literal match on the
value can see `'s k - l i v e - …'` in `timeline.json`. So the call raises
rather than the log leaking, and the take asserts nothing reached the screen
first.

**`run()` and `send()` must refuse.** Both are authored text echoed on camera,
the terminal's `caption()`. Each is called with a registered value, must raise
`SecretLeak`, must not type a character before doing so (asserted on the
screen afterwards), and must not quote the value in the exception. The two
refused beats are asserted to carry a `[redacted]` selector — positively,
because "no beat holds the secret" is equally true of a log that lost the
beats — and exactly one `send` beat must carry **no** target at all, which is
the `Secret`: it is deliberately not a `str` so that `_verb_target` cannot
write it into `timeline.json`, and teaching `_verb_target` to stringify it
fails this.

**The `hld` row is the other half of the carry rule, and it is timed.** The
scrubber holds back any trailing fragment that could still complete a secret —
which means a program whose last characters could begin a token renders short
until it writes again, and every sync verb reads that screen. So the printer
ends with `hld xe` and no newline, then parks on a `read`.

`xe` and not `gh`, and that is the case. Both are shape fragments — `e` could
begin a JWT — but this one sits *in the middle of a word*, where a credential
never starts, so it must go out on the first quiet poll. The take measures how
long it takes to appear and fails past 1.5 s. A rule that cannot tell `hld xe`
from `hld gh` puts it on the three-second anchored clock: injected, it arrives
at 3.9 s and this fails, which no assertion about the *final* screen can see.
Remove the release altogether and it never arrives at all.

The three arms are asserted separately and injected separately: this row (a
fragment mid-word, released at once), the `str`/`pau`/`anc` rows (a fragment
where a token would start, held for seconds), and the `pwd` row (a fragment of
a *registered* value, held with no clock — the echo arrives one character per
read with an idle pump between each, so releasing those would print a password
one character at a time).

**And a value the stream can never show contiguous must kill the take — on
every way out of the `with`.** A program that writes `ESC[6;1Hcup <head>` and
then `ESC[6;13H<tail>` puts the registered value on screen as one word while
no substring of the byte stream contains it; the premise is asserted, not
assumed, by requiring the value to be on the finished screen. The scrubber
cannot see that. Documented as uncovered, and uncovered has to mean *refused*,
so `_verify_redaction_final()` reads the finished terminal buffer (visible
screen *and* scrollback) and raises `SecretLeak`. No `demo.mp4`, no
`timeline.json`, no still, nothing in `.video/`, and a message that says the
value was found *on screen* without quoting it.

Three recordings, because "every way out" is three different bugs and the
first version of this check only covered the first:

| arm | how the `with` ends | what it caught |
|---|---|---|
| `clean` | the storyboard finishes | with the check removed: a normal mp4, the key legible in every frame, `issues: []`, `strict=True` satisfied — the quietest failure in this harness |
| `crash` | the storyboard raises after the value is on screen | the check was gated on `exc_type is None`, so a `wait_for_text()` timeout or a Ctrl-C skipped it entirely and **kept the still** — 129 kB of PNG with the key on it. On the web side the same structure is harmless because a still is CSS-masked when it is taken; here a still is the raw screen |
| `tail` | the value lands *after* the last verb, inside the window a narrated take holds open so it does not end mid-sentence | the check ran before that window and before the scrubber's final flush, so it vouched for a screen the recording does not end on. Injected, it writes an 82 kB mp4 and a timeline and reports nothing wrong |

The `crash` arm asserts the recorder re-raises what the *storyboard* threw
rather than a leak report: the timeout is the message that says what to fix,
and the leak has already cost the artifacts, which is the part that matters.

The `tail` arm needs a narration tail and the smoke run has no
`ELEVENLABS_API_KEY`, so it sets `_line_end` directly — the one field
`_finish_line()` reads, and the one `_start_line()` sets from
`media_duration(clip)`. Same code path, no key required.

**Evidence** — every beat left `evidence/beat-NN.json`, a text account of what
was on screen. Its acceptance criterion ([#9](https://github.com/rogvid/skills/issues/9))
is that *a reviewer given only those files can state what the frame showed
without seeing an image*, which is not a sentence a test can assert. It is
asserted as its consequence instead: named facts about the fixture app, written
out by hand in `WEB_EVIDENCE` / `TERMINAL_EVIDENCE`, looked for in the page text
the recorder captured for the beat that showed them.

**The lists come in pairs, and the second one is the one that bites.**

| beat | must be readable | must **not** be |
|---|---|---|
| `shot("01-dashboard")` | `$128,400`, `snapshot 1 of 3`, `Refresh`, `Harbor Supply Co.`, `Ferrari Logistics`, and the caption `A small dashboard.` | `$134,950`, `snapshot 2 of 3` |
| `shot("02-filtered")` | `Harbor Supply Co.`, `Seattle`, `Filter by city.` | `Ferrari Logistics`, `Cascade Outfitters`, `Pine & Poplar` |
| `shot("03-refreshed")` | `$134,950`, `snapshot 2 of 3`, `Refresh reloads it.` | `$128,400`, `snapshot 1 of 3` |
| `shot("01-echo")` (terminal) | `echo hello from demo-video` **and** `hello from demo-video` | `ls -1`, `AGENTS.md` |
| `shot("02-listing")` (terminal) | `ls -1`, `skills`, `tests`, and the earlier `hello from demo-video` still in scrollback | — |

Without the right-hand column every one of these passes on a recorder that
captured the page **once** and wrote the same dump into all 23 files: `$128,400`
appears in that dump, so does `Refresh`, so does everything else. With it, a
single stale capture fails on the first beat that should have moved on. The
same shape does the work in `02-filtered`: the evidence has to show the four
rows the filter *removed* are gone, which is the fixture's own post-condition
restated in text.

The facts are searched in the **page text only** — `aria`, `scope_aria`,
`html`, `screen` — never in the beat record embedded alongside them. Every
caption is in `beat.caption` already, so searching the whole file for one would
pass on a recorder that captured no page text at all: the assertion has to be
about what the page said, not about the log quoting itself.

Structure, checked both directions like the stills: every beat in
`timeline.json` names an `evidence` path, every named file exists and parses,
`evidence/` holds nothing no beat names, and each file's embedded beat block
matches that beat's `index`, `verb`, `selector`, `caption` and both timestamps.
Without that last check every file could hold the same screen and the facts
above would still be found *somewhere*.

**The spotlight scope** is graded on its own, because it is what the issue says
the capture is scoped to: the `spotlight("#kpi-rev")` beat must name that
selector in `scope`, carry `$128,400` in `scope_aria` and `id="kpi-rev"` in
`html`; the beat that *clears* the spotlight must carry neither, or the scope
outlives the highlight.

**The size cap is graded in the same take.** The fixture's whole ARIA tree is
2.3 kB against a 12 kB cap, so truncation cannot be provoked on it, and
slackening the cap to meet the fixture would be grading the wrong number. The
take appends 900 list items to the page and spotlights them, and then:

- the `pause` beat **before** the bloat must come back with `truncated == []`
  and an ARIA tree under the cap — a recorder that marked every field
  truncated would satisfy everything else here;
- the `pause` beat **after** it must have `aria`, `scope_aria` *and* `html` in
  `truncated`, all three carrying the marker text inline where they stop, and
  all three cut *to* the budget (`limit < len(field) <= limit + marker`) rather
  than merely under some ceiling. All three, because a cap applied to `aria`
  and not to `scope_aria` is a cap on a third of what a spotlight beat writes;
- the package's own `EVIDENCE_LIMITS` and `EVIDENCE_SCHEMA` must equal the
  numbers written in `tests/smoke`. Reading the caps off the code being graded
  would agree with it whatever it says; asserting they match means widening one
  has to be done on purpose.

`screen` is the fourth budget and no take here bloats a TUI far enough to reach
it, so it is graded as the **contract of `_cap_text` itself** — under its
budget nothing is cut, 500 over it exactly 500 are, the marker is there, and
the result never exceeds budget plus marker. That is a unit check, stated as
one, and it is the only assertion on this axis that does not come from a
recording.

Per file the ceiling is 136 kB and per directory 512 kB — observed 39 kB across
23 web beats and 9 kB across 18 terminal ones. The file ceiling is deliberately
loose because **the caps count characters and it counts bytes**: 32 000
characters of CJK is ~96 kB of UTF-8 before JSON escaping, so a tight byte
ceiling would fail on a legitimately-capped file. What grades the caps is the
character count per field above; this only catches one that stopped being
applied at all.

**Evidence is the fifth leak path, and it is the one with no pixels in it.**
Every other artifact here is an image; `redact()` is a *pixel* control, and the
value it covers is still in the DOM — which is what an evidence file is a dump
of. Two takes grade it, and they grade different halves.

`redaction/` sweeps its evidence for the same 13 literals as everything else,
which works only because that take now **sets a spotlight**. For one review
round it did not, `html` was null in all 31 files, and the entire `outerHTML`
surface sat outside the sweep — the take with the secrets in it graded none of
the field most likely to carry one. It also runs `check_evidence`, because the
sweep alone grades nothing: replacing `_evidence_payload` with a constant
returning two control strings **passed the whole take**, sweep and all.

`evidence/` is the take for the shapes that leak into *text and nothing else*.
It records `?evidence=1`, redacts nine cards, registers two values, and sweeps
for twelve literals — every one of which was readable in `evidence/*.json` when
the round that introduced it was reviewed:

| shape | why a picture never sees it |
|---|---|
| `WSPC` | a value indented on its own line in hand-written markup. `textContent` returns `"\n      sk-live-WSPC…\n    "`; the ARIA tree returns `sk-live-WSPC…`; `str.replace` between them finds nothing. **The most ordinary shape there is** — the older fixture escaped it only because every key was assigned from JS, which makes one unpadded text node |
| `TICK` | rewritten every 5 ms. The capture reads the page three times, so the harvest sees one value and the snapshot the next |
| `LBLD` | the accessible name of a redacted card, sourced by `aria-labelledby` from a `display:none` element outside it. On nobody's screen, in nobody's frame, and in the ARIA tree. The card carries `role="group"` deliberately: a plain `<div>` has no role, an ARIA snapshot shows it no name, and the shape would prove nothing |
| `SLOT` | light DOM slotted into a redacted element *inside* a shadow root. The redacted element's own `textContent` is empty and the value is a light child of the host — inside the redaction in the flattened tree, outside it in the DOM. It takes two separate mechanisms to hold: walking `assignedNodes()` when harvesting, and following `assignedSlot` when deciding what counts as outside |
| `VALU` | an `<input>` value set from JS, so there is no `value` **attribute** to read — only the property |
| `CHLD` | a key whose characters are three text nodes, each an ordinary string alone |
| `ATTR`, `JSON` | `data-*` attributes the page never renders, which only exist in evidence because the markup dump is a surface this feature created |
| `BLED` | in a card whose *label* also renders outside it — the mirror defect, below — and **captioned** by the storyboard, which is the case that reaches `timeline.json` |
| `HATT` | mirrored into `title`, `data-value`, `aria-label` and an input's `value` on siblings nothing redacts. The harvest read those when deciding what "renders in the clear", so a copy-to-clipboard button carrying the key it copies exempted that key from masking **everywhere**. None of those channels is painted by anything, and `_EVIDENCE_HTML_JS` already strips the same attributes out of `html` on exactly that reasoning — the feature contradicted itself for a round |
| `HIDE` | the same trick in CSS: a `.sr-only` clip, `opacity:0`, `visibility:hidden`, `left:-9999px`. `checkVisibility()` called with no arguments reports all four visible; it models `display` and `content-visibility` and nothing else, and `display:none` was the one shape this fixture happened to use. Measured leaking into `timeline.json` and `timeline.md` as well as all six evidence files |
| `AMPS` | a registered secret containing `&`, which `outerHTML` writes `&amp;`. The mask searched the raw literal, the withhold fallback stripped tags but not entities, and the end-of-document backstop was a plain `in` — all three missed, and the file came out with `aria` reading `token=[redacted]` and `html` carrying the value in full |

One literal covers each of `HATT` and `HIDE` rather than one per channel, and
that is deliberate: every element in a family holds the same value, so any
single channel regressing puts that value back into `outside` and un-masks it
everywhere. One assertion, four shapes, and the failure names the family.

Three of those were written the wrong way first and passed while proving
nothing: the slotted value was a DOM descendant of the redacted element, the
labelled card had no role, and the input's value was an attribute. Each was
found by injecting the fault the shape exists to catch and watching the run
stay green. **A leak fixture that cannot be made to fail is a comment**, the
same as an assertion.

The sweep runs over **every file the take wrote**, not only `evidence/`. That
is what catches the storyboard's captioned value in `timeline.json` and
`timeline.md` — the two files this skill tells people to commit. The harvest
that keeps a redacted value out of the evidence has to reach them too, or the
same string is `[redacted]` in one file and in the clear in the one beside it.

Against the secrets, `EVIDENCE_KEEP`: four strings that must **survive** — the
sentence sharing a word with a redacted card's label, an ordinary KPI, the text
of the element whose attributes hold keys, and a table row. Without that half,
every assertion above is satisfied by a recorder that captured nothing, and by
one that masked everything. Both happened: harvesting every node of a redacted
card also harvests its label, and an earlier round rewrote every unrelated
paragraph as `[redacted] for the quarter was steady.` A card holding
`sk-<i>live</i>-CHLD…` registered `"live"` and rewrote every other key on the
page.

The rule that fixes it — a harvested string is a mask only if it renders
nowhere outside the mask — turns on what "renders outside" means, and two
readings of that were wrong before this one:

- a first version counted the page's own inline `<script>` text, so every
  literal in the fixture's source read as "already on screen in the clear" and
  four keys stopped being masked at all;
- the second counted the recorder's **own caption bar**. A storyboard that
  captions a redacted card's value writes that value into an element outside
  the mask — so the value was exempted everywhere, and one authoring mistake in
  the frames (which no recorder can undo) became the same mistake in
  `timeline.json` (which it can). Recorder chrome does not get a vote on what
  the app renders.

Five more assertions in that take, each for a claim that would otherwise be
untested:

- **The refusal.** Two beats run while the rotating card is live and must come
  back `omitted`, with no `aria`, `scope_aria` or `html` — and a third, after
  the card is removed, must **not**, or "every beat refuses" would satisfy the
  first one and grade nothing. Injecting a payload that always refuses fails
  the third *and* all four `EVIDENCE_KEEP` controls, which is the shape the
  whole axis is built on.
- **Elided, not withheld.** A third spotlight lands on `#ev-child-card`, which
  the take *redacts*, and its markup must come back as the target's own tag
  wrapped around one `[redacted]` — two tags, nothing between them.
  `querySelectorAll('*')` never returns the element it was called on, so a
  serializer that elides only descendants misses exactly the element a
  storyboard redacts and spotlights together. What it writes instead is
  `sk-<i>live</i>[redacted]`: elided wherever the substring mask happened to
  reach, in the clear everywhere else, and passing every other assertion here
  — measured. Counting the tags is what catches it.
- **A refusal in the capture is fatal.** `evidence-leak-fatal/` records three
  beats with a `Recorder` subclass whose `_evidence_payload` raises
  `SecretLeak`, and the take must die with that exception and leave **nothing**
  — no mp4, no timeline, no evidence. `_capture_evidence()` runs in a `finally`
  and wraps the payload in a broad `except` so a diagnostic cannot lose an
  otherwise fine take; a `SecretLeak` travelling that path was being swallowed,
  and the take passed with the mp4 written. Injected rather than provoked, on
  purpose: every real source of one is also a source elsewhere in the take, so
  a fixture would not say which path refused.
- **Mask-then-cap, where the two meet.** The take re-pads a list item until a
  registered secret's characters *span* the 8 000-character markup budget
  (asserted, and printed: `chars 7984-8016`), then looks for 12- and
  20-character heads of it as well as the whole literal. Cap first and the
  head survives as the last thing in the file, which a search for the literal
  misses — injecting that order leaves `sk-live-CUTT` in the evidence and only
  the 12-character search finds it.
- **Stale evidence.** Two files are planted in `evidence/` before the take, as
  a previous recording would have left them: one this take's naming owns,
  which must be deleted, and one belonging to another segment, which must not.
  `record.py` is committed precisely so it can be re-run into the same folder,
  and yesterday's files would otherwise sit there holding the value you added a
  `redact()` for today.

It is also the only take that records with `segment=`, so
`evidence/<segment>.seg.beat-NN.json` is exercised rather than merely designed
([#22](https://github.com/rogvid/skills/issues/22)).

`terminal-wrap/` is the take for the one transformation the terminal
introduces on its own. `__termText()` walks the xterm.js buffer a row at a time
and joins with newlines without consulting `isWrapped`, so a credential that
crosses the last column arrives split — and the mask was elastic about
whitespace the *literal* has and exact about whitespace the *text* has, so it
matched neither half. The end-of-document backstop was a plain `in` over
`json.dumps` output, where a newline is the two characters `\n`, so it missed in
the same direction; a backstop that fails the way the thing it backs up fails is
not one.

`terminal-problems/` could never provoke it — `echo printed-below` plus a
20-character secret is ~60 columns against a 120-column terminal — so this take
measures `term.cols` at record time and pads the line so that
`TERMINAL_WRAP_HEAD` characters of the secret land before the boundary. The
geometry is asserted and printed (`chars 112-140` at column 120), because a take
that quietly stopped wrapping would be a test of an ordinary echo. The sweep
that grades it deletes whitespace from both sides before comparing, which is
what a reader with `tr -d` does.

`terminal-problems/` carries the last piece: a command *prints* a registered
secret, and the screen dump must mask it while the word printed beside it
survives. `TerminalRecorder` has no `redact()` at all
([#5](https://github.com/rogvid/skills/issues/5)), so `register_secret()` is
the entire defence for its evidence. The surviving word is looked for in
`screen` **only** — it is a word in the command, and the command is in the beat
record embedded in the same file, so searching the file finds it whether or not
one character of the terminal was captured. Written the easy way first, and an
injected `{"screen": ""}` payload was measured passing it.

`tests/smoke --evidence-only` records just this take and the refusal take,
which is what makes an injection loop over this axis affordable.

## Known gaps

Things a pass does **not** prove. They are listed because an assertion nobody
knows is missing is worse than one that is openly absent.

- **A total stylesheet failure is below the luma floor.** Measured with real
  screenshots: unstyled-HTML fallback scores 9.97, a sparse white page 3.54, an
  error page 4.05, healthy 15–17. The useful band is 6 → 15, so a page that
  rendered with no CSS at all lands at ~10, above the 6.0 floor. Raising the
  floor toward 15 would risk flake from CI font rendering. Mitigated, not
  solved, by the `getComputedStyle` check on `#refresh` — which catches the
  fixture's own stylesheet failing, but is one assertion about one property and
  will not notice arbitrary visual regressions. Tracked in
  [#16](https://github.com/rogvid/skills/issues/16).
- **The terminal caption check has the thinnest margin in the harness** — 2.7
  healthy against a 1.0 floor, where everything else has 4x or better. The
  terminal's caption is a dark box on a dark terminal, so only its text carries
  any luma change. If CI font rendering ever drops it under 1.0 this will flake;
  the DOM caption assertions would still hold. Tracked in
  [#16](https://github.com/rogvid/skills/issues/16).
- **The content rects couple to recorder internals** (`Recorder._geom`, and the
  `#__term_host` id). Reading them at runtime means a geometry change follows
  automatically, and a *removed* `_geom` fails loudly — but a change that keeps
  the attribute while moving the app elsewhere would silently score the wrong
  pixels. Tracked in [#17](https://github.com/rogvid/skills/issues/17), which
  proposes the recorder expose its geometry as public API.
- **This harness no longer sees the drift real demos have, on purpose.**
  Chromium's screencast stalls during idle stretches and Playwright's webm does
  not pad the gap, so a real take loses ~0.6 s of wall time per stall and every
  frame after it sits that much early (a 32 s take was measured losing 1.44 s;
  it is not confined to late in a take, it accumulates with idle time).
  `TICKER_JS` removes the confound here so the timing bar grades the beat log —
  which means **a pass says nothing about how well a real, tickerless demo's
  timestamps line up.** Consequence: a frame extracted at a beat timestamp can
  show the wrong beat, and narration inherits the same lag because audio rides
  the wall clock while pixels ride the screencast. Tracked in
  [#18](https://github.com/rogvid/skills/issues/18), which matters most to
  [#8](https://github.com/rogvid/skills/issues/8).
- **Nothing reads the caption text off the video.** The timing check proves the
  caption *band* changed when `timeline.json` says it did; that the words are
  the right words is a DOM assertion (`check_caption`) taken at record time.
  Between them a recorder that drew the wrong caption at the right moment would
  be caught, but only because two separate checks happen to overlap — no single
  assertion reads pixels back as text, and none is going to without OCR.
- **A review frame is graded for whether a caption was on screen, not for
  which.** `_check_frame_captions()` closes the "nothing says which beat a frame
  shows" gap only as far as one bit goes: a captioned beat's frame must show a
  bar and an uncaptioned one's must not. Two beats carrying *different* captions
  are indistinguishable to it, so a stall that slid a frame from one captioned
  beat to another captioned beat still passes. Tracked in
  [#60](https://github.com/rogvid/skills/issues/60), which would make the
  mapping readable off the frame instead of inferred.
- **Frames within 750 ms of a caption change are not graded for content at
  all**, and on these storyboards that is 8-9 of every take's frames. The
  exclusion is real coverage lost, not a formality: it is exactly where #18's
  drift puts a frame on the wrong side of a change, and where the harness
  therefore cannot tell a recorder bug from the capture. `check_beat_frames()`
  still grades those frames for placement and for byte-identity against
  `demo.mp4`; only the pixel claim is withheld.
- **No storyboard beat is long enough to make the recorder run scene
  detection.** `SCENE_MIN_SPAN_S` is 3 s and the longest beat either take
  performs is a 2 s `pause`, so the *manifest* half of that check — scene
  frames only inside long beats — is vacuous today and says so where it is
  written. The mechanism is graded directly instead (see **Review frames**),
  which is what stops the vacuity from being total.
- **The wall-clock regression cannot be fault-injected.** The recorders time
  beats with `time.monotonic()`; using `time.time()` only misreports when the
  system clock actually steps, which no assertion here can provoke. It is not
  hypothetical — a WSL2 box was measured stepping 573 ms backwards inside 8 s,
  which is how the bug was found — but a pass does not prove the fix is still
  in place. Reading the diff does.
- **Issue attribution is bounded, not exact.** Playwright's sync API delivers
  page events only while it is inside a call, so the recorder pumps every
  100 ms during a hold and refuses to attribute an event to a beat that has not
  been open since the last pump. What that leaves: an event fired inside the
  pump interval of a beat boundary can land on either side of it, and a beat
  that blocks in a long *non*-Playwright call — narration being synthesized —
  queues events for its whole duration and gets `beat: null` for all of them.
  Null is the deliberate answer in both directions, but "null" and "right" are
  not the same thing and only the second is what a reader wants.
- **Nothing checks most of an issue's fields.** `kind`, `message`, `beat`,
  `verb` and one `caption` are asserted; `t`, `url`, `line`, `status`, `method`
  are not. `t` is knowingly the *observation* time and can sit outside the beat
  it names — measured at 3.53 s for a `nonzero_exit` whose `run` beat ended at
  3.4 s. Tracked in [#34](https://github.com/rogvid/skills/issues/34).
- **Nothing checks popups or new tabs.** The recorder watches one page, so a
  demo that opens a second one records nothing about it and `strict=True`
  cannot refuse it. Tracked in
  [#33](https://github.com/rogvid/skills/issues/33).
- **Nothing checks the 200-issue cap, or a `run()` that is never waited on.**
  `issue_count` is asserted equal to `len(issues)`, which is the uncapped case
  only — so the path where a fatal issue arrives past the cap and is counted
  but not recorded is unexercised, as is a `run()` whose prompt never comes
  back and therefore ends `exit_code: null`.
- **Nothing checks what teardown flushes.** `_pump` holds back trailing bytes
  that could still become an exit-status escape *or* the start of a secret,
  and `_stop` writes both to the terminal on teardown — masking a dangling
  fragment of a registered value as it goes. No assertion reads the final
  frame, so a regression there would lose the last few bytes of a program's
  output silently, and `_StreamRedactor._mask_dangling` is unexercised. Making
  it fail needs a take that ends mid-secret and an assertion on the last
  frames of the mp4, which is a race with the screencast.
- **The terminal scrubber's colour bookkeeping is unasserted.** A masked run
  swallows any SGR sequence inside it and re-emits it after the mask, so the
  rest of the line keeps its colour. In this fixture the colour is reset
  inside the same run, so removing that re-emission changes no pixel here.
  It is cosmetic either way — nothing about *what* is hidden depends on it.
- **Only SGR-interleaved secrets are caught, and only that is tested.** A
  value broken up by a cursor movement — a redrawn progress line, a TUI
  painting in two passes, a terminal-wrapped line — is not contiguous on
  screen and is deliberately not matched (see SKILL.md). Nothing here records
  such a program, so the harness does not measure how common that is.
- **Shape detection is graded on how a token is *split*, not on the pattern
  list.** All four patterns are printed unregistered and pixel-graded — `ghp_`
  on the `shp`, `str` and `anc` rows, `sk-` on `pau`, `AKIA` on `aws`, a JWT
  on `jwt` — so removing any one of them fails the take. What is not covered
  is the *inside* of each pattern: one spelling of each shape is printed, so a
  regression that narrowed `gh[pousr]_` to `ghp_`, or dropped `ASIA` from the
  AWS pattern, still passes.
- **Nothing checks a non-bash shell.** The exit status arrives through `$?` and
  `\#` expanded in `PS1`, which is bash behaviour; zsh needs `PROMPT_SUBST` and
  would leave every `exit_code` null. Only `/bin/bash` is recorded here — the
  `terminal-race/` take's slow shell `exec`s it.
- **Determinism's motion rule is asserted only where a stylesheet can reach.**
  `element.animate()` (Web Animations), `requestAnimationFrame` loops and
  canvas rendering are untouched by it and unasserted here
  ([#35](https://github.com/rogvid/skills/issues/35)); so are animations
  inside a shadow root, and any the app declares `!important` at higher
  specificity ([#36](https://github.com/rogvid/skills/issues/36)). The
  `::before`/`::after` arms of the rule *are* asserted, because an animated
  pseudo-element is the most common spinner on the web and dropping them from
  the rule passed this harness until a probe was planted for it.
- **No take records with a non-default `clock`, `timezone_id` or `locale`.**
  Every take uses the built-in defaults, so the parameter path and
  `_clock_epoch_ms()`'s parsing are exercised nowhere, and the locale
  assertion had to be fault-injected with a forced `de-DE` to be seen failing
  at all — this box is already `en-US`. Tracked in
  [#37](https://github.com/rogvid/skills/issues/37).
- **The determinism takes prove nothing about what the recorder cannot
  control.** They record a static fixture served off the local disk, so
  "identical twice" says the *browser* was pinned — not that an app with its
  own `Math.random()`, a server that returns fresh rows, or a page whose layout
  depends on when a request came back would reproduce. Nothing here can assert
  that, because there is nothing in the recorder to assert about it; it is
  called out in `SKILL.md` as the storyboard author's problem instead. The
  fixture's `?entropy=1` hook deliberately does **not** include a random number
  for the same reason — seeding it in the fixture would be testing a control
  that does not exist.
- **`TerminalRecorder`'s PTY child is outside all of it.** The determinism
  controls are context options and page init scripts, so a `date` run in a
  terminal demo prints the real time in the machine's own zone. Tracked in
  [#26](https://github.com/rogvid/skills/issues/26).
- **Nothing checks audio.** Narration is forced off and no assertion touches the
  aac track, so the whole speech path — `tts_clip`, the `.tts/` cache, the
  `adelay`/`amix` mixing in `_convert` — is untested here.
- **Nothing checks audio.** The redaction take narrates (against a stubbed
  synthesizer) and asserts *which lines were cached*, which exercises
  `_prepare_line`, the cache path and the `adelay`/`amix` mixing in `_convert`
  far enough that a crash would surface — but no assertion decodes the aac
  track, and the clips are silence, so nothing here can tell a correctly mixed
  narration from a silent one landing at the wrong offset. The real
  ElevenLabs call is never made.
- **Nothing reads the burned-in caption text off the video, which the
  redaction take needs and does not have.** A caption holding a secret is
  refused before it is drawn, so the leak is prevented rather than detected —
  but if that guard were bypassed *only* on the drawing path, the words would
  be in the frames and every pixel assertion here would still pass. What
  catches the caption path today is the beat log, the `.tts/` set and the byte
  sweep, all of which are downstream text checks, not pixels. Same OCR-shaped
  hole as the caption-wording gap above.
- **Four guard sites cannot be fault-injected on their own.** Each is a
  redundant belt, and removing any one alone leaves the run green:
  - the first-paint gate. With `redact()` restricted to CSS the in-page
    stylesheet masks from the first paint, so weakening the gate leaks
    nothing — which is why its integrity is asserted directly (see above)
    rather than through a leak it no longer prevents.
  - `_before_shot()`, which re-pushes the mask before a still. The mask is in
    the page, the observer keeps it there, and a still *is* the page. It only
    becomes load-bearing with the observer *also* disabled, and then the
    tampered still leaks and the check fires.
  - the blur underneath the cover. It is what a stylesheet can do with no JS,
    and it reaches ink outside the cover's rectangle — but with the cover
    working, removing it changes no measurement here.
  - `caption()`'s own `_no_secrets` call, and `_prepare_line()`'s. The
    relationship is **symmetric**: `caption()` calls `_prepare_line()`
    immediately, so removing either one still leaves the other to refuse the
    line. Only removing both leaks, and then six assertions fire. An earlier
    version of this file presented the first as tested and the second as the
    redundant one; that was wrong in a way worth stating, because it claimed
    coverage that does not exist.
- **The segmented take records two parts of one storyboard, not a real
  time-skip.** Nothing waits between them, both are the web recorder against
  the same fixture, and no segment is re-recorded on its own — so the flow
  `keep_parts=True` exists for (re-record one expensive part, re-stitch) is
  exercised only as "stitch the same parts twice". A demo mixing a web and a
  terminal segment, which the merged envelope's `"mixed"` recorder value is
  for, is recorded nowhere.
- **The differential measurement dies before its own bar does.** Each reading
  goes through `caption_appearance_s`, whose search window is `ALIGN_PRE_S`
  (1.2 s) — so once a segment's *in-segment* skew passes about -0.72 s the
  measurement cannot be made at all, and the failure it produces blames a
  screencast stall (#18) rather than saying the merge was not graded. That
  cliff sits *inside* the 750 ms absolute bar, and the one segment-two stall
  measured here (-520 ms) was ~200 ms from it. The same limit makes a large
  offset error unmeasurable rather than measured: an injected nominal-timing
  merge (-2.12 s) degraded to "the caption band did not move… almost certainly
  a screencast stall", and what actually named the cause was the
  `segments`-record-vs-ffprobe check, not the acceptance criterion.
- **The merged envelope's disagreement paths are never taken.** Both segments
  are recorded by the same recorder with the same settings, so `recorder`
  resolves to `"Recorder"` and every `determinism` key agrees. The `"mixed"`
  value and `_merge_determinism`'s null-on-disagreement branch — both
  documented in `SKILL.md` as what a reader gets from a mixed demo — are
  produced by nothing here and asserted by nothing.
- **The merge's `issues` path is unexercised.** `stitch()` also offsets each
  issue's `t` and re-points its `beat` at the merged beat list, and the
  segmented take is a recording of a *healthy* app under `strict=True` — so it
  records no issues at all and none of that runs. An issue attributed to the
  wrong beat of the wrong segment would pass this suite. Tracked in
  [#51](https://github.com/rogvid/skills/issues/51).
- **The merge's error is measured at one beat per segment, not all of them.**
  Every other beat in a segment is carried by that segment's single offset, so
  one being right makes the rest right — but a merge that moved some of a
  segment's beats and not others would be caught only by the ordering and
  coverage checks, which are much coarser.
- **No segmented take writes evidence, so a merged timeline's `evidence`
  pointers are unexercised.** The `evidence/` take records with `segment=`, so
  `evidence/<segment>.seg.beat-NN.json` and the scoped stale-file clearing are
  exercised; `segments/` is what actually merges two parts, and it is graded on
  its beats rather than its evidence. So the half of
  [#22](https://github.com/rogvid/skills/issues/22) that matters to
  [#7](https://github.com/rogvid/skills/issues/7) — a merged timeline whose
  renumbered beats still point at the right files — has never run. The naming
  exists precisely so a merge has to rename nothing, and nothing here checks
  that it did not have to.
- **Nothing reads the evidence the way its acceptance criterion means it.**
  "A reviewer can state what was on screen" is graded as a list of substrings
  that must and must not be in each beat's capture. That is enough to catch an
  empty capture, a stale one, and a page that moved on — but whether an agent
  handed only `evidence/` could actually narrate the demo is the same
  unautomatable question as `SKILL.md` step 6's fresh-agent review, and
  nothing here asks it.
- **The recorder's own end-of-document guard cannot be shown catching a leak.**
  Before writing, each evidence document is re-checked over its serialized
  bytes for anything registered or redacted. It runs against the same list the
  masking does, so for a plain string value it **cannot disagree with it** —
  this is not a second opinion and nothing here should be read as saying it is.
  It exists for what the walker structurally cannot reach: a field a later
  slice adds *after* the scrub, or a secret that ends up in a dict key. What
  actually grades this axis is the byte sweep over `evidence/`.
- **`url` and `title` are only scrubbed for registered secrets.** No take puts
  an unregistered value in a query string, so the one path where evidence
  records something the app never rendered on screen is untested
  ([#50](https://github.com/rogvid/skills/issues/50)).
- **Nothing records with `evidence=False`.** The off switch, and the
  `DEMO_VIDEO_EVIDENCE=0` env var behind it, are exercised nowhere — every
  take here writes evidence
  ([#48](https://github.com/rogvid/skills/issues/48)).
- **Terminal evidence has no `redact()` to inherit.** `screen` is the whole
  rendered terminal and `register_secret()` is the only thing masked out of it,
  because `TerminalRecorder` has no `redact()` at all
  ([#5](https://github.com/rogvid/skills/issues/5)).
  `terminal-problems/` proves the registered path reaches the screen dump and
  `terminal-wrap/` proves it survives the line wrap; a value nobody registered
  is written verbatim, and there is nothing yet to assert about it.
- **A crash that is not a `SecretLeak` skips the stale-evidence clearing**
  ([#79](https://github.com/rogvid/skills/issues/79)), the end-of-document
  guard runs after capping and so cannot see a literal cut in half by a budget
  ([#80](https://github.com/rogvid/skills/issues/80)), and an unsegmented take
  never clears a previous *segmented* take's evidence
  ([#81](https://github.com/rogvid/skills/issues/81)). All three fail safe —
  nothing new is written — and all three are exercised by nothing here.
- **The normalization boundary is stated, not tested to its edges.** Matching
  is exact modulo whitespace in either direction, HTML entities and JSON string
  escapes — the four transformations `SKILL.md` lists, each with a shape here.
  Case differences, Unicode normalization forms and confusables, percent- and
  base64-encoding, and a value the app itself reformats are all outside it and
  are exercised by nothing. That is a deliberate boundary rather than a gap to
  close: it is an asymptotic surface, and the answer for a value that survives
  one of those is `redact()` on the element, not a longer list here.
- **Sub-frames are not harvested, and the argument that they need not be is
  not itself asserted.** Nothing an iframe renders can reach an evidence file
  — `aria_snapshot` is taken of the top document's `body` and stops at the
  `iframe` node, and the markup dump strips `srcdoc` — so the harvest is
  main-frame only. What holds that up is the byte sweep requiring the
  fixture's in-iframe key to be absent, which is a consequence of the claim
  rather than the claim itself. A future change that made `aria` descend into
  frames would be caught; one that made only `html` do so, on a page with no
  iframe in the spotlight, would not.
- **"Renders in the clear" still cannot see occlusion.** The rule that keeps
  the mask from eating the page exempts any string that renders outside it, and
  "renders" is now four conditions: `checkVisibility()` with `opacityProperty`,
  `visibilityProperty` and `contentVisibilityAuto` set; a box of at least 2×2
  CSS pixels; a box not entirely off the top or left of the document; and no
  attribute or input `value` counting at all. `HIDE` exercises the first three
  through four shapes at once. What none of it models is an element **painted
  underneath an opaque sibling**, or clipped away by a `clip-path` on an
  *ancestor* rather than on itself — both count as rendered, and a value
  visible only there would go unmasked
  ([#69](https://github.com/rogvid/skills/issues/69)). Deciding that properly
  needs per-node hit testing, which is a different order of cost.
- **Nothing checks that the demo is any *good*.** These are liveness checks.
  Pacing, caption wording, whether the story lands — that is what the
  fresh-agent review in `SKILL.md` step 6 is for, and it is not automatable.

Failures accumulate and print together, each naming the file or interaction and
the number that was wrong. The process exits non-zero if there is even one, and
`ok` is printed for an artifact only when *nothing* about it was wrong.

## The fixture app

`fixture/index.html` is a small fulfilment dashboard: a hero, three KPI cards,
a filter box, a refresh button, and a table. It is one file with no build step
and no dependencies, served by `python3 -m http.server`.

Everything the recorder touches has a stable id: `#kpi-rev`, `#kpi-orders`,
`#kpi-ontime`, `#search`, `#refresh`, `#rows` (plus `#row-nw-1041`… per row),
`#status`, `#empty`.

It is deterministic on purpose — no `Math.random()`, no clock on screen, no
animations. `#refresh` cycles three hard-coded snapshots in order, so a
recording made today is frame-for-frame the story of one made next year.

Two query-string hooks exist, inert unless asked for:

| URL | Effect | For |
|---|---|---|
| `?console-error=1` | logs a `console.error` **and** throws an uncaught error (Playwright `pageerror`), while the page stays usable | the Problems axis |
| `?bad-fetch=<url>` | fetches `/definitely-missing.json` (404) and `<url>` (connection refused), both during load | the Problems axis — during load so the failures land inside the recorder's `goto` beat |
| `?secret=1` | renders `#api-key` holding `sk-live-FAKE0000000000000000` | issue #4, redacting secrets from frames and stills |
| `?entropy=1` | renders four clock readings (`Date`, `Intl`, `new Date().constructor`, and one posted back by a `Worker`, each read once at load) and `#entropy-spinner`, a shape turning once every 1.7 s | issue #10, the determinism takes |

`?entropy=1` is the one hook the fixture's own "keep it deterministic" rule is
suspended for, on purpose: the determinism takes need something that *would*
differ between recordings. Each clock is read once rather than ticking, because
a ticking one would also keep the compositor painting and confound the very
thing being measured. There is deliberately no `Math.random()` in it — see
Known gaps.

The panel is **prepended** to `.page`, not appended. Four readings and a 54 px
spinner are tall enough that at the bottom of the page they sit below the
720 px fold, and `shot()` captures the viewport rather than the full page — so
every comparison in the determinism phase passed against two byte-identical
photographs of a spinner nobody had photographed. It was caught by the
controls-off assertion, which is exactly what that assertion is for.

One hook, one take. The graded `web/` take loads none of them, so the reference
recording stays a recording of a working app — which is also the assertion that
the recorder does not invent problems.
| `?console-error=1` | logs a `console.error` **and** throws an uncaught error (Playwright `pageerror`), while the page stays usable | issue #3, failing a take on console errors |
| `?secret=1` | pins a panel of keys to redact and controls not to: body-size, hero-size, two reachable only by `text=`/`xpath=`, two fields, and an **open shadow root** holding a third key and a third field | issue #4, redacting secrets from frames and stills |
| `?secret=closed` | the same, plus a **closed** shadow root holding a key nothing can mask | issue #4, proving an unmaskable selector fails the take |

None of them is a credential. Each is spelled with a four-letter word followed
by nothing but zeroes so both gitleaks and a human read it as scenery — the
default ruleset does not flag them either way. `.gitleaks.toml` allowlists the
shape anyway, and lists what each word belongs to, as insurance against a
future release that does start flagging it.

The panel is `position: fixed` rather than in the flow, which is load-bearing
rather than cosmetic: the redaction take measures pixels inside those elements,
so their rect has to be identical in every frame. In the flow the panel sits
below the fold, and anything that scrolls — Playwright scrolls a field into view
before typing into it — would move the measured region mid-take, which reads as
a leak or hides one depending on what slid into the crop.

It also has to stay clear of the bottom 160 px, where the recorder burns its
caption bar. A measured crop that overlaps the bar is measuring sharp white
caption text: the shadow field scored 34% of its control that way while being,
on inspection of the extracted pixels, thoroughly blurred. The take asserts the
clearance for every measured element, so the layout cannot drift back into it
silently — and two other measurement artifacts found the same way are worth
knowing about, because both looked exactly like a leak: the recorder's own
cursor dot parked inside a field's crop by `type_into`'s click (5.0 against
0.8), and an `<input>`'s border blurring into its own crop (2.5 against 0.8 for
the same value as text). Every number in this section was checked by extracting
the crop and looking at it before it was believed.

## Adding a case

- **A new thing to record** — add a beat to `record_web` / `record_terminal` in
  `tests/smoke`, add its `shot()` name to `WEB_SHOTS` / `TERMINAL_SHOTS` so the
  still is actually checked, and add its `(verb, target)` to `WEB_BEATS` /
  `TERMINAL_BEATS` (and its text to `WEB_CAPTIONS` / `TERMINAL_CAPTIONS` if it
  is a caption) so the timeline check knows to expect it. `record_segments`
  works the same way, except that its list is `SEGMENT_BEATS_FULL` and carries
  a third column, the segment the beat belongs to. Those lists are
  deliberately hand-maintained; see **Timeline** above for why — and
  `WEB_BEATS` is also what the **Review frames** axis counts frames against and
  searches `frames.md` for, so a stale entry there fails twice. Adding a beat
  lengthens the take; keep it inside the duration window, or widen the window
  deliberately. **Every interaction gets a `b.expect(...)` naming what it
  should have changed** — a beat with no post-condition is a beat that passes
  when the verb is a no-op. Anything that leaves the page still for more than a
  second also wants a look at `TICKER_JS`: idle is what makes the screencast
  lose time, and adding idle is how the timing bar was made flaky once already.
- **A new caption, interlude or selector** — it goes in the hand-written lists
  (`WEB_CAPTIONS`, `SEGMENT_INTERLUDES`, the beat list), and the **Review
  frames** axis then requires `frames.md` *not* to contain it. That is the
  intended direction: the sheet a context-free reviewer reads must not name the
  thing they are being asked to discover. A caption also moves the boundaries
  `_check_frame_captions()` guards, so adding one near the end of a storyboard
  can push frames out of the graded set — watch the "not graded" count in the
  pass line, and `MIN_GRADED_CAPTION_FRAMES` is the floor, not a dial.
- **Anything in the page that must keep moving** — a second ticker, an
  animation a take is *about* — has to carry `data-demo-video-animate`, or the
  recorder's determinism rule lands it on its final frame the moment it
  appears. That attribute is the recorder's published opt-out, not a test
  hook; `TICKER_JS` is the worked example.
- **A new storyboard verb in the recorder** — decorate it with `@_beat_verb`
  so it lands in the beat log, or the timeline stops being a full account of
  the take. A verb built out of other verbs records one beat, not one per
  internal step; the nesting guard in `_DemoBase._beat` handles that.
- **A new thing for the app to do** — put it in `fixture/index.html` behind a
  stable id, and keep it deterministic. If it only matters to one future
  feature, hide it behind a query-string hook the way the two above are, so the
  default recording stays clean.
- **A new thing for the recorder to notice** (a new issue kind, a new signal) —
  add it to `ISSUE_KINDS` in `core.py`, decide whether it belongs in
  `STRICT_KINDS`, make one of the storyboards cause it on purpose, and add a
  `(kind, message substring, verb)` row to `WEB_ISSUES` / `TERMINAL_ISSUES`.
  The verb is what makes the row worth writing: an issue that is recorded but
  attributed nowhere is a problem report with the page number torn off.
- **A new failure mode to catch** — prefer another assertion in `check_take()`
  or `check_issues()` over another take. Takes cost ~15 s each in CI;
  assertions are free. The two strict takes are the exception that proves it:
  "the take raises" cannot be asserted about a take that has to succeed for
  everything else to be graded, so they exist, and they are kept to a few
  seconds each and graded on nothing else.
  over another take. Takes cost ~15 s each in CI; assertions are free. The
  redaction take is the exception that earned its own recording: it needs a
  different page state (`?secret=1`), a different narration setting
  (`speech=True`), and it deliberately provokes failures — a refused caption, a
  torn-out mask — that would corrupt the expectations of the take it shared.
- **A new thing redaction must hide** — add it to the `?secret=1` panel, add a
  literal to the `REDACT_*` constants in `tests/smoke`, allowlist its shape in
  `.gitleaks.toml`, and give it *both* a masked and an unmasked measurement.
  A redaction assertion with nothing sharp to compare against is the most
  dangerous kind of vacuous test: it passes on a black frame. Adding it to
  `REDACT_LITERALS` carries it into the evidence sweep for free — but check
  that a *control* of the same kind is still found in `evidence/`, or that
  sweep is grading an empty directory.
- **A new thing the *terminal* scrubber must hide** — add a line to
  `term_printer_script()`, a literal to the `TERM_*` constants, a row to
  `TERM_MASKED_ROWS`, and allowlist the shape in `.gitleaks.toml`. Keep it 28
  characters so it lands in the same columns as the `ctl` and `ref` rows,
  which are what it is measured against. If it is meant to be caught by shape
  rather than registration, do not register it — that separation is the only
  thing that says the two mechanisms work apart.
- **A new fact evidence must record** — add a `(verb, target, present, absent)`
  row to `WEB_EVIDENCE` / `TERMINAL_EVIDENCE`. **Fill in `absent`.** A `present`
  list alone passes on a recorder that dumped the page once and copied it into
  every beat, which is the failure mode this axis exists to catch; `absent`
  is what the previous screen showed and must not still be there. Both lists
  are facts about `fixture/index.html`, written by hand, never read back off a
  recording.
- **A new field in an evidence document** — give it a budget in
  `EVIDENCE_LIMITS` if it can grow, mirror that number in
  `EVIDENCE_LIMITS_EXPECTED` in `tests/smoke`, and make sure it is built
  *before* the masking pass in `_evidence_doc` rather than after. Anything
  assembled after that pass is plaintext the recorder never checked, and only
  the end-of-document guard stands between it and the file.
- **A new way for a value to reach evidence without reaching a picture** —
  add it to the `?evidence=1` panel, add a literal to `EVIDENCE_SECRETS`, and
  allowlist its shape in `.gitleaks.toml`. **Then check `EVIDENCE_KEEP` still
  holds.** Every leak fixed here has a mirror defect: the mask that reaches
  the new shape is the same mask that can eat an unrelated paragraph, and a
  run where all nine secrets are absent because all nine files are
  `[redacted]` is not a pass. Write the shape in the *markup*, the way a
  person writes HTML, rather than assigning it from JS — an unpadded text node
  is precisely the case that does not leak, and building the fixture that way
  is how this axis passed for a round while five shapes walked through it.

**Prove any new assertion can fail.** Break the thing it watches — stub the verb
out in `skills/demo-video/helpers/`, or blank the fixture — run `tests/smoke`,
and see it fail with a message that names the real cause. Then `git checkout --
skills/` and see it pass again. Two of the checks in this file's history looked
like coverage for a whole review round and could not fail at all: a whole-frame
contrast score that a blank recording *beat*, and a cursor-position check that
was measuring Playwright's `click()` rather than the recorder's `move_to()`. An
assertion nobody has watched fail is a comment.
