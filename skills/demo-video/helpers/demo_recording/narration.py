"""Spoken captions via ElevenLabs, cached on disk by text and voice."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"  # "Sarah", premade, works on free-tier keys
DEFAULT_MODEL = "eleven_multilingual_v2"
STABILITY = 0.75  # steadier pacing from line to line


def clip(text: str, cache: Path, api_key: str, voice: str, model: str) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{voice}|{model}|{STABILITY}|{text}".encode()).hexdigest()[:20]
    path = cache / f"{key}.mp3"
    if path.exists():
        return path
    request = urllib.request.Request(
        f"{API}/{voice}?output_format=mp3_44100_128",
        data=json.dumps(
            {
                "text": text,
                "model_id": model,
                "voice_settings": {"stability": STABILITY, "similarity_boost": 0.75},
            }
        ).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                part = path.with_suffix(".part")
                part.write_bytes(response.read())
                part.rename(path)
            return path
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(
                f"ElevenLabs TTS failed ({e.code}): {e.read().decode()[:200]}"
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e
    raise AssertionError("unreachable")


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())
