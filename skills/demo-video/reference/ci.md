<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Recording on a pull request

> Read when wiring the reusable GitHub Actions workflow into a repository so demos record themselves on every branch.

## Recording on a pull request (CI)

Everything above is a storyboard being run by hand. The point of the skill is
that a reviewer never has to do that, so the same run belongs in the pipeline:
a reusable GitHub Actions workflow lives at
[`.github/workflows/demo-video.yml`](https://github.com/rogvid/skills/blob/main/.github/workflows/demo-video.yml)
in this repository. A consuming repo calls it in a few lines:

```yaml
# .github/workflows/demo.yml
on:
  pull_request:
    paths: ["app/**"]          # the coarse gate — see "What gates it" below

permissions:
  contents: read

concurrency:                    # ten pushes should cost one recording
  group: demo-${{ github.ref }}
  cancel-in-progress: true

jobs:
  demo:
    permissions:
      contents: read
      pull-requests: write      # required: the workflow writes one comment
    uses: rogvid/skills/.github/workflows/demo-video.yml@main
    with:
      working-directory: app
      app-command: npm run dev -- --port 3000
      base-url: http://127.0.0.1:3000
      demo-retention-days: 30
```

**What the pull request gets.** One comment, found by a hidden marker and
**rewritten** on every push rather than appended, carrying two things:

1. **The beat table as text** — every caption in order, straight out of
   `timeline.json`. No hosting, no expiry, no Actions access needed, and it
   renders on GitLab and Bitbucket too. This is the tier that survives the
   artifact expiring.
2. **A deep link to the artifact** — `…/actions/runs/<id>/artifacts/<id>`, so
   watching is one click and an unzip.

On a take recorded against a ticket — `Recorder(criteria={"AC-1": "…"})`, beats
tagged `ac="AC-1"` — a third thing sits **above** the beat table: the ticket's
clauses, with the ones **no beat claimed named first**, then a table of what
claimed the rest, at which beat, and which picture to open. That order is
deliberate. A rendering that opened with the covered half would be a coverage
claim whatever the sentence under it said, and the findings here that need no
judgement are the clause nobody even asserted and the clause nobody left a
picture of.

**The picture is a committed still, and clauses with none are named as a gap.**
`shot("01-search-box", ac="AC-1")` writes `images/01-search-box.png`, which is
a committed file and therefore the only piece of a take that has a URL: the
video and `frames/` are both inside artifact zips, so there is no timestamp to
deep-link and none is printed. The comment links each clause's still in your
repository at the head commit — under `working-directory`, which is where git
holds them — and a still the manifest names that this take did not publish is
reported as absent rather than linked: last week's picture under this week's
clause is worse than no picture at all.

A clause claimed only by `caption(text, ac=…)` has no still, so it hands a
reviewer nothing to open, and it is named above the table with the unclaimed
ones. The rule that follows: **tag a `shot()` for every clause, not only a
caption.** A caption tag says where to look; a still tag is the thing that can
be looked at. Neither is evidence that the clause was demonstrated — a picture
next to a clause is a frame the storyboard chose, and what it is a picture of
is still the reviewer's call.

**It says "claimed", never "demonstrated", and it says out loud that it graded
nothing.** An `ac=` tag is a string the storyboard author typed; whether the
frames show the clause is the reviewer's call, and the comment is written so it
cannot be mistaken for having made it. A claim points at a **beat index**
rather than a timestamp, because the coverage timestamps are on the recorder's
monotonic clock while the video is on the host's wall clock.

This skill's own repository holds that line in `tests/ci-unit`, with a word
sweep over the comment — not only
"demonstrated" but "verified", "shown", "proved", "passed", "met", a ticked box
and a checkmark. It sweeps the sentences the renderer *writes*: your clause
text and your captions are quoted through untouched, so a ticket that says "the
count is shown in the heading" prints as written and reddens nothing.

`demo.mp4`, `timeline.md`/`.json` and `images/` upload as the `demo-video`
artifact on an explicit `retention-days`; `evidence/` and `frames/` upload
separately on a short one (1–7 days, long enough to check a disputed finding
and not long enough to be an archive) and are **not** linked from the comment;
`failure/` uploads on the failure path only. A take that does not finish fails
the check *after* publishing all of it — the crashed take is exactly the one
somebody needs to look at.

**What gates it.** Recording is not a test job: it runs a browser and a
software encoder, and costs minutes. Two gates, doing different work:

- the caller's `paths:` filter, which decides whether a runner starts at all;
- the workflow's own discovery, which records a storyboard only when the
  branch changed something under the app that storyboard demonstrates — the
  directory containing its `demos/`. A branch that changed neither exits in
  seconds. Pass `storyboards:` explicitly to override.

A label was the alternative and was rejected: it needs a human action on every
branch, and when somebody forgets, the failure mode is *no video*.

**It refuses to record against production.** The mp4 is an outbound artifact —
it leaves the repository boundary the moment anyone downloads it, showing
whatever was on screen. So `base-url`, the caller's `extra-env`, and the
`http(s)://` literals inside each storyboard are all classified before the
browser opens: loopback always passes, a private or internal host needs
`allow-private-network-target: true`, and a **public host is refused with no
input that permits it**. That is a static check on configuration and source
text, not an egress control: a storyboard that computes its URL at run time is
invisible to it.

`allow-private-network-target` is passed to the recorders too, as
`DEMO_VIDEO_ALLOW_PRIVATE` on the `Record` step. It has to be: they classify
the target again at construction, so an input that widened only the pre-check
would pass the guard and then refuse the take one Chromium download later.
That is not hypothetical — it is what this workflow did until a check in this
repo's own suite was written, which now requires every fact the guard step
classifies on to reach the recorder from the same input.

**The classifier is the skill's, not the workflow's, and CI is not the only
place it runs.** The rules live in `helpers/demo_recording/target.py`, which
both recorders apply in `__init__` — so a storyboard run by hand refuses a
public `base_url` too, with no browser started and nothing recorded. The
workflow's pre-check is a command-line front door onto the same module:

```sh
bash <skill-dir>/ensure.sh          # once per session
<skill-dir>/scripts/demo-target-guard \
    --url "$DEMO_VIDEO_BASE_URL" --scan demos/x/record.py
```

It exits 2 and names the offending URL on stderr. Run it yourself before
pointing a storyboard at a host you have not recorded against before — given
the same two facts it reaches the same verdict the recorder will, without
paying for a browser first. `--allow-private` mirrors
`allow-private-network-target`; there is no `--allow-public`, and adding one
to the workflow would not help, because the recorder refuses independently.

**A guard run that checked nothing says so.** `--url ""` — a step passing a
variable nobody exported — prints `0 URL(s) checked — nothing was verified` and
exits 0, where it used to print `all loopback`. Exit 0 is deliberate: a terminal
storyboard has no URL, and a guard that failed those would be turned off. A
caller who knows a URL should have been there passes `--require`, which turns
the empty run into a refusal. The workflow does not, for the terminal-storyboard
reason above; a job whose target is always a URL should add it.

**A host that is a number is refused, not read as a service name.**
`http://3639549472/`, `http://0x8080808/` and `http://127.1/` are all IPv4
addresses to a browser (the first is 216.239.30.32), and they carry no dot, so
they used to classify as a container service name — which
`allow-private-network-target` permits. They are malformed now: write the
address as a dotted quad. The same applies to a host whose labels are separated
by U+3002, U+FF0E or U+FF61 rather than `.`, which Chromium reads as full stops.

**Two things the recorders check that the CLI does not**, so a clean guard run
is not a promise the take will start. `DEMO_VIDEO_BASE_URL` in the *recording*
environment is classified by both recorders even when the storyboard passes a
loopback `base_url` — deliberately, so a shell exporting production cannot be
overridden into silence — and a `TerminalRecorder` has no `base_url` at all,
so that variable is the only target it has. Pass `--url` whatever the take
will actually see, and unset the variable when it names something else.
