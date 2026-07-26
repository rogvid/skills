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
./serve                 # http://127.0.0.1:8901
./tickets list
./tickets show TQ-104
```

## What is in it

| Path | What |
|---|---|
| `serve` | stdlib HTTP server: static `web/`, plus `GET /api/tickets` |
| `tickets` | the CLI over the same data |
| `web/` | one page — queue on the left, ticket detail on the right |
| `data/tickets.json` | seven seeded tickets, `open` or `waiting` |

The data is fixed and the UI computes nothing from the clock, so a recording
of it reproduces without `deterministic=True`.
