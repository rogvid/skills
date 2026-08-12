# Demo timeline

`demo.mp4` · Recorder · 29.7s · 21 beats

Written by the demo-video recorder on every clean exit — do not edit it by hand, re-record instead.

## Acceptance criteria

This take was recorded against a ticket. **The table below is what the storyboard *claimed*, not what it proved** — an `ac=` tag is a string its author typed, and whether the frames actually show the criterion is the reviewer's judgement, not this file's.

| criterion | claimed by | at | still |
|---|---|---:|---|
| **AC-1** — A search box above the queue narrows the list as you type, case-insensitively, with no button to press. | beat 4 | 5.21 | `images/01-queue.png` |
|  | beat 6 | 5.58 |  |
|  | beat 7 | 12.31 | `images/02-criterion-card.png` |
|  | beat 13 | 19.38 | `images/03-invoice.png` |

Every one of the 1 criteria has at least one beat claiming it. Whether those beats show what they claim is the reviewer's call.

17 beat(s) claim no criterion. That is ordinary — navigation, waits and captions that set the scene are not demonstrating anything in particular.

**The host's wall clock stepped 1 time(s) while this was recorded** (-0.58s in total). The times below are `time.monotonic()`; the recording is on that wall clock, so an instant this table puts at `t` sits at `t` plus the steps its own capture recorded before `t` — not at `t`, and not at `t` plus the total above, which is the correction for no single row. `timeline.json`'s `capture_clock` carries every step and the capture it was measured in; `frames/frames.md` says whether the review frames were cut with it applied.

| # | start | end | verb | target | caption |
|---:|---:|---:|---|---|---|
| 0 | 0.44 | 1.01 | `goto` | `/` |  |
| 1 | 1.01 | 1.04 | `wait_for` | `.ticket` |  |
| 2 | 1.04 | 3.70 | `caption` |  | Seven tickets, in a browser window. |
| 3 | 3.70 | 5.21 | `hold` |  | Seven tickets, in a browser window. |
| 4 | 5.21 | 5.27 | `shot` | `01-queue` | Seven tickets, in a browser window. |
| 5 | 5.27 | 5.58 | `caption` |  |  |
| 6 | 5.58 | 12.31 | `criterion` | `AC-1` | A search box above the queue narrows the list as you type, case-insensitively, with no button to press. |
| 7 | 12.31 | 12.36 | `shot` | `02-criterion-card` |  |
| 8 | 12.36 | 12.97 | `interlude` | `card` |  |
| 9 | 12.97 | 16.64 | `caption` |  | The card is gone, and the queue is back. |
| 10 | 16.64 | 17.86 | `type_into` | `#queue-search` | The card is gone, and the queue is back. |
| 11 | 17.86 | 17.87 | `wait_for` | `.ticket` | The card is gone, and the queue is back. |
| 12 | 17.87 | 19.38 | `hold` |  | The card is gone, and the queue is back. |
| 13 | 19.38 | 19.43 | `shot` | `03-invoice` | The card is gone, and the queue is back. |
| 14 | 19.43 | 19.74 | `caption` |  |  |
| 15 | 19.74 | 22.55 | `interlude` | `card` | Same card, no clause — this is what bridges a time skip. |
| 16 | 22.55 | 22.59 | `shot` | `04-interlude-card` |  |
| 17 | 22.59 | 23.20 | `interlude` | `card` |  |
| 18 | 23.20 | 27.55 | `caption` |  | Queue, card, queue again — the card sits over the app. |
| 19 | 27.55 | 29.06 | `hold` |  | Queue, card, queue again — the card sits over the app. |
| 20 | 29.06 | 29.37 | `caption` |  |  |

## Stills

### 01-queue — 5.21s

> Seven tickets, in a browser window.

![01-queue](images/01-queue.png)

### 02-criterion-card — 12.31s

![02-criterion-card](images/02-criterion-card.png)

### 03-invoice — 19.38s

> The card is gone, and the queue is back.

![03-invoice](images/03-invoice.png)

### 04-interlude-card — 22.55s

![04-interlude-card](images/04-interlude-card.png)
