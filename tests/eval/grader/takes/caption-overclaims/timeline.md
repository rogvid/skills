# Demo timeline

`demo.mp4` · Recorder · 20.9s · 19 beats

Written by the demo-video recorder on every clean exit — do not edit it by hand, re-record instead.

## Acceptance criteria

This take was recorded against a ticket. **The table below is what the storyboard *claimed*, not what it proved** — an `ac=` tag is a string its author typed, and whether the frames actually show the criterion is the reviewer's judgement, not this file's.

| criterion | claimed by | at | still |
|---|---|---:|---|
| **AC-1** — A search box above the queue narrows the list as you type, with no button to press. | beat 2 | 1.02 |  |
|  | beat 6 | 7.10 | `images/01-invoice.png` |
| **AC-3** — Search matches the requester as well as the title — typing part of a name or an address finds that person's tickets. | beat 7 | 7.16 |  |
|  | beat 12 | 14.50 | `images/02-requester.png` |
|  | beat 13 | 14.54 |  |
|  | beat 16 | 20.07 | `images/03-who.png` |

Every one of the 2 criteria has at least one beat claiming it. Whether those beats show what they claim is the reviewer's call.

13 beat(s) claim no criterion. That is ordinary — navigation, waits and captions that set the scene are not demonstrating anything in particular.

**The host's wall clock stepped 1 time(s) while this was recorded** (-1.10s in total). The times below are `time.monotonic()`; the recording is on that wall clock, so an instant this table puts at `t` sits at `t` plus the steps its own capture recorded before `t` — not at `t`, and not at `t` plus the total above, which is the correction for no single row. `timeline.json`'s `capture_clock` carries every step and the capture it was measured in; `frames/frames.md` says whether the review frames were cut with it applied.

| # | start | end | verb | target | caption |
|---:|---:|---:|---|---|---|
| 0 | 0.42 | 0.99 | `goto` | `/` |  |
| 1 | 0.99 | 1.02 | `wait_for` | `.ticket` |  |
| 2 | 1.02 | 4.36 | `caption` |  | Typing invoice narrows the queue as you type. |
| 3 | 4.36 | 5.58 | `type_into` | `#queue-search` | Typing invoice narrows the queue as you type. |
| 4 | 5.58 | 5.59 | `wait_for` | `.ticket[data-id='TQ-101']` | Typing invoice narrows the queue as you type. |
| 5 | 5.59 | 7.10 | `hold` |  | Typing invoice narrows the queue as you type. |
| 6 | 7.10 | 7.16 | `shot` | `01-invoice` | Typing invoice narrows the queue as you type. |
| 7 | 7.16 | 10.82 | `caption` |  | Part of a requester's name finds that person's tickets. |
| 8 | 10.82 | 11.73 | `click` | `#queue-search` | Part of a requester's name finds that person's tickets. |
| 9 | 11.74 | 12.97 | `type_into` | `#queue-search` | Part of a requester's name finds that person's tickets. |
| 10 | 12.97 | 12.99 | `wait_for` | `.ticket[data-id='TQ-104'] .ticket-requester` | Part of a requester's name finds that person's tickets. |
| 11 | 12.99 | 14.50 | `hold` |  | Part of a requester's name finds that person's tickets. |
| 12 | 14.50 | 14.54 | `shot` | `02-requester` | Part of a requester's name finds that person's tickets. |
| 13 | 14.54 | 18.22 | `caption` |  | Every row the search leaves shows who raised it. |
| 14 | 18.22 | 18.55 | `spotlight` | `.ticket[data-id='TQ-104'] .ticket-requester` | Every row the search leaves shows who raised it. |
| 15 | 18.55 | 20.07 | `hold` |  | Every row the search leaves shows who raised it. |
| 16 | 20.07 | 20.14 | `shot` | `03-who` | Every row the search leaves shows who raised it. |
| 17 | 20.14 | 20.71 | `spotlight` |  | Every row the search leaves shows who raised it. |
| 18 | 20.71 | 21.02 | `caption` |  |  |

## Stills

### 01-invoice — 7.10s

> Typing invoice narrows the queue as you type.

![01-invoice](images/01-invoice.png)

### 02-requester — 14.50s

> Part of a requester's name finds that person's tickets.

![02-requester](images/02-requester.png)

### 03-who — 20.07s

> Every row the search leaves shows who raised it.

![03-who](images/03-who.png)
