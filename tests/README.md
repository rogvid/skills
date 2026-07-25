# tests

One smoke test and one fixture app. Together they answer a single question:
**does the demo-video recorder still produce a real video?**

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

## Running it

```sh
tests/smoke                       # both takes, output to a temp dir
tests/smoke --web-only            # just the Playwright take
tests/smoke --terminal-only       # just the PTY/xterm.js take
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
…
smoke: PASSED
```

Re-running into the same `--out-dir` is safe: the `web/` and `terminal/`
subdirectories are deleted before each take. That is not tidiness — every
artifact assertion works by path, so without it a leftover `demo.mp4` from the
previous run would grade a recorder that produced nothing at all as a pass, and
recording repeatedly into one directory is exactly how a change to the recorder
gets verified.

Deleting is bounded. Only `<out-dir>/web/` and `<out-dir>/terminal/` are ever
removed, and only when each is absent, empty, or carries the
`.demo-video-smoke` marker file a previous run wrote there. `--out-dir .` in a
project that has its own `web/` directory gets a refusal naming the path, not a
deleted source tree.

Unix only — `demo_recording/__init__.py` imports the PTY-backed terminal
recorder unconditionally, so the whole package needs a Unix platform. The
terminal *take* additionally skips itself with a message if `os.name` is not
`posix`.

Narration is forced off (`speech=False`), and the runner deletes every
`DEMO_VIDEO_*` variable plus `ELEVENLABS_API_KEY` from its own environment
before recording. A sourced project `.env` therefore cannot change what the
test measures.

## What it asserts

Four independent axes, because a recorder can fail on any one of them while
looking perfect on the other three.

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

When the measurement cannot be made the run says which reason it was: a caption
that was never drawn, a video that slid further than the search window can see,
or a run-up that was not quiet. They look identical from inside the window, and
only the first is the recorder losing a caption.

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
- **Nothing checks audio.** Narration is forced off and no assertion touches the
  aac track, so the whole speech path — `tts_clip`, the `.tts/` cache, the
  `adelay`/`amix` mixing in `_convert` — is untested here.
- **Nothing checks `stitch()`, segments, or `interlude()`.** Single-segment
  takes only — so `<segment>.seg.timeline.json`, and the merge
  [#7](https://github.com/rogvid/skills/issues/7) will build on it, are
  unexercised.
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

Two query-string hooks exist for the queued feature work, inert unless asked
for:

| URL | Effect | For |
|---|---|---|
| `?console-error=1` | logs a `console.error` **and** throws an uncaught error (Playwright `pageerror`), while the page stays usable | issue #3, failing a take on console errors |
| `?secret=1` | renders `#api-key` holding `sk-live-FAKE0000000000000000` | issue #4, redacting secrets from frames and stills |

That key is not a credential. It is spelled `FAKE` followed by sixteen zeroes so
both gitleaks and a human read it as scenery — the default ruleset does not flag
it either way. `.gitleaks.toml` allowlists the exact literal anyway, as
insurance against a future release that does start flagging it.

## Adding a case

- **A new thing to record** — add a beat to `record_web` / `record_terminal` in
  `tests/smoke`, add its `shot()` name to `WEB_SHOTS` / `TERMINAL_SHOTS` so the
  still is actually checked, and add its `(verb, target)` to `WEB_BEATS` /
  `TERMINAL_BEATS` (and its text to `WEB_CAPTIONS` / `TERMINAL_CAPTIONS` if it
  is a caption) so the timeline check knows to expect it. Those lists are
  deliberately hand-maintained; see **Timeline** above for why. Adding a beat
  lengthens the take; keep it inside the duration window, or widen the window
  deliberately. **Every interaction gets a `b.expect(...)` naming what it
  should have changed** — a beat with no post-condition is a beat that passes
  when the verb is a no-op. Anything that leaves the page still for more than a
  second also wants a look at `TICKER_JS`: idle is what makes the screencast
  lose time, and adding idle is how the timing bar was made flaky once already.
- **A new storyboard verb in the recorder** — decorate it with `@_beat_verb`
  so it lands in the beat log, or the timeline stops being a full account of
  the take. A verb built out of other verbs records one beat, not one per
  internal step; the nesting guard in `_DemoBase._beat` handles that.
- **A new thing for the app to do** — put it in `fixture/index.html` behind a
  stable id, and keep it deterministic. If it only matters to one future
  feature, hide it behind a query-string hook the way the two above are, so the
  default recording stays clean.
- **A new failure mode to catch** — prefer another assertion in `check_take()`
  over another take. Takes cost ~15 s each in CI; assertions are free.

**Prove any new assertion can fail.** Break the thing it watches — stub the verb
out in `skills/demo-video/helpers/`, or blank the fixture — run `tests/smoke`,
and see it fail with a message that names the real cause. Then `git checkout --
skills/` and see it pass again. Two of the checks in this file's history looked
like coverage for a whole review round and could not fail at all: a whole-frame
contrast score that a blank recording *beat*, and a cursor-position check that
was measuring Playwright's `click()` rather than the recorder's `move_to()`. An
assertion nobody has watched fail is a comment.
