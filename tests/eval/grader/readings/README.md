# The readings the corpus was scored from

What a blind reader actually answered, kept so that the numbers this corpus
reports can be re-derived from a clean checkout instead of being taken on
trust.

```sh
tests/eval-grader record                                     # the frames
tests/eval-grader score --readings tests/eval/grader/readings/2026-08-14-run-2
```

## Why these files are here at all

`skills/demo-video/scripts/demo-grade`, `tests/eval-grader`, this corpus's
`README.md` and every `brief.md` the tool renders all rest on one sentence: the
caption-overclaim planted as the negative control **was caught, twice, by
independent readers**, which is why the stated blind spot was rewritten
([#276](https://github.com/rogvid/skills/issues/276), commit `52d5159`). Until
this directory existed, `git log --all --diff-filter=A --name-only` found no
reading committed anywhere in history — the claim was unverifiable from a
checkout, which is not a claim a shipped document gets to make.

Each run is one directory of `<take>.json`, in exactly the shape
`demo-grade verdict --reading` accepts, which is also the shape
`tests/eval-grader score --readings DIR` reads.

## The runs

| run | produced | scored in | caption-overclaims AC-3 |
|---|---|---|---|
| `2026-08-13-run-1` | 2026-08-13 | `0cd1bc5` (#330), the corpus's first real run | caught — `cannot tell` |
| `2026-08-14-run-2` | 2026-08-14 | `52d5159` (#331), the run that retracted the limit | caught — `cannot tell` |

Each run is one reading per take, four in all, each from a separate reader
handed exactly two things — the take's `review/brief.md` as
`tests/eval-grader brief` wrote it, and that take's `frames/` directory. None
of them saw `record.py`, `timeline.json`, `expected.json`, another take, or
each other. That is the whole provenance the artifacts carry.

**These two are the runs the word "twice" refers to**, not a count of every run
this corpus has ever had. #331 took two further runs while measuring the span
fix (clean clauses falsely flagged `1/6 → 0/6`); they are evidence for that
ratio rather than for the sentence above, and they are not collected here.

Run 2's AC-3 sentence is the one quoted in `demo-grade`'s docstring, in this
corpus's `README.md` and in #331's commit message:

> *"…matching on a requester's name or address is asserted only by the burned-in
> caption at beat-06 and is never demonstrated on screen; the later highlight of
> `leo.fontaine@northwind.example` at beat-14 merely rings the requester column
> of a title-matched row."*

## What this does **not** pin, said here rather than assumed

- **Which model, at which build.** The readings are the output of a Claude agent
  in the session that produced each commit above; nothing in the artifact
  records a model identifier, and re-running will not reproduce this prose.
  That is the eval's dominant term and `../README.md` explains why it is not
  pinned.
- **The pixels they were read from.** `frames/` is not committed — the argument
  is in `../README.md`. Re-recording on another machine gives the same
  *storyboard* and not the same *pictures*, so a reading here is evidence of
  what a reader said about a recording, not a fixture the frames can be
  regenerated to match.
- **Anything about variance.** Two runs over one corpus is two observations.
  Both runs score identically under `52d5159` — `1/1` planted caught, `0/6`
  clean falsely flagged, `0/1` expected misses missed — and that agreement is a
  measurement, not a property.

Scoring an *older* run against *today's* `demo-grade` is a legitimate thing to
do here and is how #331 was measured: the reader's answer is a function of the
frames alone, so the comparison rule can be changed underneath a recorded
reading without invalidating it. What it cannot survive is the corpus's clauses
changing; a run recorded against clauses a take no longer declares is refused by
`score`, by name.
