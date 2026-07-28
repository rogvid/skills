<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Determinism

> Read before passing `deterministic=True` or setting `DEMO_VIDEO_DETERMINISTIC=1`. A frozen clock changes what an app does, and mostly it does so silently.

## Determinism

Re-recording a storyboard should produce the same video. That is what makes a
still diffable against the one committed last month, and what makes "did the UI
actually change?" answerable instead of "the video is different, they always
are". But the controls that get you there are not equally safe, so they are not
switched on together.

**Always on, in every recording:**

| Control | What it does |
|---|---|
| **Fixed timezone and locale** | The context is pinned to `UTC` / `en-US`, so every date, number and currency the app formats reads the same on your laptop as in CI. |
| **`prefers-reduced-motion: reduce`** | Requested on the context. An app that honours it was built to. |

**Opt-in, with `deterministic=True`:**

| Control | What it does |
|---|---|
| **Frozen wall clock** | `Date.now()`, `new Date()`, `Intl.DateTimeFormat().format()`, `performance.timeOrigin`, `document.lastModified` and a `Worker`'s clock all answer one fixed instant — `2025-01-01T09:00:00Z` by default. Explicit arguments (`new Date(iso)`), `Date.parse` and `Date.UTC` are untouched. |
| **Flattened motion** | Animations and transitions are compressed to 1 ms, so they land on their finished state within the first frame. Authored delays and fill-modes are left alone. |

```python
with Recorder(out_dir, deterministic=True) as rec:   # or DEMO_VIDEO_DETERMINISTIC=1
```

### Why the clock is opt-in — read this before turning it on

**A frozen clock breaks apps, and it usually breaks them silently.** Five
ordinary patterns, each recorded both ways against a real page:

| Pattern | With the clock frozen | Actually |
|---|---|---|
| lodash-shaped debounce (`now - last >= wait`) | never fires; the timer reschedules forever | fires |
| elapsed-time progress bar | sticks at `0%` | reaches `100%` |
| token gate (`nbf`/`exp` around now) | "not yet valid (clock skew)" | "signed in" |
| "last 7 days" chart | draws **0** bars | draws 7 |
| `while (Date.now() - t0 < ms)` spin | never exits — the take dies on a navigation timeout with **no mp4 written**, and nothing in the error mentions the clock | exits |

Four of the five produce **a plausible wrong screen**: no exception, nothing on
the console, nothing in `timeline.json` — just a demo that confidently shows a
reviewer something the app never does. That is a worse outcome than a fresh
timestamp in every take, which is why you have to ask for it.

So: turn it on deliberately, and **check the stills against the real app the
first time you do**. If something looks wrong, try moving the frozen instant
first (`clock="2026-03-01T12:00:00Z"`, so tokens minted at record time are
still valid), and drop back to the default if the app needs a moving clock.

Every take records what it was given, in `timeline.json`:

```json
"determinism": { "deterministic": true, "clock": "2025-01-01T09:00:00Z",
                 "timezone_id": "UTC", "locale": "en-US" }
```

`"clock": null` means the page's clock was live. Commit it with the stills: a
year from now it is the only thing that says whether a diff is the UI changing
or the frozen instant changing.

### Keeping something animated

Motion is flattened to 1 ms rather than to zero on purpose — a transition of
zero duration never starts, so it never fires `transitionend`, and every
accordion, modal, carousel and wizard that advances on that event would stall.
An element that must keep *moving* opts out by name:

```html
<div class="pulse" data-demo-video-animate>…</div>
```

The recorder's own overlays (`#__demo…`, `#__term…`) are exempt already, so
captions still fade. And note what is *not* frozen: `performance.now()`,
`requestAnimationFrame`, and the document animation timeline. Only the wall
clock stops. Freezing monotonic time would stop the compositor, and Chromium's
screencast only emits a frame when the page paints — a still page loses wall
time out of the recording ([#18](https://github.com/rogvid/skills/issues/18)).

One shape has no right answer and gets a deliberate one: an **infinite**
animation has no finished state, so it is stopped after a single 1 ms iteration
and the element shows the style it was declared with. A finite animation —
including `alternate` — ends where the browser would have left it.

### What it cannot control

The recorder drives a browser. Everything below is upstream of it and is the
**storyboard author's** job — a demo that ignores them re-records differently
no matter what this section does:

- **The app's own randomness.** `Math.random()`, `crypto.randomUUID()`,
  generated ids, shuffled lists, faker-seeded fixtures. Nothing here seeds
  them. Seed the app yourself (most frameworks and fixture libraries take a
  seed), or pick a screen that has none.
- **Server data.** Rows a backend returns, "5 minutes ago" rendered
  server-side, anything a background job wrote since the last take. Seed the
  state *before* recording and reset it between takes; storyboards are meant
  to be idempotent (see the Process section of [SKILL.md](../SKILL.md), step 2).
- **Network timing.** Which of two requests lands first, whether a spinner is
  on screen long enough to be photographed, a chart that draws before or after
  its data arrives. `wait_for` a concrete element rather than a delay, and
  never assert on a frame that only exists while something is in flight.
- **The terminal recorder's program.** `TerminalRecorder` runs a real PTY
  child; it does not see the frozen clock, so `date` in a terminal demo prints
  the real time. Tracked in [#26](https://github.com/rogvid/skills/issues/26).
- **Animation the browser does not drive with CSS.** `element.animate()` (Web
  Animations), `requestAnimationFrame` loops, canvas and WebGL keep running —
  no stylesheet can reach them
  ([#35](https://github.com/rogvid/skills/issues/35)). Nor can one reach into
  a shadow root, or outrank an app's own `!important`
  ([#36](https://github.com/rogvid/skills/issues/36)).
- **A module worker's clock.** A classic `Worker` gets the freeze re-injected;
  `{type: "module"}` workers, shared workers and service workers do not
  ([#38](https://github.com/rogvid/skills/issues/38)).
- **The bytes of `demo.mp4`.** H.264 is not byte-reproducible and the
  screencast's frame timing is not either. Two takes match in what they *show*,
  not in their checksums — compare the stills, which are lossless PNGs and do
  reproduce exactly.
