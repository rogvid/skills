<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# When the app is broken, and when the take does not finish

> Read when a take raises, when `strict=True` refuses one, or when a `failure/` directory and a `demo-video-FAILED.md` turn up beside the demo.

## Failing the take on a broken app

**A demo that looks perfect while the app throws `TypeError` on every render
passes any review that only watches pixels.** This is the failure mode with no
visual signature at all: the captions are right, the stills are pretty, the
video is convincing, and the feature is broken. So every take also watches the
app itself and writes what it saw into `timeline.json` as `issues`:

| `kind` | What it is | Fatal under `strict=True`? |
|---|---|---|
| `console_error` | `console.error(…)` from the page | yes |
| `console_warning` | `console.warn(…)` from the page | no |
| `page_error` | an uncaught exception or unhandled rejection | yes |
| `request_failed` | a request that never got a response | no |
| `http_error` | a response with status ≥ 400 (3xx redirects are normal) | no |
| `nonzero_exit` | a `TerminalRecorder` `run()` whose command failed | yes |
| `caption_lost` | a page load took the caption bar off the screen; the beat log cleared with it and the issue names the line and the new URL. Found only in timelines recorded before the wrapper cutover (#361): a web take's caption now lives in the recorder's own document, which no app navigation can destroy, so this can never fire — the recorder does not even subscribe the signal (#360). Caption death on navigation is a terminal-take concern only (its caption is in-page, until #362), and a terminal take's page never navigates | no |

Each issue is **attributed to the beat that was running when it fired** —
`beat` (an index into `beats`), plus the beat's `verb` and `caption` copied
alongside so the list reads on its own. "The take broke" is not a bug report;
"the take broke during `click('#refresh')`, under the caption *Refresh reloads
it*" is. `timeline.md` gets an **Issues** section saying the same thing in
prose, so a reviewer reading the PR sees it without opening the JSON.

**`beat` is `null` when no beat can honestly claim the problem**, and that is a
real answer rather than a gap. Playwright hands the recorder page events only
while it is being called, so the naive reading — blame the most recently
started beat — invents attributions in both directions: an error thrown during
a three-second `hold()` would be blamed on the beat *after* the hold and quoted
under a caption that had not appeared yet. Holds therefore pump events as they
wait, and anything still ambiguous — a problem surfacing between two verbs,
or after a long stretch where nothing reached Playwright — records `beat: null`
instead of a confident guess. Trust `beat`; `t` is when the problem was
*observed*, which can lag when it happened.

Nothing has to be asked for: **a summary prints on stderr at the end of every
take**, listing each problem and its beat, or saying plainly that there were
none.

`TerminalRecorder.run()` additionally records `exit_code` on its beat, and
`timeline.md` gets an `exit` column when any beat has one. The shell reports
the status through an invisible escape in its own prompt, carrying `$?` and
bash's command number, which the recorder strips before the terminal ever
renders it — so the status is known without typing `echo $?` into the demo.

The command number is what makes it trustworthy. The shell prints a prompt at
startup before any command, and reprints one for an empty Enter or a Ctrl-C, and
each of those reports a status belonging to no command; the number is what tells
them apart. Two `run()`s with no wait between them queue, and each status
reaches the beat that typed it, because the shell still runs them in order.

An `exit_code` is either right or `null`, never wrong. It is `null` when the
status never arrived: a `run()` the storyboard never waited on and the take
ended, a program still running at the end, or a shell that does not expand `$?`
in its prompt (zsh needs `PROMPT_SUBST`; only bash is exercised). Pair every
`run()` with `wait_for_prompt()` and it is always there.

### `strict=True`

```python
with Recorder(Path(__file__).parent, strict=True) as rec:
    ...
```

`Recorder(..., strict=True)` / `TerminalRecorder(..., strict=True)` (or
`DEMO_VIDEO_STRICT=1`) makes the take **raise `StrictTakeFailed` on exit** if it
recorded any fatal issue, naming the kind, the beat and the message for each.
Default is off, so a take that would otherwise have shipped silently still
records everything and still succeeds.

It fails *after* writing demo.mp4, the stills and the timeline. A broken take
is exactly the one somebody wants to look at, so failing it must not also
destroy the evidence.

Strict means strict. Chromium writes its own `Failed to load resource: …` to
the console for anything that 404s or refuses a connection, and that is a real
console error — so a missing favicon fails a strict take too. Use it when you
want the demo to be a check that the app works, not when you want it to be
lenient.

## When a take does not finish

A storyboard that raises — a `wait_for()` that times out, an assertion of your
own, a Ctrl-C on a hung demo — used to leave **nothing at all**: the webm the
browser already had was discarded, and the beats sitting in memory were never
written. In CI, where there is no screen to look at, that means blind retries.

It now keeps everything it had, and marks it:

```
demo.mp4               the partial recording, cut off where the storyboard
                       gave up — converted from the webm rather than deleted
timeline.json/.md      the beats. The one whose verb raised carries `error`;
                       the envelope carries `failure`
evidence/, frames/     as usual, off the recording that exists
failure/               failure.json  the failing beat in full, every issue the
                                     take recorded, and what was written
                       failure.md    the same for a person
                       screen.txt    the page's accessibility tree, or the
                                     rendered terminal buffer
                       last-frame.png the final frame of demo.mp4
demo-video-FAILED.md   what happened, when, and whether the demo.mp4 beside it
                       is this take's or an earlier run's
```

The original exception still propagates, unchanged — it is the message that
says what to fix, and the recorder does not replace it. What the recorder adds
is a line on stderr naming the beat and pointing at `failure/`.

**`demo-video-FAILED.md` is written whenever a take did not write its own
complete set of artifacts**, and there are exactly two ways to get there. One is
the storyboard raising, above — the mp4 beside the marker is this take's, cut
short. The other is the reason the marker exists:
**ffmpeg failing to convert the recording.** The storyboard finished, so the
beat log is written and is this take's, but nothing was encoded — and what sits
in the folder under `demo.mp4` is then whatever a *previous* run left there. A
watchable video next to a current `timeline.json` reads as a take that
succeeded, and the video is a recording of different code. Three things keep it
from being believed: `duration` is `null` rather than that file's length, no
review frames are extracted off it, and the marker says in the folder itself
which of the two happened. The next take that writes its own artifacts deletes
the marker, so its presence always describes the most recent run.

A `strict=True` refusal is neither of those. It writes every artifact and all of
them are current, so its marker is cleared exactly like a success's — the
`StrictTakeFailed` it raises is the report, not a hole in the folder.

**`failure/screen.txt` is a text dump of the page, and nothing in it is
hidden.** It is the ARIA tree (or the rendered terminal buffer) exactly as the
recorder read it — see the top of [SKILL.md](../SKILL.md). The last frame is
extracted from `demo.mp4` rather than screenshotted, so it is a frame of the
recording rather than a second capture of the page.

The page is read once, after `_stop()` has flushed whatever the medium was
holding back, so the dump is of the screen the recording ends on.

**What this does not do.** It does not make a crashed take's `demo.mp4` a
complete demo — it stops where the storyboard did, and it does not diagnose
the crash.

**Timestamps are monotonic offsets, and the video runs on a different clock.**
Beat timestamps are `time.monotonic()`; `demo.mp4` is on the host's **wall**
clock, because that is what Chromium stamps every screencast frame with. On a
host whose wall clock moves during a take, every frame after the move lands
that much earlier than the timestamps say. (An earlier version of this
paragraph blamed idle stretches — a screencast emitting no frames when nothing
paints. That was measured and is not what happens; see `limits.md`.) The beat
log itself is good to ~100–200 ms of the frame it describes on a host whose
clock holds still. `timeline.json`'s `capture_clock` records the movement, and
`capture_clock.measured` says whether the recorder could watch for it at all.
[#18](https://github.com/rogvid/skills/issues/18),
[#215](https://github.com/rogvid/skills/issues/215) and
[#247](https://github.com/rogvid/skills/issues/247) are where this was measured,
and all three are closed: the rule they settled on is in `limits.md` under *A
frame is aimed at a beat; it is not stamped with one*. Read that before relying
on a beat timestamp to extract a frame.
