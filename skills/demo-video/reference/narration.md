<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Speech narration

> Read before recording with `ELEVENLABS_API_KEY` set, or when a take should be spoken as well as captioned.

## Speech narration (optional)

When the `ELEVENLABS_API_KEY` environment variable is set (e.g.
`set -a; source .env; set +a` before recording), every `caption` and
`interlude` line is also spoken — synthesized with ElevenLabs and mixed
onto demo.mp4 at the moment the line appeared. No storyboard changes
needed; captions are the narration script.

- `Recorder(..., speech=True)` demands narration (fails fast if the key
  is missing); `speech=False` forces it off; default is auto by env var.
  `voice_id` / `speech_model` override the voice (default is a premade
  voice that works on free-tier keys; library voices need a paid plan).
- Clips are cached in `<out_dir>/.tts/` keyed by voice+model+text —
  retakes and crashed takes only synthesize lines they haven't seen.
  Transient 429/5xx responses and network blips retry with backoff (free
  keys get deprioritized under load).
- The first take synthesizes each new line mid-recording, which shows as
  a brief hold before the caption appears. Treat take 1 as a
  cache-warming rehearsal and judge pacing from take 2, which plays
  entirely from cache.
- Pacing self-adjusts: a caption call first waits for the previous line
  to finish speaking. Storyboard pauses are minimums, never cut-offs, and
  the recording holds at the end until the last line lands. Because of
  that wait, the caption-before-spotlight rule matters doubly with speech
  on — visuals set *before* a caption sit on screen through the tail of
  the previous spoken line.
- Write captions for the ear as well as the eye: short sentences, no
  markup, nothing you wouldn't say aloud.
- **A clip is mixed where its line is in the *video*, not where the beat
  log put it.** The log is `time.monotonic()` and the recording is stamped
  with the host's wall clock, so a host that steps that clock while a take
  records would otherwise leave the voice behind while the picture moved —
  measured once at +0.70 s of lag on every line of a stalled take. The
  recorder corrects each line by the wall-clock steps its own capture saw
  before that line, and writes down what it did: `narration` in
  `timeline.json` carries every line's `t` (the beat-log instant) and `at`
  (where it went in the mp4), with a `clock_correction` that says whether a
  correction was possible at all. When the sampler could not watch the clock
  the mix falls back to the raw offset, `timeline.md` says so in a paragraph
  above the beat table, and the audio may be out by however far the host
  moved.
- Verify audio like you verify frames: `ffprobe` shows the aac stream;
  `ffmpeg -af silencedetect` should show speech blocks spanning the video;
  if the key has STT permission, transcribe the extracted track with
  ElevenLabs Scribe and compare against the caption lines.
- Segments all get an audio track (silence if a segment has no lines), so
  `stitch()` still concatenates losslessly.
