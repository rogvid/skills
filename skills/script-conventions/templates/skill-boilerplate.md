<!--
Paste the block below into a skill that ships scripts, just above the first
place a script gets invoked. Replace <tool> and the usage lines.
Keep the "paths are relative to this skill's directory" sentence — agents do not
start in the skill directory, and dropping it is the most common cause of a
first-invocation failure.
-->

## Setup

All paths below are relative to this skill's own directory — the directory this
SKILL.md was read from, not the current working directory.

Before invoking any script here for the first time in a session, run:

```bash
bash <skill-dir>/ensure.sh
```

It installs `uv` if missing and makes the scripts executable. It is idempotent
and returns in milliseconds when there is nothing to do, so re-run it rather
than trying to remember whether it has already run.

Then invoke tools directly:

```bash
<skill-dir>/scripts/<tool> --help
```

If a script fails with `env: 'uv': No such file or directory`, `ensure.sh` has
not been run, or uv is installed but not on PATH — re-run `ensure.sh` and follow
what it prints. Do not fall back to `python3 <tool>`; the dependencies live in
uv's environment, not the system interpreter's.
