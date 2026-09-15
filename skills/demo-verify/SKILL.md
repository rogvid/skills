---
name: demo-verify
description: Use when a change has a ticket with acceptance criteria and a recorded demo should show whether the change does what the ticket says, graded by an agent that never sees the implementation - "prove this PR meets the ticket", "record evidence for the acceptance criteria", "attach a verified demo to the pull request". Builds on the demo-video skill's recorder; for a demo that only needs to look good, use demo-video on its own.
---

# demo-verify

A reviewer should not have to read a diff to learn whether a change did what its ticket said.
This workflow records the change against the ticket's own acceptance criteria, then has an **independent agent** - one that sees the clauses and the recorded frames, and never the diff, the storyboard or your reasoning - locate each clause in the frames.
A human is pulled in only where that reader cannot tell, or disagrees with what the storyboard claimed.

It answers one question, and says so in everything it publishes: **does the take show the clauses?**
A widened permission, a deleted check or a new dependency is invisible to a demo, and stays the diff's to answer.

## Prerequisite: the demo-video skill

This skill has no scripts of its own. It drives the `demo-video` skill's recorder and scripts, so that skill must be installed:

```sh
npx skills add rogvid/skills --skill demo-video
```

Every command below is written against `<demo-video-dir>`, that skill's directory.
It installs next to this one, so it is normally the sibling of the directory this SKILL.md was read from:

```sh
ls <this-skill-dir>/../demo-video/SKILL.md      # normally here
find ~ . -name SKILL.md -path '*demo-video*' 2>/dev/null   # if not
```

Run `bash <demo-video-dir>/ensure.sh` once per session before the first script.
Record a plain demo with `demo-video` first if you have not; this skill only adds what a graded one needs.

## 1. Declare the ticket in the storyboard

Start from `<demo-video-dir>/scripts/demo-new <folder>`, then quote the ticket's clauses **verbatim** and tag each beat that shows one:

```python
with Recorder(HERE, ticket="acme/app#129", criteria={
    "AC-1": "Typing in the search box filters the queue by title.",
    "AC-2": "Search also matches the requester.",
}) as rec:
    rec.criterion("AC-1")                    # the clause itself, on a card
    rec.caption("Type a word from a title.", ac="AC-1")
    rec.type_into("#search", "invoice")
    rec.wait_for(".ticket")                  # the outcome, asserted
    rec.shot("01-by-title", ac="AC-1")
```

- `ac="AC-1"` is your claim that this beat shows AC-1. It is a claim, not evidence; step 4 is what checks it.
- `shows="unmet"` points a claim the other way: evidence that a clause is **not** met.
- `criterion("AC-1")` puts the declared sentence on screen, read from `criteria=` rather than retyped.
- `ticket=` names whose clauses they are, so the quotation can be checked against the ticket.

Details, including what each field of the coverage table means: **Recording against a ticket** in `<demo-video-dir>/reference/review.md`.

## 2. Rehearse - the gate

```sh
<demo-video-dir>/scripts/demo-rehearse <folder>/record.py
```

Strict, and seconds long.
**A demo of something that does not work is not made:** until this exits 0, do not caption, polish or record.
The `wait_for` after each action is what gives it teeth; a storyboard that only acts rehearses green over a feature that does nothing.

## 3. Record, then check the captions

```sh
uv run <folder>/record.py
<demo-video-dir>/scripts/demo-caption-lint <folder>
```

When the lint reports NOT FOUND, check the app first: a screen that does not do what the caption says is a bug the demo caught, and softening the caption launders it.

## 4. Two blind readers

Run both, each in a **fresh subagent that has seen nothing else** - not the storyboard, `record.py`, `timeline.md`, the diff, or this conversation.
Nothing in the tools can enforce that isolation; it is the whole value of the pass, and it is yours to keep.

**Is the story clear?**

```sh
<demo-video-dir>/scripts/demo-review <folder>
```

Prints the frame sheet and the questions, in the words they must be asked in; paste them, do not retype them.
A narration that misses the story, or UNCLEAR, is the storyboard's fault: fix it and re-record, with a new subagent each round.
Ship on CLEAR; stop after 3 rounds and surface what is left.

**Where is each clause?**

```sh
<demo-video-dir>/scripts/demo-grade brief   <folder>                          # writes review/brief.md
<demo-video-dir>/scripts/demo-grade verdict <folder> --reading reading.json   # writes review/verdict.md
```

Give the subagent `review/brief.md` and the take's `frames/`.
Save its reply verbatim as `reading.json`.
`verdict` compares the reading with your `ac=` tags; what it catches and what it does not is printed in both files.

## 5. Put it in front of the reviewer

Commit the storyboard, stills and timeline (not `demo.mp4`, `frames/`, `evidence/` or `review/` - `<demo-video-dir>/scripts/demo-gitignore <folder>` prints the lines), push, then:

```sh
<demo-video-dir>/scripts/demo-grade pr-block <folder>
```

It prints the block for the pull request body: disagreements and every `cannot tell` first, agreements after, each clause with its text and its committed still.
Drag `demo.mp4` into a comment so the reviewer can watch it.

To have branches record and publish this themselves, use the reusable workflow described in `<demo-video-dir>/reference/ci.md`.
