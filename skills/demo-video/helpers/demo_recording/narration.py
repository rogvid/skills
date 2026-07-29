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
from pathlib import Path

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
