# The grader's eval corpus

Four takes recorded against `examples/ticket-queue`, each clause carrying a
written-down expectation, scored by `tests/eval-grader`.

```sh
tests/eval-grader record                  # ~2 min for all four, cached
tests/eval-grader brief                   # one brief per take
#   … hand each brief + frames/ to a reader that has seen nothing else …
tests/eval-grader score --readings DIR    # seconds
```

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
expected misses is not a measurement. `demo-grade`'s own docstring names this
exact defect as the one it cannot catch — the storyboard author's caption is
burned into every frame, so the blind reader and the author read the same
sentence. The take types `webhook`, a word from TQ-104's **title** that appears
in no requester in `data/tickets.json`, under a caption asserting that search
matches the requester. The screen genuinely narrows; the caption genuinely
overclaims.

> If a run scores that clause as **caught**, that is a finding about the
> reader. Report it. Do not edit `expected.json` to match the result.

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
`images/`, and `.eval-recording.json`.

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

- **Seven clauses.** Enough to tell "flags clean demos constantly" from "does
  not". Not enough for a rate.
- **One reader per clause per run**, so nothing here measures variance. #131 is
  the standing warning about the unstable half of this question.
- **One app, one recorder, one storyboard author.** Nothing about terminal
  takes, stitched demos, or screens that are not lists of rows.
- **Not the recorder.** Expectations are written against what the storyboard
  should produce; nothing in between checks that the frames are of what the
  storyboard asked for. `tests/smoke` owns that.
