# Demo timeline

`demo.mp4` · mixed · 62.0s · 47 beats

Written by the demo-video recorder when it stitched the segments below — do not edit it by hand, re-stitch instead.

Stitched from 2 segments, in order: `part1` (0.00–37.88s), `part2` (37.88–62.04s). Beat times below are on the stitched video's clock.

| # | start | end | verb | target | exit | caption |
|---:|---:|---:|---|---|---:|---|
| 0 | 0.42 | 0.99 | `goto` | `/` |  |  |
| 1 | 0.99 | 1.01 | `wait_for` | `.ticket` |  |  |
| 2 | 1.01 | 4.36 | `caption` |  |  | The support queue, every ticket the team holds. |
| 3 | 4.36 | 5.87 | `hold` |  |  | The support queue, every ticket the team holds. |
| 4 | 5.87 | 5.94 | `shot` | `01-queue` |  | The support queue, every ticket the team holds. |
| 5 | 5.94 | 8.95 | `caption` |  |  | A status filter sits above the list. |
| 6 | 8.95 | 9.28 | `spotlight` | `#status-filter` |  | A status filter sits above the list. |
| 7 | 9.28 | 10.81 | `hold` |  |  | A status filter sits above the list. |
| 8 | 10.81 | 11.40 | `spotlight` |  |  | A status filter sits above the list. |
| 9 | 11.40 | 14.05 | `caption` |  |  | Open lists only the open tickets. |
| 10 | 14.05 | 14.98 | `click` | `button[data-status='open']` |  | Open lists only the open tickets. |
| 11 | 14.98 | 16.49 | `hold` |  |  | Open lists only the open tickets. |
| 12 | 16.49 | 16.55 | `shot` | `02-open` |  | Open lists only the open tickets. |
| 13 | 16.55 | 19.54 | `caption` |  |  | The heading counts what the filter left. |
| 14 | 19.54 | 19.86 | `spotlight` | `#queue-heading` |  | The heading counts what the filter left. |
| 15 | 19.86 | 21.39 | `hold` |  |  | The heading counts what the filter left. |
| 16 | 21.39 | 21.96 | `spotlight` |  |  | The heading counts what the filter left. |
| 17 | 21.96 | 23.95 | `caption` |  |  | Waiting lists the rest. |
| 18 | 23.95 | 24.87 | `click` | `button[data-status='waiting']` |  | Waiting lists the rest. |
| 19 | 24.87 | 26.39 | `hold` |  |  | Waiting lists the rest. |
| 20 | 26.39 | 26.44 | `shot` | `03-waiting` |  | Waiting lists the rest. |
| 21 | 26.44 | 29.77 | `caption` |  |  | Escalated matches nothing, and the queue says so. |
| 22 | 29.77 | 30.74 | `click` | `button[data-status='escalated']` |  | Escalated matches nothing, and the queue says so. |
| 23 | 30.74 | 32.24 | `hold` |  |  | Escalated matches nothing, and the queue says so. |
| 24 | 32.24 | 32.29 | `shot` | `04-escalated` |  | Escalated matches nothing, and the queue says so. |
| 25 | 32.29 | 34.94 | `caption` |  |  | All brings the whole queue back. |
| 26 | 34.94 | 35.85 | `click` | `button[data-status='all']` |  | All brings the whole queue back. |
| 27 | 35.85 | 37.36 | `hold` |  |  | All brings the whole queue back. |
| 28 | 37.36 | 37.42 | `shot` | `05-all` |  | All brings the whole queue back. |
| 29 | 37.42 | 37.73 | `caption` |  |  |  |
| 30 | 38.24 | 41.65 | `interlude` | `card` |  | The same filter, on the command line. |
| 31 | 41.65 | 44.30 | `caption` |  |  | The CLI reads the same queue. |
| 32 | 44.30 | 45.13 | `run` | `./tickets list` | 0 | The CLI reads the same queue. |
| 33 | 45.13 | 45.34 | `wait_for_prompt` |  |  | The CLI reads the same queue. |
| 34 | 45.34 | 46.84 | `hold` |  |  | The CLI reads the same queue. |
| 35 | 46.84 | 46.92 | `shot` | `06-cli-list` |  | The CLI reads the same queue. |
| 36 | 46.92 | 49.91 | `caption` |  |  | --status open narrows it the same way. |
| 37 | 49.91 | 51.38 | `run` | `./tickets list --status open` | 0 | --status open narrows it the same way. |
| 38 | 51.38 | 51.59 | `wait_for_prompt` |  |  | --status open narrows it the same way. |
| 39 | 51.59 | 53.09 | `hold` |  |  | --status open narrows it the same way. |
| 40 | 53.09 | 53.17 | `shot` | `07-cli-open` |  | --status open narrows it the same way. |
| 41 | 53.17 | 55.47 | `caption` |  |  | An unknown status is refused. |
| 42 | 55.47 | 57.04 | `run` | `./tickets list --status frozen` | 2 | An unknown status is refused. |
| 43 | 57.04 | 57.24 | `wait_for_prompt` |  |  | An unknown status is refused. |
| 44 | 57.24 | 58.74 | `hold` |  |  | An unknown status is refused. |
| 45 | 58.74 | 58.82 | `shot` | `08-cli-unknown` |  | An unknown status is refused. |
| 46 | 58.82 | 59.13 | `caption` |  |  |  |

## Issues

1 recorded while this take ran — console errors, failed requests, and non-zero exit codes, each attributed to the beat it fired during. A demo can look perfect and still be a recording of a broken app.

- **nonzero_exit** — beat 42 (`run`) at 56.87s: './tickets list --status frozen' exited 2


## Stills

### 01-queue — 5.87s

> The support queue, every ticket the team holds.

![01-queue](images/01-queue.png)

### 02-open — 16.49s

> Open lists only the open tickets.

![02-open](images/02-open.png)

### 03-waiting — 26.39s

> Waiting lists the rest.

![03-waiting](images/03-waiting.png)

### 04-escalated — 32.24s

> Escalated matches nothing, and the queue says so.

![04-escalated](images/04-escalated.png)

### 05-all — 37.36s

> All brings the whole queue back.

![05-all](images/05-all.png)

### 06-cli-list — 46.84s

> The CLI reads the same queue.

![06-cli-list](images/06-cli-list.png)

### 07-cli-open — 53.09s

> --status open narrows it the same way.

![07-cli-open](images/07-cli-open.png)

### 08-cli-unknown — 58.74s

> An unknown status is refused.

![08-cli-unknown](images/08-cli-unknown.png)
