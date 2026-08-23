"""Turning a take's committed stills into links, for whatever renders them.

`images/*.png` are the only part of a take that has a URL at all: `demo.mp4` is
not committed and `frames/` is gitignored. So every renderer that wants to put
a picture in front of a person — `scripts/demo-grade pr-block`, and
`scripts/demo-shots` (#373) — needs the same five facts: which beat wrote which
still, what caption was on screen, whether the path is one this take may link,
which commit holds it, and what the remote calls the repository.

**Nothing here raises, and that is the point of the split.** The two callers
want opposite things from a link that cannot be built. `pr-block` refuses: it
renders a graded verdict, and a verdict whose evidence is a broken image is
worse than no block. `demo-shots` falls back to a relative path: it is meant to
be run in a session against a working tree, where an uncommitted take is the
normal case and refusing would make the command useless exactly when it is most
wanted. One implementation of the facts, two policies over them.

Every function returns the fact or `None`. A caller that wants a refusal writes
one, naming the thing it could not find.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote

#: The one host these functions can build an image URL for. A remote elsewhere
#: yields None rather than a guessed URL that resolves nowhere.
GITHUB_REMOTE = re.compile(
    r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$"
)


def git(demo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git inside the demo directory. Never raises; check `returncode`."""
    return subprocess.run(
        ["git", "-C", str(demo), *args], capture_output=True, text=True
    )


def git_fact(demo: Path, *args: str) -> str | None:
    """One stripped line of git output, or None if the command failed.

    None covers "not a git repository", "no origin remote" and "this ref does
    not exist" alike, because to every caller here they are the same answer:
    there is no link to build.
    """
    done = git(demo, *args)
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def github_repo(remote: str | None) -> str | None:
    """`owner/repo` out of an origin remote URL, or None if it is not GitHub."""
    if not remote:
        return None
    found = GITHUB_REMOTE.search(remote.strip())
    if not found:
        return None
    return f"{found.group('owner')}/{found.group('repo')}"


def take_relative(still: str) -> str | None:
    """`still` as a plain path inside the take, or None.

    **This is a guard, not a tidy-up.** `timeline.json` is a committed file, so
    its `still` value is editable in a pull request, and both callers paste it
    into a URL and into a `git cat-file` argument. `../../elsewhere.png` is the
    shape to refuse: it can exist on disk and would publish a picture that has
    nothing to do with this take, under this take's caption.

    A normalised relative path is the whole allowance. An absolute path, a
    backslash (a Windows path, or an attempt to smuggle a separator past the
    split) and any `..` component are refused; `./` and empty components are
    dropped, because they mean nothing and a caller comparing strings should
    not have to care.
    """
    if still.startswith("/") or "\\" in still:
        return None
    parts = [p for p in still.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def raw_url(repo: str, sha: str, path: str) -> str:
    """The raw.githubusercontent.com URL for a blob at one commit.

    The commit, never a branch name: a branch moves, and a picture embedded in
    a pull-request description has to keep showing what it showed when it was
    pasted.
    """
    return f"https://raw.githubusercontent.com/{repo}/{quote(sha)}/{quote(path)}"


def beat_stills(timeline: dict) -> dict[int, str]:
    """Which committed still each beat wrote, by beat index, from the beat log."""
    out: dict[int, str] = {}
    for beat in timeline.get("beats") or []:
        index = beat.get("index")
        still = beat.get("still")
        if isinstance(index, int) and isinstance(still, str) and still.strip():
            out[index] = still.strip()
    return out


def beat_captions(timeline: dict) -> dict[int, str]:
    """Each beat's storyboard caption, by beat index, from the beat log.

    The caption is the one sentence about a beat written for a viewer rather
    than for the recorder, so it is what a still is labelled with. A beat index
    is recorder bookkeeping: the third live read of #337 asked what "beat 20"
    was even for, and there was no answer a reviewer could use.
    """
    out: dict[int, str] = {}
    for beat in timeline.get("beats") or []:
        index = beat.get("index")
        caption = beat.get("caption")
        if isinstance(index, int) and isinstance(caption, str) and caption.strip():
            out[index] = caption.strip()
    return out
