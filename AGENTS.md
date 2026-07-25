# Working in this skills repo

This repo holds reusable agent skills, installed by the
[`skills`](https://github.com/vercel-labs/skills) CLI (`npx skills add`).

## Layout

- `skills/` — **finished, shareable** skills. Everything here is discoverable and
  gets installed by `npx skills add rogvid/skills`.
- `wip/` — **in-development** skills. Not installed by anyone.
- `docs/` — design docs. Currently gitignored (the repo's permanent home is still
  being decided); do not `git add` it.

Each skill is a directory with a `SKILL.md` at its root.

## Why `wip/` stays hidden — do not "tidy" it into `skills/`

The `skills` CLI discovers skills by walking the **repo root only one level
deep**, plus a few known container dirs (`skills/`, `skills/.curated/`,
`skills/.experimental/`, `skills/.system/`, `.claude/skills/`, …) two levels deep.
A `SKILL.md` under `wip/<name>/` sits two levels below the root, so discovery
never sees it. This is the whole mechanism:

- Do **not** move `wip/` skills into `skills/` or any `skills/.experimental/`
  subdir to "make them findable" — `.experimental/` **is** a discovery path, so
  that would ship unfinished work to everyone running `--all`.
- Keep **at least one** skill in `skills/`. If `skills/` is ever empty the CLI
  falls back to a recursive search that would surface `wip/`. `demo-video`
  currently holds this invariant.

## Authoring a new skill

1. Create it under `wip/<name>/SKILL.md`. **Never** create a skill directly in
   `skills/`.
2. Frontmatter needs `name` and `description`. `name` must equal the directory
   name. Write `description` as a **trigger condition** ("Use when …") — that text
   is what an agent matches against to decide whether to invoke the skill.
3. If the skill needs a companion executable, bundle its source under
   `<skill>/cli/` and invoke it from `SKILL.md` (e.g. via `npx tsx
   <skill>/cli/src/index.ts`) so `npx skills add` carries it along. Do not rely
   on a globally-installed binary.

## Promoting a skill (`wip/` → `skills/`)

1. `name` matches the directory name.
2. `description` states **when to use** the skill, not only what it does.
3. It has been run end-to-end in a real project at least once, not just written.
4. Prerequisites are bundled in the skill directory, or stated explicitly in
   `SKILL.md`.
5. `git mv wip/<name> skills/<name>`.
6. Update the README: add a row to the **Skills** table, remove it from
   **In development**.
7. Create the skill's issue label:
   `gh label create <name> --description "Issues for the <name> skill" --color 1d76db`.
8. Verify the per-skill install command against the pushed commit.

## Issue tracking — GitHub Issues via `gh`

**GitHub Issues is the issue tracker for this repo, and the `gh` CLI is how you
reach it.** There is no `TODO.md`, no backlog file, no list of open questions
buried in `docs/`. If work is worth remembering, it is an issue.

- Start of a work session, or before picking up anything vague: `gh issue list`.
  Read the whole issue before acting on it — `gh issue view <n>`.
- Spotted follow-up work that is out of scope for what you are doing? **File it
  yourself**, don't just mention it in chat:
  `gh issue create --title … --body … --label <skill>`. Say the issue number in
  your reply.
- Label every issue with the skill it concerns (`demo-video`,
  `script-conventions`, …). Create the label when a new skill is promoted:
  `gh label create <skill> --description "Issues for the <skill> skill"`.
  Repo-wide work gets no skill label. The default GitHub labels (`bug`,
  `enhancement`, `documentation`, …) stack on top.
- Close issues from commits — `Fixes #12` in the commit message — rather than by
  hand, so the reason a thing closed is in the history.
- Big design proposals belong in the issue body as a checklist, the way #1 does.
  Split an item into its own issue once someone actually starts on it.

## Housekeeping

- Never commit `node_modules/`, `dist/`, `build/`, `__pycache__/`, `.tts/`, or
  `*.seg.mp4` (see `.gitignore`).
- Keep the README catalog tables in sync whenever you add, promote, or remove a
  skill.

## Skill scripts

Skills in this repo ship executables as self-contained PEP 723 scripts run by
`uv`, alongside a copied-in `ensure.sh`. Never add a `requirements.txt`, a
`.venv/`, a `pip install` step, or a first-run marker file to a skill — uv's
cache already handles once-only setup.

Before writing, editing, or debugging any script inside a skill, read
`skills/script-conventions/SKILL.md` and follow it. Templates to copy live in
`skills/script-conventions/templates/`.
