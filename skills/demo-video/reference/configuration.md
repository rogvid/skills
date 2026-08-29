<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Every recorder parameter

> Read when a take needs something the short table in SKILL.md does not name — a window size or title, an opening or closing card, caption placement, colours, a pinned clock or locale, the terminal's shell/prompt/font, or the narration voice.

Every `Recorder` and `TerminalRecorder` parameter resolves **explicit
parameter → `DEMO_VIDEO_*` env var → built-in default**, so projects can put
defaults in their `.env` (load with `set -a; source .env; set +a`) and
storyboards stay clean.

**The Sets column names the parameter behind each variable** — for three it is
not the variable lowercased, so do not infer it.

## The whole table

| Variable | Sets (parameter — what it does) | Default |
|---|---|---|
| `DEMO_VIDEO_OUT_DIR` | `out_dir` — where demo files land | — (required one way or the other) |
| `DEMO_VIDEO_BASE_URL` | `base_url` — app under demo. Classified before the browser opens; a public host is refused | `http://localhost:8000` |
| `DEMO_VIDEO_ALLOW_PRIVATE` | `allow_private` — permit a private/internal target (`1`/`0`). There is no equivalent for a public one | off |
| `DEMO_VIDEO_ACCENT_RGB` | `accent_rgb` — cursor/spotlight color, `"0,127,255"` | azure |
| `DEMO_VIDEO_PACE` | `pace` — multiplier over the holds the recorder computes (caption read time; the defaults of `hold()`, `interlude()`, `criterion()`). Durations the storyboard writes itself are never touched. See **Pacing and perception** in SKILL.md | `1.0` |
| `DEMO_VIDEO_WINDOW_TITLE` | `window_title` — the wrapper window's title bar. Web default: the app's host; terminal default: `terminal_title` | — |
| `DEMO_VIDEO_INTRO` | `intro` — opt-in opening title card over the wrapper (web takes), taken down by the first `goto()`. Held ~2.8 s (scaled by `pace`), or the whole spoken line when narration is on. Terminal takes already have this as `TerminalRecorder(interlude=…)` | off |
| `DEMO_VIDEO_TERMINAL_TITLE` | `terminal_title` — web `terminal()` card title | `terminal` |
| `DEMO_VIDEO_TERMINAL_PROMPT` | `terminal_prompt` — prompt string: web card, and `TerminalRecorder`'s shell PS1 | `$ ` (web card); `❯ ` (`TerminalRecorder`) |
| `DEMO_VIDEO_TERMINAL_SHELL` | `shell` — shell `TerminalRecorder` launches | `/bin/bash` |
| `DEMO_VIDEO_TERMINAL_FONT_SIZE` | `font_size` — `TerminalRecorder` font px | `15` |
| `DEMO_VIDEO_VIEWPORT` | `viewport` — recording size, `"1920x1080"` | 1920×1080 (`quick` preset: 1280×720) |
| `DEMO_VIDEO_WINDOW_SCALE` | `window_scale` — framed-window size relative to the viewport: a fraction of it for width/height, in `(0, 1]`. A single float or `"width,height"` | 0.95 width; 0.9 height (0.85 with the reserved band — the taller default plus the band cannot fit a viewport) |
| `DEMO_VIDEO_CAPTION_OVERLAY` | `caption_overlay` — caption as a floating pill over the app's bottom edge (`1`), or a reserved band below the app rect (`0`). **Known limit of the overlay:** a camera push-in crops the frame around the spotlit element and can shave the pill — fade it (`caption("")`) before spotlighting, or turn the band back on | **on** |
| `DEMO_VIDEO_PRESET` | `preset` — quality preset, `"high"` or `"quick"`. What each one bundles is under **Quality presets** in SKILL.md | `high` |
| `DEMO_VIDEO_DETERMINISTIC` | `deterministic` — freeze the page clock and flatten motion (`1`/`0`) — **read [determinism.md](determinism.md) first** | **off** |
| `DEMO_VIDEO_CLOCK` | `clock` — the instant the page's clock is frozen at, when it is (ISO 8601) | `2025-01-01T09:00:00Z` |
| `DEMO_VIDEO_TIMEZONE` | `timezone_id` — browser timezone, always applied | `UTC` |
| `DEMO_VIDEO_LOCALE` | `locale` — browser locale, always applied | `en-US` |
| `DEMO_VIDEO_SPEECH` | `speech` — force narration on/off (`1`/`0`). **`speech=False` records silently even with a key set**; with no key it is off already, and forcing it *on* without one refuses the take | auto by API key |
| `DEMO_VIDEO_STILLS_ONLY` | `stills_only` — run the storyboard for its `shot()` pictures and record no video (`1`/`0`). Pacing zeroed, narration off; writes no mp4 and no `frames/`, and `timeline.json` says `mode: "stills"` so nothing reads it as a take — [stills.md](stills.md) | off |
| `DEMO_VIDEO_STRICT` | `strict` — fail the take on console errors / non-zero exits (`1`/`0`) | off |
| `DEMO_VIDEO_EVIDENCE` | `evidence` — write `evidence/beat-NN.json` per beat (`1`/`0`) — see [review.md](review.md) | **on** |
| `DEMO_VIDEO_VOICE_ID` | `voice_id` — ElevenLabs voice | Sarah (premade) |
| `DEMO_VIDEO_SPEECH_MODEL` | `speech_model` — ElevenLabs model | `eleven_multilingual_v2` |
| `DEMO_VIDEO_SPEECH_STABILITY` | `speech_stability` — voice stability pinned on every line, for one consistent speaking rate (without it: 2.1–3.3 words/s across one take) | `0.75` |
| `DEMO_VIDEO_OUTRO` | `outro` — opt-in closing card, the intro's mirror: voiced with speech on, left up as the take's last frame. Web takes; `TerminalRecorder` refuses it | off |
| `DEMO_VIDEO_SKILL_DIR` | *no parameter* — where storyboards find this skill | the constant baked into each storyboard |
| `ELEVENLABS_API_KEY` | *no parameter* — enables speech narration | off |

## Which recorder each applies to

`DEMO_VIDEO_BASE_URL` applies to the web `Recorder` only; the terminal `*`
variables to `TerminalRecorder`. All the rest apply to both.

The parameters with **no** env var are per-storyboard by nature: `segment`,
`criteria` and `ticket` on both recorders, plus `TerminalRecorder`'s
`interlude`, `interlude_hold` and `type_delay_ms`.
