# ticket-queue — the example app the demo-video reference PR records

A deliberately boring support-ticket queue: a web front end and a small CLI
over the same `data/tickets.json`. It exists so that this repo has one real
application to record demos of — issue
[#64](https://github.com/rogvid/skills/issues/64).

It is **not** a skill and is not installed by `npx skills add`: `examples/`
holds no `SKILL.md`, so the CLI's one-level-deep root walk does not see it.

## Running it

`uv` is the only prerequisite (both executables are PEP 723 scripts; see
`skills/script-conventions/SKILL.md`).

```sh
./serve                            # http://127.0.0.1:8901
./tickets list
./tickets list --status open       # open | waiting | escalated
./tickets show TQ-104
```

## Checking it

```sh
./test                             # ~3 s, needs Chromium for Playwright
./test --fault-inject              # break each thing an assertion watches
```

`test` starts `serve` on an ephemeral port, drives a real browser and reads the
rows the queue painted. It never imports the app's own filter: a check built
out of the code under test is blind wherever that code is blind, and
[#132](https://github.com/rogvid/skills/issues/132) is what that looks like.
`--fault-inject` is the evidence — eleven breaks to `web/`, `data/` and the
fixture, each of which must make a named test fire.

## What is in it

| Path | What |
|---|---|
| `serve` | stdlib HTTP server: static `web/`, plus `GET /api/tickets` |
| `tickets` | the CLI over the same data |
| `test` | what the queue's search does, read off the rendered page |
| `web/` | one page — queue on the left, ticket detail on the right |
| `data/tickets.json` | seven seeded tickets, `open` or `waiting` |
| `demos/` | recorded demos: a `record.py` storyboard and its beat log per feature |

The data is fixed and the UI computes nothing from the clock, so a recording
of it reproduces without `deterministic=True`.

## Re-recording a demo

The video is not committed. With the `demo-video` skill installed (it is in
this repo at `skills/demo-video`, and the storyboards find it there):

```sh
./serve --port 8901 &
uv run demos/2026-07-26-status-filter/record.py
```
