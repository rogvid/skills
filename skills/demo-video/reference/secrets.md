<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Redacting secrets

> Read before the first `redact()`, the first `register_secret()`, or any take that will run against data you would not publish. The second half is what redaction does **not** cover; it is the half that decides whether a recording is safe to release.

## Redacting secrets

A published video leaks permanently, and demos run against seeded-but-realistic
data. Two registrations, at the top of the storyboard, before the first
`goto()`:

```python
from demo_recording import Recorder, Secret

with Recorder(Path(__file__).parent) as rec:
    rec.redact("#api-key", ".customer-email")   # blur where it renders
    rec.register_secret(os.environ["DEMO_TOKEN"])  # keep the text out of narration
    rec.goto("/settings")
    rec.type_into("#token", Secret("sk-live-…"))   # both, automatically
```

- **`redact(*selectors)`** paints an **opaque cover** over matching elements,
  in the page — not with an ffmpeg box in post, which needs fixed coordinates
  while elements scroll, reflow and re-render.

  It covers rather than blurs because a blur is a *how much is enough*
  question, and every answer to it is a guess about how the ink was produced.
  Five ways of rendering text larger than its `font-size` says — a
  `::after`, a `transform: scale()`, `zoom`, an SVG `viewBox`, a value two
  shadow roots down — each defeated a radius derived from CSS, and there was
  no reason to think the fifth was the last. A cover is sized from rendered
  geometry (client rects, which include transforms and zoom by construction)
  and asks no question about the text at all. `redact(..., style="blur")`
  keeps the old look; it is an aesthetic choice, and a weaker one. It is installed as a context init
  script, so it is in place before the page's own scripts run and before the
  first frame; elements are masked from the instant they enter the DOM, and a
  `MutationObserver` re-asserts the mask if the app rewrites the element's
  `style` attribute or replaces the document's stylesheets. Stills inherit it,
  because the mask is in the page rather than in the video pipeline.
  - **Plain CSS selectors only** — an id, a class, an attribute. This is the
    one verb that does not take `text=`, `xpath=`, `>>` or `nth=`, and it
    refuses them with an error rather than accepting them. Continuous cover
    comes from a stylesheet injected into the page, and a stylesheet can only
    express CSS; a Playwright-engine selector can only be re-resolved out of
    process at whatever moments the recorder happens to check, which measured
    as four unmasked seconds of a ten-second take on an ordinary
    fetch-then-render page. Name the element with CSS, or keep the value off
    the screen and register the text.
  - **It reaches an open shadow root** — which `document.querySelectorAll`
    cannot see at all — because the mask is also applied from Python through
    Playwright's engine, and because it wraps `attachShadow` at document start
    to hold every root the app opens.
  - **Sized from what the element paints**, not from what its CSS says: the
    union of the client rects of everything in its subtree, shadow roots at
    every depth included, grown by any pseudo-element's font size (generated
    content has no rect to measure and can paint outside its parent's box).
    Redacting a wrapper is the ordinary call — `redact("#card")` where the
    value is an 80px child — and every measurement here is of the child's
    rendered box, not the wrapper's font.
  - **A blur stays underneath the cover** as a floor, sized the same way. It
    is what a stylesheet can do with no JS at all, and `filter` applies to
    everything an element renders — so it reaches ink the cover's rectangle
    can miss.
  - **It fails rather than misses.** At every checkpoint — after a navigation,
    before every still, around every verb that spends time, and before the mp4
    is written — the recorder asks Playwright, across every frame, how many
    elements each selector matches, and then asks the *browser's own hit
    testing* whether anything is painting over each cover. A cover that
    something paints above, or a selector that never matched anything, raises
    `SecretLeak`: the take writes no mp4, no timeline, and deletes the stills
    it had already taken. A redacted take also withholds the first paint of
    each navigation until that check has passed.
- **`register_secret(*values)`** is about *text*, not pixels. A `caption()`,
  `interlude()`, `terminal()`, `terminal_close()`, `run()` or `send()` line
  containing a registered value raises `SecretLeak` and **fails the take** — deliberately,
  rather than masking the line: captions are burned in *and* spoken *and*
  cached as audio in `.tts/`, and a secret in one is an authoring bug that
  wants rewording, not blurring. Text you did not author is scrubbed to
  `[redacted]` instead: `terminal_output()` (a program's output), every string
  on a beat (`selector`, `still`, `caption`), and `shot()`'s name, which is
  scrubbed before it becomes a filename so the log and the disk agree.
- **`Secret("…")`** is a value the demo types but must never show:
  `type_into(sel, Secret(v))` registers the text, blurs the field before the
  first keystroke, and types the real value. It is not a `str` — printing one
  yields `[redacted]`, and it can never be logged as a beat's target by
  accident.

### Redaction in a terminal demo

`TerminalRecorder` has no `redact()`, and that is not an omission: a CSS
selector means nothing to a PTY. What it has instead is a **scrubber on the
output path**, between `os.read()` and the terminal, so a secret a program
prints never reaches the buffer the frames are drawn from.

```python
from demo_recording import TerminalRecorder, Secret

with TerminalRecorder(Path(__file__).parent) as rec:
    rec.register_secret(os.environ["DEMO_TOKEN"])   # exact text: the guarantee
    rec.run("./deploy --show-config")               # its output comes back masked
    rec.run("ssh-add -l")                           # wait_for_prompt() sees the mask too
    rec.send(Secret(os.environ["DEMO_PW"]))         # a password, at a prompt
```

- **Registered values are the guarantee.** Every occurrence in a program's
  output becomes `[redacted]` — in the video, in the stills, and in the screen
  text `wait_for_text()` and `wait_for_prompt()` match against. It holds when
  the value is chopped across `os.read()` boundaries (the recorder holds back
  any trailing fragment that could still complete one, with no time limit) and
  when one of a **listed set** of escape sequences is printed *inside* it —
  colour and style, cursor show/hide, erase-to-end-of-line, window-title OSC,
  charset and keypad selection. Not "any sequence that does not move the
  cursor": that is the shape of the rule, not its reach, and sequences outside
  the list are where it stops. See below for both halves.
- **…and what the stream cannot express, the recorder refuses.** Before it
  writes anything, the take reads the finished terminal — visible screen and
  scrollback — and raises `SecretLeak` if a registered value is in it: no mp4,
  no timeline, no stills. That is the backstop for the case the scrubber
  cannot see (a value written in two pieces at two cursor positions), and it
  is why "not covered" below means "the take dies", not "it records the key".

  "Finished" and "no stills" both mean it. The check runs after the narration
  tail and after the recorder has flushed whatever it was still holding, so
  it reads the screen the recording actually ends on — and it runs on every
  way out of the `with`, including a storyboard that raised. A
  `wait_for_text()` that timed out still gets its stills taken back, because
  a still is written long before a take ends and a terminal still is the raw
  screen. When that happens the timeout is what gets raised, not the leak:
  the leak is printed, and the message that says what to fix is the one you
  wanted.
- **Shape detection is a safety net under that, not a substitute for it.**
  Four patterns are masked whether or not anyone registered them:

  | | what it matches |
  |---|---|
  | `sk-…` | `sk-` + 16 or more of `A-Za-z0-9_-` |
  | `ghp_…` | `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` + 16 or more alphanumerics |
  | `AKIA…` | `AKIA` or `ASIA` + 12 or more of `0-9A-Z` |
  | JWT | `eyJ` + base64url, a `.`, base64url, optionally `.` and more |

  They are deliberately narrow. Anything looser starts masking ordinary
  output, and a demo with holes punched in it at random is worse than one that
  shows a fake key. **Do not plan a demo around them**: a value that does not
  match one of those four shapes — a database URL with a password in it, a
  session cookie, an internal token format, a licence key — is not touched
  unless you register it. They are also the *only* thing the final screen
  check ignores: a registered value on screen kills the take, a shape-matched
  one does not, because failing a recording on a heuristic is worse than the
  heuristic missing.
- **`run()` and `send()` refuse authored secrets.** A command line is text the
  storyboard wrote and the PTY echoes on camera, so it is treated like a
  caption: `run("curl -H 'x-api-key: sk-live-…'")` raises `SecretLeak` and
  fails the take rather than typing a command the viewer cannot read. Pass the
  value through the environment instead (`run('curl -H "x-api-key: $KEY"')`),
  or type it with `send(Secret(...))`.
- **`send(Secret(v))` is the password case.** It registers the value, types
  the real thing, and the terminal's own echo of it comes back masked — one
  character per read, which is exactly the split the carry buffer exists for.
  Programs that turn echo off (a real `getpass`) show nothing either way.
- **`key()` refuses one too.** `key(*value)` spells a value out one keystroke
  at a time, and the beat it records is those keys joined by spaces — which no
  scrub of the value can match, in a file this skill tells you to commit. So
  the call raises rather than the log leaking.
- **A held fragment can make the screen lag.** The recorder cannot know that
  `sk-live-de` is the start of a registered value until the rest arrives, so
  it withholds it. If the program then goes quiet — a prompt waiting for
  input — those characters stay off screen, and a `wait_for_text()` looking
  for them waits with them. After two seconds the recorder says so on stderr,
  naming the count. Shape fragments are not held indefinitely: they go out
  after three seconds, or immediately if they sit in the middle of a word
  rather than where a token would start.

### What redaction does NOT cover

Read this before trusting a recording to it. It closes a specific, countable
set of paths — four on the web, one in the terminal — and nothing else:

- **The cover is erasure; `style="blur"` is not.** An opaque rectangle
  removes the pixels. A blur destroys legibility, not information — a
  determined attacker with the font and the radius can attempt deconvolution —
  and it is sized by a rule that has been wrong five times. If you opt into
  blur, treat it as a visual convention rather than a control. For a real
  credential, do not render it at all: demo against a fake value.
- **What the cover is sized from, it can miss.** It is the union of the client
  rects the recorder can find. Generated content is allowed for by growing the
  box by the pseudo's font size, but an absolutely positioned pseudo far from
  its parent, or ink painted outside every rect in the subtree, is outside it —
  the blur underneath is what covers those, and the blur is the weaker
  mechanism. Look at the stills.
- **`redact()` takes plain CSS and nothing else**, unlike every other verb
  here. `text=`, `xpath=`, `>>` and `nth=` raise. See above for why.
- **Nothing is registered for you.** `redact()` does not read the element's
  text, so the value stays *unregistered* — write it into a caption yourself
  and it will be captioned, spoken and cached without complaint. Register the
  text separately, or type it as a `Secret`.
- **Only exact substrings match, on every path but one.** No normalisation —
  a secret rendered with different whitespace, a soft hyphen, or split across
  two elements is not caught, and a caption or a beat field is checked
  literally. The single exception is the terminal recorder's PTY output, which
  also runs four shape patterns over what a program prints; those are listed
  under **Redaction in a terminal demo**, they apply nowhere else, and they
  are a net rather than a promise.
- **Registering late does not un-record anything.** A caption set before its
  value was registered is already burned into the frames and already spoken;
  what registration afterwards buys is only that the files the recorder writes
  (`timeline.json`, `timeline.md`, still filenames) come back masked. Register
  before you caption.
- **Frames recorded before the call are already on disk.** `redact()` after a
  `goto()` warns for exactly this reason: masking late cannot un-capture a
  frame.
- **A *closed* shadow root cannot be masked by anything** — not by an injected
  stylesheet, not by Playwright, not by `document.querySelector`. A take told
  to redact something inside one fails loudly and records nothing, which is the
  only honest outcome; there is no way to record that app with that value on
  screen.
- **Iframes: same-origin only, in practice.** The in-page mask is injected
  into every frame, and masking and verification now run across all of them —
  but a *cross-origin* frame's contents are a separate document the recorder
  cannot always reach, and nothing here can mask what it cannot see. A key in
  a third-party iframe is not covered.
- **Canvas: the picture is covered, the bitmap is not.** The cover is over
  the canvas element's rect, so nothing it draws is visible. Anything reading
  the bitmap back (`toDataURL`, `getImageData`) still sees the original.
- **The terminal scrubber has its own list, and it is not short.** Everything
  under **Redaction in a terminal demo** above holds; here is what it does not
  reach.
  - **A value split by an escape the scrubber does not know is not masked —
    and it can be perfectly legible.** Matching runs against a copy with the
    *inert* sequences removed, and that is a **fixed list**: colour and style
    (SGR), mode set/reset (`\x1b[?25l`, which every spinner emits),
    erase-to-end-of-line, window-title OSC, charset and keypad selection. A
    token broken by one of those is contiguous on screen and is caught.

    A token broken by a non-cursor-moving sequence that is *not* on the list
    is not. Measured, each of these renders the value as one word on screen
    while the scrubber writes it in the clear: a CSI with an intermediate byte
    (`\x1b[1 q`, the cursor-style escape), a DCS string (`\x1bPxx\x1b\\`), and
    an OSC aborted by an ESC rather than a BEL (`\x1b]0;t\x1b[0m`). For a
    *registered* value the final screen check below still kills the take, so
    the guarantee holds — the recording is refused rather than leaked. For a
    value that only shape detection was hiding, nothing catches it and it is
    in the frames.

    Cursor movement is different. `\x1b[3;1Hsk-live-` followed by
    `\x1b[3;15HKEY…` puts the value on screen as one word while no substring
    of the stream contains it, and masking across the jump would delete the
    movement and corrupt the redraw. **Do not read this as "the secret comes
    out scrambled anyway" — it comes out readable.** What saves the recording
    is the final screen check: the take raises `SecretLeak` and keeps nothing.
    A recording you wanted, refused. Keep such values off the screen.

    (A line the *terminal* wraps at the right margin is not this case and is
    caught: wrapping puts no escape in the stream.)
  - **The final screen check covers registered values only.** A shape-matched
    token written the same way is not refused and not masked. Register.
  - **Half a secret still renders.** The recorder cannot know a run of
    characters is the start of a key until the rest arrives, so a program
    killed part-way through printing one leaves what it printed on screen.
    (At teardown a dangling fragment of a registered value, or one that had
    reached a credential anchor, is masked; up to that point it is on screen
    because it might have been anything.)
  - **Shape detection has a clock, and a registered value does not.** A
    fragment that could still grow into a shape match is held across quiet
    moments — measured, a token written at 5, 20, 100 or 400 ms per character
    is masked — but not forever: three seconds where a token would start,
    and not at all in the middle of a word, because a screen permanently
    missing its last character is a `wait_for_text()` that never returns. So a
    program that pauses **longer than three seconds inside a token** defeats
    shape matching. Registered values have no such limit.
  - **A shape-matched token longer than 4096 characters may have its head
    rendered** — the fragment ceiling. A *registered* value of any length is
    held whole.
  - **Registering late is worse here than on the web.** The scrubber runs as
    output arrives, so anything already on screen when you call
    `register_secret()` stays on screen. Register before the command runs.
  - **Scrollback is the recording.** A secret masked on screen was never in
    the buffer at all, so scrollback holds the mask too — but anything the
    *program* writes elsewhere (a log file, a `tee`, its own history) is
    untouched. This hides values from the recording, not from the machine.
  - **The PTY child is a real process.** It sees your real environment; the
    recorder does not sanitize it. A screen recording of a shell is a
    recording of a shell.
- **What CSS cannot reach, the mask cannot hide**: a cross-origin iframe's
  contents, an OS-level dialog, anything drawn outside the page. A `<canvas>`
  *is* covered — `filter` on the element blurs its rendered pixels like any
  other element (verified) — but only what is *displayed*; the bitmap behind it
  is unchanged, so anything reading it back (`toDataURL`, `getImageData`) still
  sees the original.
- **Non-visual channels are untouched.** The value still exists in the DOM
  (`page.content()`), in the app's network traffic, and in whatever the app
  logs. Redaction hides it from the *recording*, not from the machine.
  - The one place this skill *does* dump the DOM is `evidence/beat-NN.json`,
    and it is plain text, so it cannot inherit a pixel control for free: the
    recorder reads what each redacted element renders and masks that text out
    of every evidence file. Read [review.md](review.md) before trusting it, and
    do not commit `evidence/`.
  - What that harvest reads is also masked out of `timeline.json` and
    `timeline.md`, which *are* committed. Without it a caption or a selector
    holding a redacted element's text would come back `[redacted]` in the
    evidence and in the clear in the file you are asked to check in.
- **A screenshot the storyboard takes itself** — `rec.page.screenshot(...)`
  rather than `rec.shot(...)` — still goes through the page, so the CSS mask
  applies; but any artifact your storyboard writes by hand (a `page.content()`
  dump, a downloaded file) is yours to clean.
- **`register_secret()` refuses anything under 8 characters**, with an error
  naming the length rather than the value. Registering is a literal
  find-and-replace over the beat log, the still filenames, the caption text,
  every line of terminal output and every evidence file — so `"1234"` would
  rewrite a `:nth-child(1234)` selector, an unrelated account number and the
  `1234` in a timestamp, and the damage reads exactly like redaction working.
  To hide something shorter, use `redact()`: it covers the pixels the element
  paints and rewrites no text at all.
- **`caption(Secret(...))` and `interlude(Secret(...))` raise `SecretLeak`**,
  by name. A caption is burned into every frame and spoken aloud, which is the
  one thing a `Secret` must never be. `Secret` is for typing —
  `type_into(sel, Secret(v))`, `send(Secret(v))`.
- **A failed take deletes its own stills, and only its own.** When the mask
  cannot be verified the recorder removes the stills *this* take wrote and
  names each one it removed. Stills a previous take left in the same folder
  are not touched — and anything your storyboard wrote by hand is yours. It
  writes no `failure/` dump either: that dump is a text account of the page,
  which is exactly what a take whose mask cannot be vouched for must not
  publish. It does leave `demo-video-FAILED.md`, because the previous run's
  files are still sitting there.
