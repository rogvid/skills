# Working in this skills repo

This repo holds reusable agent skills, installed by the
[`skills`](https://github.com/vercel-labs/skills) CLI (`npx skills add`).

## Read `GOAL.md` first

`GOAL.md` says what this repo is for: helping a person get a short, polished
demo video quickly and cheaply, with the person in the loop. It also says how
success is measured (tokens, wall-clock, watchability). Plan work against it.
Where a rule below and the goal disagree, the goal wins.

## Layout

- `skills/`: **finished, shareable** skills. Everything here is discoverable
  and gets installed by `npx skills add rogvid/skills`.
- `wip/`: **in-development** skills. Not installed by anyone.
- `examples/`: apps the skills are exercised against. `examples/ticket-queue`
  is the proving ground for `demo-video`.
- `docs/`: design docs. Gitignored; do not `git add` it.

Each skill is a directory with a `SKILL.md` at its root.

## Why `wip/` stays hidden - do not "tidy" it into `skills/`

The `skills` CLI discovers skills by walking the **repo root only one level
deep**, plus a few known container dirs (`skills/`, `skills/.curated/`,
`skills/.experimental/`, `skills/.system/`, `.claude/skills/`, ...) two levels
deep. A `SKILL.md` under `wip/<name>/` is two levels below the root, so
discovery never sees it.

- Do **not** move `wip/` skills into `skills/` or `skills/.experimental/` to
  make them findable. `.experimental/` **is** a discovery path, so that would
  ship unfinished work to everyone running `--all`.
- Keep **at least one** skill in `skills/`. If `skills/` is ever empty, the CLI
  falls back to a recursive search that would surface `wip/`.

## Authoring a new skill

1. Create it under `wip/<name>/SKILL.md`. **Never** create a skill directly in
   `skills/`.
2. Frontmatter needs `name` and `description`. `name` must equal the directory
   name. Write `description` as a **trigger condition** ("Use when ..."), since
   that text is what an agent matches against.
3. Bundle any companion executable under the skill and invoke it from
   `SKILL.md`, so `npx skills add` carries it along. A Python executable goes
   in `<skill>/scripts/` as a PEP 723 uv script (see
   `skills/script-conventions`).
4. Every line of a `SKILL.md` is paid for in tokens on every use. Keep it to
   what the default path needs.

## Promoting a skill (`wip/` -> `skills/`)

1. `name` matches the directory name, and `description` says when to use it.
2. It has been run end to end in a real project at least once.
3. Prerequisites are bundled, or stated in `SKILL.md`.
4. `git mv wip/<name> skills/<name>`, and update the README's **Skills** table.
5. `gh label create <name> --description "Issues for the <name> skill" --color 1d76db`.

## Issue tracking - GitHub Issues via `gh`

GitHub Issues is the tracker; there is no backlog file. Label every issue with
the skill it concerns. Close issues from commits (`Fixes #12`).

**A true observation is not automatically work.** File an issue only if it
makes a demo worse for its viewer, costs a user real tokens or time, or blocks
the next step of `GOAL.md`. Anything else goes in the pull request body as a
stated limit, or nowhere.

## Changing `demo-video`

- **Look at the output.** A change to what the video looks like is checked by
  recording `examples/ticket-queue/demo` (`mise run example`) and looking at
  `sheet.png`, and at frames pulled from `demo.mp4` for motion. Put the sheet
  or frames in the pull request.
- **Measure the cost.** A change to the workflow or `SKILL.md` is judged by
  what a demo costs: take and render time from the recorder's summary, and
  the tokens a session spends to reach an accepted video.
- The pure parts (the clock, geometry) have unit tests in `tests/`. Rendering
  and recording are checked by eye, as above.

## Setting up, and what runs when

```sh
mise run bootstrap  # uv, prek, gitleaks, the git hooks; reports ffmpeg/Chromium
mise run check      # ruff and the unit tests, a few seconds
```

GitHub runs one job, gitleaks. The git hooks run ruff and gitleaks over the
staged diff. Everything else runs when you ask for it (`mise tasks`). A green
branch means only the secret scan passed; put whatever else you ran in the
pull request.

## Skill scripts

Skills ship executables as self-contained PEP 723 scripts run by `uv`,
alongside a copied-in `ensure.sh`. Never add a `requirements.txt`, a `.venv/`,
a `pip install` step, or a first-run marker file. Before writing or editing a
script in a skill, read `skills/script-conventions/SKILL.md`.

## Housekeeping

- Never commit `node_modules/`, `dist/`, `__pycache__/`, `.tts/`, `.take/` or
  `demo.mp4` (see `.gitignore`).
- Keep the README's Skills table in sync when adding, promoting or removing a
  skill.
