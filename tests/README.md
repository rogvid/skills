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
smoke: serving …/tests/fixture at http://127.0.0.1:59557
smoke: web demo.mp4 ok (13.9s, 205 kB, contrast 60)
smoke: web still 01-dashboard.png ok (77 kB, contrast 19)
…
smoke: PASSED
```

Re-running into the same `--out-dir` is safe: the `web/` and `terminal/`
subdirectories are deleted before each take. That is not tidiness — every
artifact assertion works by path, so without it a leftover `demo.mp4` from the
previous run would grade a recorder that produced nothing at all as a pass, and
recording repeatedly into one directory is exactly how a change to the recorder
gets verified. Nothing outside those two subdirectories is ever removed.

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
modified by *this* run rather than a previous one, and clear a size floor
(20 kB / 5 kB). Duration, via the `media_duration` helper, falls inside a wide
window (6–30 s web, 4–30 s terminal): the low bound catches a take that died
early, the high bound catches a hang, everything between is normal variation
between a laptop and a cold CI runner.

**Content** — the frames contain a picture. This is measured, not inferred from
file size: **no byte count can separate a blank recording from a real one.** A
flat white 14-second 720p H.264 is about 20 kB, comfortably over any floor that
a real 110 kB terminal take also clears. So `frame_contrast()` has ffmpeg decode
frames to raw 8-bit grayscale at 160×90 and computes their luma standard
deviation in pure Python — no image library, no extra dependency. Anything
visible scores tens; a blank frame scores 0.0. The bottom 20% of each frame is
cropped away first, so the recorder's own caption bar cannot supply the contrast
for an otherwise empty app.

Healthy values, for calibrating the floors (`MIN_FRAME_STDDEV = 8`,
`MIN_STILL_STDDEV = 6`): web mp4 ≈ 60, terminal mp4 ≈ 79, web stills 18–19,
terminal stills ≈ 78.

**Behaviour** — the interactions actually did something. Byte sizes cannot tell
a filtered table from an unfiltered one, so each verb is followed by the
observable post-condition it must have caused, read back out of the live page:

| Verb | Post-condition checked |
|---|---|
| `goto` | `#rows` has 5 rows, `#status` reads `snapshot 1 of 3` |
| `spotlight(sel)` / `spotlight()` | `#kpi-rev` computed `outline-style` is `solid`, then `none` |
| `type_into("#search", …)` | the field holds `seattle` and `#rows` is down to 1 row |
| `click("#refresh")` | `#status` reads `snapshot 2 of 3`, `#kpi-rev` reads `$134,950` |
| `move_to` (via `click`) | the recorder's drawn cursor sits inside `#refresh`'s box |
| `run` (terminal) | the command's *output* appears on a whole screen line (`^hello from demo-video$`, `^skills$`) — anchored so the echoed command line cannot satisfy it |

Post-condition failures are collected, not raised, so the take still finishes
and produces the video that the other two axes grade.

Failures accumulate and print together, each naming the file or interaction and
the number that was wrong. The process exits non-zero if there is even one.

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
