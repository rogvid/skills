# skills

Reusable [agent skills](https://vercel.com/docs/agent-resources/skills) I share
across projects, installable with the [`skills`](https://github.com/vercel-labs/skills)
CLI. Finished skills live in [`skills/`](skills/); skills still under development
live in [`wip/`](wip/) and are intentionally invisible to the installer.

## Install

Install every finished skill (nothing under `wip/`):

```sh
npx skills add rogvid/skills
```

Install one skill by name:

```sh
npx skills add rogvid/skills --skill demo-video
```

Or install a single skill by its path:

```sh
npx skills add https://github.com/rogvid/skills/tree/main/skills/demo-video
```

Useful flags: `--list` (show without installing), `-g` (install globally to
`~/`, not the current project), `-a claude-code` (target a specific agent).

## Skills

| Skill | What it does | Prerequisites | Install |
|---|---|---|---|
| [`demo-video`](skills/demo-video/) | Script, record, and verify a self-explanatory screen-recorded demo of a web app or a terminal program — CLI, REPL, or full-screen TUI (optionally with spoken narration and a written guide). | `uv`, `ffmpeg`; Chromium via Playwright (terminal demos are Unix-only) | `npx skills add rogvid/skills --skill demo-video` |
| [`script-conventions`](skills/script-conventions/) | The house convention for shipping executable scripts inside a skill — PEP 723 `uv` scripts and the shared `ensure.sh` bootstrap. | none (Unix only) | `npx skills add rogvid/skills --skill script-conventions` |

## In development

Skills under [`wip/`](wip/) are intentionally invisible to `npx skills add` — the
installer only walks the repo root one level deep, so nothing there is discovered
or installed. (You can still pull one directly by path if you want to try it.)

*Nothing in development right now.*

## Issues

Planned work, bugs, and design proposals live in
[GitHub Issues](https://github.com/rogvid/skills/issues), one label per skill —
`gh issue list --label demo-video`. There is no backlog file in the repo.

## Adding or promoting a skill

See [`AGENTS.md`](AGENTS.md) for the layout rules and the promotion checklist.
