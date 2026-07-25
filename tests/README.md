# tests

One smoke test and one fixture app. Together they answer three questions:
**does the demo-video recorder still produce a real video, does it still notice
when the thing it recorded was broken, and does a registered secret stay out of
everything it produces?**

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
a secret, plus a second few-second take that must *fail* — and `segments/`,
one demo recorded in two parts and joined with `stitch()`.

## Running it

```sh
tests/smoke                       # every take, output to a temp dir
tests/smoke --web-only            # just the Playwright takes
tests/smoke --terminal-only       # just the PTY/xterm.js takes
tests/smoke --determinism-only    # just the three re-recording takes
tests/smoke                       # all three takes, output to a temp dir
tests/smoke --web-only            # just the Playwright take
tests/smoke --terminal-only       # just the PTY/xterm.js take
tests/smoke --redaction-only      # just the secret-redaction take
tests/smoke --segments-only       # just the two-segment take and its stitch
tests/smoke --out-dir /tmp/smoke  # keep the recordings at a known path
tests/smoke --keep                # keep the temp dir even when it passes
```

Prerequisites: `uv`, `ffmpeg`/`ffprobe` on PATH, and Chromium for Playwright
(`uv run --with playwright playwright install chromium`; add `--with-deps` on a
fresh Linux box). A pass looks like this, and takes about half a minute:

```
smoke: serving …/tests/fixture at http://127.0.0.1:36321
smoke: web demo.mp4 ok (20.2s, 279 kB, content 16.0)
smoke: web still 01-dashboard.png ok (77 kB, content 16.9)
smoke: web caption is visible on screen (delta 25.6)
smoke: web first caption 'A small dashboard.' logged at 3.03s, on screen at 2.95s (-80 ms)
smoke: web closing caption 'Recorded end to end.' logged at 17.03s, on screen at 16.99s (-40 ms)
smoke: web beat clock holds across the take (+40 ms)
smoke: web timeline.json ok (23 beats)
smoke: web healthy app under strict=True records no problems
smoke: redaction #api-key is blurred in every frame of demo.mp4 (worst 1.5 vs control 52.0, 3%)
smoke: redaction still 01-key-blurred.png ok (key 1.0, token 2.9, control 39.3)
smoke: redaction .tts/ holds 2 clips — the narrated lines, and nothing for the refused one
smoke: redaction no artifact holds either secret verbatim
smoke: segments recorded 2 parts, each with its own beat log (part1 6.8s, part2 7.8s)
smoke: segments the merge puts the second segment's closing caption +0 ms from where its own segment does (-80 ms in part2.seg.mp4, -80 ms in demo.mp4)
smoke: segments stitched 2 parts into a 14.6s demo.mp4 and merged their beat logs (15 beats); keep_parts=True kept every part and its log, the default removed them
smoke: segments closing caption 'Recorded end to end.' logged at 11.43s, on screen at 11.35s (-80 ms)
smoke: segments timeline.json ok (15 beats)
…
smoke: web-problems timeline.json records 8 problem(s), 6 of them fatal under strict — take still passed
smoke: web-strict strict=True refused the take, naming beat 0 (goto) (4 fatal issues, artifacts kept)
smoke: terminal-problems timeline.json records 2 problem(s), 2 of them fatal under strict — take still passed
smoke: terminal-race exit status survives a shell that starts 1.2s late (logged 5)
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
(`web/`, `terminal/`, `segments/`, `web-problems/`, `terminal-problems/`,
`terminal-race/`, `web-strict/`, `terminal-strict/`, `determinism-a/`,
`determinism-b/`, `determinism-off/`) are deleted before each take. Only the first two are graded
on their video; the rest are short and exist to break, or to reproduce, in one
specific way each. That is not tidiness — every artifact assertion works by
path, so without it a leftover `demo.mp4` from the previous run would grade a
recorder that produced nothing at all as a pass, and recording repeatedly into
one directory is exactly how a change to the recorder gets verified.
Re-running into the same `--out-dir` is safe: the `web/`, `redaction/` and
`terminal/` subdirectories are deleted before each take. That is not tidiness — every
artifact assertion works by path, so without it a leftover `demo.mp4` from the
previous run would grade a recorder that produced nothing at all as a pass, and
recording repeatedly into one directory is exactly how a change to the recorder
gets verified.

Deleting is bounded. Only those named subdirectories are ever
removed, and only when each is absent, empty, or carries the
`.demo-video-smoke` marker file a previous run wrote there. `--out-dir .` in a
Deleting is bounded. Only `<out-dir>/web/`, `<out-dir>/redaction/` and
`<out-dir>/terminal/` are ever removed, and only when each is absent, empty, or
carries the `.demo-video-smoke` marker file a previous run wrote there. `--out-dir .` in a
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

Six independent axes, because a recorder can fail on any one of them while
looking perfect on the other five.
Five independent axes, because a recorder can fail on any one of them while
looking perfect on the other four.

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

The two text paths are checked by searching bytes, not by asking the recorder:

- every file the take wrote — `timeline.json`, `timeline.md`, the stills, the
  mp4, the narration clips — is read and searched for both literals, with no
  exemptions, so a leak path nobody anticipated still shows up;
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
100 ms.** The closing caption is timed *twice* — once in `part2.seg.mp4`
against that segment's own beat log, and once in the stitched `demo.mp4`
against the merged one. `stitch()` copies the streams, so those are literally
the same frames carrying the same capture loss, and the **difference** between
the two skews is the merge's offset error with issue #18 cancelled out.
Measured across six takes: **+0 ms**, every time, against a 100 ms bar; the
absolute skews behind it ranged -200 to +0 ms. A bar on the absolute skew
could not be set anywhere near that, because a segment whose capture stalled
shows every caption early in its own video too.

That cancellation is also why the sharp `MAX_SKEW_DRIFT_S` (250 ms) does *not*
apply between the take's two probes here: they sit in different segments, so
they rode different screencasts, each with its own ~0.7 s of untickerable
recorder setup, and a stall in the second moves only the second. Measured
across four takes: -80, +80, +80, and one at **-520** — a real segment-two
stall, which would have made this axis flake. Across a boundary the bound is
therefore one capture-loss window, and the tight claim is made by the
differential measurement instead.

The rest is what is true of a merge and of nothing else:

| Checked | Why |
|---|---|
| before any stitch, each part has an `.seg.mp4` *and* an `.seg.timeline.json`/`.md`, and no `demo.mp4`/`timeline.json` exists yet | the cleanup assertion below is otherwise satisfied by a recorder that never wrote them, and every path assertion by a leftover |
| each part's own log starts within `MAX_UNMERGED_FIRST_BEAT_S` of zero | "the merged timestamps are large" proves nothing if they were large before the merge |
| `stitch(keep_parts=True)` leaves every part **and its beat log** | re-recording one expensive segment and re-stitching is the whole reason that flag exists, and it needs the logs as much as the mp4s |
| stitching twice produces the same beats | the merge has to be a function of what is on disk |
| the default `stitch()` leaves **no** `*.seg.*` at all | [#21](https://github.com/rogvid/skills/issues/21): a `.seg.timeline.json` outliving its `.seg.mp4` names a file that is gone, and the next stitch cannot tell it from a fresh one |
| the merged envelope's `segments` records match ffprobe, in order, and tile `demo.mp4` | it is what maps a merged timestamp back to the file it came from |
| `index` is renumbered to the position in the merged file, `segment_index` is **not** | [#22](https://github.com/rogvid/skills/issues/22): `(segment, segment_index)` names a beat the same way before and after a merge, which `index` alone cannot. Asserted in every take, not just this one — for a single take it is 0, 1, 2, … |
| a take recorded in one piece carries no `segments` key | that key means "assembled by stitch()", and a reader would otherwise be told a single recording has parts |

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
- **Nothing checks that the withheld half-marker is flushed.** `_pump` holds
  back trailing bytes that could still become an exit-status escape, and
  `_stop` writes them to the terminal on teardown. No assertion reads the final
  frame, so a regression there would lose the last few bytes of a program's
  output silently.
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
- **The merge's `issues` path is unexercised.** `stitch()` also offsets each
  issue's `t` and re-points its `beat` at the merged beat list, and the
  segmented take is a recording of a *healthy* app under `strict=True` — so it
  records no issues at all and none of that runs. An issue attributed to the
  wrong beat of the wrong segment would pass this suite. Tracked in
  [#51](https://github.com/rogvid/skills/issues/51).
- **The merge's error is measured at one beat, not all of them.** The
  differential measurement below reads the *closing caption* out of two
  videos. Every other beat in the second segment is carried by the same single
  offset, so one being right makes the rest right — but a merge that moved
  some beats and not others would be caught only by the ordering and coverage
  checks, which are much coarser.
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
  deliberately hand-maintained; see **Timeline** above for why. Adding a beat
  lengthens the take; keep it inside the duration window, or widen the window
  deliberately. **Every interaction gets a `b.expect(...)` naming what it
  should have changed** — a beat with no post-condition is a beat that passes
  when the verb is a no-op. Anything that leaves the page still for more than a
  second also wants a look at `TICKER_JS`: idle is what makes the screencast
  lose time, and adding idle is how the timing bar was made flaky once already.
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
  dangerous kind of vacuous test: it passes on a black frame.

**Prove any new assertion can fail.** Break the thing it watches — stub the verb
out in `skills/demo-video/helpers/`, or blank the fixture — run `tests/smoke`,
and see it fail with a message that names the real cause. Then `git checkout --
skills/` and see it pass again. Two of the checks in this file's history looked
like coverage for a whole review round and could not fail at all: a whole-frame
contrast score that a blank recording *beat*, and a cursor-position check that
was measuring Playwright's `click()` rather than the recorder's `move_to()`. An
assertion nobody has watched fail is a comment.
