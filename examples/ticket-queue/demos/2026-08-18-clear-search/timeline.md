# Demo timeline

`demo.mp4` · Recorder · 33.3s · 34 beats

Written by the demo-video recorder on every clean exit — do not edit it by hand, re-record instead.

Recorded against **rogvid/skills#336**, as the storyboard names it. The recorder never fetched it: nothing here has compared anything in this file with what that ticket says.

## Acceptance criteria

This take was recorded against a ticket. **The table below is what the storyboard *claimed*, not what it proved** — an `ac=` tag is a string its author typed, and whether the frames actually show the criterion is the reviewer's judgement, not this file's.

| criterion | claimed by | at | still |
|---|---|---:|---|
| **AC-1** — While the search box holds text, a clear control ("×") is visible beside it. While the box is empty, the control is absent. | beat 2 | 0.70 |  |
|  | beat 5 | 7.28 | `images/01-empty-box.png` |
|  | beat 10 | 12.30 |  |
|  | beat 16 | 20.48 | `images/02-control-appears.png` |
| **AC-2** — Activating the clear control empties the box and restores the list to what the active status filter alone would show, with the heading count agreeing. | beat 18 | 21.16 |  |
|  | beat 26 | 27.56 | `images/03-restored.png` |
|  | beat 27 | 27.65 |  |
|  | beat 31 | 32.86 | `images/04-heading.png` |

Every one of the 2 criteria has at least one beat claiming it. Whether those beats show what they claim is the reviewer's call.

26 beat(s) claim no criterion. That is ordinary — navigation, waits and captions that set the scene are not demonstrating anything in particular.

**The host's wall clock stepped 1 time(s) while this was recorded** (-1.49s in total). The times below are `time.monotonic()`; the recording is on that wall clock, so an instant this table puts at `t` sits at `t` plus the steps its own capture recorded before `t` — not at `t`, and not at `t` plus the total above, which is the correction for no single row. `timeline.json`'s `capture_clock` carries every step and the capture it was measured in; `frames/frames.md` says whether the review frames were cut with it applied.

| # | start | end | verb | target | caption |
|---:|---:|---:|---|---|---|
| 0 | 0.08 | 0.66 | `goto` | `/` |  |
| 1 | 0.66 | 0.70 | `wait_for` | `.ticket` |  |
| 2 | 0.70 | 5.41 | `caption` |  | The search box is empty, and no clear control sits beside it. |
| 3 | 5.41 | 5.75 | `spotlight` | `.queue-search` | The search box is empty, and no clear control sits beside it. |
| 4 | 5.75 | 7.28 | `hold` |  | The search box is empty, and no clear control sits beside it. |
| 5 | 7.28 | 7.39 | `shot` | `01-empty-box` | The search box is empty, and no clear control sits beside it. |
| 6 | 7.39 | 7.99 | `spotlight` |  | The search box is empty, and no clear control sits beside it. |
| 7 | 7.99 | 11.32 | `caption` |  | Choosing Open, so a status filter is active. |
| 8 | 11.32 | 12.29 | `click` | `button[data-status='open']` | Choosing Open, so a status filter is active. |
| 9 | 12.29 | 12.30 | `wait_for` | `.ticket` | Choosing Open, so a status filter is active. |
| 10 | 12.30 | 17.34 | `caption` |  | Typing a term narrows the list, and a × appears beside the box. |
| 11 | 17.34 | 18.60 | `type_into` | `#queue-search` | Typing a term narrows the list, and a × appears beside the box. |
| 12 | 18.60 | 18.61 | `wait_for` | `.ticket` | Typing a term narrows the list, and a × appears beside the box. |
| 13 | 18.61 | 18.62 | `wait_for` | `#clear-search` | Typing a term narrows the list, and a × appears beside the box. |
| 14 | 18.62 | 18.95 | `spotlight` | `#clear-search` | Typing a term narrows the list, and a × appears beside the box. |
| 15 | 18.95 | 20.48 | `hold` |  | Typing a term narrows the list, and a × appears beside the box. |
| 16 | 20.48 | 20.60 | `shot` | `02-control-appears` | Typing a term narrows the list, and a × appears beside the box. |
| 17 | 20.60 | 21.16 | `spotlight` |  | Typing a term narrows the list, and a × appears beside the box. |
| 18 | 21.16 | 24.50 | `caption` |  | One click on the × empties the box. |
| 19 | 24.50 | 25.45 | `click` | `#clear-search` | One click on the × empties the box. |
| 20 | 25.46 | 25.48 | `wait_for` | `.ticket[data-id='TQ-101']` | One click on the × empties the box. |
| 21 | 25.48 | 25.50 | `wait_for` | `.ticket[data-id='TQ-102']` | One click on the × empties the box. |
| 22 | 25.50 | 25.52 | `wait_for` | `.ticket[data-id='TQ-104']` | One click on the × empties the box. |
| 23 | 25.52 | 25.54 | `wait_for` | `.ticket[data-id='TQ-106']` | One click on the × empties the box. |
| 24 | 25.54 | 26.05 | `move_to` | `#queue-heading` | One click on the × empties the box. |
| 25 | 26.05 | 27.56 | `hold` |  | One click on the × empties the box. |
| 26 | 27.56 | 27.65 | `shot` | `03-restored` | One click on the × empties the box. |
| 27 | 27.65 | 30.99 | `caption` |  | The heading counts what the Open filter lists. |
| 28 | 30.99 | 31.00 | `wait_for` | `#queue-heading:has-text('(4)')` | The heading counts what the Open filter lists. |
| 29 | 31.00 | 31.34 | `spotlight` | `#queue-heading` | The heading counts what the Open filter lists. |
| 30 | 31.34 | 32.86 | `hold` |  | The heading counts what the Open filter lists. |
| 31 | 32.86 | 32.99 | `shot` | `04-heading` | The heading counts what the Open filter lists. |
| 32 | 32.99 | 33.56 | `spotlight` |  | The heading counts what the Open filter lists. |
| 33 | 33.56 | 33.87 | `caption` |  |  |

## Stills

### 01-empty-box — 7.28s

> The search box is empty, and no clear control sits beside it.

![01-empty-box](images/01-empty-box.png)

### 02-control-appears — 20.48s

> Typing a term narrows the list, and a × appears beside the box.

![02-control-appears](images/02-control-appears.png)

### 03-restored — 27.56s

> One click on the × empties the box.

![03-restored](images/03-restored.png)

### 04-heading — 32.86s

> The heading counts what the Open filter lists.

![04-heading](images/04-heading.png)
