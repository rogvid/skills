"""Where a take that did not finish writes itself down.

Only the constants live here — the paths, the schema and the message budget.
The documents themselves are built by the recorder, because building them
means reading a live page, and they are built in memory and refused whole if
the mask cannot be vouched for.
"""

from __future__ import annotations

# -- failure artifacts (issues #11, #20, #24, #32, #46) ----------------------
#
# What a take leaves behind when it does not finish. The rule the whole section
# is built to satisfy: **after an abnormal exit, every artifact present is
# either current, or absent, or explicitly marked stale.** Three things used to
# violate it, and all three lived in `__exit__`:
#
#   * a take that raised converted nothing and wrote nothing, so the one
#     recording anybody wanted to look at was deleted with `.video/` (#32).
#     In CI there is no screen, so that means blind retries.
#   * `_timeline_doc()` probed `demo.mp4` unconditionally, so a take that wrote
#     no mp4 reported the *previous* take's duration beside this take's beats
#     (#20) — and `stitch()` offsets segment timelines by exactly that number.
#   * a failed re-record left the previous run's `demo.mp4` sitting in the
#     folder looking current (#46), which in a review gate produces a confident
#     approval of something that was never recorded.
#
# What is written now, on any abnormal exit the recorder is allowed to keep
# artifacts from:
#
#   demo.mp4              the partial recording, converted from the webm that
#                         was already in hand
#   timeline.json/.md     the beats, with `error` on the one that raised (#24)
#                         and `failure` on the envelope
#   failure/              this section: a self-contained account of the crash
#   demo-video-FAILED.md  the marker (#46), written whether or not anything
#                         else was, and deleted by the next take that succeeds
#
# **The redaction ordering is the constraint that shapes all of it.** A crash
# dump of a page mid-secret is the worst leak path this package has, and
# `_verify_redaction_final()` — the thing that decides whether *any* of it may
# be kept — runs after `_stop()` and vouches for the page as it then is.
# So nothing here reads the page after that point:
#
#   * the last frame is extracted from `demo.mp4` with ffmpeg. It is a frame of
#     the recording the verifier already vouched for, so it inherits the whole
#     guarantee and costs no page access at all;
#   * the DOM / terminal screen is read **once, before** the verifier runs
#     (`_failure_screen()`), buffered in memory, and only masked and written
#     after the verifier has passed;
#   * the console log and the failing beat were in memory the whole time.
#
# Everything textual then goes through `_evidence_forbidden()` — the registered
# secrets *and* the harvested rendered text of everything `redact()` covers —
# is masked with it, and is checked with `_evidence_holds()` over the serialized
# bytes. A document that still holds a forbidden literal raises `SecretLeak`,
# and it raises it while the dump is still in memory, so the failure cannot
# leave half a directory behind. That is the same shape `_build_evidence()` /
# `_write_evidence()` already have, for the same reason.
FAILURE_DIR = "failure"
FAILURE_SCHEMA = 1

# The marker (#46). Named visibly rather than as the dotfile the issue sketched
# (`.demo-video-failed`): the artifact it exists to contradict is a `demo.mp4`
# somebody is about to watch, and a hidden file next to it is exactly as easy
# to miss as the problem. `ls` shows this one, and so does a file browser.
FAILURE_MARKER = "demo-video-FAILED.md"

# How much of an exception message reaches the marker and the dump. A
# `wait_for_text()` timeout quotes a thousand characters of terminal screen,
# and a Playwright error quotes the selector, a call log and a page snippet;
# past a point that is a file nobody opens rather than a report. The timeline's
# per-beat `error.message` is **not** capped — it is the machine-readable copy
# and something may want to match on it — so nothing is lost by capping here.
FAILURE_MESSAGE_CHARS = 2_000
