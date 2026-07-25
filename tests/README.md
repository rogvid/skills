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
smoke: web demo.mp4 ok (16.2s, 244 kB, content 16.0)
smoke: web still 01-dashboard.png ok (77 kB, content 16.9)
smoke: web caption is visible on screen (delta 25.6)
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

Three independent axes, because a recorder can fail on any one of them while
looking perfect on the other two.

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
- **Nothing checks audio.** Narration is forced off and no assertion touches the
  aac track, so the whole speech path — `tts_clip`, the `.tts/` cache, the
  `adelay`/`amix` mixing in `_convert` — is untested here.
- **Nothing checks `stitch()`, segments, or `interlude()`.** Single-segment
  takes only.
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
  `tests/smoke`, and add its `shot()` name to `WEB_SHOTS` / `TERMINAL_SHOTS` so
  the still is actually checked. Adding a beat lengthens the take; keep it
  inside the duration window, or widen the window deliberately. **Every
  interaction gets a `b.expect(...)` naming what it should have changed** — a
  beat with no post-condition is a beat that passes when the verb is a no-op.
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
