"""Synthesizing a narration line, and caching it by content.

This is the whole of the recorder's speech path that does not need a browser:
given a line of text and a voice, produce an mp3 and remember it. What a
`_DemoBase` does with the clip — waiting one line out before starting the next,
mixing it onto the video at the offset the line appeared — stays in `core`,
because it needs the recorder's clock and its idle loop.

It lives here rather than in `core` for the reason the recorders are lazy
(#139): `core` imports Playwright at module scope, and none of this does. A
cache key is a function of three strings; it should not cost a browser to check
that it is the right one.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from .timeline import capture_clock_shift

# How long to wait between retries, and how many. Free-tier keys get 429
# "system_busy" under load, and any network can blip mid-recording — losing a
# take to either is worse than the delay.
TTS_ATTEMPTS = 5
TTS_RETRY_CODES = (429, 500, 502, 503)
# Characters of the sha256 kept. 20 hex characters is 80 bits: the cache is
# per-take and holds tens of lines, so this is collision-free by an enormous
# margin and short enough to read in a directory listing.
TTS_KEY_CHARS = 20

# What separates the three fields before hashing.
#
# **It must be a character that cannot occur in a voice or model id**, and that
# is the entire reason the concatenation is unambiguous. Voice and model ids
# are alphanumeric (`EXAVITQu4vr4xnSDxMaL`, `eleven_multilingual_v2`), so any
# non-alphanumeric character does. The *text* may contain it freely: it is the
# last field, so nothing follows it that a stray separator could be mistaken
# for.
#
# A separator an id could hold would make two different takes hash the same
# string, and the symptom would be a take replaying another voice's audio with
# correct timing — the failure this whole module is graded on.
TTS_KEY_SEP = "|"

# Where a cache miss goes. A module constant rather than a literal buried in
# `tts_clip` so a caller that must not reach the real service can say so.
#
# `tests/smoke`'s narration take points this at a closed local port before it
# records. Every line it narrates is a cache hit, so nothing should be
# requested at all — and pinning the endpoint is what turns "should" into
# "cannot": a key the recorder computes differently from the harness fails in
# milliseconds against a dead socket, instead of putting a fabricated
# credential on the wire to a third party to find out.
TTS_API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"


# -- putting a clip where its line is, in the video ---------------------------
#
# A line is logged at `time.monotonic() - _t0`, and the video it is mixed into
# is stamped with the host's *wall* clock — Chromium's screencast is, and the
# encode inherits it. So on a host that steps that clock the two part company by
# the size of the step, and `adelay` at the raw offset leaves the voice where it
# was while the picture moved: issue #18's second comment measured **+0.70 s of
# lag on all three lines** of a take that stalled in its run-up, against +0.11
# to +0.14 s in a clean one, and that 0.70 s is a wall-clock step. Unlike every
# other consequence of the two clocks, this one is *audible* — the viewer hears
# the narration drift off the caption it belongs to (issue #226).
#
# The recorder measures those steps for the life of the capture, so the fix is
# arithmetic and not estimation: mix at `t + (the steps recorded before t)`.
#
# Two properties of that rule are worth stating because both were paid for:
#
#   * **it is indexed by the instant being converted**, which here is each
#     line's own offset. The same rule read once per beat left every instant in
#     a beat's first half uncorrected — roughly half of a take's wall time —
#     and that was the blocking defect in the review-frame version of this
#     (#253);
#   * **`measured` is read before `steps`.** A record that could not watch the
#     clock reports an empty step list too, so a reader that only looked at
#     `steps` cannot tell "the clock held still" from "nobody knows". Zero is
#     still the number applied — there is no other — but it is a fallback and
#     not a correction, and `mix_plan` hands its caller the state to say so.
#
# And one property of the *step* that the arithmetic above got wrong until
# issue #256: a backward step of Δ does not slide the video, it deletes a
# Δ-wide window of wall time from the file. A line spoken inside that window
# was spoken over a moment `media` does not contain, and `t + (the steps before
# t)` puts its clip up to a whole step early — over content that predates the
# step, which for a narration line means the caption before the one it is
# about. `capture_clock_shift` clamps such an instant to the last moment the
# file has and says how much it swallowed; `no_video` carries that onto the
# line, for the same reason `clamped` does, and `timeline.md` states it. The
# clip is still mixed, because the alternative is dropping a spoken line out
# of the audio over a defect of the host's clock.


def mix_plan(
    offsets: Sequence[float], record: object
) -> tuple[list[dict], dict]:
    """Where each narration line goes in the encoded media. -> (lines, state)

    `offsets` are the beat-log instants the lines appeared at, in the order
    they were spoken; `record` is the take's `capture_clock`. Each returned
    line carries `t` (what was logged) and `at` (where that instant is in the
    video, and what the mix delays the clip by). `state` is the three-state
    clock record — see the section above; a caller that drops it publishes a
    demo whose audio placement cannot be told from a guess.

    `at` never goes below zero, and **a line that hit that floor says so**. A
    backward step larger than a line's own offset puts that instant before this
    capture's first frame — the wall time it occupied is genuinely not in the
    file — and `adelay` has no way to express a negative delay, so the clip
    starts at the beginning of this capture's own audio. That line's `at` is
    then *not* its `t` plus the steps before it, which is what every other
    line's is and what the artifact says about all of them; `clamped` carries
    the seconds of correction that were swallowed, and is absent from the lines
    that got the whole of theirs — including the ones whose shortfall rounds
    away to nothing.

    **Zero here is this capture's zero, not the demo's.** `stitch()` moves a
    part's lines onto the joined clock by that part's `offset`, and `clamped`
    travels with them, so a clamped line of part two has an `at` of that
    part's offset. Anything printing prose about it has to say "the start of
    its own capture" rather than "0.0".

    A line whose instant a backward step deleted from the file carries
    `no_video` instead — also **only when it has one** — being the seconds
    between where the clip was put and where the video starts again. Its `at`
    is the last moment the file has before the gap rather than `t` plus the
    steps before it, for the reason the section above gives: there is no such
    moment in the video, and the placement every other line gets would put
    this clip a whole step early (issue #256).
    """
    place, state = capture_clock_shift(record)
    lines = []
    for off in offsets:
        placed = place(off)
        want = placed.at
        # Rounded *before* the test, not after. A `want` of −5e-5 is a
        # truncation of nothing at the precision this record is written at,
        # and a `clamped: 0.0` beside it would be a line claiming its `at` is
        # not `t` plus the steps before it when it is. Same for `no_video`.
        clamped = round(-want, 3) if want < 0 else 0.0
        line = {"t": round(float(off), 3), "at": round(max(0.0, want), 3)}
        if clamped:
            line["clamped"] = clamped
        if round(placed.lost, 3):
            line["no_video"] = round(placed.lost, 3)
        lines.append(line)
    return lines, state


def _tts_key(text: str, voice_id: str, model_id: str) -> str:
    """The cache filename stem for one line, in one voice, from one model.

    **All three inputs are in the key, and that is the contract.** Switching
    voice or model has to re-generate rather than replay the old audio — a
    cache that keyed on text alone would hand a take recorded in one voice the
    clips of another, and nothing downstream would notice: the mp4 would come
    out with a full, correctly-timed audio track in the wrong voice.
    """
    joined = TTS_KEY_SEP.join((voice_id, model_id, text))
    return hashlib.sha256(joined.encode()).hexdigest()[:TTS_KEY_CHARS]


def tts_clip(
    text: str,
    cache_dir: Path,
    voice_id: str,
    model_id: str,
    api_key: str,
) -> Path:
    """Synthesize one narration line with ElevenLabs, cached by content.

    Cached clips make retakes free — the API is only hit for new lines, and
    `api_key` is not read at all on a hit. That is what lets `tests/smoke`
    grade the pacing and the audio mix without a key or a network: seed the
    cache with clips of known duration and every line is a hit.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    clip = cache_dir / f"{_tts_key(text, voice_id, model_id)}.mp3"
    if clip.exists():
        return clip
    req = urllib.request.Request(
        f"{TTS_API_BASE}/{voice_id}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": model_id}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    for attempt in range(TTS_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                partial = clip.with_suffix(".part")
                partial.write_bytes(resp.read())
                partial.rename(clip)  # atomic: no truncated clip is cached
            return clip
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code in TTS_RETRY_CODES and attempt < TTS_ATTEMPTS - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs TTS failed ({e.code}): {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < TTS_ATTEMPTS - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e
    raise AssertionError("unreachable")
