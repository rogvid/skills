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
smoke: web demo.mp4 ok (13.7s, 327 kB)
smoke: web still 01-dashboard.png ok (77 kB)
…
smoke: PASSED
```

Unix only — `demo_recording/__init__.py` imports the PTY-backed terminal
recorder unconditionally, so the whole package needs a Unix platform. The
terminal *take* additionally skips itself with a message if `os.name` is not
`posix`.

Narration is forced off (`speech=False`), and the runner deletes every
`DEMO_VIDEO_*` variable plus `ELEVENLABS_API_KEY` from its own environment
before recording. A sourced project `.env` therefore cannot change what the
test measures.

## What it asserts

Per take (web, terminal):

- `demo.mp4` exists and is at least 20 kB — "the file is there" proves nothing
  when a half-failed run still leaves one behind
- its duration, via the `media_duration` helper, falls inside a wide window
  (6–30 s web, 4–30 s terminal). The low bound catches a take that died early,
  the high bound catches a hang; everything between is normal variation
  between a laptop and a cold CI runner
- every still the storyboard asked for exists in `images/` and is at least 5 kB

Failures accumulate and print together, each naming the file and the number
that was wrong. The process exits non-zero if there is even one.

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

That key is not a credential. It is spelled `FAKE` followed by zeroes so both
gitleaks and a human read it as scenery; `.gitleaks.toml` allowlists that exact
literal and nothing else.

## Adding a case

- **A new thing to record** — add a beat to `record_web` / `record_terminal` in
  `tests/smoke`, and add its `shot()` name to `WEB_SHOTS` / `TERMINAL_SHOTS` so
  the still is actually checked. Adding a beat lengthens the take; keep it
  inside the duration window, or widen the window deliberately.
- **A new thing for the app to do** — put it in `fixture/index.html` behind a
  stable id, and keep it deterministic. If it only matters to one future
  feature, hide it behind a query-string hook the way the two above are, so the
  default recording stays clean.
- **A new failure mode to catch** — prefer another assertion in `check_take()`
  over another take. Takes cost ~15 s each in CI; assertions are free.
