# The grader's eval corpus

Four takes recorded against `examples/ticket-queue`, each clause carrying a
written-down expectation, scored by `tests/eval-grader`.

```sh
tests/eval-grader record                  # ~2 min for all four, cached
tests/eval-grader brief                   # one brief per take
#   … hand each brief + frames/ to a reader that has seen nothing else …
tests/eval-grader score --readings DIR    # seconds
```

`readings/` holds the answers the published numbers were scored from, so
`tests/eval-grader score --readings tests/eval/grader/readings/2026-08-14-run-2`
reproduces them without dispatching a reader.

## Why this exists

The blind reader in `skills/demo-video/scripts/demo-grade` had been measured
once: three readers over one real take agreed exactly. That is an anecdote.
Nothing said what it catches, what it misses, or how often it flags a demo that
is fine. This is the measurement.

## The mechanic every take is built around

**The reader is blind to `coverage.claimed`, structurally.** `demo-grade`'s two
renderers are handed the clause text and the frame filenames and cannot reach
for a claim. So mutating `claimed` moves the *comparison* and never the
reader's answer — a corpus of such mutations would measure `demo-grade`'s
arithmetic, which `tests/unit` already covers, while reporting a number about
the reader.

Every defect here is therefore in the **pixels**.

## The four takes

| Take | Clauses | Planted | Expected |
|---|---|---|---|
| `clean-status-filter` | AC-1, AC-2 | nothing | both located, both agree |
| `clean-search` | AC-1, AC-2 | nothing | both located, both agree |
| `never-demonstrated` | AC-1, AC-2 | AC-2 claimed, never shown | AC-2 `not seen` → disagreement |
| `caption-overclaims` | AC-1, AC-3 | AC-3's caption overclaims | AC-3 **missed** |

**Two clean takes, not one.** A single clean take cannot tell a reader that
reads from a reader that agrees with whatever it is shown. They are
deliberately different shapes: one clicks, one types; one clause's evidence is
a narrowed list, another's is a line of text where the rows used to be.

**`caption-overclaims` is the negative control and it is not a joke.**
`AGENTS.md`, under *Where an eval replaces the injections*: a corpus with no
expected misses is not a measurement. When this corpus was written,
`demo-grade`'s own docstring named this exact defect as the one it cannot catch
— the storyboard author's caption is burned into every frame, so the blind
reader and the author read the same sentence. The take types `webhook`, a word
from TQ-104's **title** that appears in no requester in `data/tickets.json`,
under a caption asserting that search matches the requester. The screen
genuinely narrows; the caption genuinely overclaims.

> If a run scores that clause as **caught**, that is a finding about the
> reader. Report it. Do not edit `expected.json` to match the result.

### The corpus's own stated limit: the negative control is not an instance of the blind spot

That clause has now been caught **twice**, by independent readers, and the
expectation has not been edited. Both readings are committed, in
[`readings/`](readings/), so that sentence can be checked from a clean checkout
rather than believed; that directory's README says when each was produced and
what its reader was given. The finding it produced is about the limit
rather than about the reader: the reasoning behind it — "the caption is burned
into the pixels, so both readers read it" — is true and is not the binding
constraint, because **the reader is never asked to compare the screen against
the caption. It is given the ticket's clause text.** A caption that overclaims
against that text is therefore catchable, and one reader said so in as many
words:

> *"matching on a requester's name or address is asserted only by the burned-in
> caption at beat-06 and is never demonstrated on screen; the later highlight of
> `leo.fontaine@northwind.example` merely rings the requester column of a
> title-matched row."*

`demo-grade` now states the real blind spot: **a declared clause text that is
itself the misreading.** If `criteria={"AC-3": <a wrong paraphrase of the
ticket>}` and the demo faithfully satisfies the paraphrase, the reader agrees,
the storyboard agrees, and the ticket is still unmet — every input the reader
has is downstream of the paraphrase. Issue **#276** is what closes it, by
comparing the declared clause with the ticket's own words.

**So this corpus currently has no expected miss that is an instance of the
blind spot it claims to hold.** `caption-overclaims` stays an `expected-miss`
and stays reported as an `UNEXPECTED CATCH`, because the score has to keep
saying out loud that the negative control does not do its job. Rebuilding it to
plant a wrong paraphrase the demo faithfully satisfies is #276's work, not this
corpus's. Until then, read the score as: honest about what the reader catches,
and untested about what it cannot.

Two runs on one take is also not a proof that a caption overclaim is *always*
caught. It is two observations, and the corrected limit in `demo-grade` says so
in those words.

## What "caught" means

`agreement` is the only verdict class that closes a clause without a human
looking at it. So a clause is *surfaced* when its class is anything else —
`disagreement`, `cannot tell`, or `no reading`. A planted clause is caught when
it is surfaced; a clean clause is a false alarm when it is; an expected-miss
clause is missed-as-expected when it is not.

The table also prints an `exact` column — whether the reader's status *and* the
verdict class matched what was written down — because "caught" and "caught for
the reason we expected" are worth telling apart.

## What is committed, and what is not

Committed: `record.py`, `expected.json`, `timeline.json`, `timeline.md`,
`images/`, and `.eval-recording.json` — plus `readings/`, the answers a blind
reader gave on the runs this corpus's published numbers come from. Those are
committed for the reason the rest of this section argues the frames are not:
they are what a claim in a shipped document rests on, they are small, and
nothing regenerates them.

**Not committed: `frames/`.** This was a judgement call and here is the
argument, so it can be overruled on its merits — it costs one line of
`.gitignore`.

Pinning the frames would pin the pixels, but the eval's answer already depends
on something no repository can pin: the model that reads them. A different
reader, or the same reader tomorrow, gives a different reading, and that is the
dominant term. Sixteen megabytes to hold the smaller term still while the
larger one moves freely buys precision the measurement cannot spend.

What the frames *do* need to be is constant while you vary something else — the
brief's wording, say — and the cache already provides that inside a working
tree: `record` re-records only when `.eval-recording.json`'s digest stops
matching the storyboard, the app, and `helpers/demo_recording/`. `score` prints
a footer when it is scoring older pictures.

**The gap this leaves, stated rather than discovered later.** The digest covers
the files in this repository. It does not cover Chromium, ffmpeg, the font
stack, or the host clock — this box stepped its wall clock by 2.08 s during an
unrelated recording, which `demo-video` corrects for and reports. So a corpus
re-recorded on another machine is of the same *storyboard* and not of the same
*pixels*, and a score compared across machines carries that caveat. If that
becomes the thing in dispute, committing `frames/` is the fix.

## What this corpus does not measure

Also in `tests/eval-grader`'s docstring, which is where a reader of the score
will be:

- **Eight clauses — six clean, one planted, one expected miss**, over four
  takes. `tests/eval-grader score` prints that shape on the line above its
  table, counted off the corpus, so this sentence has a printed counterpart to
  be checked against rather than being the only place the number lives. Enough
  to tell "flags clean demos constantly" from "does not". Not enough for a rate.
- **One reader per clause per run**, so nothing here measures variance. #131 is
  the standing warning about the unstable half of this question.
- **One app, one recorder, one storyboard author.** Nothing about terminal
  takes, stitched demos, or screens that are not lists of rows.
- **Not the recorder.** Expectations are written against what the storyboard
  should produce; nothing in between checks that the frames are of what the
  storyboard asked for. `tests/smoke` owns that.
