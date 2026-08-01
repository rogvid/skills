# Demo timeline

`demo.mp4` · mixed · 62.8s · 48 beats

Written by the demo-video recorder when it stitched the segments below — do not edit it by hand, re-stitch instead.

Stitched from 2 segments, in order: `part1` (0.00–38.56s), `part2` (38.56–62.76s). Beat times below are on the stitched video's clock.

| # | start | end | verb | target | exit | caption |
|---:|---:|---:|---|---|---:|---|
| 0 | 0.44 | 0.99 | `goto` | `/` |  |  |
| 1 | 0.99 | 1.02 | `wait_for` | `.ticket` |  |  |
| 2 | 1.02 | 4.35 | `caption` |  |  | The support queue, every ticket the team holds. |
| 3 | 4.35 | 5.86 | `hold` |  |  | The support queue, every ticket the team holds. |
| 4 | 5.86 | 5.92 | `shot` | `01-queue` |  | The support queue, every ticket the team holds. |
| 5 | 5.92 | 8.91 | `caption` |  |  | A status filter sits above the list. |
| 6 | 8.91 | 9.24 | `spotlight` | `#status-filter` |  | A status filter sits above the list. |
| 7 | 9.24 | 10.76 | `hold` |  |  | A status filter sits above the list. |
| 8 | 10.76 | 11.32 | `spotlight` |  |  | A status filter sits above the list. |
| 9 | 11.32 | 13.98 | `caption` |  |  | Open lists only the open tickets. |
| 10 | 13.98 | 14.90 | `click` | `button[data-status='open']` |  | Open lists only the open tickets. |
| 11 | 14.90 | 16.41 | `hold` |  |  | Open lists only the open tickets. |
| 12 | 16.41 | 16.46 | `shot` | `02-open` |  | Open lists only the open tickets. |
| 13 | 16.46 | 19.45 | `caption` |  |  | The heading counts what the filter left. |
| 14 | 19.45 | 19.78 | `spotlight` | `#queue-heading` |  | The heading counts what the filter left. |
| 15 | 19.78 | 21.30 | `hold` |  |  | The heading counts what the filter left. |
| 16 | 21.30 | 21.88 | `spotlight` |  |  | The heading counts what the filter left. |
| 17 | 21.88 | 23.86 | `caption` |  |  | Waiting lists the rest. |
| 18 | 23.86 | 24.80 | `click` | `button[data-status='waiting']` |  | Waiting lists the rest. |
| 19 | 24.80 | 26.31 | `hold` |  |  | Waiting lists the rest. |
| 20 | 26.31 | 26.37 | `shot` | `03-waiting` |  | Waiting lists the rest. |
| 21 | 26.37 | 29.72 | `caption` |  |  | Escalated matches nothing, and the queue says so. |
| 22 | 29.72 | 30.64 | `click` | `button[data-status='escalated']` |  | Escalated matches nothing, and the queue says so. |
| 23 | 30.64 | 32.16 | `hold` |  |  | Escalated matches nothing, and the queue says so. |
| 24 | 32.16 | 32.21 | `shot` | `04-escalated` |  | Escalated matches nothing, and the queue says so. |
| 25 | 32.21 | 34.86 | `caption` |  |  | All brings the whole queue back. |
| 26 | 34.86 | 35.80 | `click` | `button[data-status='all']` |  | All brings the whole queue back. |
| 27 | 35.80 | 37.32 | `hold` |  |  | All brings the whole queue back. |
| 28 | 37.32 | 37.38 | `shot` | `05-all` |  | All brings the whole queue back. |
| 29 | 37.38 | 37.69 | `caption` |  |  |  |
| 30 | 38.88 | 41.70 | `interlude` | `card` |  | The same filter, on the command line. |
| 31 | 41.70 | 42.31 | `interlude` | `card` |  |  |
| 32 | 42.31 | 44.95 | `caption` |  |  | The CLI reads the same queue. |
| 33 | 44.95 | 45.79 | `run` | `./tickets list` | 0 | The CLI reads the same queue. |
| 34 | 45.79 | 45.99 | `wait_for_prompt` |  |  | The CLI reads the same queue. |
| 35 | 45.99 | 47.50 | `hold` |  |  | The CLI reads the same queue. |
| 36 | 47.50 | 47.58 | `shot` | `06-cli-list` |  | The CLI reads the same queue. |
| 37 | 47.58 | 50.57 | `caption` |  |  | --status open narrows it the same way. |
| 38 | 50.57 | 52.06 | `run` | `./tickets list --status open` | 0 | --status open narrows it the same way. |
| 39 | 52.06 | 52.27 | `wait_for_prompt` |  |  | --status open narrows it the same way. |
| 40 | 52.27 | 53.78 | `hold` |  |  | --status open narrows it the same way. |
| 41 | 53.78 | 53.86 | `shot` | `07-cli-open` |  | --status open narrows it the same way. |
| 42 | 53.86 | 56.16 | `caption` |  |  | An unknown status is refused. |
| 43 | 56.16 | 57.74 | `run` | `./tickets list --status frozen` | 2 | An unknown status is refused. |
| 44 | 57.74 | 57.95 | `wait_for_prompt` |  |  | An unknown status is refused. |
| 45 | 57.95 | 59.45 | `hold` |  |  | An unknown status is refused. |
| 46 | 59.45 | 59.53 | `shot` | `08-cli-unknown` |  | An unknown status is refused. |
| 47 | 59.53 | 59.84 | `caption` |  |  |  |

## Issues

1 recorded while this take ran — console errors, failed requests, and non-zero exit codes, each attributed to the beat it fired during. A demo can look perfect and still be a recording of a broken app.

- **nonzero_exit** — beat 43 (`run`) at 57.58s: './tickets list --status frozen' exited 2


## Stills

### 01-queue — 5.86s

> The support queue, every ticket the team holds.

![01-queue](images/01-queue.png)

### 02-open — 16.41s

> Open lists only the open tickets.

![02-open](images/02-open.png)

### 03-waiting — 26.31s

> Waiting lists the rest.

![03-waiting](images/03-waiting.png)

### 04-escalated — 32.16s

> Escalated matches nothing, and the queue says so.

![04-escalated](images/04-escalated.png)

### 05-all — 37.32s

> All brings the whole queue back.

![05-all](images/05-all.png)

### 06-cli-list — 47.50s

> The CLI reads the same queue.

![06-cli-list](images/06-cli-list.png)

### 07-cli-open — 53.78s

> --status open narrows it the same way.

![07-cli-open](images/07-cli-open.png)

### 08-cli-unknown — 59.45s

> An unknown status is refused.

![08-cli-unknown](images/08-cli-unknown.png)
