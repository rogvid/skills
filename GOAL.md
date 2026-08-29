# What this repo is for

Read this before planning work here. It is the thing every change is judged
against, and it is deliberately short enough that there is no excuse for
drifting from it.

## The problem

Agents now write code far faster than humans can review it. The cost has moved
from writing to **understanding what an agent built and checking it against what
was expected** — and it lands on reviewers who often had no say in the
architecture, the planning, or the ticket. With no context to review against,
line-by-line reading is the only tool they have left, and it does not scale with
agent output.

That is **cognitive debt**: the same shape as technical debt, accruing on
people instead of code.

## The answer this repo is a part of

A layered set of **machine-checkable gates** — CI steps, tests, architectural
fitness functions, guidelines, and tools like the skills here — each answering a
review question before a human is involved, so human attention is spent only
where it is genuinely required.

No single gate answers everything. Each one owns a question, answers it well,
and says plainly what it does not answer.

## What `demo-video` owns

**One question: did the change do what the ticket said?**

Answered by watching rather than reading, and graded by an **independent agent**
— one that sees the ticket's clauses and the recorded frames, and never sees the
implementation, the diff, `record.py`, or the implementing session's reasoning.
That isolation is the whole value: it is a genuinely fresh reader, which is
exactly what a human reviewer is and what the implementing agent's self-report
can never be.

A human is pulled in only on `cannot tell`, or on disagreement.

## What it explicitly does not own

Watching a demo replaces reading the diff **for that one question only**.
Anything else the change touches — a widened permission, a deleted check, a new
dependency — is invisible to a demo and is still the diff's to answer. That
sentence ships in the pull-request body, as `DIFF_LIMIT` in
`.github/scripts/demo-pr-body`, and must keep shipping.

It once did not. It lived in `.github/scripts/demo-comment`, which #420
deleted, and for three commits nothing in the tree carried it — because this
line named a commit rather than a live file, and a commit cannot go red. It is
now pinned by `BlockDiffLimit` in `tests/ci-unit`. **Pin a rule here to
something that fails**, not to a sha.

It also grades whether the frames show the clause, **not** whether the clause was
the right thing to build.

## Success

> A developer opens a pull request and within **30 seconds** knows whether to
> merge it, without reading the diff to answer "did it do what the ticket said."

The metric is **seconds of human attention per reviewed ticket**, measured with
a stopwatch on real tickets in `examples/ticket-queue`. Not "the artifacts are
honest," not "every assertion is graded," not merged pull requests.

Honesty of the artifacts is a *precondition* — necessary, already largely built,
and not the product.

## Rules that follow from this

- **Never ask a human to *measure* a pixel, a colour, a duration or a count.**
  Arbitrating a value across screenshots, or comparing two hex codes by eye, is
  the harness's job, and a human doing it is a bug in the harness. **Asking one
  whether the result reads right is not that.** The harness answers what the
  value *is* (`tests/pixel`, for the recorder's chrome, warm in seconds); only
  a person answers whether it *works* — #291 was a card the
  harness measured correctly, 1.3 luma levels of separation with every
  assertion green, that a viewer watching read as a terminal window
  (`skills/demo-video/reference/review.md`). Do not route that question away
  from them.
- **A true observation is not automatically work.** See `CLAUDE.md`.
- **CI is a gate before merge, not the iteration loop.** If the loop is slow,
  fix the loop rather than routing around it through a human.
- **Ask a model one perceptual question at a time.** "Is this clause visible in
  this frame" is stable; "is this pull request good" folds perception,
  aggregation and a threshold into one answer and was measured unstable here
  (#131 — the finding was stable, the ship/no-ship field was a coin flip). Any
  roll-up is arithmetic over per-clause answers, done in code, with the rule
  written down.
- **Secrets: the skill has no masking, no scrubbing and no redaction, by
  design.** `skills/demo-video/SKILL.md` states the constraint and the reasoning;
  it is not a gap to be closed.
