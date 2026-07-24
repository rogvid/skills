---
name: script-conventions
description: The house convention for shipping executable scripts inside a skill — PEP 723 uv scripts, the shared ensure.sh bootstrap, and how a skill should tell an agent to invoke them. Consult this whenever you are authoring, editing, reviewing, or debugging a skill that includes anything runnable (a Python script, a CLI, a binary), whenever you are about to add a dependency to a skill, and whenever a skill's script fails to start. Also use it when the user asks how skills should handle setup, prerequisites, or installation.
compatibility: Unix only (Linux/macOS). First run of a script needs network access to PyPI to resolve dependencies.
---

# Script conventions

Skills in this repo do not ship `requirements.txt`, virtualenvs, or setup markers.
Every executable is a self-contained [PEP 723](https://peps.python.org/pep-0723/)
script run by `uv`, and every skill that ships one also ships `ensure.sh`.

## Layout

```
<skill>/
├── SKILL.md
├── ensure.sh          # copied verbatim from script-conventions/templates/
├── mise.toml          # optional, only for non-Python tooling
└── scripts/
    └── mytool         # executable, no extension, PEP 723 shebang
```

## Writing a script

Start every script with the uv shebang and an inline dependency block:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "rich"]
# ///
```

Rules that matter:

- **Name scripts without a `.py` extension.** They are commands, not modules.
  `--script` in the shebang is what makes this work: uv otherwise uses the
  extension to tell a local script path from the name of a tool to look up.
- **Keep dependencies few and pinned with lower bounds.** First invocation in a
  fresh environment pays the resolve; everything after hits `~/.cache/uv`. In
  sandboxes whose filesystem resets between sessions, that cost recurs once per
  session, so a fat dependency list is a recurring tax.
- **`uv lock --script scripts/mytool`** if you need reproducibility. It writes a
  `.lock` next to the script that later runs reuse.
- **One script per job.** Deps are per-file, so splitting is free — no shared
  environment to keep consistent.

## Wiring it into the skill's SKILL.md

Paste the block from `templates/skill-boilerplate.md` into the consuming skill.
It does two things, both of which are load-bearing:

1. Tells the agent to run `ensure.sh` once before the first script invocation.
2. States that paths are relative to the skill's own directory. Agents start in
   `~` or a project directory, never in the skill directory, so a bare
   `./scripts/mytool` will not resolve and the agent will start guessing paths.

## What ensure.sh handles

Copy it verbatim; it needs no per-skill edits. It finds or installs `uv`
(preferring `pip install uv`, since sandboxes allowlist PyPI far more often than
`astral.sh`), verifies uv is reachable **on PATH** rather than merely present on
disk, restores exec bits that packaging stripped, and runs `mise install` if the
skill has a `mise.toml`. It is idempotent and returns in ~15ms once satisfied.

The PATH check is the one worth understanding: the shebang resolves `uv` through
PATH in a non-interactive shell. A uv in `~/.local/bin` that isn't on that PATH
produces `env: 'uv': No such file or directory`, and an agent seeing that will
usually "fix" it by running `python3 scripts/mytool` — which then fails on
missing imports and sends it down a debugging path that has nothing to do with
the real problem. `ensure.sh` fails early instead, printing the `export PATH=...`
that resolves it.

## Non-Python tooling

Reach for `mise` only when the skill needs a pinned binary that isn't a Python
package. Add a `mise.toml` to the skill directory; `ensure.sh` picks it up.

Invoke tools as `(cd <skill-dir> && mise exec -- <cmd>)`. Do **not** use
`mise activate` — it installs shell hooks that don't exist in the one-shot
non-interactive shells agents spawn, so it silently no-ops and you get the system
binary instead of the pinned one.

## Reviewing a skill against this convention

- Does every executable have the `env -S uv run --script` shebang?
- Is `ensure.sh` present and byte-identical to the template?
- Does SKILL.md mention `ensure.sh` *before* the first script invocation?
- Are script paths in SKILL.md expressed relative to the skill directory, with
  that fact stated explicitly?
- Any stray `requirements.txt`, `pip install` line, `.venv/`, or setup-marker
  file? Delete it — uv's cache already is the once-only mechanism.
