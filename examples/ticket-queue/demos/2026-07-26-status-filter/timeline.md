# Demo timeline

`demo.mp4` · mixed · 61.2s · 48 beats

Written by the demo-video recorder when it stitched the segments below — do not edit it by hand, re-stitch instead.

Stitched from 2 segments, in order: `part1` (0.00–37.76s), `part2` (37.76–61.16s). Beat times below are on the stitched video's clock.

| # | start | end | verb | target | exit | caption |
|---:|---:|---:|---|---|---:|---|
| 0 | 0.44 | 1.01 | `goto` | `/` |  |  |
| 1 | 1.01 | 1.04 | `wait_for` | `.ticket` |  |  |
| 2 | 1.04 | 4.39 | `caption` |  |  | The support queue, every ticket the team holds. |
| 3 | 4.39 | 5.92 | `hold` |  |  | The support queue, every ticket the team holds. |
| 4 | 5.92 | 5.96 | `shot` | `01-queue` |  | The support queue, every ticket the team holds. |
| 5 | 5.96 | 8.96 | `caption` |  |  | A status filter sits above the list. |
| 6 | 8.96 | 9.31 | `spotlight` | `#status-filter` |  | A status filter sits above the list. |
| 7 | 9.31 | 10.84 | `hold` |  |  | A status filter sits above the list. |
| 8 | 10.84 | 11.18 | `spotlight` |  |  | A status filter sits above the list. |
| 9 | 11.18 | 13.83 | `caption` |  |  | Open lists only the open tickets. |
| 10 | 13.83 | 14.74 | `click` | `button[data-status='open']` |  | Open lists only the open tickets. |
| 11 | 14.74 | 16.26 | `hold` |  |  | Open lists only the open tickets. |
| 12 | 16.26 | 16.30 | `shot` | `02-open` |  | Open lists only the open tickets. |
| 13 | 16.30 | 19.31 | `caption` |  |  | The heading counts what the filter left. |
| 14 | 19.31 | 19.65 | `spotlight` | `#queue-heading` |  | The heading counts what the filter left. |
| 15 | 19.65 | 21.17 | `hold` |  |  | The heading counts what the filter left. |
| 16 | 21.17 | 21.49 | `spotlight` |  |  | The heading counts what the filter left. |
| 17 | 21.49 | 23.48 | `caption` |  |  | Waiting lists the rest. |
| 18 | 23.48 | 24.43 | `click` | `button[data-status='waiting']` |  | Waiting lists the rest. |
| 19 | 24.43 | 25.94 | `hold` |  |  | Waiting lists the rest. |
| 20 | 25.94 | 25.98 | `shot` | `03-waiting` |  | Waiting lists the rest. |
| 21 | 25.98 | 28.97 | `caption` |  |  | Escalated matches nothing. The list is empty. |
| 22 | 28.97 | 29.89 | `click` | `button[data-status='escalated']` |  | Escalated matches nothing. The list is empty. |
| 23 | 29.89 | 31.42 | `hold` |  |  | Escalated matches nothing. The list is empty. |
| 24 | 31.42 | 31.46 | `shot` | `04-escalated` |  | Escalated matches nothing. The list is empty. |
| 25 | 31.46 | 34.11 | `caption` |  |  | All brings the whole queue back. |
| 26 | 34.11 | 35.05 | `click` | `button[data-status='all']` |  | All brings the whole queue back. |
| 27 | 35.05 | 36.56 | `hold` |  |  | All brings the whole queue back. |
| 28 | 36.56 | 36.60 | `shot` | `05-all` |  | All brings the whole queue back. |
| 29 | 36.60 | 36.91 | `caption` |  |  |  |
| 30 | 38.05 | 40.86 | `interlude` | `card` |  | The same filter, on the command line. |
| 31 | 40.86 | 41.47 | `interlude` | `card` |  |  |
| 32 | 41.47 | 44.12 | `caption` |  |  | The CLI reads the same queue. |
| 33 | 44.12 | 44.97 | `run` | `./tickets list` | 0 | The CLI reads the same queue. |
| 34 | 44.97 | 45.18 | `wait_for_prompt` |  |  | The CLI reads the same queue. |
| 35 | 45.18 | 46.69 | `hold` |  |  | The CLI reads the same queue. |
| 36 | 46.69 | 46.76 | `shot` | `06-cli-list` |  | The CLI reads the same queue. |
| 37 | 46.76 | 49.74 | `caption` |  |  | --status open narrows it the same way. |
| 38 | 49.74 | 51.25 | `run` | `./tickets list --status open` | 0 | --status open narrows it the same way. |
| 39 | 51.25 | 51.46 | `wait_for_prompt` |  |  | --status open narrows it the same way. |
| 40 | 51.46 | 52.97 | `hold` |  |  | --status open narrows it the same way. |
| 41 | 52.97 | 53.05 | `shot` | `07-cli-open` |  | --status open narrows it the same way. |
| 42 | 53.05 | 55.36 | `caption` |  |  | An unknown status is refused. |
| 43 | 55.36 | 56.93 | `run` | `./tickets list --status frozen` | 2 | An unknown status is refused. |
| 44 | 56.93 | 57.15 | `wait_for_prompt` |  |  | An unknown status is refused. |
| 45 | 57.15 | 58.66 | `hold` |  |  | An unknown status is refused. |
| 46 | 58.66 | 58.75 | `shot` | `08-cli-unknown` |  | An unknown status is refused. |
| 47 | 58.75 | 59.06 | `caption` |  |  |  |

## Issues

1 recorded while this take ran — console errors, failed requests, and non-zero exit codes, each attributed to the beat it fired during. A demo can look perfect and still be a recording of a broken app.

- **nonzero_exit** — beat 43 (`run`) at 56.77s: './tickets list --status frozen' exited 2


## Stills

### 01-queue — 5.92s

> The support queue, every ticket the team holds.

![01-queue](images/01-queue.png)

### 02-open — 16.26s

> Open lists only the open tickets.

![02-open](images/02-open.png)

### 03-waiting — 25.94s

> Waiting lists the rest.

![03-waiting](images/03-waiting.png)

### 04-escalated — 31.42s

> Escalated matches nothing. The list is empty.

![04-escalated](images/04-escalated.png)

### 05-all — 36.56s

> All brings the whole queue back.

![05-all](images/05-all.png)

### 06-cli-list — 46.69s

> The CLI reads the same queue.

![06-cli-list](images/06-cli-list.png)

### 07-cli-open — 52.97s

> --status open narrows it the same way.

![07-cli-open](images/07-cli-open.png)

### 08-cli-unknown — 58.66s

> An unknown status is refused.

![08-cli-unknown](images/08-cli-unknown.png)
