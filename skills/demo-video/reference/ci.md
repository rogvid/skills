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
pointing a storyboard at a host you have not recorded against before — it is
the same verdict the recorder will reach, without paying for a browser first.
`--allow-private` mirrors `allow-private-network-target`; there is no
`--allow-public`, and adding one to the workflow would not help, because the
recorder refuses independently.
