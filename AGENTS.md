# Working in this skills repo

This repo holds reusable agent skills, installed by the
[`skills`](https://github.com/vercel-labs/skills) CLI (`npx skills add`).

## Read `GOAL.md` first

`GOAL.md` states what this repo is for — reducing the **cognitive debt** that
agent-speed development pushes onto reviewers — and how success is measured
(seconds of human attention per reviewed ticket). Every rule below serves that;
where a rule and the goal appear to disagree, the goal wins and the rule is
wrong. Plan work against `GOAL.md`, not against the backlog.

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
3. If the skill needs a companion executable, bundle its source under the
   skill and invoke it from `SKILL.md` so `npx skills add` carries it along.
   Do not rely on a globally-installed binary. **A Python executable goes in
   `<skill>/scripts/` as a PEP 723 uv script** — that is what
   `skills/script-conventions` specifies, what `ruff.toml`'s `extend-include`
   lints, and what `ensure.sh` restores the exec bits on. `<skill>/cli/` is
   for a bundled TypeScript CLI run via `npx tsx <skill>/cli/src/index.ts`,
   which is a different animal; do not put a uv script there.

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

**A true observation is not automatically work.** This is the rule the repo
spent its first year missing, and its absence cost more than any defect in it:
every genuine finding became a durable ticket, the backlog grew faster than it
closed, and the quality ratchet ran with no throughput term. File an issue only
if the thing **makes the demo lie to its reader, or blocks the next phase of
`GOAL.md`**. Everything else true-but-minor goes in the pull-request body as a
stated limit, with its measurement, and dies there. A limit stated in the pull
request is not a lesser outcome than an issue — it is the same information
without a ticket nobody will pick up.

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
- Big design proposals go in the issue body as a checklist, together with the
  reasoning that motivated them. Before anyone starts, split that checklist into
  vertical slices — one issue per slice, each with its own acceptance criterion
  and its own note of what it deliberately leaves out — and keep the original as
  the design record. A single issue holding a quarter of work is a backlog, and
  nobody picks up a backlog. #1 split into #2–#12 is the worked example.

## When a change gets a demo video

**The test: can the acceptance criterion be verified by watching?** If yes, the
change gets a demo and a human reviews the video. If it can only be verified by
reading a file, an assertion, or a log, it does not — a video of it would be
ceremony, and ceremony is what makes people stop watching.

| Demoable | Not demoable |
|---|---|
| How the recording looks — spotlight, interludes, framing, captions | Whether a mask holds — absence is not watchable |
| A new verb a storyboard author would call | Beat schema, timeline fields, exit paths |
| Anything a viewer sees happen | Anything only a sweep or an assertion can see |
| A visible bug someone reported by eye | Test-only, CI, lint, docs |

The judgment is the author's, not the reviewer's, and it is made **before** the
work starts — it decides whether a human is in the loop at all.

Note what this implies for this repo: most work here is correctness in
secret-handling and artifact integrity, which is not demoable. That is expected.
`examples/ticket-queue` is where demoable features live, and it is the realistic
proving ground for anything about delivery.

## Reviewing changes, and writing the assertions that gate them

**Read `wip/verified-review/SKILL.md` before reviewing a change, and before
writing or fixing any assertion that gates one.** It is the house discipline
and it is not optional here.

**Where it applies, and where it does not.** It applies to **recorder
behaviour** and to anything that changes what a viewer sees or what an artifact
claims — that is where a wrong answer reaches a human as a false verdict. It
does **not** apply to documentation sentences, prose, README tables, test
counts, or the wording of a comment: those get an ordinary read, and a
disagreement about them is settled in one round, in the pull request. Running
an adversarial round on prose is how roughly half of a year's merged work ended
up being about prose.

Two rules:

- **Authoring: an assertion you have not seen fail is not evidence.** Break the
  thing it watches, run it, show the failure output in the pull request, then
  undo the break. Confirm the injection landed — make the harness refuse to
  proceed unless its pattern matched exactly once.
- **Reviewing: answer only "does this meet its stated acceptance criterion, and
  does it regress anything."** Everything else genuine that you notice goes in
  the PR body as a stated limit, or into an issue with its measurement. It does
  not block the merge, and it does not earn another round.

A finding blocks only if the change misses its acceptance criterion, regresses
something, makes an artifact lie, or adds an assertion that cannot fail for the
reason it claims. Merge when the blocking list clears; file the rest.

The skill's catalogue of *measurements that grade nothing* is the reviewer's
checklist. Every entry in it came from a change in this repo that had green CI
and an honest author.

### Where an eval replaces the injections

**Code whose correctness is measured by an eval does not also owe injections.**
The discipline above exists because a recorder defect is invisible until an
assertion catches it. That reasoning does not carry to code that is graded by
running it against a corpus with known answers — there, the corpus *is* the
evidence, and it is better evidence, because it measures the thing the code is
for rather than the code's own internals.

This applies today to the grader (`skills/demo-video/scripts/demo-grade` and
whatever reads its brief). Its question — *does a blind reader find the clause
in the frames* — is answered by the eval corpus: takes with known defects
planted, scored on what was caught and what was falsely flagged. Injections
there are optional. Write them where they are cheap and skip them where they
are not.

The number that made this rule: a five-item assertion-hygiene round on the
grader's own tests cost **85 minutes**, against an eval that answers the product
question in **four**. Each item was individually defensible under the rules
above, which is exactly why the scope had to be written down rather than left
to judgement.

An eval carries its own honesty requirement, and it is the same one: **a corpus
with no expected misses is not a measurement.** It must contain at least one
defect the reader is expected *not* to catch — the caption the screen agrees
with is this repo's known blind spot — and the score must show it uncaught. A
corpus that catches everything is measuring its own fixtures.

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
