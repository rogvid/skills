<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# The verbs in full

> Read when a verb in SKILL.md's table needs more than its one line gives you — what it does at the edges, what it refuses, and the mistakes each one has produced.

SKILL.md's table is the index: every verb, one line, enough to write an
ordinary storyboard. This file is the same list with the caveats attached.
Each caveat below is here because a take shipped wrong without it.

## Navigation and framing

**`goto(path)`** — navigate, relative to `base_url`. Waits for networkidle but
gives up after 10 s, for apps that poll. It **classifies its own argument**
before Playwright navigates: `goto("https://app.acme.com/")` is refused, and so
is a relative path that reaches another host through userinfo,
`goto("@app.acme.com/")`.

Because it gives up after 10 s, `wait_for` the *content* element rather than
the page chrome — `wait_for("h1")` passes while the data is still on its way.

**`pause(s)`** / **`shot(name)`** — hold the frame; capture
`images/<name>.png`. `shot()` stills match the video: one encode per take, and
the page is the finished picture.

**`wait_for(selector)`** — wait for something the app does on its own. Use this
and not `rec.page.wait_for_selector`: the verb stamps a beat, the raw call does
not.

## Captions

**`caption(text)`** — the narrator line, in the caption pill riding the app
rect's bottom edge (a reserved band below the app with `caption_overlay=False`).
`""` clears it.

- Both media draw the caption **in the recorder's own document**, so the line
  survives full page loads and SPA routing alike, and `caption_lost` cannot
  fire at all any more. The corollary is a footgun: a line left up across a
  navigation reads as narrating the next view too. `caption("")` before the
  click that navigates, fresh caption after.
- A line taller than the two-line zone is shaved at its edges and recorded as a
  `caption_clipped` issue. Shorten it, or split it over two captions.
- With the overlay pill, fade the line (`caption("")`) **before** a
  `spotlight()`: the camera push-in crops the frame around the spotlit element
  and can shave a pill riding the bottom edge.
- A caption long enough to wrap can silence the held-picture warning on an
  app's own modal, so keep captions to one line.

**`caption(text, ac="AC-3")`** / **`shot(name, ac="AC-3")`** — tag this beat
with the acceptance criterion it is there to demonstrate. Needs
`Recorder(criteria={...})`; a tag naming an undeclared criterion is refused.

Add `shows="unmet"` to point the claim the other way — this beat is evidence
the clause is **not** met, which is the case worth the most to a reviewer. It
needs an `ac=`, and it is still the author's assertion: nothing read the
ticket. See [review.md](review.md).

**`criterion("AC-3")`** — raise a card carrying **AC-3's own declared
sentence**, read out of `criteria={...}` rather than retyped, so the viewer
meets the clause and then watches it happen. The beat claims AC-3 and nothing
else; the beats after it are untagged. Held to reading speed, and cleared by
`interlude("")` like any card.

## Pointing and acting

**`move_to`** / **`click`** / **`click_fast`** / **`scroll_to`** — visible
cursor motion. `click_fast` for elements that re-render continuously.
`scroll_to` brings the element to the *centre* of the viewport, which is what
keeps a narrated element out from under the caption.

The dot is verb-driven: raw `rec.page.mouse` never moves it, and it draws at
the first pointer verb, keeping its spot across `goto()`. Elements the app
inserts mid-recording move and the cursor does not — re-`move_to` after any
reflowing wait.

**`type_into(selector, text)`** — click a field and type visibly, key by key,
for form demos. It types at the caret, so it **appends** to what is already
there: `clear()` first to replace it.

**`clear(selector)`** — empty a field, visibly: click, select what is in it,
delete. Its own beat, because emptying a field is something the viewer watches
happen.

**`press(key, hold_s=0.5)`** — press one named key wherever the focus already
is: `"Enter"` to submit, `"Escape"` to dismiss, `"Tab"` to move on,
`"Control+A"`. Playwright's key names; an unknown one raises.

Selector-free on purpose: `Tab` *is* the focus demo, `Escape` acts on whatever
is up, and `type_into`/`clear` leave the caret where they put it. Holds
`hold_s` so the change is on screen long enough to read.

**`spotlight(selector)`** — ring and enlarge the element the caption discusses;
`spotlight()` clears.

- It eases in *and out* over 250 ms and the verb waits out its own exit, so the
  element is back exactly as it was found before the next beat starts — about
  250 ms per clear on an ordinary take, ~0 under `deterministic=True`, which
  flattens the transition.
- An element **positioned by a transform** — React Flow nodes, dnd-kit items,
  anything carrying an inline or stylesheet `transform` — gets the ring but
  **not** the enlarge: setting `transform` would replace its own and teleport
  it for the beat (#398).
- Each spotlight interval also becomes a **camera push-in** (1.3×, eased 0.5 s
  each way, centred on the element) rendered after the take — see
  `helpers/demo_recording/camera.py`. The moves land in `demo.mp4`
  automatically, and `timeline.json`'s `camera` key publishes the geometry.

## Cards, props and structure

**`terminal(cmd)`** / **`terminal_output(text)`** / **`terminal_close()`** — a
*decorative* on-screen terminal card for off-browser actions **inside a web
demo**. A prop, not a real shell: it is how you put an event the script
triggers outside the browser (dropping a file, calling an API) on screen.
Perform the real action right after raising it; `terminal_close()` stamps ✓ and
fades it. To record an actual CLI or TUI use `TerminalRecorder`
([terminal.md](terminal.md)).

**`interlude(text, hold=2.8, style=…)`** — bridge a jump. `hold` is how long
the card stays before the storyboard moves on.

- `style="card"` (the default) is a full-screen title card — dark on a terminal
  take, so a segment can open on it; the window's own body colour on a web one,
  so the content area becomes the window with the sentence on it (#291). For
  real time-skips.
- `style="light"` is a centred label over a soft scrim with the scene still
  visible, for short transitions.
- **`interlude("")` fades out whatever is up, whichever style raised it** — the
  clear takes no `style` and ignores one it is given.
- Leave a card up and the take says so on stderr and in `content.warnings`;
  nothing else will notice ([limits.md](limits.md)).

**`stitch(out_dir, [segments])`** — lossless concat of segment recordings into
`demo.mp4`, **and** a merge of their beat logs into one `timeline.json` /
`timeline.md` beside it. `keep_parts=True` leaves each `.seg.mp4` and its
`.seg.timeline.*` on disk for a re-stitch.

## The escape hatch

**`act(label)`** — stamp one beat around raw `rec.page` work:

```python
with rec.act("apply the filter"):
    rec.page.select_option("#status", "open")
```

The block gets a frame, an evidence file and a named beat, like a verb. An
exception inside still closes the beat and fails the take (#344).

**`rec.page`** — the live Playwright page, for anything the verbs do not cover
(iframes, drag, hover-only menus). `rec.page` is the framed page; `rec.app` is
the app's document.

**Bare `rec.page` work stamps no beat: no frame is aimed at it, no evidence is
written, and the review cannot see it happened.** Wrap it in `rec.act(…)`, or
follow it with a beat-stamping verb.

It is also the hole in the target classifier, deliberately and permanently:
`rec.page.goto(...)`, the app's own `fetch`, and any URL you compute reach the
network unexamined. See the top of SKILL.md.
