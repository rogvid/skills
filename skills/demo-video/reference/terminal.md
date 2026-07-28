<!-- Part of the demo-video skill. SKILL.md is the entry point and
     links here at the point of use; this file is not meant to be read cover
     to cover before writing a storyboard. -->

# Terminal demos: verbs, opening cards, patterns and gotchas

> Read when writing a `TerminalRecorder` storyboard. The essentials are in SKILL.md; this is the full verb table and the four patterns.

### TerminalRecorder verbs (plus the shared ones above)

| Verb | Use |
|---|---|
| `run(command)` | Type a shell command visibly, press Enter. Pair with `wait_for_prompt()`. |
| `send(text, enter=True)` | Type a response to the running program (answer a prompt, a REPL expression). Takes a `Secret(v)` for a password: the value is registered, typed for real, and the terminal's echo of it comes back masked. |
| `key(*names)` | Send keys: `"Up" "Down" "Left" "Right" "Enter" "Tab" "Escape" "Home" "End" "PageUp" "PageDown" "Backspace" "Delete" "Space"`, `"C-<letter>"` (e.g. `"C-c"`), or any single literal char (`"q"`, `"/"`). |
| `wait_for_prompt(timeout_s=60)` | Wait until the shell prompt returns — i.e. the command finished. |
| `wait_for_text(pattern, timeout_s=60)` | **The universal sync.** Wait until the rendered screen (visible text + scrollback, ANSI-stripped) matches `pattern`; `^`/`$` anchor to screen lines. |
| `rec.page` | The live Playwright page (escape hatch). `rec._write(str)` sends raw bytes to the PTY. |

### Opening a terminal segment on a title card

**Pass `interlude=` to the constructor — do not make `interlude()` the
storyboard's first statement.**

```python
with TerminalRecorder(
    out_dir, segment="part2",
    interlude="…the same thing, on the command line.",
    interlude_hold=2.8,          # optional; the default
) as rec:
    rec.caption("Same filter, one command.")
    rec.run("orders --city Berlin")
```

The recorder starts capturing when it creates the page, which is before any
storyboard statement can paint anything — so a card raised by the first verb
arrives ~290 ms late and the segment opens on an empty terminal with a lone
prompt. `interlude=` raises the card from a context init script instead,
before the page has painted at all, and the PTY, the terminal's own setup and
the shell's first prompt all happen behind it. The recorder also **takes it
down** when `interlude_hold` is up, so there is no `interlude("")` to forget.

It records an ordinary `interlude` beat, so `timeline.json` reads the same
either way. `Recorder` (web) has no such argument and does not need one: its
page is blank until `goto()`, so there is no "before" to flash — and a card
painted before that first `goto()` would be destroyed by it.

### Driving the four patterns

- **Non-interactive CLI:** `run(cmd)` → `wait_for_prompt()`.
- **Interactive prompt / REPL:** `run(cmd)` → `wait_for_text(prompt)` →
  `send(answer)` → repeat.
- **Full-screen TUI:** `key(...)` → `wait_for_text(a marker on the new
  screen)` or `pause(...)` → `shot(...)`; quit, then `wait_for_prompt()`.
- **Long-running / streaming:** `run(server)` → `wait_for_text("Listening…")`,
  tour the output; skip big waits with the same `segment=` + `interlude` +
  `stitch` machinery the web path uses. Output streams into the recording
  live, so you see it scroll.

### Terminal gotchas

- **Sync on the *rendered screen*, not a guessed delay.** `wait_for_text`
  reads what xterm.js actually displays (scrollback included), so it
  survives TUIs that repaint continuously and never print a clean "done".
- **`wait_for_prompt` keys on an *idle* prompt** — the last screen line
  being exactly the prompt marker. Programs that clear the screen (`top`,
  `clear`, most TUIs) erase earlier prompt lines, which is why counting
  prompts does not work and this does.
- **Typing is real echo.** `run`/`send` write to the PTY; the terminal
  echoes each key, so it appears typed. Programs that turn echo off
  (password prompts, raw-mode TUIs) correctly show nothing.
- **A secret a command prints is masked on the way in.** `register_secret()`
  before the command runs, and its output — plus the screen text
  `wait_for_text()` reads — comes back `[redacted]`. `run()` and `send()`
  refuse a command line holding a registered value outright. Read
  [secrets.md](secrets.md) → *Redaction in a terminal demo*, and the list of what
  it does not cover, before trusting it.
- **Keep the prompt distinctive.** The default `❯ ` rarely collides with
  output. If you theme it via `terminal_prompt`, keep it a string unlikely
  to appear as the last line of a command's output.
- **A program that never returns** (a server) needs `wait_for_text`, not
  `wait_for_prompt` — there is no prompt until it exits.
- **Pagers are disabled by default.** A real PTY makes `git`, `man`,
  `systemctl`, etc. pipe through `less`, which holds the terminal and hangs
  `wait_for_prompt`. The recorder sets `PAGER`/`GIT_PAGER`/`SYSTEMD_PAGER` to
  `cat` so commands print inline. To demo a pager on purpose, launch it and
  drive it with `key` (`"Space"`, `"q"`).
