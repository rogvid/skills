# tests

Three suites. Two of them are fast and one is not, and which is which is the
whole of how this directory is organised.

`smoke` answers three questions: **does the demo-video recorder still produce a
real video, does it still notice when the thing it recorded was broken, and can
a reader say what each frame showed without decoding one?** It used to answer a
fourth — whether a registered secret stayed out of everything the take wrote —
and that went with the masking it graded ([#138](https://github.com/rogvid/skills/issues/138)).
The recorder does not defend against a secret reaching the screen and no longer
claims to; see the top of `skills/demo-video/SKILL.md`. Nothing short of running the recorder
can check any of that — its interesting behaviour is "shell out to ffmpeg,
drive a headless browser, come back with an mp4" — so the smoke test runs it,
end to end, and asserts on what lands on disk. It costs about ten minutes and
takes an exclusive lock.

`unit` answers everything that never needed a browser: the coverage report, the
timeline's two renderings, the content and opening warnings, the merge a stitch
performs, and whether `SKILL.md`'s reference links still resolve. It costs 0.07 s and has no dependencies at all.

**That split is the point, not tidiness.** [#136] measured the asymmetry it
exists to remove: the fault-injection rule was *executed* for `ci-unit` and
written down as prose for the 12,369-line suite, because at 12–620 s per
injection under a lock nobody maintains a manifest. `unit` carries a real
`INJECTIONS` table for the half of the recorder that can afford one. It does
not reduce what `smoke` has to run.

`smoke-inject` is the other half of that answer, for the assertions that
genuinely need a browser, a PTY and ffmpeg. It is **not a fourth suite**: it
runs `smoke` itself, one arm at a time, against a copy of the recorder it has
broken on purpose, and requires the *named* assertion to be the one that
fires. Per-arm flags are what made it affordable — an injection aimed at
`--coverage-only` costs 8 s, not the ten minutes the whole suite does. It runs
nightly, and its own guards run on every push. See **The injection manifest**
below for what it covers and what it does not.

```
tests/
├── smoke              # the recorder, end to end (~10 min, needs Chromium + ffmpeg)
├── smoke-inject       # proves smoke's assertions can still fail (~41 min, nightly)
├── unit               # the browser-free half (~0.07 s, no dependencies)
├── ci-unit            # the three .github/scripts helpers (~0.2 s)
├── lint               # ruff at the version ci.yml pins, over the files CI
│                      #   sees, plus the docs' python fences (~0.3 s)
└── fixture/
    └── index.html     # the app smoke records: static, dependency-free, deterministic
```

[#136]: https://github.com/rogvid/skills/issues/136

**A fourth suite lives outside this directory**, and it is here so nobody has
to find that out by accident: `examples/ticket-queue/test` grades the example
app the demo-video reference PR records — 12 assertions read off a real browser
and 11 injections against `web/app.js`, its stylesheet and the seeded data. On a
16-core developer box that is 3.6 s and 87 s; on a CI runner the whole job,
Chromium install included, measured **2m08s**. It belongs beside the app rather
than here because it grades *that application*, not the recorder.
`.github/workflows/ticket-queue.yml` runs both halves on any push touching
`examples/ticket-queue/**` and nightly
([#182](https://github.com/rogvid/skills/issues/182)); before that workflow
existed nothing ran either half, so its injections graded the change that
introduced them and nothing after it.

Takes: `web/` and `terminal/` (the two media), the determinism pair, the
problem takes, `segments/` — one demo recorded in two parts and joined with
`stitch()` — and `evidence/`, a few seconds against what a beat's page text
carries and what it caps.

## Running it

Start with the fast pair — they need nothing installed and finish before you
have read this sentence:

```sh
tests/unit                        # the browser-free half of the recorder
tests/unit --fault-inject         # break each thing an assertion watches
tests/ci-unit                     # the CI workflow's three helper scripts
tests/ci-unit --fault-inject
tests/lint                        # ruff check + ruff format --check + doc fences
tests/lint --self-test            # prove all three grade something
```

**Lint with `tests/lint`, not with `uvx ruff`.** They are not the same command.
`uvx ruff` resolves to whatever ruff is current, which on this tree sees a
different set of files and disagrees about them — in the direction where you
reformat files CI was happy with and land an unrelated diff. `tests/lint` reads
the `RUFF_VERSION:` line out of `.github/workflows/ci.yml` and runs *that*
ruff, and CI's `lint` job runs `tests/lint --github`, so there is one command
and one pin. Change the pin and the local command changes with it;
`tests/lint --self-test` is what keeps that true, and refuses a workflow that
reaches ruff any other way.
[#189](https://github.com/rogvid/skills/issues/189) is what this cost before.

**One pin is not one question, though — the file set is the other half.** With
agent worktrees un-ignored under the repo root, `tests/lint` read **657** files
where CI read 13, and the 644 extra were copies of this repo at other commits;
a red run then named files on other branches, and the diagnosis came only from
noticing that 657 is not 13
([#219](https://github.com/rogvid/skills/issues/219)). `--self-test` grades
that by **planting**, not by reading config: a throwaway checkout goes in at
`.claude/worktrees/`, carrying this repo's own `ruff.toml` the way a real
worktree does, and the file set must not move — while a control `.py` at the
repo root, where nothing is ignored, must move it by exactly one. The control
is what stops "nothing appeared" from meaning "nothing was measured". Asserting
`.gitignore` contains `.claude/` would have graded a string, and said nothing
about the next tool with its own ignore semantics.

The same guard asks the question in the other direction: **every PEP 723
executable in the tree must be inside that file set**, read off the shebangs
rather than off `ruff.toml`. `examples/ticket-queue/test` — 416 lines, the gate
on the queue's search — was outside `extend-include` and therefore unlinted
until [#212](https://github.com/rogvid/skills/issues/212).

**The pin is 0.16.1, and `ruff.toml` excludes `*.md` from the formatter**
([#192](https://github.com/rogvid/skills/issues/192)). From 0.16 ruff's
formatter reads Python out of Markdown code fences — its checker still does
not — and that one behaviour was the entire disagreement between 0.14.2 and a
current ruff on this tree: 3 files, all documentation. A fence in a document is
a figure rather than source; nothing imports or runs it, its reader is a person,
and the reformat measured at 0.16.1 ragged out two columns of deliberately
aligned trailing comments and spent the last line of `SKILL.md`'s 600-line
budget on a blank one. What the exclusion gives up is **only layout**: the
formatter does not validate a fence either way — hand it ```` ```python ````
followed by `def f(:` and it prints "1 file already formatted" and exits 0. The
reasoning is written at the exclusion in `ruff.toml`, which is the file a reader
lands in.

**So `tests/lint` compiles the fences itself**
([#211](https://github.com/rogvid/skills/issues/211)). A parse check, not a
lint: the fences legitimately name things that do not exist here (`rec`, `OUT`,
`mytool`), so `ruff check` semantics would be wrong even if ruff read Markdown.
It walks the tracked `*.md` — 21 files, 39 fences — and `compile()`s the 10
whose info string says `python`/`py`/`python3`. The other 29 are skipped **by
language and counted out loud** (`sh` 11, none 8, `json` 5, `yaml` 2, `bash` 2,
`html` 1), because a checker that silently skipped everything reports the same
clean line a healthy tree does; `MIN_PY_FENCES` is the floor that fires if the
walker stops finding fences at all.

A fence's own indent is stripped before it is compiled, so a block inside a
list item is graded as the Python it renders as. Two things that look like
fences and are not — a run of backticks written inline in a sentence, and a
four-backtick block quoting a three-backtick one — open nothing, and each has a
case in `--self-test` that fails if it starts to.

`KNOWN_FRAGMENTS` in `tests/lint` waives the figures that are deliberately not
whole Python — today exactly one, a `with` header with no body in
`reference/determinism.md`. It is a waiver list graded like one: an entry whose
fence has vanished, or whose fence now compiles, **fails**, so it can only
shrink.

Then the recorder itself:

```sh
tests/smoke                       # every take, output to a temp dir
tests/smoke --web-only            # just the Playwright takes
tests/smoke --terminal-only       # just the PTY/xterm.js takes
tests/smoke --determinism-only    # just the three re-recording takes
tests/smoke --segments-only       # just the two-segment take and its stitch
tests/smoke --evidence-only       # just the per-beat evidence takes
tests/smoke --failure-only        # just the takes that do not finish
tests/smoke --polish-only         # just the two takes that grade how it looks
tests/smoke --content-only        # just the pair that grades whether a
                                  #   recording shows anything (issue #97)
tests/smoke --overlay-only        # just the light-interlude pair (#162/#163)
tests/smoke --coverage-only       # just the acceptance-criterion take (#12)
tests/smoke --strict-only         # just the two takes strict=True must refuse
tests/smoke --issues-only         # just the broken page and the failing
                                  #   commands, which is what check_issues
                                  #   grades (issue #197)
tests/smoke --lock-only           # records nothing: what a run the machine
                                  #   lock refuses leaves behind (issue #105)
tests/smoke --cheap               # every arm except web/content/terminal —
                                  #   what CI records per push (issue #61)
tests/smoke --out-dir /tmp/smoke  # keep the recordings at a known path
tests/smoke --keep                # keep the temp dir even when it passes
```

Then, when you have changed an assertion in `smoke` or the measurement it
grades, the manifest that proves it can still fail:

```sh
tests/smoke-inject --self-test    # the harness's own guards (instant)
tests/smoke-inject --list         # every entry, its arm and what it costs
tests/smoke-inject --arm coverage # one arm's entries (~48 s)
tests/smoke-inject                # all 49 entries, ~41 min
```

Those three figures, and every number in **The injection manifest** below, are
checked against the manifest by `tests/smoke-inject --self-test` on every push.
Editing one by hand turns a run red; see that section for why.

**One suite at a time, per machine.** The script takes an exclusive `flock` on
`$TMPDIR/demo-video-smoke.lock` and refuses to start while another run holds
it. This is not tidiness: two suites share the CPU and the software encoder,
and the bars that measure *time* — `MAX_BLANK_RUN_S` and the duration ranges —
go red on a recorder that is working perfectly. Two such false failures cost an
afternoon, and worse, they made a genuine intermittent bug undiagnosable
because every red run had a second, more plausible explanation.
[#78](https://github.com/rogvid/skills/issues/78) is about the bars themselves
and stays open. `--allow-concurrent` overrides the refusal; a run that needed
it cannot be read as a verdict.

Prerequisites: `uv`, `ffmpeg`/`ffprobe` on PATH, and Chromium for Playwright
(`uv run --with playwright playwright install chromium`; add `--with-deps` on a
fresh Linux box). The script's PEP 723 header pins **Playwright ≥ 1.49**:
per-beat evidence uses `locator.aria_snapshot()`, which arrived there, and the
`page.accessibility` API it replaced has since been removed outright. A pass looks like this:

```
smoke: serving …/tests/fixture at http://127.0.0.1:41847
smoke: web demo.mp4 ok (20.6s, 277 kB, content 16.0)
smoke: web still 01-dashboard.png ok (77 kB, content 16.9)
smoke: web still 02-filtered.png ok (49 kB, content 15.9)
smoke: web still 03-refreshed.png ok (51 kB, content 15.5)
smoke: web caption is visible on screen (delta 25.6)
smoke: web content ok (score 16.0, longest still 6.0s against a 15.0s limit, over 1 rect(s) [(128, 90, 1024, 460)])
smoke: web first caption 'A small dashboard.' logged at 3.11s, on screen at 3.03s (-80 ms)
smoke: web closing caption 'Recorded end to end.' logged at 17.36s, on screen at 17.36s (+0 ms)
smoke: web beat clock holds across the take (+80 ms)
smoke: web timeline.json ok (23 beats)
smoke: web each review frame shows its own beat's caption state (10 captioned frames from 11.2, 4 bare ones to 3.3; 9 within 0.75s of a caption change and not graded)
smoke: web frames/ ok (23 beat frames, each byte-identical to the demo.mp4 frame it claims to be)
smoke: web evidence ok (23 beats, 38 kB, largest 2450 bytes)
smoke: web opens on the app (frame 0 scores 17.25 against a 15.99 median, over a 0.45s hold)
smoke: opening-gap reads a blank opening and a static picture differently (blank-then-painted, painted-throughout)
smoke: web healthy app under strict=True records no problems
smoke: terminal demo.mp4 ok (18.2s, 165 kB, content 8.4)
smoke: terminal still 01-echo.png ok (135 kB, content 5.1)
smoke: terminal still 02-listing.png ok (150 kB, content 8.3)
smoke: terminal caption is visible on screen (delta 2.7)
smoke: terminal content ok (score 8.43, longest still 9.5s against a 15.0s limit, over 1 rect(s) [(74, 110, 1132, 432)])
smoke: terminal first caption 'A real shell, recorded.' logged at 2.37s, on screen at 2.29s (-80 ms)
smoke: terminal closing caption 'Recorded end to end.' logged at 11.97s, on screen at 11.93s (-40 ms)
smoke: terminal beat clock holds across the take (+40 ms)
smoke: terminal timeline.json ok (18 beats)
smoke: terminal each review frame shows its own beat's caption state (7 captioned frames from 2.7, 2 bare ones to 0.3; 9 within 0.75s of a caption change and not graded)
smoke: terminal frames/ ok (18 beat frames, each byte-identical to the demo.mp4 frame it claims to be)
smoke: terminal evidence ok (18 beats, 9 kB, largest 629 bytes)
smoke: terminal healthy app under strict=True records no problems
smoke: serving …/tests/fixture at http://127.0.0.1:38885
smoke: segments recorded 2 parts, each with its own beat log (part1 6.6s, part2 7.9s)
smoke: segments part1's probe caption is +0 ms from where its own segment puts it (-120 ms in part1.seg.mp4, -120 ms in demo.mp4)
smoke: segments part2's probe caption is +0 ms from where its own segment puts it (-40 ms in part2.seg.mp4, -40 ms in demo.mp4)
smoke: segments stitched 2 parts into a 14.5s demo.mp4 and merged their beat logs (15 beats); keep_parts=True kept every part and its log, the default removed them
smoke: segments demo.mp4 ok (14.5s, 245 kB, content 17.0)
smoke: segments still 01-part1.png ok (78 kB, content 16.9)
smoke: segments caption is visible on screen (delta 26.0)
smoke: segments content ok (score 16.97, longest still 6.0s against a 15.0s limit, over 2 rect(s) [(128, 90, 1024, 460), (128, 90, 1024, 460)])
smoke: segments first caption 'One demo, in two parts.' logged at 3.06s, on screen at 2.95s (-120 ms)
smoke: segments closing caption 'Recorded end to end.' logged at 11.23s, on screen at 11.19s (-40 ms)
smoke: segments beat clock holds across the take (+80 ms)
smoke: segments timeline.json ok (15 beats)
smoke: segments each review frame shows its own beat's caption state (2 captioned frames from 16.8, 5 bare ones to 0.2; 8 within 0.75s of a caption change and not graded)
smoke: segments frames/ ok (15 beat frames, each byte-identical to the demo.mp4 frame it claims to be)
smoke: segments healthy app under strict=True records no problems
smoke: serving …/tests/fixture at http://127.0.0.1:50223
smoke: spotlight demo.mp4 ok (7.5s, 106 kB, content 17.0)
smoke: spotlight eases both ways (enter 4 intermediate frames, exit 3)
smoke: spotlight healthy app under strict=True records no problems
smoke: terminal-opening demo.mp4 ok (12.8s, 105 kB, content 4.6)
smoke: terminal-opening card covers the first 2.80s (corner 26 -> 226), then clears
smoke: terminal-opening healthy app under strict=True records no problems
smoke: all 22 storyboard verbs are classified (14 acting, 8 passive)
smoke: content static limit 15.0s sits in [8.8, 21.3]s (healthy 5.5s, covered 30.5s)
smoke: content-covered stills 1/5 distinct where the terminal is, video 47.5 dB apart, over 6 evidence screens
smoke: content-shown stills 5/5 distinct where the terminal is, video 25.5 dB apart, over 6 evidence screens
smoke: content video held 47.5 dB against moved 25.5 dB — 22.0 dB apart, over the 8.0 dB gap
smoke: content rect 6.58 vs blanked 0.22 (floor 1.0); whole frame 82.25 vs blanked 90.33 — the frame ranks the blank recording higher, the rect does not
smoke: content-toured held one picture for 29.0s, over the 15.0s limit, across ['wait_for_prompt', 'shot', 'caption', 'hold', 'caption', 'hold', 'caption', 'hold'] — and the recorder said nothing, which is correct
smoke: serving …/tests/fixture at http://127.0.0.1:55241
smoke: coverage ok (3 criteria, 4 tagged beats, unclaimed ['AC-3'])
smoke: coverage refusals ok (6 refused, 3 controls accepted)
smoke: coverage merge ok (union of 3 criteria, unclaimed AC-3, merged indices, 1 wording conflict named)
smoke: serving …/tests/fixture at http://127.0.0.1:40453
smoke: web-problems timeline.json records 8 problem(s), 6 of them fatal under strict — take still passed
smoke: serving …/tests/fixture at http://127.0.0.1:32881
smoke: web-strict strict=True refused the take, naming beat 0 (goto) (4 fatal issues, artifacts kept)
smoke: serving …/tests/fixture at http://127.0.0.1:48441
smoke: evidence ok (9 beats as shapes.seg.beat-NN.json, 2181 chars of page text on the control beat, source and unrendered attributes out of the markup, all three fields capped and marked)
smoke: terminal-problems timeline.json records 2 problem(s), 2 of them fatal under strict — take still passed
smoke: terminal-race exit status survives a shell that starts 1.2s late (logged 5)
smoke: terminal-strict strict=True refused the take, naming beat 1 (run) (1 fatal issues, artifacts kept)
smoke: serving …/tests/fixture at http://127.0.0.1:40413
smoke: determinism froze all four clocks identically in both takes
smoke:   frozen  1/1/2025, 9:00:00 AM · 1735722000000
smoke:   frozen  intl 01/01/2025, 09:00:00 AM
smoke:   frozen  ctor 1735722000000 · same true
smoke:   frozen  worker 1735722000000
smoke:   default 7/28/2026, 12:37:19 PM · 1785242239679
smoke:   default intl 07/28/2026, 12:37:19 PM
smoke:   default ctor 1785242239679 · same true
smoke:   default worker 1785242239723
smoke: determinism stills reproduce byte for byte across takes (the same two stills move 22.4 over the spinner with the recorder's default settings)
smoke: determinism demo.mp4 reproduces (takes differ by 0.31, against 6.84 with the default settings)
smoke: determinism ok (3 takes)
smoke: serving …/tests/fixture at http://127.0.0.1:52509
smoke: crash-web crashed and kept everything it had — demo.mp4 (5.9s), timeline.json, failure/ (dump, page text, last frame), demo-video-FAILED.md
smoke: crash-interrupt crashed and kept everything it had — demo.mp4 (3.9s), timeline.json, failure/ (dump, page text, last frame), demo-video-FAILED.mddemo-video: narration OFF — no ELEVENLABS_API_KEY in this environment, so captions record silently. Export the key (e.g. `set -a; source .env; set +a`) before recording to enable spoken narration.
smoke: crash-between crashed and kept everything it had — demo.mp4 (3.9s), timeline.json, failure/ (dump, page text, last frame), demo-video-FAILED.md
smoke: stale-media a take that encoded nothing reports duration: null beside a 2.0s file it did not write, extracts no frames from it, and says so on stderr and in demo-video-FAILED.md
smoke: marker-cleared a successful take removed the demo-video-FAILED.md and the failure/ dump a previous run left
smoke: crash-terminal crashed and kept everything it had — demo.mp4 (10.8s), timeline.json, failure/ (dump, page text, last frame), demo-video-FAILED.md
smoke: PASSED
smoke: recordings kept in /tmp/claude-1000/-home-kvist-personal-projects-skills/b621d914-48bb-4de5-9397-3cc9102d52e7/scratchpad/smoke3
```

Re-running into the same `--out-dir` is safe: the take subdirectories
(`web/`, `terminal/`, `segments/`, `web-problems/`, `terminal-problems/`,
`terminal-race/`, `web-strict/`, `terminal-strict/`, `evidence/`,
`determinism-a/`, `determinism-b/`, `determinism-off/`) are deleted before each take. Only the first two are graded
on their video; the rest are short and exist to break, or to reproduce, in one
specific way each. That is not tidiness — every artifact assertion works by
path, so without it a leftover `demo.mp4` from the previous run would grade a
recorder that produced nothing at all as a pass, and recording repeatedly into
one directory is exactly how a change to the recorder gets verified.

Deleting is bounded. Only those named subdirectories are ever
removed, and only when each is absent, empty, or carries the
`.demo-video-smoke` marker file a previous run wrote there. `--out-dir .` in a
project that has its own `web/` directory gets a refusal naming the path, not a
deleted source tree.

Unix only — `demo_recording/__init__.py` imports the PTY-backed terminal
recorder unconditionally, so the whole package needs a Unix platform. The
terminal *take* additionally skips itself with a message if `os.name` is not
`posix`.

The runner deletes every `DEMO_VIDEO_*` variable plus `ELEVENLABS_API_KEY` from
its own environment before recording, so a sourced project `.env` cannot change
what the test measures. Every take then forces narration off (`speech=False`) —
except one.

**The narration take records with `speech=True`, from a seeded cache**
([#157](https://github.com/rogvid/skills/issues/157)). The speech path had been
graded only by accident: the redaction axis swept every file a take wrote for a
registered value, `.tts/` was one of those files, so some take had to really
synthesize speech for that sweep to mean anything. #150 deleted the sweep and
with it the only reason anything ran the synthesizer, the pacing or the mix.

What makes it affordable to grade on purpose: `tts_clip` returns a cached clip
*before* it reads `api_key`, and the recorder only requires the env var to be
non-empty. So a take whose every line is already in `.tts/` runs the entire real
path with no key, no network, and none of the non-determinism a remote service
brings. The clips are tones of a known length rather than speech, which is what
makes the pacing bar exact — a real clip's duration is whatever ElevenLabs
decided, and a bar you cannot predict is one you end up widening until it
passes.

The cache is seeded by a key this file computes **by hand**, not by calling
`_tts_key`. A harness that seeded itself through the function under test would
agree with that function's bugs by construction, and a key that dropped the
voice would still find every clip. Here a divergence is a cache *miss*, and a
miss fails the take.

Still ungraded: the HTTP call itself and its retry ladder. See "Known gaps".

## When each take runs — the per-push split (issue #61)

A whole run is **427 s** on this box and three arms are 74% of it:
`--terminal-only` (186 s), `--content-only` (148 s) and `--web-only` (123 s).
Since #61, CI does not record those three on every push.

| when | what CI runs | job in `ci.yml` |
|---|---|---|
| every pull-request commit, and every push to `main` | `tests/smoke --cheap` | `smoke (cheap arms, every push)` |
| merge to `main`, or a pull request labelled `smoke-full` | `tests/smoke`, the whole suite | `smoke (web, content and terminal takes)` |

The merge job runs the **whole suite** rather than the three arms, because the
arm flags are mutually exclusive: three invocations cost 123 + 148 + 186 =
457 s of takes against a measured 427 s for one whole run, since the arms share
takes. A whole run is cheaper and is the only invocation that grades them
together.

### The number the split is justified by

**Measured, not summed**, because summing per-arm figures is what produced
every wrong number this issue has carried. Three consecutive
`tests/smoke --cheap` runs on this 16-core box, one at a time behind the
machine lock, with no other suite running and the 1-minute load average read
off `/proc/loadavg` immediately before each:

| run | loadavg before | wall clock | verdict |
|---|---|---|---|
| 1 | 0.31 | 223.0 s | PASSED |
| 2 | 1.28 | 221.5 s | PASSED |
| 3 | 1.25 | 221.9 s | FAILED — see below |

So **~222 s**, spread 1.5 s across the three: a 48% cut against the whole
suite's 427 s, or about 3.4 minutes off every push once the runner's ~1.1x is
applied.

Run 3's red is [#215](https://github.com/rogvid/skills/issues/215)/[#224](https://github.com/rogvid/skills/issues/224)
and not this selection: the host's wall clock stepped **-875 ms at 0.6s inside
`segments/part2`**, which is the bimodal failure *Known gaps* describes on this
box, on an arm the whole suite already ran per push before this change. It is
recorded here rather than re-rolled until green, because the wall-clock reading
is what this table is for and 221.9 s is a reading. What the split does change
about that exposure is that `--web-only` and `--terminal-only`, the other two
arms sensitive to the same host clock, now run on merge instead of per push.

**Why not the arm sums.** Adding up `ARM_SECONDS` for the eleven arms `--cheap`
covers gives 216 s, which is an upper bound on *separate* invocations rather
than a reading of this one — the arms share takes, and the fourteen per-arm
figures sum to 672 s against the measured whole-suite 427 s. The 142 s that
circulated on #61 before anybody ran this included an arm that was deleted
before merge ([#210](https://github.com/rogvid/skills/issues/210)) and silently
dropped five others; it was never a measurement of anything.

### What `--cheap` is, and why it is a complement

`run_phases` guards every phase with `selects(only, arms)`, and `--cheap` takes
a phase when **any** arm reaching it is not one of the three above. It is not a
list, deliberately: a list is a second place to forget, and an arm added to
`run_phases` and not to the list would drop off the per-push run silently.
`tests/unit`'s `CheapArm` grades the rule against the guards read out of
`run_phases`' AST, names the four phases `--cheap` skips rather than counting
them, and refuses a guard that names an arm `main()` does not define — which is
what stops `--cheap` from being written into a guard by hand. Its four
assertions have six injections in `tests/unit --fault-inject`, which runs on
every push.

### What now grades only at merge

Four phases — `run_web`, `run_terminal`, `run_content` and `run_terminal_race`
— and with them **eight check functions no other phase reaches**:

- `check_content_pair` — content/terminal; 1 `smoke-inject` entry, so nightly
- `check_content_toured` — content/terminal; 1 entry, so nightly
- `check_form_pacing` — web; 4 entries, so nightly
- `_check_scored_region` — content/terminal; covered by the content entries
- `_check_occlusion` — content/terminal; no entry, and none before this either
- `check_opening` — web; **no entry**
- `check_opening_gap` — web; **no entry**
- `check_verb_classification` — content/terminal; **no entry**

The last three are the real cost of the split and are written up under *Known
gaps*: no injection and no per-push take means nothing exercises them between a
pull request opening and its merge, and `check_verb_classification` is the
guard that caught `clear`/`press` going unclassified in #130.
[#233](https://github.com/rogvid/skills/issues/233) is the entries that would
close it.

### Why the four middle arms stayed on the push

`--polish-only` (26 s), `--segments-only` (29 s), `--overlay-only` (31 s) and
`--failure-only` (48 s) are the arms the decision did not name, and the
argument for keeping them is cost per check function moved. Dropping one from
`--cheap` moves this much to merge-only:

| arm | seconds | check functions it would move | seconds per check moved |
|---|---|---|---|
| segments | 29 | 11 | 2.6 |
| polish | 26 | 2 | 13 |
| overlay | 31 | 1 | 31 |
| failure | 48 | 1 | 48 |
| the three expensive arms | 457 | 8 | 57 |

Every one of the four buys check coverage more cheaply than the arms the
decision *did* move, so a second cut inside the cheap tier would be a worse
trade than the first one, made on no measurement. Two specifics on top of the
ratio: `--polish-only`'s two functions (`check_opening_card`,
`check_spotlight_transitions`) have no injection anywhere, so the per-push run
is their only exercise in the repo; and `--failure-only` is the only thing that
runs the recorder's exception paths, which is where the catalogue's
*clean-path-only assertion* lives. `--failure-only` is nonetheless the one to
revisit first if the per-push budget ever binds — it is 22% of `--cheap` for
one check function.

## What it asserts

Eleven independent axes, because a recorder can fail on any one of them while
looking perfect on the other ten.

**Artifacts** — `demo.mp4` and every still the storyboard asked for exist, were
modified by *this* run rather than a previous one, clear a size floor
(20 kB / 5 kB), and no two consecutive stills are the same picture. Duration,
via the `media_duration` helper, falls inside a wide window (6–32 s): the low
bound catches a take that died early, the high bound catches a hang, everything
between is normal variation between a laptop and a cold CI runner.

**Content** — the frames contain a picture. This is measured, not inferred from
file size: **no byte count can separate a blank recording from a real one.** A
flat white 14-second 720p H.264 is about 20 kB, comfortably over any floor that
a real 117 kB terminal take also clears. `gray_frames()` has ffmpeg decode
frames to raw 8-bit grayscale at 160×90 and the luma standard deviation is
computed in pure Python — no image library, no extra dependency.

**Where** it measures is the whole trick. Scoring the full frame does not work
and is worse than not scoring at all: a fifth to a third of every frame is the
recorder's own chrome — a pastel gradient at ~230 luma against a ~35 luma
window — and that bimodal spread alone scores 60–79. A fully blank web
recording scores **61.8** that way and a healthy one **60.2**, so the metric is
anti-correlated and no floor can work. Instead, the app's own rect is measured:

- **web video** — `Recorder._geom`, the composited window position, read off the
  live recorder rather than re-derived, so a change to the window geometry
  carries the measurement with it
- **web stills** — the full frame, since `shot()` captures the page full-bleed
  before compositing
- **terminal** — the bounding box of `#__term_host`, the xterm.js host div

The bottom 20% of each rect is dropped so the recorder's caption bar cannot
supply the contrast for an otherwise blank app. Video is sampled at 1 fps and
scored by the **median** frame, so one good frame cannot excuse a blank video.

| | healthy | blank | floor |
|---|---|---|---|
| web video | 16.0 | 0.0 | 6.0 |
| web stills | 15.5–16.9 | 0.1–1.1 | 6.0 |
| terminal video | 8.0 | 0.2 | 2.0 |
| terminal stills | 5.1–7.9 | 0.4 | 2.0 |

The floors differ per medium because the media do: a web page fills its rect
with light and dark, a terminal is mostly empty dark background with a few
lines of text on it.

**Behaviour** — the verbs actually did something. Byte sizes cannot tell a
filtered table from an unfiltered one, so each verb is followed by the
observable post-condition it must have caused:

| Verb | Post-condition checked |
|---|---|
| `goto` | `#rows` has 5 rows, `#status` reads `snapshot 1 of 3`, and `#refresh`'s computed background is the accent orange — the last one resolves a total stylesheet failure, which the luma metric cannot (see Known gaps) |
| `caption(text)` | `#__demo_caption` exists, holds exactly `text`, and has computed opacity > 0.5 (or ≤ 0.5 after `caption("")`) — checked after *every* caption in both takes |
| `caption`, on screen | two stills taken back to back with the page frozen and only the caption changing must differ in the caption band. Self-calibrating: no absolute threshold tied to whatever the fixture renders near the bottom. Healthy 25.6 (web) / 2.7 (terminal); not drawn 0.00 |
| `spotlight(sel)` / `spotlight()` | `#kpi-rev` computed `outline-style` is `solid`, then `none` |
| `type_into("#search", …)` | the field holds `seattle` and `#rows` is down to 1 row |
| `click("#refresh")` | `#status` reads `snapshot 2 of 3`, `#kpi-rev` reads `$134,950` |
| `move_to` | the page saw ≥ 10 `mousemove` events during the call. **Not** where the cursor ended up: Playwright's own `locator.click()` dispatches a `mousemove` to the target, so a final-position check passes with `move_to` stubbed out entirely — it measures Playwright, not the recorder. The 30-step glide is the only thing that produces a trail |
| `run` (terminal) | the shell prompt returns, and the command's *output* appears on a whole screen line (`^hello from demo-video$`, `^skills$`) — anchored so the echoed command line cannot satisfy it |

All post-condition failures are collected, never raised, in both takes. A take
that aborts writes no mp4, and CI's failure-only artifact upload then has
nothing to upload at exactly the moment somebody wants to look at it.

**Timeline** — the beat log the recorder writes as `timeline.json` and
`timeline.md` says what actually happened, and points at the right frames.

The beats are checked against `WEB_BEATS` / `TERMINAL_BEATS`, a hand-written
`(verb, target)` sequence per storyboard. That duplication is the point: a
count or a sequence derived from the log being graded agrees with that log no
matter what it says, which is how a dropped beat would pass. `WEB_CAPTIONS` /
`TERMINAL_CAPTIONS` do the same for the caption text, separately, so a
missing beat and a wrong caption fail independently.

Three of the checks exist because an earlier round of this file had them
missing and did not notice:

- **Every beat carries the caption it ran under**, not just the `caption`
  beats. That context is what makes a `shot` or a `click` beat mean anything,
  and it is what `timeline.md` quotes over each still — but checking only
  `verb == "caption"` beats is blind to losing it. The expected per-beat
  caption is derived from the two hand-written lists, never from the log.
- **`t_end` has to carry information.** Setting it equal to `t_start` satisfies
  every ordering check. So: a `caption(text)` or `hold()` beat must span at
  least a second (the recorder enforces 1.4 s and 1.5 s floors itself), and the
  beats together must account for ≥ 80% of the time from the first starting to
  the last ending. #8 wants the beat *midpoint* for frame extraction precisely
  because `t_start` is 0% into the caption's fade, so this is load-bearing for
  the next PR, not decoration.
- **`timeline.md`'s beat table specifically**, one row per beat. Checking that
  each caption "appears in the file" is satisfied by the Stills section alone,
  so the entire table could vanish and the run would pass — and the table is
  the only place a beat *without* a still (every click, every spotlight, the
  shape of the take) shows up at all.

Alongside them: `schema` matches the `TIMELINE_SCHEMA` the package exports,
indices match positions, timestamps are monotonic and inside the mp4's
duration, the recorder's own `duration` matches ffprobe, and every `still` a
beat names is a file on disk *and* every file in `images/` is named by a beat.

**Where the timestamps point** is the assertion worth having, and it is
measured rather than computed. Both takes set a caption after two seconds of
caption-band quiet; the band is then sampled every frame around what
`timeline.json` claims, and the first frame that has travelled a quarter of the
way to the caption's final state is taken as when it appeared. A quarter, not
"any change at all", because the bar fades in over 0.3 s and those two
definitions are a third of a second apart. The run-up is validated too — but on
frames well before the crossing, never the ones just before it, which *are* the
fade partway up and would read as a busy run-up on any take whose fade got
captured as a ramp.

Both the take's first caption and its last are timed, and the skew is graded
three ways, because the two directions have different causes and only one of
them is the beat log's:

Every reading is taken **after the host's wall clock is subtracted**, and
that is the part to understand before trusting this axis
([#215](https://github.com/rogvid/skills/issues/215)). Chromium stamps every
screencast frame with `Page.screencastFrame`'s `metadata.timestamp` — wall
clock by the protocol's own definition — and Playwright turns that straight
into the frame's position in the webm, while the beat log is
`time.monotonic()`. On a host that steps its wall clock the two part company
by exactly the size of the step, at exactly the instant of it. So `HostClock`
samples `time.time() - time.monotonic()` beside every recorded take, in this
process, and each probe is measured against `t_start + steps_before(t_start)`.
The raw figure is printed next to the corrected one, always, so a take that
really did lose 0.8 s of video says so.

| | bound | why |
|---|---|---|
| log **ahead** of the frame | 250 ms | nothing about the capture can move an event *later*, so a positive skew is the log's own error |
| video **ahead** of the log, host clock subtracted | 750 ms | what is left once the host's steps are out: the gap before the screencast's *first* frame, which the video's zero is, plus the 40 ms sampling grid and the caption's fade. Measured at 20-140 ms over fifteen idle takes and **500-540 ms at load 3.1** — it is how long Chromium takes to paint, so it stays wide on purpose ([#78](https://github.com/rogvid/skills/issues/78) is what tightening it would become) |
| the two probes **drifting apart** | 250 ms | whatever the capture loses at the head, it loses for every frame equally, so it cancels here — and a wall-clock step landing *between* the probes is now subtracted per probe rather than reaching this bar. **This is the sharp one, and the correction is what made it sharp:** before it, 680 ms of drift on a healthy recorder was indistinguishable from a beat log that was not being read monotonically |

Observed across eight consecutive `--web-only` runs and six full runs, both
media: first caption **-80 to -200 ms**, closing caption **-160 to 0 ms**,
drift **0 to 80 ms**. Nothing came near the 250 ms *ahead* bound — no run has
ever produced a positive skew — which is the point of splitting by direction:
the tight bound guards a failure mode with no natural variation near it.
`_t0` set after `_start()` instead of at page creation measures **+320 ms** and
fails it; `_t0` set 0.9 s *early* measures **-900 ms** and fails the second
(`tests/smoke-inject`, "every beat is stamped 0.9s after the frame it
describes"); a beat clock running 3% fast drifts **-360 ms** and fails the
third.

`TICKER_JS` is still injected for the length of both storyboards, and what it
is for is now smaller than this file used to claim. Instrumenting Playwright's
driver to log every screencast frame shows that an idle page loses **no** wall
time on Playwright 1.62.0 / Chromium 151.0.7922.34: the recorder numbers each
frame from its timestamp and writes the gaps into the webm's cluster
timestamps, so 30 s of a take with nothing painting at all — seven frames in
total — came back the full 30 s long. The 3/3-idle-stalled measurement that
justified the ticker is the wall-clock step, sampled six times without the
clock being watched. The ticker still buys frames to *measure* — a caption
transition can only be timed to the nearest frame the screencast sent — so it
stays, with its claim reduced to that.

The recorder's determinism controls ([#10](https://github.com/rogvid/skills/issues/10))
land an animation on its final frame — which is exactly what the ticker must
not do, and how a green harness could quietly stop being one. Two things keep
them apart, and both are asserted rather than assumed:

- **The freeze is of the wall clock only.** `Date.now()` and `new Date()` stop;
  `performance.now()`, the document animation timeline, and
  `requestAnimationFrame` do not, and CSS animations run on the second of
  those. The web take samples the page at its start and at its end and fails
  unless the wall clock moved **0 ms** while the monotonic clock moved seconds.
- **The motion rule cannot match an opt-out.** It is written
  `*:not([data-demo-video-animate])…`, and the ticker carries that attribute.
  `start_ticker()` reads the ticker's computed `animation-duration` *and*
  plants a control element with the same animation and no attribute: the take
  fails unless the rule flattened the control to `0.001s` and left the ticker
  at `0.18s`. Checking only the ticker would pass just as happily on a
  recorder that had stopped injecting the rule at all. Both takes pass
  `deterministic=True` for this reason — under the recorder's default the rule
  is not injected and the control assertion would have nothing to say.

When the measurement cannot be made the run says which reason it was: a caption
that was never drawn, a video that slid further than the search window can see,
or a run-up that was not quiet. They look identical from inside the window, and
only the first is the recorder losing a caption.

**Review frames** — the `frames/` a reviewer is actually handed: one PNG per
beat, and `frames.md` embedding them in order. What is graded is what the
recorder claims, and it deliberately claims very little:

- **One frame per beat, named for it.** Counted against the hand-written
  `WEB_BEATS`/`TERMINAL_BEATS`, so a dropped frame, a doubled one or an
  off-by-one name fails without a pixel being read. Every file on disk is named
  by the manifest and vice versa.
- **Each frame is the moment it says it is.** Two halves, and only together.
  Its timestamp must be its beat's midpoint **moved onto the video's clock by
  this harness's own wall-clock watcher** ([#229](https://github.com/rogvid/skills/issues/229)),
  computed *here* from
  `timeline.json` — not imported from the recorder, and not corrected with the
  take's own `capture_clock`, because a check that re-derives its expectation
  from the numbers it is grading passes on whatever they say. A beat whose
  midpoint sits within `MAX_CLOCK_STEP_TIME_DISAGREEMENT_S` of a step is not
  placement-graded and is counted in the arm's output: two samplers on their
  own 20 ms grids do not both know which side of a step a beat fell on.
  And the PNG must be that frame: the harness **cuts the same second
  out of `demo.mp4` again and compares the bytes**. 56 of 56 identical across
  the three graded takes — 23 web, 18 terminal, and 15 off the stitched
  `segments/` demo; one frame away (40 ms) is already a different file.

  Exact rather than approximate, because approximate does not work here. A PNG
  and a decoded video frame reach a luma reduction through different colour
  conversions and sit ~1.0 mean luma apart *when they are the same frame*,
  while two moments three seconds apart in this fixture differ by 0.87 (a
  filtered table and a refreshed one are mostly the same white page). A
  threshold loose enough to absorb the first cannot see the second — measured,
  by injecting exactly that and watching it pass.
- **The sheet says which clock it cut them on.** On a host whose clock never
  steps the corrected instant and the uncorrected one are the same number, so
  nothing above can tell a recorder that applies `capture_clock` from one that
  ignores it — but "a correction was applied" and "nobody could compute one"
  are still two different sentences over identical timestamps. `frames.json`
  must carry the answer, `frames.md` must say it in words, and a sheet that
  reports no correction on a take *this harness* watched to within its own
  interval is a failure. One `smoke-inject` entry breaks each half.

- **The sheet leaks no storyboard.** `frames.md` goes to a *context-free*
  reviewer who is asked what story the pictures tell. It is searched for every
  caption in `WEB_CAPTIONS`/`TERMINAL_CAPTIONS` and every selector in the beat
  list, and finding any of them is a failure; `frames.json` must carry no
  `caption`, `verb` or `selector` key, because a manifest that duplicates the
  storyboard is how it ends up back on the sheet.
- **A re-run clears the previous run's frames**, and only those. `beat_frames()`
  is called a second time with a planted `beat-99.png` and a planted file it did
  not write: the first must be gone, the second must survive, and the frame list
  must be identical. SKILL.md advertises the re-run and step 6 tells a reviewer
  to read the whole directory, so a storyboard that lost beats between runs
  must not leave plausible-looking frames from a demo that no longer exists.
- **A single segment's timeline gets no frames — and only that.** Graded by
  handing `beat_frames()` this take's own timeline with a segment name on it:
  it must write nothing and say why. Both reasons are properties of that
  document, not of the world around it: its beats are numbered from zero, so
  two segments collide on `beat-00.png`, and its `media` is a `.seg.mp4` that
  `stitch()` deletes on its way to `demo.mp4`. Neither survives the merge, so
  the **stitched** demo gets frames like any other take — the `segments/` take
  runs the whole of this axis, `_check_frame_captions()` included, against the
  15-beat merged timeline `stitch()` writes.
- **Frame N shows beat N** — issue #8's acceptance criterion, and the only
  claim here about a frame's *content*. For every beat the hand-written
  storyboard says had a caption bar up, the frame must show one; for every beat
  it says had none, the frame must not. Decided by ranking rather than by a
  threshold: each frame's caption band is reduced and measured against the
  take's own first caption-off frame, and every captioned frame must sit
  further from that baseline than every uncaptioned one, by at least
  `MIN_ALIGN_BAND_DELTA`. Observed margins: web 8.1, terminal 2.3, segments
  16.6. A recorder that stopped drawing the bar, or extraction that returned
  one picture for every beat, collapses the two groups together and the margin
  goes to zero — there is nothing to tune past it.

  **One bit per frame, deliberately.** *Which* caption is a stronger claim and
  this band cannot carry it: two of the fixture's own terminal captions sit 1.5
  mean luma apart against a 1.0 floor, so a check that named them would be
  reporting noise. That is [#60](https://github.com/rogvid/skills/issues/60).

  **And a stated tolerance, which is the honest part.** The video runs ahead of
  the beat log ([#18](https://github.com/rogvid/skills/issues/18)), so a frame
  cut at a beat's midpoint shows a moment slightly later in the story than that
  beat. Frames within `FRAME_CAPTION_GUARD_S` — the same `MAX_CAPTURE_LOSS_S`
  the skew bars use, 750 ms — of a caption *change* are therefore not graded:
  that close, the log and the video genuinely disagree about which side of the
  change a frame is on. This is not theoretical. Set the guard to zero and the
  suite fails on `segments/beat-13.png`, the frame for a 50 ms `shot()` beat
  that ends 25 ms before a caption clears: the video is ~80 ms ahead, so the
  entire beat is already past the change and the frame shows the *next* beat's
  screen. `MIN_GRADED_CAPTION_FRAMES` and a one-of-each-class rule keep the
  guard from turning the check off — set it to 3 s instead and the suite fails
  with "only 0 of 23 review frames … were graded".

**What is still not graded: which caption a frame shows.** The recorder makes
no such claim, and neither does this file. An earlier round graded a caption
printed under each frame by reading the caption bar back out of the pixels;
that measurement worked, and the thing it was measuring did not. The recorder
inferred which caption a frame showed by locating caption transitions in the
video, and review found the inference mislabelling frames on ordinary
storyboards: two captions of the same length change under 0.25 mean luma in the
band against a 1.5 floor, an app repainting under the bar supplies a stronger
and earlier edge than the caption does, and a mid-take `goto()` destroys the
bar while logging no caption change to measure. The claim was withdrawn rather
than tuned — see [#60](https://github.com/rogvid/skills/issues/60), which is
what earning it back would take.

**Scene-change detection**, the fallback for what the storyboard did not
script, is graded directly against `demo.mp4` rather than through a take: no
beat in either storyboard runs the 3 s the recorder needs before it reaches for
it, and stretching one to provoke it would cost every run the seconds. It must
see the largest change a take contains and stay quiet where nothing moves.

The positive half — at least one cut somewhere in the video — is **web only**,
and that is about the medium rather than a convenience. The biggest thing that
happens to the web frame is the caption bar arriving, at 0.023–0.026 against
the recorder's 0.02 threshold, while *nothing* in the terminal take reaches it:
its largest change is two lines of shell output on a dark background at 0.011,
against an idle 0.004. At a threshold separating those, an ordinary terminal
repaint would be reported as a cut. Tracked in
[#57](https://github.com/rogvid/skills/issues/57), which proposes scoring the
app's rect instead of the whole composited frame.

The quiet half runs on both, over the stretch after the **last beat's logged
end** — where the recording holds its closing frame until it stops. Anchored
there rather than in the middle of the take because the video only ever runs
*ahead* of the beat log (#18), so the real end of that beat is at or before
this; a first version picked "the middle of the longest pause beat" and a take
that stalled 540 ms slid a caption change into it on the first run.

**Problems** — what the recorder saw *behind* the pixels. This is the axis the
other four are structurally blind to: a demo of an app throwing `TypeError` on
every render is pixel-for-pixel a demo of a working one, scores the same luma,
logs the same beats, and satisfies every post-condition the storyboard checks.

It splits four ways, and no single take answers more than one of them — which
is why there are seven takes and not two.

**A healthy app must record nothing.** The two graded takes record the plain
fixture, with `strict=True`, and `check_healthy()` demands an empty `issues`
list. This is the only assertion here that can fail on **over**-reporting, and
without it the axis is one-directional: every check below is "at least one
issue matches", which a recorder that flagged every healthy 2xx as a fatal
console error satisfies perfectly — while refusing every strict take of every
working app ever recorded. That is not hypothetical; it was measured passing
the entire suite before this existed. Recording them strict is the second half:
over-reporting does not merely get noticed, it aborts the take.

Keeping the graded takes healthy also matters for what they *are*. They are the
reference demo a reader watches; the fixture hooks belong in takes of their
own, the way `?evidence=1` does.

**A broken app must record what broke, where.** `web-problems/` loads
`?console-error=1&bad-fetch=<url>`: the fixture logs a `console.error`, throws
an uncaught error, and fires two doomed requests — a 404 and a connection
refused on a port nothing is listening on. All four fire **during page load**,
on purpose, so the recorder's `goto` beat is open and there is a real
attribution to check. `terminal-problems/` runs `(exit 3)` — a subshell, so the
recorder's own shell survives, and 3 rather than 1 so the assertion proves the
*status* was read and not "something failed" inferred from elsewhere.

Two cases in `web-problems/` exist because the obvious implementation of
attribution — blame `self._beats[-1]` — is wrong in both directions:

- an error thrown **one second into a three-second hold** must land on the
  `pause`, under the caption that was on screen, not on the caption beat that
  follows the hold. Without the recorder pumping events as it waits, it lands
  on the later beat and gets stamped with a line that did not exist when it
  fired. Both the beat *and* the caption are asserted.
- an error logged **between two verbs**, where no beat is open, must come back
  `beat: null`. A confidently wrong index is worse than no answer.

These takes are graded on `timeline.json` alone — nothing about their video is
checked. They also carry the other half of the strict assertion: the **default**
recorder tolerates every one of these problems and still writes every artifact.

| Checked | Why |
|---|---|
| each deliberate problem appears, by kind and message | the whole axis |
| …attributed to the beat it fired during — `beat` indexes a real beat *and* that beat's `verb` is the expected one | `verb` alone is a string the recorder could copy from anywhere; `beat` alone is an integer that means nothing. Together they say the attribution is real and right |
| …or to no beat at all, when none was open | the null case above |
| …under the caption that was up when it fired | the field a reviewer reads as context; quoting a later line is the failure a wrong beat index produces |
| `run` beats carry the exit status of their command | hand-written like the beat lists, `{echo ok: 0, (exit 3): 3, sleep 1: 0, (exit 9): 9}` |
| `nonzero_exit` is in the package's `STRICT_KINDS` | links the recorded data to the policy: recording a failing command that strict would ignore is not catching it |
| `issue_count` equals `len(issues)` | nothing here comes near the 200 cap, so the two disagreeing means one is wrong |
| every `kind` is in `ISSUE_KINDS` | the published contract, not whatever the recorder felt like emitting |
| `timeline.md` has an Issues section naming each, and an exit column | the human-readable half of the log must not say the take was fine |

**An exit status must be right or absent, never wrong.** Two shapes of that,
both found by review after the first round shipped them silently wrong:

- `terminal-problems/` types `sleep 1` and `(exit 9)` with **no wait between
  them**. The shell buffers the second and runs it after the first, so both
  statuses arrive in order and must reach different beats. A single pending
  slot gave `sleep`'s 0 to `(exit 9)` and dropped the 9 — a *wrong* exit code,
  which strict passes, rather than a missing one.
- `terminal-race/` runs against a shell that **sleeps 1.2 s before exec'ing
  bash**, with typing instant, so `run()` finishes before the shell has printed
  its first prompt. That prompt reports the shell's own 0, and a recorder that
  takes the next marker it sees writes that 0 onto the command. Its own take
  because the condition has to be manufactured: on a normal box the startup
  prompt always wins, and removing the guard passes every other take here.

**Strict mode must refuse what the default tolerates.** `web-strict/` and
`terminal-strict/`, deliberately tiny. Each must raise `StrictTakeFailed`, the
message must **name the beat** (issue #3's acceptance criterion verbatim,
matched as `beat N (verb)`), it must name the kind the storyboard caused, and
**demo.mp4 and timeline.json must still be on disk** — a broken take is
precisely the one somebody wants to look at, so failing it by destroying the
evidence would be worse than not failing it.

**Determinism** — recording the same storyboard twice produces the same
recording. Three extra takes, each about six seconds, against `?entropy=1`: a
page rendering what a re-record is otherwise free to differ by — four
*different* clocks, and a spinning shape.

Four, because they are four clocks under the hood and patching the `Date`
global reaches only the first. `Intl.DateTimeFormat().format()` formats from
its own internal clock, a `Worker` has its own global that page init scripts
never run in, and `new Date().constructor` walked straight past a proxied
global to the real constructor. All three were found running behind a frozen
`Date.now()`, by two takes that differed while every assertion passed.

| Take | `deterministic` | What it is for |
|---|---|---|
| `determinism-a` | `True` | the reference |
| `determinism-b` | `True` | must match `determinism-a` |
| `determinism-off` | *not passed* | must **not** match — grades the default |

The third take passes no `deterministic` argument at all, deliberately. The
frozen clock is opt-in (it changes what a debounce, a token check or an
elapsed-time bar does, usually silently), so the default is the setting every
user gets and the one worth grading. The web and terminal takes above go the
other way and pass `deterministic=True` explicitly, because that is where the
frozen clock and the motion rule have to be shown coexisting with
`TICKER_JS`.

What is compared, and why each comparison is not free:

- **The stills, byte for byte.** They are lossless PNGs of a frozen page, so
  there is no threshold to argue about and no encoder noise to tolerate:
  `sha256(a/01-entropy.png) == sha256(b/01-entropy.png)`, or the take failed.
  This is the sensitive one — it catches a four-digit change in a timestamp,
  which nothing measuring luma will. The same two stills are also compared
  *within* `determinism-a`, a second apart on a page nobody touched, and that
  is the comparison that catches a running animation: headless Chromium turns
  out to reproduce animation phase across two takes of an identically-paced
  storyboard remarkably well (a spinner exempted from the motion rule produced
  byte-identical stills in both takes and was caught only within one).
- **…and the same two stills inside `determinism-off`, which must differ.**
  This is the assertion that keeps the ones above honest. Two blank screenshots
  are byte-identical too, and so are two files a comparison forgot to read. The
  same storyboard, the same page, nothing pinned: 28.6-30.0 mean luma over the
  spinner, against a 4.0 floor.
- **The video, where bytes cannot be compared.** H.264 at crf 20 is not
  byte-reproducible and the screencast's frame timing is not either, so the
  closing frame of each take is sampled over the entropy panel instead: two
  deterministic takes score 0.00-0.59 mean luma apart, a deterministic take
  against `determinism-off` scores 6.85-7.22. Both bars (1.5 and 2.5) sit in
  that gap, and **both directions are asserted** — the second is what says the
  comparison can see a difference at all. Know what it cannot see: a *coarse*
  measure over a 160x90 reduction, it caught a whole panel changing colour
  (24.14) and did not notice four digits of a timestamp changing (0.22). The
  stills are what make the fine claim; this makes the claim about the artifact
  people actually watch.
- **The clock the page printed.** Frozen takes must agree on it, and
  `determinism-off` must disagree with them. Printed on every run, so a reader
  sees which instant was frozen and what the live clock said.
- **What the page reports about itself**, in every take including the web and
  terminal ones: `Date.now()`, `new Date().toISOString()`, the resolved
  timezone and locale, `navigator.language`, `prefers-reduced-motion`, and the
  computed `animation-duration` / `transition-duration` of a probe element
  planted for the purpose. Read from *inside the page*, never off the
  recorder's own attributes — a constructor that stored `deterministic=True`
  and forgot to wire it to the context satisfies any check made in Python.
  With determinism unasked-for, every clock-related one is asserted the other
  way, including that the page's clock is within five minutes of this
  process's — while timezone, locale and reduced motion are asserted *pinned*
  in both, because those three are not gated on `deterministic`.

  Four of those checks are not clock readings at all and hold in both modes:
  `Date.prototype.constructor === Date`, `Date.now === Date.now`,
  `Date.now.name === "now"`, and the flattened durations being **1 ms rather
  than 0s**. The proxy that freezes the clock is exactly what breaks the first
  three, and a transition of zero duration never starts — so it never fires
  `transitionend`, and every accordion, modal and wizard that advances on that
  event stalls. Both were live regressions, caught by review rather than by
  this harness, which is why they are asserted by value and not by "not the
  original".

Before any of that, each still has to have a picture in it at all, on the same
whole-frame luma floor the web take uses (6.0, healthy 15-17). Two blank
recordings reproduce beautifully.

And one reading is checked in the DOM rather than left to the pixels: the
worker's. The fixture falls back to rendering `worker unavailable` if the
`Worker` constructor throws, and that reproduces byte for byte across takes
exactly as happily as a frozen timestamp does — so a wrapper that broke every
worker on the page would pass this whole phase on the strength of failing
consistently. The take reads the line and requires `worker <frozen epoch>`.
All three takes also run `strict=True` (issue #3's machinery), which is what
would catch the blob shim breaking worker *loading* rather than its clock.

**Segments and the merge** — a demo recorded in two parts and joined by
`stitch()` ([#7](https://github.com/rogvid/skills/issues/7)). `segments/`
records the storyboard `SKILL.md` prescribes for a real time-skip: part one,
then a second `Recorder(segment=…)` that opens with an `interlude()` on the
blank page before navigating back. Each part writes its own `.seg.mp4` and its
own beat log; the demo-wide `timeline.json` is assembled from them.

**The merged timeline is graded by `check_timeline()` — the same function, and
the same assertions, that grade a single take.** That is the point rather than
an economy: the beats, the captions, the per-beat caption context, the
monotonicity and coverage of the timestamps, `timeline.md`'s table, the stills
on disk, and the measured "does this timestamp point at that frame" check all
apply unchanged. A segmented demo graded more softly than a recorded one is a
segmented demo nobody can trust. What the merge adds is a hand-written
*segment* column — a stitch that merged part one twice produces a perfectly
monotonic timeline of the right length, and only that column notices.

The offsets are the parts' **ffprobe durations**, never the storyboard's
nominal timing, and that distinction is load-bearing: the screencast drops
wall time during idle stretches, so a segment's video routinely runs ~0.9 s
shorter than its beats say it took. Injecting nominal timing here moves the
second segment's beats 2.1 s off their frames.

**How the acceptance criterion is measured, and why it can be stated at
100 ms.** Every segment carries a probe caption with a quiet run-up, and each
is timed *twice* — once in that segment's own `.seg.mp4` against that
segment's own beat log, and once in the stitched `demo.mp4` against the merged
one. `stitch()` copies the streams, so those are literally the same frames
carrying the same capture loss, and the **difference** between the two skews
is that segment's offset error with issue #18 cancelled out. Measured across
several takes: **+0 ms** for both segments, against a 100 ms bar; the absolute
skews behind them ranged -200 to +0 ms. A bar on the absolute skew could not
be set anywhere near that, because a segment whose capture stalled shows every
caption early in its own video too.

**One probe per segment, and that is load-bearing rather than thorough.** The
differential at segment *k* measures `offset_true - offset_recorded` for that
segment and nothing else. Timing only the last segment therefore checks only
the last cumulative offset: a constant shift applied to segment one's beats
leaves it exact, and with three or more segments every intermediate offset
would have no pixel measurement at all. That is not hypothetical — an earlier
round of this file timed one beat, and injecting +350 ms onto segment one
passed, printing `beat clock holds across the take (+400 ms)`.

The other half is each segment's *own* skew, graded against the same
directional bars a single take gets (250 ms log-ahead, 750 ms video-ahead) but
read out of that segment's own mp4. The differential cancels capture loss on
purpose, so it is blind by construction to a segment whose own video has slid
away from its own beat log; this is where that shows up, per capture.

Between them, `MAX_SKEW_DRIFT_S` across a boundary has nothing left to say,
and it is explicitly **a flake guard rather than a check**: the take's two
probes sit in different segments, so they rode different screencasts, each
with its own ~0.7 s of untickerable recorder setup, and a stall in the second
moves only the second. Measured across four takes: -80, +80, +80, and one at
**-520** — a real segment-two capture stall, not a merge error, which a 250 ms
bar here would fail on about one run in four. It is widened to one capture-loss
window for that reason alone, and the file says so where the number is set. A
constant shift of any segment's beats is caught by the two measurements above,
at 100 ms, not by this one at any width.

The rest is what is true of a merge and of nothing else:

| Checked | Why |
|---|---|
| before any stitch, each part has an `.seg.mp4` *and* an `.seg.timeline.json`/`.md`, and no `demo.mp4`/`timeline.json` exists yet | the cleanup assertion below is otherwise satisfied by a recorder that never wrote them, and every path assertion by a leftover |
| each part's own log starts within `MAX_UNMERGED_FIRST_BEAT_S` of zero | "the merged timestamps are large" proves nothing if they were large before the merge |
| `stitch(keep_parts=True)` leaves every part **and its beat log** | re-recording one expensive segment and re-stitching is the whole reason that flag exists, and it needs the logs as much as the mp4s |
| stitching twice produces the same beats | the merge has to be a function of what is on disk |
| the default `stitch()` leaves **no** `*.seg.*` at all | [#21](https://github.com/rogvid/skills/issues/21): a `.seg.timeline.json` outliving its `.seg.mp4` names a file that is gone, and the next stitch cannot tell it from a fresh one |
| the merged envelope's `segments` records, **all six fields**: `segment` / `media` in order, `duration` / `offset` against ffprobe and tiling `demo.mp4`, and `beats` / `recorder` / `determinism` against the segment's own log | it is what maps a merged timestamp back to the file it came from, and `SKILL.md` points a reader at the last three for the per-segment truth the envelope cannot carry once segments disagree. Checking only the first four was measured passing with `beats` hardcoded to 0 and `recorder` to `"Bogus"` |
| `segments[].beats` also equals how many merged beats carry that segment | the two can only differ if the merge dropped or duplicated some |
| `stitch()` refuses parts that disagree on codec, geometry, frame rate, or having an audio track | `concat -c copy` joins them and exits 0. A frame-rate mismatch was measured putting a beat **1.92 s** from its frame; a geometry mismatch silently keeps part one's dimensions; a silent part followed by a narrated one makes concat drop the narration entirely. None is reachable through the shipped recorders — nothing enforced it at the join |
| `stitch()` refuses a segment log written for a different recording of that segment | the `media`-name check cannot see it: both sides derive from the same segment string. Re-recording one part and merging it against the previous take's log is the ordinary way to get here, and it was accepted silently (6.6 s log against a 2.0 s part) |
| every part is probed *before* ffmpeg runs, and `.concat.txt` is removed even when it fails | a truncated part makes concat exit 0 and `media_duration` raise afterwards, leaving `demo.mp4` with no `timeline.json` — the one state a reader cannot tell from a demo that never had beats |
| `index` is renumbered to the position in the merged file, `segment_index` is **not** | [#22](https://github.com/rogvid/skills/issues/22): `(segment, segment_index)` names a beat the same way before and after a merge, which `index` alone cannot. Asserted in every take, not just this one — for a single take it is 0, 1, 2, … |
| a take recorded in one piece carries no `segments` key | that key means "assembled by stitch()", and a reader would otherwise be told a single recording has parts |


**Evidence** — every beat left `evidence/<segment>.seg.beat-NN.json`, a text
account of what was on screen, and it says what it does not know.

**Most of this axis used to be about masking** and went with it (#150). The
`evidence/` take once recorded nine redacted cards, swept every file it wrote
for thirteen literals, and graded the mask's edges: a value split across tags,
one spelled with an `&`, one mirrored into a `title` attribute, a card
rewritten every 5 ms that had to refuse capture rather than guess. None of
those shapes exists now — per-beat evidence is not a masking feature, and what
survives is what it was always for: a reviewer reading what a frame showed
without decoding it.

So the assertions were **written rather than trimmed**, and there are three:

- **the page text is real.** Every other check here is an absence — this
  attribute is not in the markup, this script text is not — and an absence
  holds trivially in an empty file. The control asserts that the fixture's own
  rendered string is in the ARIA tree, over a floor of 400 characters, before
  anything else is claimed. It is the catalogue's vacuous sweep, and it is the
  one assertion that fires if the capture wrote nothing. The control beat
  measures 1,463 characters since #145 took the leak-shape panel out of that
  view — a narrower margin than the ~2.3 kB it had, and worth knowing before
  anything else is deleted from the fixture.
- **the markup serializer drops what was never on screen.** Inline `<script>`
  text, a `srcdoc` document, and value-bearing attributes (`data-*`, `title`,
  `href`, …). This survives `redact()`'s deletion for a reason that has nothing
  to do with secrets: an attribute nothing renders was in no frame, no still
  and no caption, so serializing it here would make evidence the only place it
  exists. **It had no check of its own** — every old one reached the same code
  through the mask, so deleting the mask deleted the only thing watching a
  serializer that still has this job. The take now injects an element holding a
  script and a `srcdoc`, spotlights it, and requires neither in the markup.
- **truncation is marked, never silent**, on all three text fields — `aria`,
  `scope_aria` and `html` — cut *to* the budget with only the marker past it,
  and named in `truncated`. A cap applied to `aria` and not to `scope_aria` is
  a cap on a third of what a spotlight beat writes.

Plus the two that never touched masking: a previous take's evidence is cleared
from the directory on a re-record while another *segment's* files survive, and
the beat's `evidence` pointer is what names the file rather than anything
derived from `index`.

**The three new assertions were fault-injected**, since none of them had ever
been watched to fail:

| break | what fired |
|---|---|
| `drop(clone, 'script,…')` stops naming `script` | beat 6's `html` carries inline script text, and a `<script` tag |
| `srcdoc` leaves the stripped-attribute list | beat 6's `html` carries a srcdoc document, and the attribute |
| the page ARIA snapshot returns `""` | beat 2's tree is 0 characters, under the 400 this grades |

**Narration** — the take really spoke, waited for itself, and the audio landed
where the line did. Recorded from a seeded cache, as described above.

Four things, and the third is the one the axis exists for:

- **nothing was synthesized.** `.tts/` holds exactly the files seeded before the
  take and no more. A new file means the recorder computed a different key than
  this harness did — the two are written independently on purpose — and went
  looking for it.
- **a beat cannot start while the previous line is still speaking.** The first
  line's clip (1.6 s) outlasts its beat's hold (0.5 s), so the *next* beat's
  `t_start` must be at least 1.6 s after the line began. `_finish_line` idles
  between beats, so this gap is the only place the wait is observable.
  **With a control**: the second line's clip is 0.3 s and finishes inside its
  hold, so nothing is added — a recorder that idled a fixed amount after every
  line passes the first bar and fails this one.
- **the mix carries audio where a line is, and silence where none is.** Mean
  volume over a 0.4 s window, measured with `volumedetect`. Inside the first
  line it must clear −60 dBFS; over the window *before* it, it must stay under
  −80. **Neither bar means anything alone.** A silent track passes every other
  assertion in this suite — it is present, `aac`, stereo, 44.1 kHz, and exactly
  as long as the video — and that is precisely the failure that leaves every
  artifact looking healthy. A track of noise, or a mix that laid one clip across
  the whole timeline, clears the loud bar everywhere and fails the quiet one.
  Measured on the seeded tones: **−25 dBFS inside a line against −91 before
  one**, so both bars sit a long way from either number.
- **the stream is shaped the way `stitch()` needs.** `aac`, 2 channels,
  44100 Hz. `_convert` pins these with `aformat` rather than letting `amix`
  decide, because mono TTS clips otherwise yield a mono track that `-c copy`
  cannot concatenate with the stereo silence of a segment that narrated nothing.

**All four were fault-injected**, none of them having been watched to fail
before:

| break | what fired |
|---|---|
| `_finish_line` stops idling out the remaining clip | *the beat after a 1.6s line started 0.56s after it began — the recorder cut its own narration off* |
| `_convert` takes the `anullsrc` branch with lines present | *the window inside the first line measures −91.0 dBFS, under the −60.0 this grades* |
| `adelay` is pinned to 0 instead of the line's offset | *the window **before** the first line measures −19.4 dBFS — audio is playing where no line was spoken* |
| the `aformat` filter is dropped from the graph | *audio channels is 1, expected 2 — stitch() cannot join streams that disagree* |
| `_tts_key` hashes different text than the harness seeds | the take raises: `ElevenLabs TTS failed: Connection refused` |

**Two of those rows are now executed rather than remembered.** The first and
the third are entries in `tests/smoke-inject`, aimed at `--narration-only` at
8 s each, and the manifest re-performs them nightly
([#238](https://github.com/rogvid/skills/issues/238)); two re-runs read
*0.55-0.57 s* and *−19.4 dBFS* against the 0.56 s and −19.4 dBFS recorded here
by hand. The other three rows are still prose — a break somebody performed once,
which nothing repeats, which is the exact condition #136 exists to end.

The last one is why `TTS_API_BASE` exists as a module constant. Before it, that
break put `NARRATION_KEY` on the wire to `api.elevenlabs.io` and read a 401
back — an outbound request carrying a fabricated credential to a third party, on
a path somebody breaking things deliberately is *expected* to take. The take now
pins the endpoint to a closed local port for its duration, so a miss cannot
leave the machine.

### How the recording looks — the spotlight's exit, and the card a terminal segment opens on

Two takes, and the only two in this file that grade defects **a human found by
watching**. Everything else here grades something a viewer cannot see; these
grade the picture, from the viewer's side, out of nothing but pixels.

`spotlight/` records with the recorder's **default**, `deterministic=False`,
which no other take does. That is not a preference: the determinism rule
flattens every CSS transition to 1 ms with `!important`, so under it the
spotlight's enter and its exit both snap, both are correct, and an assertion
about easing cannot fail for the reason it claims. Injecting `deterministic=True`
into the take is one of the arms below, and it fires the control.

**A transition is measured as the states it passes through.** Around each
spotlight beat, every frame of the element's crop is scored by how far it is
from the settled frame at the end of the window, as a fraction of how far the
frame at the start of it is; a frame between 12% and 88% is one the transition
was part way through. A snap produces none — not "few": there is no
intermediate state for a frame to be in. The first version of this counted
frames that *changed*, which is not the same claim and is not safe: a hard cut
in H.264 rings for a frame or two afterwards, so a snap also produces three
consecutive frames that differ from each other, and the bar had to sit
uncomfortably close to them.

|  | enter | exit |
|---|---|---|
| eased, four takes | 3-4 | 3-4 |
| the pre-#111 clear, injected | 3-4 | **0** |
| recorded with `deterministic=True` | **0** | **0** |

The **enter is a control, not the thing under test**: it eased before the change
and eases after it, so it reads 3-4 in every arm where the recorder is
non-deterministic. A run where the exit is the only empty one is a reading about
the exit; a run where both are empty is a reading about the take's settings, and
says so in its own message.

Two things pixels cannot say are asserted in the storyboard instead. The
element's inline `style` must be **identical before and after** — attribute
present or absent, and its value — which is #111's other half and is invisible
in every frame. And `spotlight()`'s clear must **take at least 0.45 s**, which
pins the decision that the verb waits out its own exit. That second one exists
because injecting a clear that resolves early *passed* a version of this take
that only compared the style: the verb ends in a 300 ms pause, so a style read
after it is 300 ms too late to see a restore that was still pending. A lower
bound on a wait is also the one timing bar contention cannot turn red.

`terminal-opening/` records a segment opened with
`TerminalRecorder(interlude=…)` and reads **one corner of the frame**, outside
the terminal window, at 20 fps for the whole take:

| | mean luma |
|---|---|
| the card (`#1c1a17`, full bleed) | 26 |
| bare terminal (the recorder's pastel gradient) | 226 |

Neither number is a threshold anybody tuned — they are two constants in the
recorder's own styling, an order of magnitude apart, and the corner is read off
the live `#__term_win` box rather than hardcoded. Three statements, each broken
by a different mistake: the recording's **first** frame is card; the card
covers at least the first second (it is held 2.5); and the corner **does** end
up bare, which is the control — without it, the first two are equally true of a
recorder that painted a black rectangle and stopped, and that is exactly
[#91](https://github.com/rogvid/skills/issues/91).

Nine injections, each one exact string in one file, with a driver that refuses
to run unless the pattern matched exactly once:

| injected | what fires |
|---|---|
| the pre-#111 clear (restore the whole style attribute in one assignment) | exit passes through 0 intermediate frames |
| the individual reverts kept, but the attribute restored in the same frame | exit passes through 0 |
| record the take with `deterministic=True` | the enter control reads 0, and says which of the two causes it is |
| the enter's `transform` removed | "the highlight never went on, so the exit measurement is about nothing" |
| the clear leaves `style=""` on an element that had no attribute | the before/after style comparison |
| the clear's promise resolves before the transition ends | the 0.45 s bar |
| the card raised 400 ms into the document instead of at document start | first frame is bare, and the prefix is 0.00 s |
| the card built at `opacity: 0` like `interlude()` builds it | the same two, plus the content floor |
| the card never cleared | "the corner never reaches 150 mean luma — the card is never taken down" |

**What this does not catch**, and is a stated limit rather than an oversight: a
card that *fades in* over 450 ms rather than being painted opaque is invisible
here. Measured — a faded-in card and a painted one produce byte-identical
corner readings for the first 14 frames, because the recorder spends longer
than the fade injecting xterm.js before Chromium's screencast emits anything.
The recorder has no fade-in path (the element is appended already opaque, so no
transition can run), but the suite is relying on setup cost for that and would
not notice if it changed.

**The corner is the discriminator; the timeline gap is not, and it was written
down twice as though it were.** [#110](https://github.com/rogvid/skills/issues/110)
measured the flash as part2's offset against the interlude beat's timestamp
(37.76 s against 38.05 s), and
[#206](https://github.com/rogvid/skills/issues/206) restated that gap as the
measurement that would let the fix be graded without watching — *"the gap
should be absent rather than merely smaller"*. It is neither.
[#207](https://github.com/rogvid/skills/issues/207) measured both takes of the
same storyboard, one line apart, on one box:

| | before the fix | after |
|---|---:|---:|
| timeline gap | 0.358 s | 0.365 s |
| corner luma, first part2 frame | 226.5 (bare) | 25.8 (card) |
| bare-terminal frames before the card | 6 (0.30 s) | 0 |

The defect is gone and the gap moved **+7 ms the wrong way**, so the proposed
check would have reported the fixed take as marginally worse. The gap is
`TerminalRecorder`'s setup cost, not the flash: `_t0` is set before `_start()`,
which goes to `about:blank`, injects xterm.js, opens the PTY and waits for the
first prompt before it raises the card, so the first beat lands ~0.36 s into
the segment either way. A beat's timestamp says when the card was *logged*;
only the pixels say when it was up. The corner sweep discriminates it 226 → 26
at the boundary frame, across four re-records including one under load. This is
recorded here because nothing asserts on that gap today, and a number written
into two closed issues as *the* check is the kind that becomes an assertion
later — one that would look green forever.

### What a web take opens on (issue #119)

The third defect in this file found by a human watching, and the most plausible-
looking of the three: Chromium's screencast starts with the page, the page is
`about:blank` until the first `goto()` returns, and `about:blank` paints white —
so a web take opened on ~400 ms of flat white inside a *correct-looking* window
frame. It does not read as a broken recorder. It reads as an app that loaded
blank.

Nothing in this file moved when that shipped, and neither did the recorder's own
picture check: its `score` is a median, so it cannot see a leading blank shorter
than half the take, and `static_for` saw one 0.5 s gap against a 15 s limit.
Both are the right design for what they grade, and both are the reason this
needed its own assertion.

`check_opening` rides on the `web/` take rather than recording a fourth one, and
the placement is load-bearing: the fix is an overlay switched off part way
through, so no timestamp may move, and `check_beat_frames` in that same take
already matches each beat's frame against the caption that beat put up. A hold
that shifted the clock lands those frames on the wrong captions.

Two arms, and they fail for different reasons:

| arm | what it grades |
|---|---|
| `content.opening.held` is above zero | that this take **had** a gap to cover. Without it, frame zero shows the app whatever the recorder does, and the arm below grades nothing. |
| frame zero scores at least half the take's own median contrast | that the app is visible at t = 0, out of pixels — never through `opening_gap`, which is the code under test asking itself whether it worked. |

**The first version of the second arm graded nothing, and the fault injection is
what said so.** It sampled with `sample_fps=1` and read `frames[0]`. The `fps`
filter quantises to its own output slots, and at 1 fps slot zero is a whole
second wide — measured, it returns a frame from around 0.5 s, which on a broken
take is *after* the blank has ended. It scored 17.06 on a video whose first
frame was flat white. The window is now cut with `-t` instead, which decodes
from the file's own first frame: 17.25 healthy against 0.00 blanked. Reading the
assertion would not have found this; breaking the recorder did.

`check_opening_gap` is the other half, and it exists because **the recorded
takes can only ever show one of the two shapes**. A web take always opens blank,
so nothing in this suite reaches the blank floor — the constant that stops
`opening_gap` firing on an app that painted immediately and then held still. Two
videos are synthesised with ffmpeg, no browser: white until 0.6 s then colour
bars (must measure 0.6 s), and colour bars throughout (must measure 0.0). The
second is the control. Colour bars rather than `testsrc2` on purpose —
`testsrc2` animates, so a video of it changes every frame and could not express
"painted and holding still", which is the whole distinction being graded.

Injections caught:

| break | what fires |
|---|---|
| the hold is composited but switched off (`enable='lt(t,0)'`) | frame zero scores 0.00 against the take's median |
| the opening is never detected, so nothing is ever held | the premise arm — `held` comes back 0.0 |
| the blank floor is removed | the synthetic control: a static painted picture reads as a 1.95 s opening |

**What this does not cover.** Only the `web/` take is graded; the web segment
inside `segments/` and the entropy takes hold their openings too, and nothing
checks it there. And nothing here compares the held frames against what the app
*would* have shown — the hold is the app's own first painted frame, so a wrong
frame would have to come from somewhere else in the same recording.

### Acceptance-criterion coverage (issue #12)

The `coverage/` take is recorded against a three-criterion ticket and
deliberately demonstrates only two. What is graded is that the report **cannot
flatter the storyboard**, and the arms are chosen for the three ways it could:

| arm | what it grades |
|---|---|
| `unclaimed` names the third criterion | the one machine-checkable finding the report exists to produce. The fixture has exactly one undemonstrated criterion so the arm has something to find. |
| every beat the report points at really carries that tag, in the same file | correspondence, not count. "3 criteria produced 3 rows" is nearly free to satisfy; the claim is that row K points at beat K, at beat K's timestamp, naming beat K's still. |
| a tag naming an undeclared criterion is refused at the call | left through, the criterion the author meant comes back unclaimed while the storyboard looks complete — wrong in the one direction nobody checks. |

`check_coverage_refusals` runs without a browser (`Recorder(...)` launches one
only on `__enter__`), and every refusal has a control beside it: a valid tag, a
duplicate tag that must de-duplicate, and an untagged beat. Without those the
refusals would pass on a function that rejected everything.

`check_coverage_merge` grades the half a single take cannot reach. Each segment
knows only its own criteria and numbers its beats from zero, so a merged report
assembled by unioning the segments' own reports would point a reviewer at beat
numbers absent from the file they are reading, and could never name a criterion
*no* segment claimed. It asserts the union of criteria, `unclaimed` naming the
one neither segment tagged, merged indices rather than per-segment ones, and a
wording conflict reported rather than silently resolved.

**One assertion here was rewritten because the injection showed it graded
nothing.** The markdown arm originally checked `"AC-3" in timeline.md` — but
AC-3 appears on its own table row whatever the report concludes, so it passed on
a document that had dropped the finding entirely. It now looks for the sentence
that *states* the finding and requires the criterion to be named in it, and
likewise checks for "not what it proved" rather than for the word "claimed",
which is a column header.

Injections caught:

| break | what fires |
|---|---|
| nothing is ever reported unclaimed | the finding arm, in both the recorded take and the merge |
| the report points one beat past the beat that claimed it | the correspondence arm |
| a tag naming an undeclared criterion is accepted | the refusals arm |
| a merged demo is judged against only the first segment's ticket | the merge arm's union assertion |
| timeline.md stops stating the finding | the markdown arm — the one the weaker assertion slept through |

**What this deliberately does not grade**: whether a tagged beat *shows* what it
claims. That is the reviewer's judgement, and the artifact is written to say so
rather than to assert it.

### Whether the recorder notices that the recording shows nothing (issue #97)

Everything above is this harness measuring the picture. The recorder now
measures it too — `content` in `timeline.json`, plus a line on stderr — because
a user recording their own demo does not run this suite. This axis grades that
check, and only that: the floors and rects above stay as the harness's own,
because **a check graded by the measurement it makes is not graded**.

Three takes. `content-shown/` and `content-covered/` are one terminal
storyboard recorded twice, differing by a single line — whether `interlude("")`
takes the card back down — and otherwise the same five commands, the same
captions, the same exit codes and the same `evidence/`. That pair is issue #91
reproduced: under the card every beat runs and none of it reaches a frame.

`content-toured/` is a **different** healthy storyboard, and it exists because
the pair above structurally cannot reach the failure that matters most here.
The recorder's content rect excludes its own caption bar, so swapping captions
over a still screen is invisible to the held-picture arm — and swapping captions
over a still screen is precisely what `SKILL.md` tells authors to do during a
wait. Measured on real takes:

| take | `static_for` |
|---|---|
| healthy terminal, 2 touring captions | 16.5s |
| healthy web, 3 touring captions | 20.0s |
| healthy terminal, 3 touring captions | 21.5–22.0s |
| **reference take 1, card over the terminal** | **23.0s** |

There is no threshold between the healthy rows and the defect. The first
version of this axis warned on duration alone and would have called all three
healthy takes broken — in `timeline.json`, blaming "a title card or modal left
up over the app", which never happened. It went unnoticed because
`CONTENT_COMMANDS` was deliberately capped at three-line commands with no
touring captions "to stay clear of" the limit: **a fixture shaped to avoid a
failure mode cannot grade it.** That is the catalogue's *config-hidden path*.

So the recorder correlates the stretch with the beat log — a held picture
spanning only `caption`/`hold`/`shot`/`wait_for*` is a narrated hold; one
spanning `run`/`click`/`goto`/`type_into`/… is worth a human's time — and
`content-toured/` is asserted **silent** while holding *past* the limit.

Five commands rather than three because the covered take cannot hold one frame
for longer than it runs, and the band below needs it well clear of the
recorder's limit. **Each prints at most three lines, and that is a constraint
rather than a style**: the recorder's content rect drops the bottom fifth of
the terminal, so output landing in the last rows of a not-yet-scrolled screen
is outside the measured region. An earlier version of this storyboard filled 25
of ~32 rows and pushed two commands into that band, where the *healthy* take
reported 9.5 s of held picture while it was visibly printing. That limit is
real and is stated in `SKILL.md`; the fixture stays clear of it so that what is
graded here is the check rather than the limit.

Every assertion is a *comparison between the two takes*, because each one has a
way to pass vacuously alone — "the covered take warns" is satisfied by a
recorder that warns on everything, "the shown one does not" by a recorder that
never warns, and both by a metric measuring the wrong region entirely.

| | asserted on `content-shown` | asserted on `content-covered` |
|---|---|---|
| `content.warnings` | empty | says "held one picture" |
| stderr from the take | no warning | `WARNING`, unasked |
| `static_for` | under `static_limit` | ≥ 75% of the take's duration |
| the five stills, cropped to `#__term_host` | 5 distinct files | 1 file, five times |
| `evidence/` | ≥ 5 distinct screens | ≥ 5 distinct screens |

…plus one assertion across the pair: the video at the first and last `run` beat
must be **at least 8 dB PSNR further apart in the covered take than in the
shown one**.

The last row is the control that makes the two above it mean anything: it is
what says the five commands really printed five different things, so "the
frames are identical" is a statement about the *recording* rather than about a
storyboard that did nothing. It is also #97's finding stated as one line — the
text tier says the demo worked, the pixels say nothing was shown.

Stills are compared **byte for byte** and need no threshold at all: they are
lossless PNGs of the page. The video cannot be, so it is compared with ffmpeg's
PSNR — and that comparison is **relative between the two takes**, which was
learned the expensive way. The first version asserted "the covered take reads
at least 40 dB": 47.5 dB on the development machine, **39.8 dB on the CI
runner**, where a different x264 build re-quantises a held frame slightly
differently, and the suite went red on a recorder that was working. That is the
catalogue's *threshold tuned to this box*, and the fix is the one this file
already uses for the caption band — compare the takes against each other, same
run, same encoder, no absolute number claimed:

| | this box | CI runner |
|---|---|---|
| covered | 47.5 dB | 39.8 dB |
| shown | 25.5 dB | 25.9 dB |
| gap | 22.0 dB | 13.9 dB |

**The recorder's `static_limit` is graded as a band, from this run's own two
takes rather than from a number in a comment**: it must sit at least 1.6x above
the *healthy* take's longest still stretch and at most 0.7x of the covered
take's — one run measured `15.0s sits in [8.8, 21.3]s (healthy 5.5s, covered
30.5s)`. Halve the constant and every honest demo warns; double it and the take
this whole issue is about goes unremarked. Both turn the suite red.

**The anti-correlated metric is a standing regression test now.** The section
at the top of this file explains why the app's rect is measured rather than the
frame; nothing asserted it. This axis takes `content-shown/demo.mp4`, paints
the app rect flat black with `drawbox` — keeping the recorder's chrome, which
is the whole point — and scores the result both ways:

| | healthy | app painted flat |
|---|---|---|
| over the content rect | 6.6 | 0.2 |
| over the whole frame | 82.3 | **90.3** |

The rect ranks the blank recording far below the healthy one; the whole frame
ranks it **above**. Both directions are asserted, and the second is the one
that matters: if a future change scores the frame again, or the fixture stops
exhibiting the anti-correlation, the suite says so instead of passing on a
number that grades chrome.

Three more assertions round it out.

**`content-toured/` must hold past the limit and be met with silence**, and the
first half is the premise the second needs: if the take stopped holding long
enough it would keep passing after the thing it grades regressed, so
`static_for >= static_limit` is asserted explicitly. **That premise has already
earned its keep**: the first version of this take used sentence-length captions,
which wrapped to three lines on the CI runner — and a wrapping caption bar grows
*upward*, past the bottom fifth the content rect trims off and into the measured
region, 266 changed pixels a time. The stretch fell from 25.0s to 11.0s and the
take stopped reaching the path it exists for. CI said so instead of passing. The mechanism is asserted
too, not just the symptom — `content.static_beats` must be non-empty and must
contain no acting verb — because "no warning" alone would also pass on a
recorder whose static arm was simply switched off.

**The covered take's message must not name a cause.** It is asserted to contain
neither "title card or modal left up" nor "is not visible", and to say which
region was measured. A warning that blames an overlay is wrong on three of this
suite's own healthy takes, and a confidently wrong artifact is the thing #97
exists to remove — the detector must not become an instance of it.

**Every storyboard verb must be classified.** `check_verb_classification()`
scrapes `@_beat_verb("…")` and `self._beat("…")` out of the package source —
scraped rather than imported, so an omission cannot hide on both sides — and
requires each of the 22 verbs to be in exactly one of the recorder's two sets.
An unclassified verb silently counts as passive, which would quietly switch the
arm off for a whole class of demo. It aborts if the scrape finds fewer than 15
verbs, so a broken regex reports itself instead of passing on an empty set.

Finally, `check_content_healthy()` hangs off *every* graded take — web,
terminal and the stitched segments demo — asserting that each reports a
measured `content` with no warnings, a score well clear of the recorder's blank
floor, and a scored rect that lies **inside** the app rect this harness read off
the live recorder. That last one is the assertion that catches a recorder
grading its own window chrome, which produces a perfectly plausible `content`
block and a number that means nothing.

What it deliberately does **not** assert is that `static_for` stays under
`static_limit`. That rule was there in the first version and it was wrong: a
healthy demo narrating a rendered screen holds the measured region for longer
than the limit and is supposed to. What a healthy take owes is silence, not a
small number.

`tests/smoke --content-only` records just these three takes.

### Failure artifacts — what a take that did *not* finish leaves behind

Every axis above records a take that works. This one records six that do not,
and grades one sentence: **after an abnormal exit, every artifact present is
either current, or absent, or explicitly marked stale.**

| take | the way out of the `with` | what it grades |
|---|---|---|
| `crash-web` | a `wait_for()` timeout | the common case: mp4, timeline, `failure/`, marker |
| `crash-terminal` | a `wait_for_text()` timeout | the same, where `failure/screen.txt` is the *only* account of what went wrong — a TUI's state is not recoverable from a frame |
| `crash-interrupt` | `KeyboardInterrupt` inside a `pause` beat | `BaseException`, not `Exception`. A handler written for the latter misses a Ctrl-C entirely, and a Ctrl-C on a hung demo is exactly the take somebody is about to look at |
| `crash-between` | a raise in storyboard code, no beat open | the *absence* of a confidently wrong attribution: no beat may claim a failure it did not cause |
| `stale-media` | ffmpeg cannot write `demo.mp4` | `duration: null` beside a previous run's recording, no review frames off it, and a stderr line saying so |
| `marker-cleared` | it succeeds, into a folder a failure left | the marker and the stale dump are removed. A marker that outlives its run is the same lie inverted |

`refused-take-marker` went with the masking (#150): the only path that wrote
*nothing* was a take whose mask could not be verified, and no such path exists
now. `stale-media` and `marker-cleared` still grade the marker on the paths
that remain.

Three things about how these are built are worth knowing before trusting them:

- **`stale-media` reaches its state without monkeypatching anything.** The
  recorder runs unmodified; a real, probeable `demo.mp4` is planted and made
  mode-444, so ffmpeg fails for a reason that happens to people (a file this
  process may read and may not overwrite) and the stale recording survives to
  be probed. Both halves of that premise are asserted: the planted file has to
  still be there afterwards, and it has to be probeable — without the second,
  `duration is null` would also be true of a broken fix and the assertion would
  grade nothing. The arm refuses to run as root rather than passing silently.
- **The beat-`error` check is a bound in both directions.** Exactly one beat
  may carry `error` on the three arms that fail inside a verb, and *none* may
  on the arm that fails between them. Blanket-stamping every beat fails it just
  as removing the key does.
- **`failure/last-frame.png` is graded for picture, not existence.** ffmpeg
  writes a file for a blank video too, so it is scored on luma standard
  deviation against the same 6.0 floor the web stills use — which transitively
  says `demo.mp4` has a picture where it stopped.

### What a run that never started leaves behind (issue #105)

`tests/smoke --lock-only` records nothing and takes under a second. It spawns
two child runs of `tests/smoke` and grades what they say about their own output
directory — the suite's account of itself, on the one path where the suite used
to lie.

`main()` built its output directory and announced it *before* taking the
machine lock, so a run the lock refused created an empty
`/tmp/demo-video-smoke-*`, never removed it, and printed `recordings left in`
naming it, directly under `smoke: FAILED`. 85 such directories, 80 MB, over
three days of ordinary work — and a reader who followed that last line went
looking for a failure's evidence and found an empty directory.

It is **a pair**, and it has to be:

| child | how it ends | what it must show |
|---|---|---|
| refused | the arm itself holds the machine lock, so the child is refused by construction | it added nothing to `$TMPDIR`, and printed no `recordings left in` |
| started, then failed | `--allow-concurrent`, into an `--out-dir` whose take directory carries a planted file `fresh_take_dir` refuses | it *did* print `recordings left in`, naming that directory |

Without the second, "never print that line" is a passing answer to #105 and it
is the wrong one: the line is how somebody reading `smoke: FAILED` finds the
recordings, on every failure of a run that actually started. What the two pin
between them is the only rule true on both paths — **the line follows whether
this run started**, not whether the directory happens to hold anything. All
three of the manifest's entries for this arm are there to keep both halves
gradeable.

## The injection manifest — proving `smoke` can still fail

Everything above is an assertion. `tests/smoke-inject` is what says those
assertions still grade something: a table of named breaks, each with the arm
that must go red and the **specific message** that must be the one to appear in
the failure list. `tests/smoke-inject --list` prints it; `--self-test` proves
the harness's own guards hold and records nothing.

**Why this is a file and not a habit.** The habit was real — the tables above
were performed by hand, honestly, once — but nothing re-ran them, so an
assertion that stopped being able to fail would stay green forever
([#136](https://github.com/rogvid/skills/issues/136)). The cost was the reason:
one injection meant a ten-minute suite under an exclusive lock. Per-arm flags
are what changed that, and they are now load-bearing rather than a convenience.

| arm | clean, measured on one box |
|---|---|
| `--lock-only` | 1 s |
| `--evidence-only` | 7 s |
| `--coverage-only` | 8 s |
| `--narration-only` | 8 s |
| `--strict-only` | 13 s |
| `--determinism-only` | 19 s |
| `--issues-only` | 26 s |
| `--polish-only` | 26 s |
| `--segments-only` | 29 s |
| `--overlay-only` | 31 s |
| `--failure-only` | 48 s |
| `--web-only` | 123 s |
| `--content-only` | 148 s |
| `--terminal-only` | 186 s |
| the whole suite | 427 s |

That whole-suite reading includes a 15 s arm the same branch dropped before
merge (#210), so the tree as it stands is nearer 410 s. It is left as measured
rather than corrected by subtraction — a number nobody has read off a stopwatch
is how this row came to say 622 s.

The per-arm figures are the calibration this manifest was built on. The
whole-suite row is a fresh reading taken while
[#197](https://github.com/rogvid/skills/issues/197) split the arms below, and
it replaces a **622 s** that had been sitting here wrong: `--web-only` and
`--terminal-only` are disjoint and re-measured at 133 s and 187 s on the same
run, which with the determinism, segments, failure and pointer arms accounts
for the whole 427 s to within a few seconds. Nothing got faster; the old number
was never checked, which is the same reason every figure in **What it covers**
below is now read back out of this file rather than maintained by hand. The
per-arm rows were spot-checked in the same session and held (`--segments-only`
28 s, `--evidence-only` 6 s); `--web-only`'s 123 s is the one that has drifted,
and it is left as-is rather than churned on a single reading.

**What that ratio means for what runs per push**: the two medium arms are 75%
of the suite, and neither is reducible — `check_caption` and `check_beat_frames`
are pixel measurements. What #197 changed is that they are no longer the *only*
way to reach the claims that do not need pixels.

`--strict-only` was added *for* this file. The two takes `strict=True` must
refuse record in thirteen seconds between them, and were reachable only from
`--web-only` and `--terminal-only` — 123 s and 186 s. **An assertion is only as
gradeable as its cheapest arm**, and that is the first thing this manifest
turned into a number.

### What an entry has to satisfy

1. `old` matches **exactly once** in the file it targets, or the whole run
   aborts. This is `tests/unit`'s guard and it is not weakened here: an
   injection that silently does nothing would otherwise "prove" a hollow
   assertion is sound.
2. `sites` names the check function(s) whose assertions must fire, and each
   `must_contain` string must be a **literal in one of them** — verified
   statically, before anything records, one level into the helpers a check
   delegates its wording to. A reworded message is a refusal at the start of
   the run rather than a puzzling FAIL twelve minutes in.
3. `must_contain` must then appear in that arm's **failure list**, not merely
   somewhere on stderr and not merely in the exit code.
   [#135](https://github.com/rogvid/skills/issues/135) is why: an injected
   suite went red while every assertion naming that fault passed, and the red
   came from an unrelated premise guard whose stated remedy would have
   re-greened the bug.
4. The same arm is run **clean** first and must pass. Without that, an arm red
   for any other reason would certify every injection aimed at it.

Nothing is patched in the working tree — each entry stages its own copy of the
skill, the fixture and `tests/smoke` under a temp directory — and a run that
finds another suite holding the machine lock aborts rather than reporting the
refusal as an assertion that failed.

### What it covers

Entries are chosen by *what a silent failure would cost* rather than by what is
easy to break. This is what `tests/smoke-inject --list` reports today, quoted
rather than remembered:

```
49 entries, 12 arms, ~41.4 min of takes
```

That figure is `--list`'s **estimate** — each entry's arm from the table above,
plus one clean baseline per arm — not a stopwatch reading. It has now been
measured against a real run:
[30705025900](https://github.com/rogvid/skills/actions/runs/30705025900), a
`workflow_dispatch` of the nightly on main, took **41m23s** end to end, of which
**40.3 minutes** was `tests/smoke-inject` itself and about a minute was the
checkout and the ffmpeg and Chromium installs. So a CI runner costs about
**1.16x** the estimate above; the 25-entry manifest, measured the same way on
2026-08-01, gives 1.09x. `.github/workflows/smoke-inject.yml` sets its
`timeout-minutes` from that measurement and says so
([#191](https://github.com/rogvid/skills/issues/191)) — the 45 it replaced came
from a rule that assumed 2x and would have predicted ~71 minutes for a manifest
that costs 41.

Every number in this section is read back out of this file and compared against
the manifest by `tests/smoke-inject --self-test`, which runs on every push. It
is checked rather than maintained because it was maintained: by
[#184](https://github.com/rogvid/skills/issues/184) this section claimed sixteen
entries over five arms and "23 of 32 check functions have no entry" against a
real 22 of 35 — a coverage claim reading *better* than the truth, in the one
paragraph whose job is to say what this manifest does not cover.

| arm | entries | what a miss would mean |
|---|---|---|
| `--lock-only` | 3 | a run the machine lock refuses goes back to building an output directory it will never write to and printing `recordings left in` under `smoke: FAILED`, naming it ([#105](https://github.com/rogvid/skills/issues/105)) — or the fix overshoots and no failing run is told where its recordings are, which the third entry is the control for |
| `--narration-only` | 4 | the narration fixture goes back to leaving its interlude card up for the whole take, so every frame after the third beat — both captions the arm measures included — is the card and not the app, and nothing fails ([#168](https://github.com/rogvid/skills/issues/168)); or the three claims this 8 s arm is the cheapest way to reach stop grading ([#238](https://github.com/rogvid/skills/issues/238)) — the recorder reporting a healthy 2xx as a problem, which is the *only* over-reporting assertion in the file; a beat opening while the voice is still on the previous line; and every clip mixed in at zero offset, which the silent window before the first line is the control for |
| `--coverage-only` | 5 | the report flatters the storyboard: nothing reported unclaimed, a claim pointing at the wrong beat or forgetting its segment, an undeclared tag accepted, the finding dropped from `timeline.md` |
| `--strict-only` | 2 | a take that should have been refused passes, or the refusal never says which beat caused it |
| `--determinism-only` | 3 | a re-recording stops reproducing: the pointer parked wherever the race left it, a frozen clock that freezes at the wall time, an animation still moving when the still is taken |
| `--issues-only` | 2 | what the recorder saw behind the pixels stops being true: a problem that fired with no beat open acquires a confident beat index and caption, or a command's exit status lands on the wrong `run()` beat and a failure is recorded as a success |
| `--segments-only` | 14 | the merge renumbers `segment_index`, so `(segment, segment_index)` stops naming the same beat across a stitch ([#22](https://github.com/rogvid/skills/issues/22)); every review frame is cut at its beat's start instead of its midpoint, and the sheet is caption fade-ins; the sheet stops saying **which clock** it cut them on, so a reviewer cannot tell a corrected sheet from one cut on the raw beat log ([#229](https://github.com/rogvid/skills/issues/229)); the take stops recording the clock `demo.mp4` is actually on — the field gone, a step invented, the total disagreeing with its own steps, or the beat log stamped half a second off the frames and nothing saying so ([#215](https://github.com/rogvid/skills/issues/215)); or the *merge* stops carrying that clock — no merged record at all, every capture boundary at zero, a step belonging to no capture, or a part's own record never reaching the segment it was measured in ([#225](https://github.com/rogvid/skills/issues/225)); or the record stops saying **how well it watched** — the `measured` flag gone, the flag disagreeing with the `max_gap` it is derived from, or the recorder refusing to report on a host it could have measured, which is the failure that looks like silence ([#247](https://github.com/rogvid/skills/issues/247)) |
| `--evidence-only` | 1 | one capture of the page is stamped onto every beat, so what a beat's evidence describes is not what that beat showed — [#9](https://github.com/rogvid/skills/issues/9)'s acceptance criterion, on a 7 s arm instead of a 123 s one |
| `--overlay-only` | 4 | the four breaks [#170](https://github.com/rogvid/skills/pull/170) performed by hand: the pre-fix `interlude("")` dispatch, the overlay probe silent, the probe reporting everything, and the healthy "shows a picture" line disappearing — the control without which "the covered take does not say it" is satisfied by a recorder that stopped saying it about anything |
| `--failure-only` | 2 | a crash dump that exists and says nothing — an empty `screen.txt`, a marker that names neither the exception nor whether the mp4 is this take's |
| `--web-only` | 6 | the form verbs lie about what they did: `press` logging a key it never sent or returning before the page saw it, `clear` selecting without deleting or emptying the field between two frames, either of them driving the page and writing no beat |
| `--content-only` | 3 | the recorder stops noticing a recording nobody can watch, starts warning about honest demos that hold still, or goes back to scoring the whole frame (issue #17's anti-correlated metric) |

### What it does **not** cover

- **16 of `tests/smoke`'s 40 check functions have no entry**, and the harness
  prints every one of them as `ungraded` at the end of a run rather than
  leaving the boundary to somebody's memory.

  **`ungraded` is not the same as graded by nothing**, and by
  [#196](https://github.com/rogvid/skills/issues/196) that difference had grown
  to most of the list: after [#195](https://github.com/rogvid/skills/issues/195)
  the browser-free half of several of these is certified in `tests/unit`, where
  an injection costs 0.2 s. A reader who followed the run's closing line here
  and concluded that nothing watched them was reading a document written before
  that. So the roster below answers per function, and it is read back out of
  this file as text and compared against the manifest **both ways** by
  `--self-test`: a name missing from it is a reader sent to a table their
  function is not in, and a name in it that has an entry is the older mistake —
  one check function stayed written here as uncovered for as long as it had six
  entries aimed at it, and a count would never have said so.

  | ungraded check function | what carries its browser-free claims |
  |---|---|
  | `check_take` | `ContentRect` — the rect the picture half is scored over, exactly, on all four numbers (#135/#195). The artifact half — the files exist, are this run's, and are not repeats of one another — is genuinely ungraded |
  | `check_content_healthy` | `ContentRect`, same six tests: the trim reaches the caption bar on both media, does not eat the app, and never comes back zero-sized |
  | `check_caption` | genuinely ungraded as a *picture*. `CaptionTruth` grades which caption a beat is stamped with across a navigation (#134), never that the bar was drawn |
  | `check_verb_classification` | `VerbClassification` — every classified verb is one a recorder logs, and every verb a recorder logs is classified, with the set size asserted first so neither holds vacuously. **Merge-only since #61**: the only arms that reach it are `--content-only` and `--terminal-only`, so nothing runs it on a pull request |
  | `check_determinism` | genuinely ungraded. It reads the clock, the locale and the motion setting *out of the page*, which is the whole point of it — a constructor that stored the flag and never wired it up satisfies anything asserted on the Python side |
  | `check_merge_offset` | genuinely ungraded. `MergeContent` grades the merge of the content *report* (#121); the per-segment caption timing this measures against two mp4s has no browser-free half |
  | `check_opening_gap` | `OpeningWarning` — `held: null` against `held: 0.0`, and the blank floor that keeps the warning readable. **Merge-only since #61**: `--web-only` is the only arm that reaches it |
  | `check_opening` | genuinely ungraded — the first frame of a web take, measured in pixels (#119). **Merge-only since #61**: `--web-only` is the only arm that reaches it, so on a pull request nothing runs it and nothing injects against it |
  | `check_opening_card` | genuinely ungraded — three statements about one sweep of one corner of a frame (#110) |
  | `check_spotlight_transitions` | genuinely ungraded — the shape of the spotlight's exit, sampled frame by frame (#111) |
  | `_check_video` | genuinely ungraded — ffprobe against the file the take wrote |
  | `_check_occlusion` | genuinely ungraded — PSNR between two moments of a recording |
  | `_check_frame_captions` | genuinely ungraded — the caption band of frame N read against the hand-written storyboard |
  | `_check_stale_frames` | genuinely ungraded. `FailureCleanup` is the same shape for the failure dump, not for `frames/` |
  | `_check_segment_refusal` | genuinely ungraded — an unmerged segment's document, graded against the frames a recorder did not write |
  | `_check_scene_fallback` | genuinely ungraded — measured straight off `demo.mp4`, because no beat in either storyboard is long enough to provoke it |

  **Three rows above are worse off than the rest, and #61 is why.**
  `check_opening`, `check_opening_gap` and `check_verb_classification` are
  ungraded by this manifest *and* reachable only from the three arms that no
  longer run per push, so between a pull request opening and its merge nothing
  exercises them at all. The others in this table are either reached by an arm
  `--cheap` still runs or covered by a `tests/unit` class that runs in a
  second. This is the one real cost of the split, it was measured before the
  split was made, and closing it means giving those three an entry — see
  **When each take runs** near the top of this file, and the *Known gaps*
  entry at the bottom.

  **What is left is not there for cost, and this file used to say it was.**
  The sentence that stood here read "what is left in that list is there for
  cost or for pixels", which was never measured. Measured — the call graph of
  `tests/smoke` walked from each `run_*` phase transitively through the take
  helper, the review-frame helper, the `record_*` functions and the stitch,
  against `run_phases`' `selects()` guards and `smoke-inject`'s `ARM_SECONDS`
  — only **four** of the sixteen cost a medium arm. The other twelve are
  reachable from arms of 19-29 s and are ungraded because nobody wrote the
  entry:

  - **`--determinism-only`, 19 s an entry** — `check_determinism`.
    [#239](https://github.com/rogvid/skills/issues/239).
  - **`--polish-only`, 26 s an entry** — `check_spotlight_transitions`,
    `check_opening_card`, `_check_video`. The arm carries no entry at all
    today, so it also pays one baseline.
    [#240](https://github.com/rogvid/skills/issues/240).
  - **`--segments-only`, 29 s an entry** — `check_caption`, `check_take`,
    `check_content_healthy`, `check_merge_offset`, `_check_frame_captions`,
    `_check_stale_frames`, `_check_segment_refusal`, `_check_scene_fallback`.
    [#241](https://github.com/rogvid/skills/issues/241), which supersedes
    [#200](https://github.com/rogvid/skills/issues/200) — that issue counted
    two of these eight.
  - **The four that really are expensive** — `check_opening` and
    `check_opening_gap` on `--web-only` (123 s), `check_verb_classification`
    and `_check_occlusion` on `--content-only` (148 s).
    [#233](https://github.com/rogvid/skills/issues/233) covers the first
    three; `_check_occlusion` is PSNR between two moments of a recording and
    has neither an issue nor a cheaper arm.

  An arm above is the **cheapest** phase that reaches the function, which is
  not the arm this roster's prose implies for several of them: `check_take`,
  `check_content_healthy`, `check_caption` and the four review-frame helpers
  all read as web/terminal claims and are all reachable from
  `--segments-only`, and `_check_video` is reachable from `--polish-only`
  without going through the take helper at all. Three rows this table used to
  carry were the same mistake at 8 s — the healthy-take assertion and the two
  narration ones, all three reached by `run_narration` — and they are graded
  as of [#238](https://github.com/rogvid/skills/issues/238), which is why they
  are gone from it.

  #197 took the cost half as far as it went at the time: the claims that only
  needed *a* take rather than the long one moved to `--issues-only` (26 s),
  `--segments-only` (29 s) and `--evidence-only` (7 s). What genuinely needs a
  picture nothing makes cheaper — but that is four functions, not sixteen.
- **It does not find assertions nobody wrote.** Every entry names a message
  that already exists. A behaviour with no check at all is invisible here —
  that is [#103](https://github.com/rogvid/skills/issues/103)'s shape and still
  needs a person.
- **It is not mutation testing**, and that was considered and rejected in #136
  with the numbers: ~2,340 naive sites against a suite this expensive is 52-139
  hours serial, and half of `web.py` is JavaScript inside string literals no
  Python mutation operator can reach.
- **An entry proves an assertion can fail for *that* break**, not for every
  break of the same subject. Three entries aim at the overlay probe because one
  would only have shown the probe is wired up, not that it is wired up in both
  directions.
- **It cannot tell a right reason from a coincidental one.** The check is that
  the named message appears; a message that appeared for an unrelated reason
  with the same wording would pass. The narrower the `must_contain`, the less
  room that leaves, which is why the 20-character floor exists.
- **The baseline is one clean run per arm, not one per entry.** An arm that
  fails intermittently can still be green for its baseline and red for an
  injection for the wrong reason. What protects against that is the *named*
  message rather than the exit code, which is the same protection #135 asked
  for.

### When it runs

- **Every push** — `tests/smoke-inject --self-test`, in ci.yml's `unit` job. It
  records nothing and costs nothing, and it is what stops the harness itself
  from reporting PASS on no evidence: each guard is handed the input it exists
  to refuse and has to refuse it. It also reads the figures above back out of
  this file and compares them with the manifest, so a stale count here is a red
  run and not a discovery.
- **Nightly, and on demand** — the whole manifest, in
  `.github/workflows/smoke-inject.yml`. Not per-push: CI already pays ~10
  minutes for `smoke` on every commit, and what rots here is an *assertion*,
  which rots over weeks rather than commits.
- **On a pull request labelled `fault-inject`** — for the diffs where an
  assertion can quietly stop grading: `tests/smoke`, `content.py`,
  `coverage.py`, or anything that changes what the recorder measures.

### Registering an entry

Add an `Injection(...)` to `INJECTIONS` in `tests/smoke-inject` naming the
break, the arm, the check function and the message. Run
`tests/smoke-inject --only <part of its name>` and watch it go from FAIL to
PASS as you get the message right. If the only arm that reaches your assertion
costs three minutes, that is worth saying out loud in the pull request — the
cheap arm that would fix it is usually twenty lines of `run_phases`, which is
exactly where `--strict-only` came from.

## Known gaps

Things a pass does **not** prove. They are listed because an assertion nobody
knows is missing is worse than one that is openly absent.

- **That a real Chromium hands a click's deferred document event to
  `evaluate("0")`.** [#214](https://github.com/rogvid/skills/issues/214) is
  closed: a beat now forces one pump before it stamps the caption it inherited,
  so the `domcontentloaded` a click left in the connection lands *inside* that
  beat instead of one beat later.
  `MeasuredNavigations.test_a_load_the_verb_did_not_wait_for_reaches_the_log_in_the_same_beat`
  grades it by queueing the measured late half of each stream on a page that
  releases it when the recorder calls — which is Playwright's documented sync
  dispatch, and is a *stand-in* for it. What no assertion here can see is a
  build that stopped delivering the queued event on a trivial `evaluate`, or
  delivered it later than the beat that pumped. That is a claim about a browser
  and belongs to `tests/smoke`, which has no arm for it
  ([#228](https://github.com/rogvid/skills/issues/228)).

- **The take-level sentence both cursor fixes were accepted on is ungraded.**
  [#186](https://github.com/rogvid/skills/issues/186) and
  [#202](https://github.com/rogvid/skills/issues/202) were accepted on "two
  takes of a storyboard that never moves the pointer produce byte-identical
  stills". `tests/unit`'s `CursorMotion` grades the *rule* against event shapes
  measured off three Chromium builds; the determinism arm parks the pointer
  before anything is photographed and is structurally blind to it. An arm was
  built for it and removed before merge, because the only event that exercises
  the guard in such a take — the `mousemove` Chromium dispatches at load — is
  delivered only when the page's `load` event fires inside 22 ms: 7 of 7 takes
  under that bar received it, 0 of 9 over it, and the reviewer's box saw 0 of
  12. Not machine load (7/9 loaded against 8/9 idle) and not listener timing
  (installed at `readyState: 'loading'`, 7.2-8.4 ms, 16 of 16). The full
  measurement, and the one route that might still work, are in
  [#210](https://github.com/rogvid/skills/issues/210).

- **That a pointer move made before `DOMContentLoaded` places the dot is graded
  as a shape, not in a browser.**
  [#203](https://github.com/rogvid/skills/issues/203) moved the overlay's
  pointer subscriptions to `document_start` and left only the dot's insertion
  at `DOMContentLoaded`. What `tests/unit`'s `CursorMotion` grades is exactly
  that: the region the script defers holds no `addEventListener(`, read out of
  the shipped `_CURSOR_JS`. It is a **textual** claim, and a subscription
  registered through an indirection — a `const listen = () => window.add…`
  called from `attach` — would satisfy it while the defect was back. The
  browser measurement is in the pull request, not in any suite: 12 `Recorder`
  takes per build through `goto(wait_until="commit")` plus a raw
  `page.mouse.move`, counting only the takes where a probe confirmed the move
  was delivered at `readyState: 'loading'`. Dot placed 0 of 17 such takes
  before, 13 of 13 after, on Chromium 136, 147 and 149. **Chromium 151 could
  not be measured at all**: its `DOMContentLoaded` lands at 11-17 ms and
  Playwright's move at 39-68 ms, so 0 of 24 takes reached the window. Nothing
  re-runs any of this, and a smoke arm for it would inherit
  [#210](https://github.com/rogvid/skills/issues/210)'s problem — the browser,
  not the storyboard, decides whether a take exercises the path.

- **The same escape hatch loses the move outright in some takes, and no suite
  sees that either.** Measured while grading #203 and unchanged by it: the
  document receives no `mousemove` at all in 3 of 12 takes on Chromium 136, 4
  of 12 on 147, 2 of 12 on 149 and **7 of 12 on 151**, so the take records no
  cursor. `check_parked_pointer` cannot catch it — the determinism storyboard
  parks after `Recorder.goto()`, which waits for `load`. Tracked with its
  measurement in [#230](https://github.com/rogvid/skills/issues/230).

- **Nothing grades the opening frame of a demo anybody ships.**
  `check_opening_card` sweeps the corner of `terminal-opening/`, a take this
  suite records itself, so what passes is a claim about the *recorder*.
  `examples/ticket-queue/demos/2026-07-26-status-filter` — the take
  [#110](https://github.com/rogvid/skills/issues/110) and
  [#206](https://github.com/rogvid/skills/issues/206) were reported against —
  is graded by a person watching, and always has been: demo directories commit
  `record.py`, `timeline.json`, `timeline.md` and `images/` but never
  `demo.mp4` or its `.seg.mp4` parts, so no committed artifact carries the
  first frame of part2. Three human sightings of the same flash is what that
  costs. **The timeline gap does not stand in for it** — see the
  `terminal-opening/` section above, and
  [#207](https://github.com/rogvid/skills/issues/207) for the two takes it was
  measured on. What would close it is the same corner strip read off the live
  `#__term_win` box at *record* time, on the segment's own first frame, written
  into the take's report where a reviewer reads a number instead of squinting
  — card `<= 60` mean luma, bare `>= 150`, the constants `check_opening_card`
  already uses. That is
  [#235](https://github.com/rogvid/skills/issues/235). Separately, the sweep
  itself has no `tests/smoke-inject` entry — it is in the ungraded roster
  above, it was fault-injected by hand when it was written, and since
  [#61](https://github.com/rogvid/skills/issues/61) the per-push
  `--polish-only` run is its only exercise in the repo (see **Why the four
  middle arms stayed on the push**, which is the measurement that kept it
  there).

- **Nothing calls the ElevenLabs API.** The narration take grades everything a
  cache hit reaches — the key, the pacing, the mix — and by construction never
  takes the miss path, which is the point. So `tts_clip`'s request, its 429/5xx
  retry ladder with backoff, the `.part`-then-rename that keeps a truncated
  download out of the cache, and every error message it raises are unexercised.
  A regression there costs a take at record time with a legible exception, which
  is the mildest failure in this file — but it is a gap, and closing it needs a
  local HTTP stub rather than a real key. `TTS_API_BASE` is the seam that would
  take one.

- **The no-lines audio branch is ungraded.** `_convert` gives a speech-enabled
  segment that narrated nothing a track of `anullsrc` silence, so `stitch()`'s
  `-c copy` concat sees uniform streams. Every take here either narrates or
  disables speech, so that branch runs nowhere. Ironically it is exactly what
  the mix injection above *produces*, which is how we know the silence is well
  formed — but nothing asserts it is what a line-less segment gets.

- **A conversion failure writes no `failure/` dump**, only the marker, the
  timeline with `duration: null` and the stderr line. The dump is built from
  the exception that came out of the `with`, before conversion is attempted,
  so a failure that happens *after* that point has nowhere to land.

- **A total stylesheet failure is below the luma floor.** Measured with real
  screenshots: unstyled-HTML fallback scores 9.97, a sparse white page 3.54, an
  error page 4.05, healthy 15–17. The useful band is 6 → 15, so a page that
  rendered with no CSS at all lands at ~10, above the 6.0 floor. Raising the
  floor toward 15 would risk flake from CI font rendering. Mitigated, not
  solved, by the `getComputedStyle` check on `#refresh` — which catches the
  fixture's own stylesheet failing, but is one assertion about one property and
  will not notice arbitrary visual regressions. Tracked in
  [#16](https://github.com/rogvid/skills/issues/16).
- **The terminal caption check has the thinnest margin in the harness** — 2.7
  healthy against a 1.0 floor, where everything else has 4x or better. The
  terminal's caption is a dark box on a dark terminal, so only its text carries
  any luma change. If CI font rendering ever drops it under 1.0 this will flake;
  the DOM caption assertions would still hold. Tracked in
  [#16](https://github.com/rogvid/skills/issues/16).
- **The content rects couple to recorder internals** (`Recorder._geom`, and the
  `#__term_host` id). Reading them at runtime means a geometry change follows
  automatically, and a *removed* `_geom` fails loudly — but a change that keeps
  the attribute while moving the app elsewhere would silently score the wrong
  pixels. Tracked in [#17](https://github.com/rogvid/skills/issues/17), which
  proposes the recorder expose its geometry as public API.
- **The video and the beat log are on different clocks, and this harness
  corrects for that rather than fixing it.** Chromium stamps every screencast
  frame with the host's *wall* clock and Playwright turns that into the frame's
  position in the webm; the beat log is `time.monotonic()`. A host that steps
  its wall clock therefore takes that much wall time out of `demo.mp4` and
  leaves the log where it was. The box this was found on stepped **-0.75 to
  -0.81 s every 32.2 s** in April, which is a coin flip inside a 19 s take and
  is the whole of the bimodality
  [#215](https://github.com/rogvid/skills/issues/215) reported — and **-0.50 s
  every 5.5 s** when it was re-measured in August
  ([#247](https://github.com/rogvid/skills/issues/247)). Same shape, different
  settings. Nothing here is tuned to either number.

  What is fixed: the recorder measures the same clock and writes it into
  `timeline.json` as `capture_clock`, warns on the way out, and this harness
  measures it independently and subtracts it before grading. Since
  [#229](https://github.com/rogvid/skills/issues/229) the recorder also
  *applies* it where it owns the consumer — the review frames are cut on the
  video's clock, and both `frames.md` and `timeline.md` say when the clock
  stepped — so a reader of those two artifacts is no longer on their own.

  What is **not** fixed: a real demo's `timeline.json` still carries beat
  timestamps on a clock the video is not on, because that is what the log is,
  and anything else reading them has to apply the field itself. Narration
  still inherits the lag, because audio is mixed at wall-clock offsets while
  pixels ride the screencast — measured at +0.70 s and now correctable from
  `capture_clock`, which is
  [#226](https://github.com/rogvid/skills/issues/226). What is left of
  [#18](https://github.com/rogvid/skills/issues/18) is that boundary, and it
  matters most to [#8](https://github.com/rogvid/skills/issues/8).

  **And on a host whose clock never steps, the correction is a no-op** — a
  corrected cut and an uncorrected one are the same number, so no arm of this
  suite can tell them apart there. The arithmetic is graded on a *scripted*
  record by `FrameClockCorrection` in `tests/unit`, where six injections cost
  0.2 s each; what `--segments-only` adds on any host is that the sheet states
  which of the three cases it was, and that a step the recorder invents moves
  the frames and is caught by a placement check reading this harness's own
  watcher.

- **~~…and the correction above rests on a premise that did not reproduce on
  2026-08-08.~~ Retracted; the premise holds and the *sampler* was broken**
  ([#247](https://github.com/rogvid/skills/issues/247)). The entry that stood
  here read the field as an aliased fragment of an oscillation the video did
  not follow. Both halves of that are wrong, and the way it went wrong is
  worth keeping:

  - **It is not aliasing.** The waveform, at 1 ms over 300 s, is a
    *rectangular* pulse: the offset jumps +10.03 to +10.10 s, holds flat for
    40–230 ms, falls 10.53–10.60 s, and lands 0.43–0.56 s below where it
    started, every 5.509 s. Sub-sampling that 1 ms record at 20 ms — the rate
    `capture_clock` uses — recovers **110 of 110 edges** and a total within
    2 % of the truth. A 20 ms sampler is entirely adequate to this waveform.
  - **The sampler was captured by the clock it was sampling.** Both
    `_CaptureClock` and `HostClock` slept on `threading.Event.wait`, whose
    deadline on the interpreter `uv` installs (CPython 3.13.11 from
    python-build-standalone, built without `sem_clockwait`) is an absolute
    `CLOCK_REALTIME` instant. Measured directly: 81 waits of 20 ms in 25 s
    instead of ~1140, five of them **5.44–5.49 s** long, every one entered
    while the +10 s pulse was up. A sampler that reads the clock inside a
    pulse sleeps until the wall clock climbs back — the *next* pulse — and is
    then phase-locked, sampling only ever inside pulses. Eight idle 20 s runs
    of the old loop against a 1 ms reference: `total` wrong by **+10.59 to
    +10.60 s**, every time. Six recorded takes: `total` **+9.09 s** where the
    truth was **−2.00 s**.
  - **The video does follow the wall clock.** Six takes, seven caption
    transitions each, located by luma straight off `demo.mp4`: uncorrected,
    the video was up to **−1.50 s** from the beat log by 13.5 s in; corrected
    by a correctly sampled offset, **all 38 landed within 101 ms**, and within
    40 ms at the caption-on edges.
  - **And this file's own check could not catch it**, because `HostClock` had
    the recorder's bug line for line. Two samplers, two processes, no shared
    import — and they agreed on `+9.09 s` because they failed the same way.
    That is the catalogue's *check that shares the bug's blind spot*, and it
    is the reason `covered` / `max_gap` now exist on both sides: a reading
    that cannot state how well it covered the take is not a reading.

  What is left of the earlier entry is one real limit, restated: **a frame
  stamped inside the ~50 ms pulse inflates the encode and costs the tail.**
  Two of the six takes above encoded 17.2 s instead of 13.96 s and lost their
  last three transitions. `capture_clock` records the pulse honestly (both
  edges, so the cumulative sum still telescopes correctly), but it cannot tell
  a consumer that the encoder padded. Nothing grades that yet.

- **`--segments-only` is red on that WSL2 box, before and after #247, and its
  three new injections therefore could not be run there.** Measured both ways
  on 2026-08-09, same host, same arm, one after the other:

  - `origin/main` @ `3c71130`: FAILED, 5 problems. Its own artifact carried
    the bug — the recorder warned `+10105 ms in total` and "demo.mp4 is 10.11s
    longer than the take's own wall time" for a take whose clock had moved
    **−501 ms**, and `check_capture_clock` caught *that* one only because this
    harness's watcher happened not to be trapped on the same run.
  - this branch: FAILED too, and differently — on run 1 the take's video
    genuinely lost its tail (frozen from 6.56 s to 17.88 s, part2's content
    never encoded) and on run 2 the beat-time coverage floor, from a ~9.5 s
    stall inside the storyboard. Both runs printed `capture_clock agrees with
    the harness` for **both** parts, with honest paired pulse edges and totals
    of −0.49/−0.49 and −0.51/−1.00.

  So the arm is red for host reasons either way, and `smoke-inject` — rightly
  — refuses to grade an injection whose clean baseline already fails. The
  three `--segments-only` entries added for the coverage claim are registered
  and match the tree, and **on this box they have not been run**. What was run
  instead: `_check_clock_coverage` is a pure function of a record and a
  watcher, so `ClockCoverageCheck` in `tests/unit` exercises all four of its
  branches plus a control, and four `tests/unit` injections break each branch
  in `tests/smoke` itself and were seen failing. That is a weaker claim than
  the arm passing — it does not prove the guard is *reached* on a real take —
  and it is the strongest one this host allows.

  **Re-measured on 2026-08-09 while #229 was implemented, and it was green.**
  Same box, same arm, `--segments-only` clean: **PASSED in 37 s**, with
  `capture_clock agrees with the harness (the host's wall clock did not step
  during this take)` for both parts and 0 merged steps. The host's 5.5 s pulse
  was simply not running on that reading. That does not retract the entry
  above — the arm was red twice earlier the same day, and a box that is red
  when its clock steps and green when it does not is exactly the bimodality
  #215 reported — but it does mean the three coverage entries, and #229's two,
  are runnable here when the host is quiet, and #229's two were run and caught.
  Treat a green `--segments-only` on this box as a reading of the host as much
  as of the recorder.

- **The terminal arm loses roughly a second more than its host clock explains,
  and nothing here knows why.** The correction is exact on the web arm — six
  consecutive `--web-only` runs after it, residual 20-140 ms, three of them
  with a step inside the take — and on both segments of the stitched demo. The
  terminal take is not. Four `--terminal-only` runs, each with the recorder's
  own `capture_clock` read back out of the take:

  | run | step | first probe | closing probe | result |
  |---|---|---|---|---|
  | 1 | none | -180 ms | -140 ms | PASSED |
  | 2 | -800 ms at 1.8s | unmeasurable, ~-1.94 s raw | over the bar | FAILED |
  | 3 | -839 ms at 8.9s | -100 ms | **-900 ms** after correction | FAILED |
  | 4 | -830 ms at 15.5s, past the last beat | -100 ms | -60 ms | PASSED |

  Both runs that failed are runs whose step landed *inside* the storyboard;
  both that passed are runs where it did not. Run 3 is the shape: the step is subtracted, and what is left is another
  0.9 s of wall time gone from the video between 8.9 s and 11.95 s — about one
  more step, in a take where only one was measured and where this harness and
  the recorder agree on that, inside the storyboard's own window. The take's
  *length* only lost the one step (`duration` fell by 0.76 s against a
  step-free run), so the video did not simply get shorter: something between
  the jump and the closing caption is compressed. The most likely candidate is
  what ffmpeg does with the non-monotonic cluster timestamps Playwright writes
  after Chromium's clock goes backwards, which is not something this repo can
  measure from outside. Tracked in
  [#224](https://github.com/rogvid/skills/issues/224).

  **The bars were not widened for it.** `MAX_SKEW_DRIFT_S` at 250 ms is the
  sharp claim this whole correction exists to make usable, and a bar wide
  enough for -800 ms of it grades nothing at all. So a `--terminal-only` run on
  a box whose wall clock steps inside the take is still red about half the
  time, and it is red about something true and now says which part of it is
  the host and which is not.

- **~~`stitch()` does not merge `capture_clock`.~~ Fixed**
  ([#225](https://github.com/rogvid/skills/issues/225)). The merged envelope
  now carries every part's steps moved onto the stitched clock by that part's
  ffprobe offset, each naming the `segment` that measured it, plus the capture
  `boundaries` — so `check_merge_offset`'s stitched reading is corrected from
  the artifact alone while its per-part reading is corrected from this
  harness's own measurement, and the differential between them is the claim.
  What remains true of the *measured* half: **on a host whose wall clock never
  steps, every step list is empty and the per-beat agreement in
  `check_merged_capture_clock` compares nothing to nothing.** That is the
  environment-agreeing shape, and it is why the merge's arithmetic — the
  offsets, the per-capture attribution, and the rule that a step in an earlier
  part must not correct a later part's beats — is graded on a *scripted* clock
  by `MergedCaptureClock` in `tests/unit`, where five injections cost 0.2 s
  each. What this arm adds on any host is the structure a reader needs:
  the field exists, totals its own steps, names its captures, and puts their
  boundaries where ffprobe puts them.

  **One entry had to be rewritten for exactly that reason, and the manifest is
  what caught it.** The injection for "a step that names no capture" first
  stripped the `segment` off every merged step — which is a no-op on a run
  where the clock never stepped, and the arm passed against it. It now *adds* a
  step nobody measured, with a `delta` of 0.0 so the record still totals its
  own steps: one fault, on any host.

  **The harness had the bug it was the reference for.** `joined_clock()` laid
  every part's steps onto the merged clock, including the ones its watcher
  sampled *after* that part's last frame — the encode, the conversion and the
  timeline write all run inside the `with`, and a step there sits past the next
  part's boundary. `before()` keys on time, so it handed those to the next
  part's beats. Measured on the run that found it: a -876 ms step at 7.2 s of a
  part whose video is 6.88 s moved the closing caption's search window 876 ms
  off the frame and failed `--segments-only` about something untrue — while the
  *same* caption in the *same* file timed to -20 ms through
  `check_merge_offset`, which corrects from the merged `timeline.json`, where
  the recorder had already stopped sampling and the merge attributes per
  capture. `joined_clock()` now drops a step that lands past its own part's
  video; each part's own clock is untouched.

  One more beat is ungraded per step: a
  beat starting within `MAX_CLOCK_STEP_TIME_DISAGREEMENT_S` of one is skipped
  and counted in the arm's output, because two samplers on their own 20 ms
  grids do not both know which side of that beat the step fell on — and the
  alternative, a bar as wide as a step, would grade nothing.

- **~~`--web-only` still goes red when the capture loses more than 0.75 s, and
  the bars were not widened to stop it.~~ Diagnosed and fixed** — the cause was
  the host's wall clock and it is now measured and subtracted, per probe
  ([#215](https://github.com/rogvid/skills/issues/215)). The measurement that
  led there is kept below because it is what the fix was checked against, and
  because "bimodal, and not load" is the reading that mattered.
  [#209](https://github.com/rogvid/skills/issues/209) asked whether the
  caption-timing bars measure something real that load breaks, or an artefact
  of the harness's own timing. Measured, four `--web-only` runs on this box,
  one at a time behind the machine lock, reading how far the video sits ahead
  of the beat log at each of the two probes:

  | run | loadavg | result | first probe | closing probe |
  |---|---|---|---|---|
  | 1 | 1.25 | FAILED | -880 ms | -800 ms |
  | 2 | 2.05 | PASSED | -80 ms | 0 ms |
  | 3 | 2.85 | FAILED | -120 ms | -800 ms |
  | 4 | 19.8, 16 busy workers | FAILED | -880 ms | -840 ms |

  **Real, and not load.** The reading is bimodal — either under 120 ms or
  800-880 ms, never in between — and it is taken off a file that was already
  written, so nothing the analysis does can produce it. Two of the three runs
  with no load generator failed, at the loads the issue's own
  counter-measurement called idle; the run at loadavg 19.8 failed the same way
  and took 383 s against 137 s, with extra failures in
  [#78](https://github.com/rogvid/skills/issues/78)'s shape (a blank opening,
  both spotlight windows). Load makes it worse and much slower. It does not
  cause it.

  **Why the bars are unchanged.** Run 3 is the reason. Its first probe read
  -120 ms and its closing probe -800 ms: 680 ms of screencast stall landing
  *between* the probes, with `TICKER_JS` injected and asserted alive. A
  `MAX_CAPTURE_LOSS_S` wide enough to absorb runs 1 and 4 turns run 3 into a
  `MAX_SKEW_DRIFT_S` failure instead — and that bar's message attributed drift
  to the beat log's clock, so the arm would have gone from red to *confidently
  wrong* about a third of the time. A bar tuned to this box, buying a worse
  artifact, is not a trade worth making, so it was not made.

  What did change is the one thing here that was the harness's own.
  `ALIGN_PRE_S` was a hand-written 1.2 s against a requirement of
  `MAX_CAPTURE_LOSS_S + 0.48 s` = 1.23 s, so a slide *inside* the tolerance
  this file states was reported as "the caption could not be timed" instead of
  passing; its comment claimed 0.45 s of margin and the real figure was
  -0.03 s. It is derived from the bar now, and reaches `ALIGN_OVERSHOOT_S`
  past it so a slide the bar rejects is reported as a number rather than as a
  measurement that could not be made. The drift message no longer names a
  cause it cannot tell apart from the other one.

  **What it turned out to be.** Playwright's driver, instrumented to log every
  screencast frame, caught two consecutive frames 84 ms apart on the monotonic
  clock and **711 ms backwards** on Chromium's. Chromium's frame timestamps are
  the host's wall clock; a separate sampler that never opens a browser showed
  that clock stepping -0.75 to -0.81 s every 32.2 s on this box **on the day
  that was measured**, at the same instants and the same sizes to the tenth of
  a millisecond. (Four months later the same box was doing -0.50 s every
  5.5 s. The size and the period are the host's; only the shape is stable.
  See [#247](https://github.com/rogvid/skills/issues/247).) Seven takes of one
  storyboard: the four whose window contained a step encoded 0.78 s less video
  than the three that did not, to within 12 ms. The bars are now on the
  residual after that is subtracted, and the residual is 20-140 ms on an idle
  box. Six consecutive `--web-only` runs afterwards: **6/6 clean on the timing
  bars**, three of them with a step inside the take and one of those between
  the two probes — the shape that made the drift bar unusable. The two runs
  that went red went red on the spotlight windows, at loads 1.7 and 3.1, which
  is [#78](https://github.com/rogvid/skills/issues/78) and not this.
- **Nothing reads the caption text off the video.** The timing check proves the
  caption *band* changed when `timeline.json` says it did; that the words are
  the right words is a DOM assertion (`check_caption`) taken at record time.
  Between them a recorder that drew the wrong caption at the right moment would
  be caught, but only because two separate checks happen to overlap — no single
  assertion reads pixels back as text, and none is going to without OCR.
- **A review frame is graded for whether a caption was on screen, not for
  which.** `_check_frame_captions()` closes the "nothing says which beat a frame
  shows" gap only as far as one bit goes: a captioned beat's frame must show a
  bar and an uncaptioned one's must not. Two beats carrying *different* captions
  are indistinguishable to it, so a stall that slid a frame from one captioned
  beat to another captioned beat still passes. Tracked in
  [#60](https://github.com/rogvid/skills/issues/60), which would make the
  mapping readable off the frame instead of inferred.
- **Frames within 750 ms of a caption change are not graded for content at
  all**, and on these storyboards that is 8-9 of every take's frames. The
  exclusion is real coverage lost, not a formality: it is exactly where #18's
  drift puts a frame on the wrong side of a change, and where the harness
  therefore cannot tell a recorder bug from the capture. `check_beat_frames()`
  still grades those frames for placement and for byte-identity against
  `demo.mp4`; only the pixel claim is withheld.
- **No storyboard beat is long enough to make the recorder run scene
  detection.** `SCENE_MIN_SPAN_S` is 3 s and the longest beat either take
  performs is a 2 s `pause`, so the *manifest* half of that check — scene
  frames only inside long beats — is vacuous today and says so where it is
  written. The mechanism is graded directly instead (see **Review frames**),
  which is what stops the vacuity from being total.
- **Half the wall-clock class can now be fault-injected, and half still
  cannot.** The half that can: everything the recorder *does* about a stepping
  host — `_CaptureClock`'s sampler, its floor, the sign it records, the field
  it writes and the warning it prints — is graded by `tests/unit`'s
  `CaptureClock` over a **scripted** clock, and by four `tests/smoke-inject`
  entries that break the recorder while `tests/smoke` watches a real one. None
  of those depends on the box's clock actually stepping.

  The half that cannot: that the recorders *pace* on `time.monotonic()` rather
  than `time.time()`. Swapping them back only misreports when the system clock
  steps during a take, which no assertion here can provoke — it can only wait
  for it. On the box this was written on that wait is 32 s, which is why the
  bug was found at all; on a machine with a well-behaved clock a pass proves
  nothing about it. Reading the diff still does.
- **Issue attribution is bounded, not exact.** Playwright's sync API delivers
  page events only while it is inside a call, so the recorder pumps every
  100 ms during a hold and refuses to attribute an event to a beat that has not
  been open since the last pump. What that leaves: an event fired inside the
  pump interval of a beat boundary can land on either side of it, and a beat
  that blocks in a long *non*-Playwright call — narration being synthesized —
  queues events for its whole duration and gets `beat: null` for all of them.
  Null is the deliberate answer in both directions, but "null" and "right" are
  not the same thing and only the second is what a reader wants.
- **Nothing checks most of an issue's fields.** `kind`, `message`, `beat`,
  `verb` and one `caption` are asserted; `t`, `url`, `line`, `status`, `method`
  are not. `t` is knowingly the *observation* time and can sit outside the beat
  it names — measured at 3.53 s for a `nonzero_exit` whose `run` beat ended at
  3.4 s. Tracked in [#34](https://github.com/rogvid/skills/issues/34).
- **Nothing checks popups or new tabs.** The recorder watches one page, so a
  demo that opens a second one records nothing about it and `strict=True`
  cannot refuse it. Tracked in
  [#33](https://github.com/rogvid/skills/issues/33).
- **Nothing checks the 200-issue cap, or a `run()` that is never waited on.**
  `issue_count` is asserted equal to `len(issues)`, which is the uncapped case
  only — so the path where a fatal issue arrives past the cap and is counted
  but not recorded is unexercised, as is a `run()` whose prompt never comes
  back and therefore ends `exit_code: null`.
- **Nothing checks what teardown flushes.** `_pump` holds back trailing bytes
  that could still become an exit-status escape, and `_stop` writes them to the
  terminal on teardown. No assertion reads the final frame, so a regression
  there would lose the last few bytes of a program's output silently. Making it
  fail needs an assertion on the last frames of the mp4, which is a race with
  the screencast.
- **The segmented take records two parts of one storyboard, not a real
  time-skip.** Nothing waits between them, both are the web recorder against
  the same fixture, and no segment is re-recorded on its own — so the flow
  `keep_parts=True` exists for (re-record one expensive part, re-stitch) is
  exercised only as "stitch the same parts twice". A demo mixing a web and a
  terminal segment, which the merged envelope's `"mixed"` recorder value is
  for, is recorded nowhere.
- **The differential measurement dies before its own bar does.** Each reading
  goes through `caption_appearance_s`, whose search window is `ALIGN_PRE_S`
  (1.2 s) — so once a segment's *in-segment* skew passes about -0.72 s the
  measurement cannot be made at all, and the failure it produces blames a
  screencast stall (#18) rather than saying the merge was not graded. That
  cliff sits *inside* the 750 ms absolute bar, and the one segment-two stall
  measured here (-520 ms) was ~200 ms from it. The same limit makes a large
  offset error unmeasurable rather than measured: an injected nominal-timing
  merge (-2.12 s) degraded to "the caption band did not move… almost certainly
  a screencast stall", and what actually named the cause was the
  `segments`-record-vs-ffprobe check, not the acceptance criterion.
- **The merged envelope's disagreement paths are never taken.** Both segments
  are recorded by the same recorder with the same settings, so `recorder`
  resolves to `"Recorder"` and every `determinism` key agrees. The `"mixed"`
  value and `_merge_determinism`'s null-on-disagreement branch — both
  documented in `SKILL.md` as what a reader gets from a mixed demo — are
  produced by nothing here and asserted by nothing.
- **The merge's `issues` path is unexercised.** `stitch()` also offsets each
  issue's `t` and re-points its `beat` at the merged beat list, and the
  segmented take is a recording of a *healthy* app under `strict=True` — so it
  records no issues at all and none of that runs. An issue attributed to the
  wrong beat of the wrong segment would pass this suite. Tracked in
  [#51](https://github.com/rogvid/skills/issues/51).
- **The merge's error is measured at one beat per segment, not all of them.**
  Every other beat in a segment is carried by that segment's single offset, so
  one being right makes the rest right — but a merge that moved some of a
  segment's beats and not others would be caught only by the ordering and
  coverage checks, which are much coarser.
- **No segmented take writes evidence, so a merged timeline's `evidence`
  pointers are unexercised.** The `evidence/` take records with `segment=`, so
  `evidence/<segment>.seg.beat-NN.json` and the scoped stale-file clearing are
  exercised; `segments/` is what actually merges two parts, and it is graded on
  its beats rather than its evidence. So the half of
  [#22](https://github.com/rogvid/skills/issues/22) that matters to
  [#7](https://github.com/rogvid/skills/issues/7) — a merged timeline whose
  renumbered beats still point at the right files — has never run. The naming
  exists precisely so a merge has to rename nothing, and nothing here checks
  that it did not have to.
- **Nothing reads the evidence the way its acceptance criterion means it.**
  "A reviewer can state what was on screen" is graded as a list of substrings
  that must and must not be in each beat's capture. That is enough to catch an
  empty capture, a stale one, and a page that moved on — but whether an agent
  handed only `evidence/` could actually narrate the demo is the same
  unautomatable question as `SKILL.md` step 6's fresh-agent review, and
  nothing here asks it.
- **Nothing records with `evidence=False`.** The off switch, and the
  `DEMO_VIDEO_EVIDENCE=0` env var behind it, are exercised nowhere — every
  take here writes evidence
  ([#48](https://github.com/rogvid/skills/issues/48)).
- **Three checks are exercised by nothing between a pull request and its
  merge.** `--cheap` is what CI records per push since
  [#61](https://github.com/rogvid/skills/issues/61), and `check_opening`,
  `check_opening_gap` and `check_verb_classification` are reachable only from
  `--web-only`, `--content-only` and `--terminal-only`, which now run on merge.
  They also have no `tests/smoke-inject` entry, so nightly injection does not
  cover them either — the merge run is the whole of their exercise, and a
  reviewer looking at a green pull request has not seen them pass. Five other
  check functions moved to merge-only with them; those five do have injections
  and are exercised nightly. Measured before the split rather than found after
  it, and tracked in
  [#233](https://github.com/rogvid/skills/issues/233), which is the entries
  that would close it.
- **Nothing checks that the demo is any *good*.** These are liveness checks.
  Pacing, caption wording, whether the story lands — that is what the
  fresh-agent review in `SKILL.md` step 6 is for, and it is not automatable.
- **The target guard classifies a configured host, and seven things about that
  are not graded anywhere.** `target.py` is applied by both recorders at
  construction and by `scripts/demo-target-guard` in CI. `tests/unit`'s
  `TargetGuard` and `OneClassifier`, and `tests/ci-unit`'s `Classify` /
  `Check` / `Scan` / `WorkflowGates`, grade the rule, each recorder's
  application of it, that there is one copy of it, and that the workflow hands
  the pre-check and the recorder the same facts. What none of them can see:

  1. **A copy of the rules re-appearing *outside* the skill directory.**
     `OneClassifier` sweeps `SKILL_DIR` only, because `--fault-inject` copies
     that directory and an assertion reading the real repository from inside a
     broken copy would grade the wrong tree.
  2. **A rule re-implemented under different names.** `OneClassifier`'s
     markers (`_PRIVATE_SUFFIXES`, `is_loopback`, `ipaddress`) are
     name-shaped; a hand-rolled copy that spells them differently is
     invisible. The identity check beside it covers the shape that has
     actually happened — a helper shadowing `check` — and not this one.
  3. **An opt-in read straight from `os.environ`.**
     `test_nothing_spells_an_allow_public` matches `_env("…")` and
     `_env_flag("…")` calls, which is how every recorder setting is read; a
     direct `os.environ.get("DEMO_VIDEO_ALLOW_PUBLIC")` would not be seen, and
     `core.py` already reads `ELEVENLABS_API_KEY` that way, so the shape is
     available.
  4. **Exactly which tests an injection turns red.** `--fault-inject` requires
     the named tests to be *among* the failures, not to be all of them, so a
     break with wider blast radius than its entry claims still passes. The
     entries are written narrow on purpose; nothing enforces that.
  5. **The refusal's ordering for `TerminalRecorder` specifically.**
     `test_the_refusal_lands_before_anything_reaches_a_browser` reads the
     browser stand-in through `Recorder`. The shared base is what refuses in
     both, so the claim carries, but it carries by argument rather than by
     measurement.
  6. **Whether `npx skills add` still carries `scripts/` and `ensure.sh`.** A
     claim about a third-party CLI's copying rules, checked once by installing
     the skill and running the guard out of the install — it does — and
     nothing re-checks it when that CLI changes.
  7. **That a real `workflow_call` with `allow-private-network-target: true`
     records.** Nothing here runs GitHub. `WorkflowGates` grades the text of
     `.github/workflows/demo-video.yml` and actionlint type-checks its
     expressions; neither executes a job. No in-repo caller sets that input,
     so the regression it exists to catch would not appear on this
     repository's own pull requests either.

  `WorkflowGates` also has a **known false positive**, stated in its docstring:
  it reads the two steps' own `env:` blocks, so hoisting the export to the
  job-level `env:` is reported as missing. That is wrong in the conservative
  direction — a working configuration fails rather than a broken one passing —
  but it will mislead whoever hits it, and the fix is to teach `step_env`
  about the job block rather than to delete the assertion.

  And the standing one, which is a scope statement rather than a gap:
  **anything the take reaches other than its classified target.** A page that
  fetches another origin, a terminal storyboard that curls one, a URL computed
  at run time. This is a static classifier over configuration and source text,
  not an egress control, and `target.py`'s docstring says so in the same
  words. `scripts/demo-target-guard` is also outside mypy's scope, which runs
  over `skills/demo-video/helpers/` only.

Failures accumulate and print together, each naming the file or interaction and
the number that was wrong. The process exits non-zero if there is even one, and
`ok` is printed for an artifact only when *nothing* about it was wrong.

## The fixture app

`fixture/index.html` is a small fulfilment dashboard: a hero, three KPI cards,
a filter box, a refresh button, and a table. It is one file with no build step
and no dependencies, served by `python3 -m http.server`.

Everything the recorder touches has a stable id: `#kpi-rev`, `#kpi-orders`,
`#kpi-ontime`, `#search`, `#refresh`, `#rows` (plus `#row-nw-1041`… per row),
`#status`, `#empty`.

It is deterministic on purpose — no `Math.random()`, no clock on screen, no
animations. `#refresh` cycles three hard-coded snapshots in order, so a
recording made today is frame-for-frame the story of one made next year.

Four query-string hooks exist, inert unless asked for:

| URL | Effect | For |
|---|---|---|
| `?console-error=1` | logs a `console.error` **and** throws an uncaught error (Playwright `pageerror`), while the page stays usable | the Problems axis |
| `?bad-fetch=<url>` | fetches `/definitely-missing.json` (404) and `<url>` (connection refused), both during load | the Problems axis — during load so the failures land inside the recorder's `goto` beat |
| `?evidence=1` | renders one element carrying `data-token` and `data-cfg` attributes the page never paints, beside text it does | issue #9, the Evidence axis |
| `?entropy=1` | renders four clock readings (`Date`, `Intl`, `new Date().constructor`, and one posted back by a `Worker`, each read once at load) and `#entropy-spinner`, a shape turning once every 1.7 s | issue #10, the determinism takes |

`?entropy=1` is the one hook the fixture's own "keep it deterministic" rule is
suspended for, on purpose: the determinism takes need something that *would*
differ between recordings. Each clock is read once rather than ticking, because
a ticking one would also keep the compositor painting and confound the very
thing being measured. There is deliberately no `Math.random()` in it — see
Known gaps.

The panel is **prepended** to `.page`, not appended. Four readings and a 54 px
spinner are tall enough that at the bottom of the page they sit below the
720 px fold, and `shot()` captures the viewport rather than the full page — so
every comparison in the determinism phase passed against two byte-identical
photographs of a spinner nobody had photographed. It was caught by the
controls-off assertion, which is exactly what that assertion is for.

One hook, one take. The graded `web/` take loads none of them, so the reference
recording stays a recording of a working app — which is also the assertion that
the recorder does not invent problems.
## Adding a case

- **A new thing to record** — add a beat to `record_web` / `record_terminal` in
  `tests/smoke`, add its `shot()` name to `WEB_SHOTS` / `TERMINAL_SHOTS` so the
  still is actually checked, and add its `(verb, target)` to `WEB_BEATS` /
  `TERMINAL_BEATS` (and its text to `WEB_CAPTIONS` / `TERMINAL_CAPTIONS` if it
  is a caption) so the timeline check knows to expect it. `record_segments`
  works the same way, except that its list is `SEGMENT_BEATS_FULL` and carries
  a third column, the segment the beat belongs to. Those lists are
  deliberately hand-maintained; see **Timeline** above for why — and
  `WEB_BEATS` is also what the **Review frames** axis counts frames against and
  searches `frames.md` for, so a stale entry there fails twice. Adding a beat
  lengthens the take; keep it inside the duration window, or widen the window
  deliberately. **Every interaction gets a `b.expect(...)` naming what it
  should have changed** — a beat with no post-condition is a beat that passes
  when the verb is a no-op. Anything that leaves the page still for more than a
  second also wants a look at `TICKER_JS`: idle is what makes the screencast
  lose time, and adding idle is how the timing bar was made flaky once already.
- **A new caption, interlude or selector** — it goes in the hand-written lists
  (`WEB_CAPTIONS`, `SEGMENT_INTERLUDES`, the beat list), and the **Review
  frames** axis then requires `frames.md` *not* to contain it. That is the
  intended direction: the sheet a context-free reviewer reads must not name the
  thing they are being asked to discover. A caption also moves the boundaries
  `_check_frame_captions()` guards, so adding one near the end of a storyboard
  can push frames out of the graded set — watch the "not graded" count in the
  pass line, and `MIN_GRADED_CAPTION_FRAMES` is the floor, not a dial.
- **Anything in the page that must keep moving** — a second ticker, an
  animation a take is *about* — has to carry `data-demo-video-animate`, or the
  recorder's determinism rule lands it on its final frame the moment it
  appears. That attribute is the recorder's published opt-out, not a test
  hook; `TICKER_JS` is the worked example.
- **A new storyboard verb in the recorder** — decorate it with `@_beat_verb`
  so it lands in the beat log, or the timeline stops being a full account of
  the take. A verb built out of other verbs records one beat, not one per
  internal step; the nesting guard in `_DemoBase._beat` handles that.
- **A new thing for the app to do** — put it in `fixture/index.html` behind a
  stable id, and keep it deterministic. If it only matters to one future
  feature, hide it behind a query-string hook the way the two above are, so the
  default recording stays clean.
- **A new thing for the recorder to notice** (a new issue kind, a new signal) —
  add it to `ISSUE_KINDS` in `core.py`, decide whether it belongs in
  `STRICT_KINDS`, make one of the storyboards cause it on purpose, and add a
  `(kind, message substring, verb)` row to `WEB_ISSUES` / `TERMINAL_ISSUES`.
  The verb is what makes the row worth writing: an issue that is recorded but
  attributed nowhere is a problem report with the page number torn off.
- **A new failure mode to catch** — prefer another assertion in `check_take()`
  or `check_issues()` over another take. Takes cost ~15 s each in CI;
  assertions are free. The two strict takes are the exception that proves it:
  "the take raises" cannot be asserted about a take that has to succeed for
  everything else to be graded, so they exist, and they are kept to a few
  seconds each and graded on nothing else.
- **A new fact evidence must record** — add a `(verb, target, present, absent)`
  row to `WEB_EVIDENCE` / `TERMINAL_EVIDENCE`. **Fill in `absent`.** A `present`
  list alone passes on a recorder that dumped the page once and copied it into
  every beat, which is the failure mode this axis exists to catch; `absent`
  is what the previous screen showed and must not still be there. Both lists
  are facts about `fixture/index.html`, written by hand, never read back off a
  recording.
- **A new field in an evidence document** — give it a budget in
  `EVIDENCE_LIMITS` if it can grow, and mirror that number in
  `EVIDENCE_LIMITS_EXPECTED` in `tests/smoke`. The two are asserted equal, so a
  cap widened on one side has to fail rather than pass by agreeing with itself.
- **A new thing the markup serializer must drop** — say so with a *pair* of
  assertions, never one. Every claim in this axis is that something is
  **absent**, and absence holds trivially over an empty capture: the arm asserts
  `EVIDENCE_RENDERED_TEXT` is present first, and anything added here needs the
  same kind of control. Inject the element from the storyboard
  (`EVIDENCE_SOURCE_JS` is the pattern) rather than adding it to the fixture,
  unless a spotlight has to be able to name it.

**Prove any new assertion can fail.** Break the thing it watches — stub the verb
out in `skills/demo-video/helpers/`, or blank the fixture — run `tests/smoke`,
and see it fail with a message that names the real cause. Then `git checkout --
skills/` and see it pass again. Two of the checks in this file's history looked
like coverage for a whole review round and could not fail at all: a whole-frame
contrast score that a blank recording *beat*, and a cursor-position check that
was measuring Playwright's `click()` rather than the recorder's `move_to()`. An
assertion nobody has watched fail is a comment.

**Then register it**, if the assertion is one whose silent failure would cost
something: an `Injection(...)` in `tests/smoke-inject` turns the break you just
performed by hand into one that re-runs nightly. See **The injection manifest**
above for the contract. The hand-injection stays the first step — the entry is
how it stays proven after you have moved on, which is the half that was missing.
