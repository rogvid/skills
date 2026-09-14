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

  **This is your job locally. Nothing runs it for you.** `mise run
  fault-inject` is `tests/unit --fault-inject` (132 s) and `tests/ci-unit
  --fault-inject` (298 s); `mise run anchors` is the second-long sweep that
  every injection's pattern still matches its file exactly once and still
  names tests that exist. Neither runs in CI and neither is a git hook - see
  the section below for why. The cheap one catches a stale anchor, which is
  the failure the manifest actually has; it does **not** catch an assertion
  that stopped grading its subject. So when you add or change an injection,
  run the driver yourself and put its output in the pull request. A green
  branch says nothing about it, because a branch is green either way.
- **Reviewing: answer only "does this meet its stated acceptance criterion, and
  does it regress anything."** Everything else genuine that you notice goes in
  the PR body as a stated limit, or into an issue with its measurement. It does
  not block the merge, and it does not earn another round.

A finding blocks only if the change misses its acceptance criterion, regresses
something, makes an artifact lie, or adds an assertion that cannot fail for the
reason it claims. Merge when the blocking list clears; file the rest.

The skill's catalogue of *measurements that grade nothing* is the reviewer's
checklist. Every entry in it came from a change in this repo that had green
checks and an honest author.

### A change to a rendered frame runs `tests/pixel` first

Some changes move what a viewer sees: the chrome in
`skills/demo-video/helpers/demo_recording/` — captions, cards, cursor,
spotlight, framing. Before such a change opens its pull request, run
`tests/pixel` (#324). Put its pass/fail lines in the PR body. For anything
that changed on purpose, attach `--dump` frames from before and after.

The loop takes no lock, and a warm run measures ~2 s, so not running it is
the odd choice. It is the iteration loop; `mise run smoke` is the slower,
more complete reader of the same frames, and you run that one too before you
call a chrome change done.

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
defect the reader is expected *not* to catch, and the score must show it
uncaught. A corpus that catches everything is measuring its own fixtures.

**Which defect to plant, and which one not to.** The grader's real blind spot is
**a declared clause text that is itself the misreading** (#276): the demo
faithfully satisfies a wrong paraphrase of the ticket, so every input the reader
has is downstream of the paraphrase and no reading of any frame reaches it. Do
**not** plant "a caption the screen agrees with" — this file named that as the
blind spot, and `skills/demo-video/scripts/demo-grade` retracted it after the
corpus caught it twice. The corpus now holds one expected miss that **is** an
instance of the real blind spot: `tests/eval/grader/takes/clause-is-the-misreading`,
whose declared clause says *title* where the ticket it documents says
*requester*, and whose committed reading shows the reader agreeing with the
paraphrase — the miss is structural, and only #276's quotation check against
the ticket's own words would catch it. The rule that made it stands: a corpus
with no expected misses is not a measurement, and the requirement is not met by
editing an `expected.json` until it agrees with a result — a corpus that can
only agree with itself measures nothing.

## Setting up, and who decides when a check runs

```sh
mise run bootstrap  # uv, prek, gitleaks, and the git hooks
```

`mise run <task>` installs the `[tools]` block on its own, so `bootstrap` only
does the two things mise cannot infer: it installs the git hooks, and it
**reports** what it deliberately does not install - ffmpeg and a Chromium
build. Neither is needed by `check`; both are needed by every recording task
(`smoke`, `smoke-full`, `smoke-inject`, `pixel`, `ticket-queue`). It prints the
install command for whichever is missing, because without that those tasks fail
minutes into a recording with an error that never mentions a browser.

The name is mise's own convention: `mise bootstrap`, the machine-level command,
finishes by running a task called `bootstrap` if the config defines one.

**If a `mise run` here dies naming a tool this repo never mentions**, the tool
is in your *global* config and has no build for your platform - mise resolves
the merged config and installs all of it. Fix it where it lives, by gating the
tool to the platforms it actually ships for, rather than by disabling
auto-install here:

```toml
# ~/.config/mise/config.toml
age-plugin-yubikey = { version = "latest", os = ["macos", "windows"] }
```

**This repo is a set of skills, not a service, and it is deliberately not
gated like one.** Two things run without being asked:

- **GitHub runs one job**, `secrets` in `.github/workflows/ci.yml`: gitleaks
  over the pushed range. A leaked credential is the one failure that cannot be
  undone by running something later, which is the whole reason it is automatic.
- **The git hooks run two things**, `tests/lint` and gitleaks over the staged
  diff, together about a second. Bypass with `git commit --no-verify`; nothing
  downstream will ask the same question, so say so in the pull request.

Everything else is a `mise` task and runs when **you** decide the change is
worth the time - `mise tasks` is the list. `mise run check` is the fast gate by
hand (lint, typecheck, both unit suites, ~7 s); past that, `anchors`,
`fault-inject`, `workflows`, `issues`, `pixel`, `smoke`, `smoke-full`,
`smoke-inject`, `ticket-queue`, `budget`.

The consequence, stated rather than implied: **a green branch here means the
secret scan passed and nothing else.** Whatever else you claim about a change,
you ran yourself, and the output belongs in the pull request. That is the
trade - the author picks the evidence that fits the change instead of every
change paying for every check.

No task and no hook names a tool version. The repo has exactly one pin per
tool, on the `RUFF_VERSION:` / `MYPY_VERSION:` lines of `ci.yml`, and
`tests/lint` and `tests/typecheck` read that file as text (#189). Anything
calling `ruff` or `mypy` directly would be the second pin; the two
`--self-test` modes refuse one. Those two `env:` lines are why `ci.yml` still
carries an `env:` block no job uses.

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
