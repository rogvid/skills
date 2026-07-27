---
name: verified-review
description: Use when reviewing a change, when writing tests or assertions that will gate a change, or when a review keeps finding real problems without ever converging. Covers the two halves of a review loop that terminates — a bounded reviewer contract that stops findings multiplying without limit, and the fault-injection discipline that stops a green suite from meaning nothing. Reach for it when a pull request is blocked for the third time, when every closed issue spawns five new ones, or when you are about to trust a passing test you have never seen fail.
---

# Verified review

Two rules, one for each side of a review.

**Authoring:** an assertion you have not seen fail is not evidence.

**Reviewing:** answer *does this meet its stated acceptance criterion, and does
it regress anything* — and nothing else.

The first rule stops a green suite from being decorative. The second stops a
review from generating work faster than the work gets done. They fail
independently, and a project needs both.

## Why bounded review

An unbounded question produces unbounded output. Ask a competent reviewer
"what is wrong with this?" and you will get an honest, correct, ever-growing
list, because on any real surface — security, concurrency, error handling —
there is always another case. The list is not wrong. It is just not a plan.

The measured version, from the project this skill came out of: ten issues were
closed and thirty new ones were filed against them. Two features accounted for
most of it — "redact secrets" spawned eight, "make takes deterministic" spawned
five. Neither is a feature you finish. Both are properties with an unbounded
surface, and both were being tracked as though they had a done state.

The fix is not to review less carefully. It is to decide, before the review,
what the change is *for*, and to route everything else somewhere that is not
the blocking path.

## The reviewer contract

A reviewer is asked exactly two questions:

1. **Does this meet its stated acceptance criterion?** Not "is it good" — does
   it do the thing the issue said it would do.
2. **Does it regress anything that worked before?**

Everything else the reviewer notices — and it will notice a lot, most of it
genuine — goes to one of two places:

- **The pull request body**, as a stated limit. "This does not cover X" is a
  deliverable. A user who knows the boundary can work around it.
- **An issue**, with the measurement attached.

Neither blocks the merge.

### Blocking, precisely

A finding blocks only if one of these is true:

- The change **does not do what its issue said it would do**.
- The change **regresses** something that previously worked.
- The change makes an **artifact lie** — reports success on failure, reports a
  stale value as current, attributes something confidently to the wrong place.
  Confidently wrong is worse than absent, and worse than an honest `null`.
- An assertion the change adds **cannot fail** for the reason it claims. This
  is the one people skip. See the catalogue below.

Everything else is non-blocking. A leak in a path nobody takes, an inefficiency
nobody has measured, an untested branch of a flag nobody sets — real, worth
recording, not worth another round.

### The round cap

**Do not open round N+1 for non-blocking findings.** When the blocking list
clears, merge, and file the rest.

This is the rule that actually ends things, and it is the one that feels
wrong, because the non-blocking findings are real and you have them written
down right there. File them. They will be better issues written up calmly with
their measurements than they would be as a rushed fourth round.

### Asymptotic properties need declared boundaries

Some goals have no done state: "no secrets leak", "every take reproduces",
"handles all malformed input". A reviewer will always find another hole,
forever, and each one is legitimately a bug.

Treat these differently. Declare what the thing *does* cover, prove that with
tests, and write the rest down as a stated limit. Then a newly discovered gap
outside the boundary is a documentation line, not a defect — and the project
converges instead of accumulating.

If you cannot state the boundary, you do not have a feature yet; you have a
direction.

## The fault-injection rule

**For every assertion you write or fix: break the thing it watches, run it,
and show the failure output.**

Then undo the break. The failure output is the deliverable — paste it into the
pull request. An assertion nobody has watched fail is a claim, not a check.

This is cheap, it takes a minute per assertion, and in the project this came
from it found a defect in *every single* change it was applied to, including
several that no amount of code reading had surfaced.

### Confirm the injection landed

The injection itself can silently do nothing, and then the suite prints PASSED
and you conclude the assertion is sound. This has a distinctive signature: you
believe you have proven the opposite of what happened.

Make the harness refuse to proceed unless the pattern it is replacing matched
**exactly once**. Prefer exact strings or line numbers over regexes. Print the
resulting diff before running.

The best version of this seen in practice: a driver that aborted on a match
count other than one, which caught a non-matching regex on its first use — an
injection that would otherwise have "proved" a hollow assertion was sound.

## Catalogue: measurements that grade nothing

Every one of these was found in a real change that had green CI and an honest
author. This is the reviewer's checklist, and it is the most transferable part
of this skill.

**The vacuous sweep.** A check that scans output for forbidden content, which
passes because there is almost no output to scan. One byte sweep passed on
60 bytes per file — it would have passed on empty files.
*Detect:* assert the haystack is non-trivial before searching it. Add a control
that fires if the input is degenerate.

**The anti-correlated metric.** A quality score that moves the wrong way. A
blank screen recording scored 61.8 and a healthy one 60.2, because a third of
every frame was fixed window chrome whose contrast dominated the measurement.
*Detect:* score the thing you mean, not the frame it sits in. Run the metric
against known-bad input and check the number moves the direction you expect.

**The stale-input pass.** A test that re-uses a working directory and grades
the previous run's output. Two features were broken simultaneously and the
suite still reported PASSED, on last run's files.
*Detect:* clear the directory, assert freshness by mtime, write a marker.

**The wrong-scope search.** An assertion that searches a whole document when it
means one field. A check for a secret in a transcript's `screen` key searched
the entire file — and the key it was looking for also appeared in an embedded
command record, so a payload of `{"screen": ""}` passed.
*Detect:* search the narrowest scope that expresses the claim.

**The clean-path-only assertion.** A guard tested only where it was already
safe. A verifier that blocked artifacts on the success path was never exercised
on the exception path, where it was skipped entirely — leaving a screenshot on
disk with the secret legible.
*Detect:* for every guard, ask which exits skip it. Test the crash, the
timeout, the interrupt.

**The environment-agreeing assertion.** A check that passes because the machine
already satisfies it. A locale assertion could only be seen failing by forcing
a different locale, because the developer's box was already `en-US`.
*Detect:* if the assertion would pass with the feature entirely removed on your
machine, it grades your machine.

**The ungraded constant.** A tunable nothing pins. A hold time of 3.0 seconds
could be set to any value above roughly 0.45 with the whole suite still
passing, because the only test of it used a 0.4-second input — inside the
window, never near the boundary.
*Detect:* for each constant, ask what test fails if you double it. Then if you
halve it. Test at the boundary, not comfortably inside it.

**The threshold tuned to this box.** A timing bar with headroom that exists
only on the developer's hardware. One had 1.4x margin measured under load on a
16-core machine, destined for a 2-core CI runner also encoding video.
*Detect:* measure under contention, not idle. Prefer bars separated by an order
of magnitude over bars separated by a comfortable-looking margin.

**The config-hidden path.** A suite whose fixed configuration structurally
cannot reach the path real usage takes. A verifier ran before a final flush;
the suite disabled the feature that made that flush non-empty, so the gap could
not appear in any test.
*Detect:* list the options the suite pins, and ask what is unreachable because
of each.

**The self-inflicted condition.** A test that creates the phenomenon it
measures. An alignment probe waited two seconds between samples; that idle was
precisely what caused the stall it then attributed to the system under test.
*Detect:* when a measurement is unstable, check whether the harness causes it
before widening the tolerance. Widening a bar to accommodate your own artefact
hides the real signal.

**The dominated assertion.** A check that cannot fire because an earlier check
already guarantees the state it looks for. One asserted that a refused take
wrote no output frames — twenty lines after asserting the take wrote no video,
and the frame extractor returns early when there is no video. Removing the
guard it claimed to watch changed nothing; the assertion stayed silent.
*Detect:* for each assertion, ask which earlier assertion would already have
failed. If the answer is "one of them", this one is decoration. Fault injection
finds these immediately, which is why it is not optional.

**The check that shares the bug's blind spot.** A verification written from the
same mental model as the code, so it is blind in the same direction. A sweep
searching output files for a forbidden literal missed values containing `&`,
because the file stored them HTML-escaped — the same transformation the code
under test had failed to account for. The check could not catch the class of
bug it existed to catch.
*Detect:* write the check from the **consumer's** side — what can a reader
recover from this artifact? — not from the producer's. Never import the
normalization used by the code under test; hand-write it. If the check and the
code share a helper, a bug in that helper hides itself.

*Prove independence behaviourally, not structurally.* "It imports nothing from
the module" is weak — shared assumptions do not travel through imports. Break
the code three different ways and confirm the check catches each. A check that
disagrees with broken code is independent; one that merely lives in a different
file is not. Where the check is deliberately **broader** than the code (matching
things the code would not), a bug on the code's side surfaces as a failure
rather than hiding, which is the direction you want.

**The count that stands in for the content.** "N inputs produce N outputs" is
nearly free to satisfy and says almost nothing. Assert that output K
corresponds to input K.

## Working the loop

1. **Author** states the acceptance criterion, implements, and fault-injects
   every assertion. The failure output goes in the pull request body.
2. **Reviewer** answers the two questions, uses the catalogue above on the new
   assertions, and separates findings into blocking and non-blocking.
3. **Blocking findings** go back once, with reproductions.
4. **Non-blocking findings** become issues, with their measurements.
5. **Merge** when blocking clears. Do not reopen for polish.

### Reviewer instructions worth stating explicitly

- Green CI is not the bar. Say so in the prompt.
- Do not manufacture findings to appear thorough. "Nothing blocking" is a valid
  and useful result.
- Do not pass because the author was diligent and the change is large.
- Verify the author's claims about their own tests by reading the assertions,
  not by trusting the summary. Authors who fault-inject honestly still
  mis-target injections.

### Hand the reviewer the last review's findings

Bugs of this kind are structural, not incidental. A guard skipped on the
exception path in one module is worth checking for in every module with guards.
Passing the previous review's blocking findings into the next review as
"check whether this shape exists here too" costs nothing and has a high hit
rate.

## When to ignore this skill

If the change is mechanical and reversible — a rename, a formatting pass, a
dependency bump with a green build — this is overhead. Apply it where a wrong
answer would be believed: anything that gates a merge, guards a secret, reports
a status, or produces an artifact someone will act on without re-deriving it.
