"""The take recorders, split verbatim out of the pre-split `tests/smoke`.

Part of the smoke suite package (`tests/smokekit/`); the executable entry
is `tests/smoke`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from _pixels import Rect

from .checks import (  # noqa: E402
    check_caption,
    check_determinism,
    check_undrawn_pointer,
)
from .constants import (  # noqa: E402
    _FOCUSED_JS,
    _TRAIL_JS,
    CAPTION_PROBE,
    CONTENT_CARD,
    CONTENT_COMMANDS,
    CONTENT_TAKES,
    CONTENT_TOUR_CAPTIONS,
    CONTENT_TOUR_COMMAND,
    CONTENT_TOUR_HOLD_S,
    CONTENT_TOURED,
    COVERAGE_CARD,
    COVERAGE_CRITERIA,
    ENTROPY_GAP_S,
    ENTROPY_SETTLE_S,
    ENTROPY_SHOTS,
    FIXTURE_DIR,
    FROZEN_EPOCH_MS,
    MIN_MONOTONIC_ADVANCE_MS,
    MIN_SPOTLIGHT_CLEAR_S,
    NARRATION_HOLD_S,
    NARRATION_KEY,
    NARRATION_KEY_CHARS,
    NARRATION_LINES,
    NARRATION_LONG_LINE,
    NARRATION_MODEL_ID,
    NARRATION_SHORT_LINE,
    NARRATION_STABILITY,
    NARRATION_VOICE_ID,
    OPENING_CARD,
    OPENING_HOLD_S,
    OPENING_STRIP_FRACTIONS,
    OVERLAY_HOLD_S,
    OVERLAY_LABEL,
    OVERLAY_QUIET_S,
    OVERLAY_TAKES,
    PROBE_CAPTION,
    PROBE_QUIET_S,
    SEGMENT_INTERLUDE,
    SEGMENT_INTERLUDE_HOLD_S,
    SEGMENT_NAMES,
    SEGMENT_OPENING,
    SEGMENT_SHOTS,
    SERVER_START_TIMEOUT_S,
    SPOTLIGHT_HOLD_S,
    SPOTLIGHT_PAD_PX,
    SPOTLIGHT_TARGET,
    TICKER_JS,
    WRAPPER_CAPTION,
    WRAPPER_CLAUSE,
    WRAPPER_LONG_CAPTION,
    WRAPPER_SURVIVES,
)
from .support import (  # noqa: E402
    Beats,
    EntropyTake,
    HostClock,
    SmokeFailure,
    _StoryboardFailed,
    free_port,
    fresh_take_dir,
    start_ticker,
    watch_wall_clock,
)


def record_web(
    out_dir: Path, base_url: str, clock: HostClock | None = None
) -> tuple[list[str], dict, tuple[int, int]]:
    """Land, read a KPI, filter the table, refresh it.

    Returns the post-condition failures plus the take's chrome geometry and
    frame size. A wrapper take records the framed page itself (#358/#361),
    so the app sits at the same rect in the video and in every still —
    `run_web` derives one content rect from the geometry for both.

    A recording of a *working* app, and recorded with `strict=True` so it has
    to stay one. That is the assertion the rest of this harness structurally
    cannot make: every issue check elsewhere is "at least one of these
    appeared", which a recorder that flagged every healthy response as fatal
    would satisfy while refusing every real demo ever recorded. Here it would
    raise, and take the whole take with it.
    """
    from demo_recording import Recorder

    b = Beats("web")
    outline = "el => getComputedStyle(el).outlineStyle"
    bg = "el => getComputedStyle(el).backgroundColor"

    # deterministic=True, though the recorder's default is off: this take is
    # where the frozen clock and the motion rule have to be shown coexisting
    # with TICKER_JS, and the control-element assertion in start_ticker() has
    # nothing to say unless the rule is actually injected. The default path is
    # graded by the determinism-default take instead. strict=True because this
    # is the healthy fixture: determinism must not itself produce a console
    # error or a failed request.
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        # Frame zero, so the host-clock steps this run measured land on the
        # same clock the beats do. `_t0` is a `time.monotonic()` reading and
        # not part of what `capture_clock` claims — see HostClock.
        if clock is not None:
            clock.rebase(rec._t0)
        rec.goto("/")
        # #142's carve-out, graded. `framenavigated` was written for the paint
        # gate, and the gate went with the masking — but it is the recorder's
        # only reaction to a document being replaced, and #134 (a mid-take
        # goto() leaving `self._caption` stale, so every later beat logs a
        # caption that is not on screen into a committed file) cannot be fixed
        # without it. Deleting the listener along with everything else it was
        # written for is the mistake this watches for, and nothing else here
        # would notice: no artifact records a navigation today.
        b.expect("goto('/') is noticed as a navigation", rec._navigated, True)
        rec.wait_for("#kpi-rev")
        # In the app document, both of them: the ticker's opt-out control and
        # the determinism probes are claims about what the recorder does to
        # the *app*, and the app lives in the iframe (#358/#361). The ticker
        # still keeps the whole page's compositor awake from in there — an
        # iframe paint is a page paint.
        start_ticker(b, rec.app)
        opening = check_determinism(b, rec.app, "on landing")
        # Doubles as the run-up for the *early* timing probe: the page has
        # finished painting and the caption band does not move until the
        # first caption. See MAX_CAPTION_SKEW_S.
        rec.pause(PROBE_QUIET_S)
        b.expect(
            "goto('/'), #rows row count",
            rec.app.locator("#rows tr").count(),
            5,
        )
        b.expect(
            "goto('/'), #status text",
            rec.app.locator("#status").inner_text(),
            "snapshot 1 of 3",
        )
        # A stylesheet that failed to load leaves the DOM intact and the page
        # legible-ish, which the luma metric scores around 10 — above its
        # floor. This resolves that case exactly, with no pixel threshold.
        b.expect(
            "goto('/'), #refresh background (did the stylesheet apply?)",
            rec.app.eval_on_selector("#refresh", bg),
            "rgb(235, 110, 20)",
        )

        rec.caption("A small dashboard.")
        check_caption(b, rec.page, "A small dashboard.")
        rec.shot("01-dashboard")

        rec.spotlight("#kpi-rev")
        b.expect(
            "spotlight('#kpi-rev'), computed outline-style",
            rec.app.eval_on_selector("#kpi-rev", outline),
            "solid",
        )
        rec.hold()
        rec.spotlight()
        b.expect(
            "spotlight() cleared, computed outline-style",
            rec.app.eval_on_selector("#kpi-rev", outline),
            "none",
        )

        rec.caption("Filter by city.")
        check_caption(b, rec.page, "Filter by city.")
        rec.type_into("#search", "seattle")
        rec.pause(0.8)
        b.expect(
            "type_into('#search'), field value",
            rec.app.input_value("#search"),
            "seattle",
        )
        b.expect(
            "type_into('#search'), #rows row count",
            rec.app.locator("#rows tr").count(),
            1,
        )
        rec.shot("02-filtered")

        rec.caption("Refresh reloads it.")
        check_caption(b, rec.page, "Refresh reloads it.")

        # move_to() is the sole source of the 30-step cursor glide. Asserting
        # only where the cursor ends up proves nothing, because Playwright's
        # locator.click() dispatches its own mousemove to the target — that
        # measures Playwright, not move_to. Count the intermediate moves
        # instead: a glide is many, a click is one. Counted in the *app*
        # document: the moves' coordinates land over the iframe (the glide
        # runs from #search to #refresh, both inside the app rect), and no
        # wrapper listener can hear a move whose target is inside it.
        rec.app.evaluate(_TRAIL_JS)
        rec.move_to("#refresh")
        trail = rec.app.evaluate("() => window.__smokeTrail.length")
        b.fail_if(
            trail < 10,
            f"move_to('#refresh') produced {trail} mousemove events; the glide "
            f"is 30 steps, so this is not a glide",
        )

        rec.click("#refresh")
        rec.pause(1.0)
        b.expect(
            "click('#refresh'), #status text",
            rec.app.locator("#status").inner_text(),
            "snapshot 2 of 3",
        )
        b.expect(
            "click('#refresh'), #kpi-rev text",
            rec.app.locator("#kpi-rev").inner_text(),
            "$134,950",
        )
        rec.shot("03-refreshed")

        # -- the form verbs (issue #130) --------------------------------------
        #
        # Every assertion here reads the *app*, not the beat log: a verb that
        # logged a beautiful beat and pressed nothing fails each one. The beat
        # log is graded separately, by WEB_BEATS and by the two WEB_EVIDENCE
        # entries keyed on ("clear", "#search") and ("press", "Enter") — which
        # is the half of the issue no post-condition can see, since
        # `rec.page.keyboard` would satisfy everything below and write nothing.
        rec.caption("Keys, not just clicks.")
        check_caption(b, rec.page, "Keys, not just clicks.")

        # The pre-condition is asserted, not assumed: "the field is empty" is
        # not news about a field that was already empty, which is the vacuous
        # sweep in wip/verified-review with a different haystack.
        b.expect(
            "before clear('#search'), #search value",
            rec.app.input_value("#search"),
            "seattle",
        )
        rec.clear("#search")
        b.expect(
            "clear('#search'), field value",
            rec.app.input_value("#search"),
            "",
        )
        b.expect(
            "clear('#search'), #rows row count (all four rows are back)",
            rec.app.locator("#rows tr").count(),
            4,
        )
        # The caret stays where the viewer last saw it, which is what lets the
        # press() below be selector-free rather than careless — and it is the
        # post-condition Escape does *not* produce, so neither verb can pass an
        # assertion meant for the other.
        b.expect(
            "clear('#search'), the focused element (the caret stays in the box)",
            rec.app.evaluate(_FOCUSED_JS),
            "search",
        )
        rec.shot("04-cleared")

        # Enter submits from inside the field clear() left the caret in.
        rec.press("Enter")
        b.expect(
            "press('Enter'), #status text",
            rec.app.locator("#status").inner_text(),
            "snapshot 3 of 3",
        )
        b.expect(
            "press('Enter'), #kpi-rev text",
            rec.app.locator("#kpi-rev").inner_text(),
            "$119,180",
        )

        rec.press("Tab")
        b.expect(
            "press('Tab'), the focused element",
            rec.app.evaluate(_FOCUSED_JS),
            "refresh",
        )
        # ...and the half of Tab a viewer can see. `:focus-visible` in the
        # fixture draws this ring for keyboard focus only, so the mouse click
        # on #refresh above leaves it 'none' and this cannot pass on that.
        b.expect(
            "press('Tab'), #refresh computed outline-style (the ring)",
            rec.app.eval_on_selector("#refresh", outline),
            "solid",
        )

        # Escape last, with a term in the box for it to dismiss — and a row
        # count that says the box really holds one, because an Escape that
        # emptied nothing would satisfy the value check below on its own.
        rec.type_into("#search", "harbor")
        rec.pause(0.6)
        b.expect(
            "type_into('#search', 'harbor'), #rows row count",
            rec.app.locator("#rows tr").count(),
            1,
        )
        rec.press("Escape")
        b.expect(
            "press('Escape'), #search value",
            rec.app.input_value("#search"),
            "",
        )
        b.expect(
            "press('Escape'), #rows row count (all six rows are back)",
            rec.app.locator("#rows tr").count(),
            6,
        )
        b.expect(
            "press('Escape'), the focused element (the dismiss let the box go)",
            rec.app.evaluate(_FOCUSED_JS),
            "body",
        )

        # Two stills back to back with the page frozen and only the caption
        # changing. Their difference in the caption band is pixel proof that
        # the bar was actually drawn — see MIN_CAPTION_BAND_DIFF. The quiet
        # second in the middle is what makes the same moment usable as the
        # timing probe — see caption_appearance_s().
        rec.caption("")
        check_caption(b, rec.page, "")
        rec.shot(CAPTION_PROBE[0])
        rec.pause(PROBE_QUIET_S)
        rec.caption(PROBE_CAPTION)
        check_caption(b, rec.page, PROBE_CAPTION)
        rec.shot(CAPTION_PROBE[1])

        # The clock has to still be frozen ~15 s later, not merely at load —
        # and the page's *monotonic* clock has to have kept running, because
        # that is the one CSS animations are on. A freeze that stopped it too
        # would stop the compositor, and the recording would start losing wall
        # time again (TICKER_JS, issue #18).
        closing = check_determinism(b, rec.app, "at the end of the take")
        b.fail_if(
            closing["now"] != opening["now"],
            f"the frozen clock moved during the take: {opening['now']} at the "
            f"start, {closing['now']} at the end — it is pinned at page load "
            f"and then drifts, which is worse than not pinning it",
        )
        advance = closing["monotonic"] - opening["monotonic"]
        b.fail_if(
            advance < MIN_MONOTONIC_ADVANCE_MS,
            f"the page's monotonic clock advanced {advance:.0f} ms across a "
            f"take that took several seconds — the freeze has reached past the "
            f"wall clock into the clock CSS animations run on, so the "
            f"compositor is not painting and issue #18 is back",
        )
        rec.caption("")

        # ...and again for a navigation the *storyboard did not make* — a
        # link click, a form submit, `location.href` all replace the app's
        # document with no verb involved. `rec.app.goto` stands in for all
        # of them: a real navigation of the app frame, driven past the verb
        # layer, recording no beat of its own — so this asserts the listener
        # rather than the verb, and adds nothing to WEB_BEATS. The wrapper
        # page itself never navigates (#358), which is why the caption
        # cannot be lost to any of these; the listener noticing the frame is
        # #142's carve-out, kept.
        rec._navigated = False
        rec.app.goto(rec.app.url)
        b.expect("a navigation no verb made is noticed too", rec._navigated, True)

        # Where the app lands, read off the live recorder rather than
        # re-derived here, so a change to the window geometry carries this
        # with it instead of silently scoring the wrong pixels.
        geom = dict(rec._geom)
        size = (rec._size["width"], rec._size["height"])

    return b.problems, geom, size


def record_terminal(
    out_dir: Path, clock: HostClock | None = None
) -> tuple[list[str], Rect, Rect, tuple[int, int]]:
    """Two trivial commands — enough to exercise PTY, xterm.js, and prompt sync."""
    from demo_recording import TerminalRecorder

    b = Beats("terminal")

    # Both terminal syncs raise on timeout, which would abort the take before
    # the mp4 was written — and then CI's failure-only artifact upload has
    # nothing to show at exactly the moment somebody wants to look at it.
    # Collect instead, and keep the timeouts short so a broken take fails in
    # seconds rather than minutes.
    def expect_screen(rec, after: str, pattern: str) -> None:
        try:
            rec.wait_for_text(pattern, timeout_s=10)
        except RuntimeError as exc:
            tail = " ".join(str(exc).split())[:200]
            b.fail_if(
                True,
                f"after {after}, the rendered screen never matched /{pattern}/ "
                f"— {tail}",
            )

    def expect_prompt(rec, after: str) -> None:
        try:
            rec.wait_for_prompt(timeout_s=15)
        except RuntimeError as exc:
            tail = " ".join(str(exc).split())[:200]
            b.fail_if(True, f"after {after}, the shell prompt never came back — {tail}")

    with TerminalRecorder(
        out_dir, speech=False, strict=True, deterministic=True
    ) as rec:
        if clock is not None:
            clock.rebase(rec._t0)  # see HostClock
        start_ticker(b, rec.page)
        # The determinism controls live on the context, so the terminal
        # recorder inherits every one of them — and a page that renders a real
        # PTY is where a frozen clock is most likely to break something.
        check_determinism(b, rec.page, "in the terminal page")
        # Let xterm.js settle, and give the early timing probe below a
        # baseline that is not the browser's first paint. See
        # MAX_CAPTION_SKEW_S.
        rec.pause(PROBE_QUIET_S)
        rec.caption("A real shell, recorded.")
        check_caption(b, rec.page, "A real shell, recorded.")
        rec.run("echo hello from demo-video")
        expect_prompt(rec, "run('echo …')")
        # Anchored to a whole screen line, and matching the command's *output*
        # rather than the echoed command line — so it only passes if the PTY
        # really ran what run() typed.
        expect_screen(rec, "run('echo …')", r"^hello from demo-video$")
        rec.shot("01-echo")

        rec.caption("Any command works.")
        check_caption(b, rec.page, "Any command works.")
        rec.run("ls -1")
        expect_prompt(rec, "run('ls -1')")
        expect_screen(rec, "run('ls -1')", r"^skills$")
        rec.pause(0.8)
        rec.shot("02-listing")

        rec.caption("")
        check_caption(b, rec.page, "")
        rec.shot(CAPTION_PROBE[0])
        rec.pause(PROBE_QUIET_S)
        rec.caption(PROBE_CAPTION)
        check_caption(b, rec.page, PROBE_CAPTION)
        rec.shot(CAPTION_PROBE[1])
        rec.caption("")

        # The xterm.js host div — a real element with a stable id, so the
        # content rect follows any change to the window chrome.
        box = rec.page.locator("#__term_host").bounding_box()
        if box is None:
            raise SmokeFailure("#__term_host has no box — the terminal never rendered")
        rect: Rect = (
            int(box["x"]),
            int(box["y"]),
            int(box["width"]),
            int(box["height"]),
        )
        size = (rec._size["width"], rec._size["height"])

    # The terminal frames itself in-page and is not composited, so its video
    # and its stills share one geometry.
    return b.problems, rect, rect, size


def record_segments(
    out_dir: Path, base_url: str
) -> tuple[list[str], Rect, Rect, tuple[int, int], list[HostClock]]:
    """One demo, recorded as two segments — the shape a real time-skip takes.

    Deliberately the storyboard SKILL.md tells people to write: record part
    one, do the slow thing (here, nothing at all), then open part two with an
    `interlude()` on the blank page before navigating back. Both segments
    write their own `.seg.mp4` and their own beat log; `stitch()` joins them.

    Nothing is stitched here — the caller does it, so that what the parts look
    like *before* the merge can be asserted. Without that, "the merged
    timestamps are large" would prove nothing.
    """
    from demo_recording import Recorder

    b = Beats("segments")
    settings = {
        "base_url": base_url,
        "speech": False,
        # Same reasoning as record_web(): deterministic=True is what makes
        # start_ticker()'s control-element assertion mean anything, and
        # strict=True keeps this a recording of a working app.
        "strict": True,
        "deterministic": True,
    }

    # One watcher per segment, because one watcher for the pair would be
    # wrong: each segment is its own capture with its own first frame, so a
    # wall-clock step between them moves nothing at all, and a step inside
    # segment one does not move segment two's frames (issue #215). What is
    # returned is therefore per-segment and `run_segments()` maps each onto the
    # merged video's clock using the parts' own durations.
    clocks: list[HostClock] = []

    with (
        watch_wall_clock() as clock_one,
        Recorder(out_dir, segment=SEGMENT_NAMES[0], **settings) as rec,
    ):
        clock_one.rebase(rec._t0)
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        start_ticker(b, rec.app)
        # The run-up for the early timing probe: the page has finished painting
        # and nothing moves in the caption band until the caption does.
        rec.pause(PROBE_QUIET_S)
        rec.caption(SEGMENT_OPENING)
        check_caption(b, rec.page, SEGMENT_OPENING)
        rec.shot(SEGMENT_SHOTS[0])
        rec.caption("")

        g = rec._geom
        video_rect: Rect = (g["appx"], g["appy"], g["appw"], g["apph"])
        size = (rec._size["width"], rec._size["height"])
        # One rect for both: a wrapper still is the framed frame (#361).
        still_rect: Rect = video_rect
    clocks.append(clock_one)

    with (
        watch_wall_clock() as clock_two,
        Recorder(out_dir, segment=SEGMENT_NAMES[1], **settings) as rec,
    ):
        clock_two.rebase(rec._t0)
        # Before anything else: the second segment's opening seconds are the
        # ones most likely to go idle, and idle is what makes the screencast
        # lose wall time (TICKER_JS, issue #18). The interlude card covers it
        # while it is up — see SEGMENT_INTERLUDE_HOLD_S. In the app frame,
        # which is still about:blank here — the goto below replaces that
        # document and the ticker with it.
        start_ticker(b, rec.app)
        rec.interlude(SEGMENT_INTERLUDE, hold=SEGMENT_INTERLUDE_HOLD_S)
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        # The navigation took the first one with it.
        start_ticker(b, rec.app)

        # The closing probe, in the *second* segment on purpose: its beat
        # timestamps are the ones the merge has to move, and this is where the
        # acceptance criterion of #7 is actually measured.
        rec.caption("")
        check_caption(b, rec.page, "")
        rec.shot(CAPTION_PROBE[0])
        rec.pause(PROBE_QUIET_S)
        rec.caption(PROBE_CAPTION)
        check_caption(b, rec.page, PROBE_CAPTION)
        rec.shot(CAPTION_PROBE[1])
        rec.caption("")
    clocks.append(clock_two)

    return b.problems, video_rect, still_rect, size, clocks


def record_spotlight(
    out_dir: Path, base_url: str, clock: HostClock | None = None
) -> tuple[list[str], dict]:
    """A spotlight put up and taken down again, with quiet either side.

    Recorded with the recorder's **default** (`deterministic=False`), which no
    other take in this file does on purpose. The determinism rule flattens
    every CSS transition to 1 ms, so under it the spotlight's enter and its
    exit both snap — correctly and consistently — and an assertion about
    easing has nothing to say. Issue #111 is only visible in a take that
    records real motion.
    """
    from demo_recording import Recorder

    b = Beats("spotlight")

    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=False
    ) as rec:
        if clock is not None:
            clock.rebase(rec._t0)  # see HostClock
        rec.goto("/")
        rec.wait_for(SPOTLIGHT_TARGET)
        # The ticker, but not start_ticker(): that helper also asserts the
        # determinism CSS is in force, and this take deliberately records
        # without it. What the ticker is for here is only that the screencast
        # keeps emitting frames through the quiet stretches, so the windows
        # below sit where the beat log says they do.
        rec.app.evaluate(TICKER_JS)
        b.fail_if(
            not rec.app.evaluate("() => !!document.getElementById('__smoke_ticker')"),
            "the compositor ticker did not attach — the windows this take "
            "measures its two transitions in are not trustworthy",
        )
        # Nothing else may move in the element's rect, or a frame that differs
        # from the one before it stops meaning "the spotlight is moving".
        rec.pause(SPOTLIGHT_HOLD_S)

        style_before = rec.app.locator(SPOTLIGHT_TARGET).first.evaluate(
            "el => [el.hasAttribute('style'), el.getAttribute('style')]"
        )
        rec.spotlight(SPOTLIGHT_TARGET)
        lit = rec.app.locator(SPOTLIGHT_TARGET).first.evaluate(
            "el => getComputedStyle(el).transform"
        )
        # Cheap, and it separates "the exit did not animate" from "the
        # spotlight never went on in the first place", which look identical in
        # a frame sweep that finds nothing.
        b.fail_if(
            lit in ("none", "", None),
            f"spotlight({SPOTLIGHT_TARGET!r}) left the element's computed "
            f"transform at {lit!r} — the highlight never went on, so the exit "
            f"measurement below is about nothing",
        )
        rec.pause(SPOTLIGHT_HOLD_S)

        clearing = time.monotonic()
        rec.spotlight()
        cleared_in = time.monotonic() - clearing
        # #111's second half, and the one no pixel can see: the element is
        # handed back exactly as it was found, byte for byte, including having
        # no style attribute at all when it started with none.
        style_after = rec.app.locator(SPOTLIGHT_TARGET).first.evaluate(
            "el => [el.hasAttribute('style'), el.getAttribute('style')]"
        )
        b.fail_if(
            style_after != style_before,
            f"after spotlight() cleared, {SPOTLIGHT_TARGET}'s inline style is "
            f"(has_attr, value) {style_after!r}, but it was {style_before!r} "
            f"before the spotlight — the element was not returned as it was "
            f"found. If only the flag differs, the clear is leaving an empty "
            f"style attribute behind; if the value differs too, it is leaving "
            f"the spotlight's own properties on the element.",
        )
        # ...and the decision that goes with it: the verb waits. See
        # MIN_SPOTLIGHT_CLEAR_S for why the assertion above cannot say this.
        b.fail_if(
            cleared_in < MIN_SPOTLIGHT_CLEAR_S,
            f"spotlight() cleared and returned in {cleared_in:.2f}s, under the "
            f"{MIN_SPOTLIGHT_CLEAR_S}s bar — it did not wait out its own exit "
            f"transition, so the next beat starts mid-fade and this beat's "
            f"evidence records a style attribute that depends on when the "
            f"compositor happened to fire. (A take that recorded with "
            f"deterministic=True reads about this too; the enter control in "
            f"check_spotlight_transitions says which of the two it is.)",
        )
        rec.pause(SPOTLIGHT_HOLD_S)

        box = rec.app.locator(SPOTLIGHT_TARGET).first.bounding_box()
        if box is None:
            raise SmokeFailure(
                f"{SPOTLIGHT_TARGET} has no box — tests/fixture/index.html "
                f"changed and this take is aimed at nothing"
            )
        pad = SPOTLIGHT_PAD_PX
        # `bounding_box()` answers in wrapper-page coordinates even for
        # iframe elements, and the wrapper page is the video at true pixel
        # size (#358/#361) — so the padded box is already the video rect,
        # with no scale and no offset left to apply.
        target_rect: Rect = (
            int(box["x"]) - pad,
            int(box["y"]) - pad,
            int(box["width"]) + 2 * pad,
            int(box["height"]) + 2 * pad,
        )
        geom = dict(rec._geom)
        size = (rec._size["width"], rec._size["height"])

    return b.problems, {
        "rect": target_rect,
        "app": (geom["appx"], geom["appy"], geom["appw"], geom["apph"]),
        "size": size,
    }


def record_terminal_opening(out_dir: Path) -> tuple[list[str], dict]:
    """A terminal segment opened with `TerminalRecorder(interlude=…)`.

    Deliberately the shape issue #110 measured on the reference demo: a
    terminal segment whose first thing on screen is a title card. The
    storyboard says nothing about the card — that is the whole point of the
    constructor argument — so everything the assertions read comes from the
    recorder's own behaviour.
    """
    from demo_recording import TerminalRecorder

    b = Beats("terminal-opening")

    with TerminalRecorder(
        out_dir,
        speech=False,
        strict=True,
        deterministic=True,
        interlude=OPENING_CARD,
        interlude_hold=OPENING_HOLD_S,
    ) as rec:
        start_ticker(b, rec.page)
        rec.caption("The card came up before the terminal did.")
        rec.run("echo opened on a card")
        try:
            rec.wait_for_prompt(timeout_s=15)
        except RuntimeError as exc:
            b.fail_if(True, f"the shell prompt never came back — {exc}")
        rec.pause(0.6)
        rec.caption("")

        host = rec.page.locator("#__term_host").bounding_box()
        if host is None:
            raise SmokeFailure(
                "#__term_host has no box — the terminal never rendered in "
                "the chrome's slot, so there is no strip to read the cover "
                "out of"
            )
        app: Rect = (
            int(host["x"]),
            int(host["y"]),
            int(host["width"]),
            int(host["height"]),
        )
        geom = dict(rec._geom)
        size = (rec._size["width"], rec._size["height"])

    # The opening strip: this file's own fractions of the shared chrome's
    # app rect (#362) — where the cover and, later, the shell's first rows
    # are. Far from TICKER_JS's 8x8 corner element, so the ticker cannot
    # contribute a single level to this.
    fx, fy, fw, fh = OPENING_STRIP_FRACTIONS
    strip: Rect = (
        geom["appx"] + int(geom["appw"] * fx),
        geom["appy"] + int(geom["apph"] * fy),
        max(8, int(geom["appw"] * fw)),
        max(8, int(geom["apph"] * fh)),
    )
    return b.problems, {"strip": strip, "app": app, "size": size}


def record_content(out_dir: Path, cleared: bool) -> tuple[list[str], dict]:
    """One storyboard, recorded with the title card taken down — or left up.

    The A/B of issue #91, and the only difference between the two takes is the
    `interlude("")` on the line below. Everything else about them is identical,
    which is what makes the comparison worth anything: the covered take has the
    same beats, the same commands, the same exit codes and the same evidence as
    the take beside it, and differs only in whether any of it reached a frame.

    Terminal rather than web on purpose. That is the medium #91 happened in,
    and it is the harder case for the picture check: an occluding card is dark,
    carries a line of text, and scores as perfectly good *content* — only the
    fact that nothing ever changes gives it away.
    """
    from demo_recording import TerminalRecorder

    label = CONTENT_TAKES[0] if cleared else CONTENT_TAKES[1]
    b = Beats(label)

    def expect_prompt(rec, after: str) -> None:
        try:
            rec.wait_for_prompt(timeout_s=15)
        except RuntimeError as exc:
            b.fail_if(True, f"after {after}, the shell prompt never came back — {exc}")

    with TerminalRecorder(
        out_dir, speech=False, strict=True, deterministic=True
    ) as rec:
        start_ticker(b, rec.page)
        rec.interlude(CONTENT_CARD)
        if cleared:
            rec.interlude("")

        # Three commands whose output is different every time, each followed by
        # a hold. Under the card every one of them runs, exits zero, lands in
        # `evidence/` and changes nothing on screen — which is the finding.
        for n, (caption, command) in enumerate(CONTENT_COMMANDS, start=1):
            rec.caption(caption)
            rec.run(command)
            expect_prompt(rec, f"run({command!r})")
            rec.shot(f"{n:02d}-content")
            rec.hold()
        rec.caption("")

        box = rec.page.locator("#__term_host").bounding_box()
        if box is None:
            raise SmokeFailure(
                f"{label}: #__term_host has no box — the terminal never rendered"
            )
        app: Rect = (
            int(box["x"]),
            int(box["y"]),
            int(box["width"]),
            int(box["height"]),
        )
        size = (rec._size["width"], rec._size["height"])

    return b.problems, {"app": app, "size": size}


def record_content_toured(out_dir: Path) -> tuple[list[str], dict]:
    """A healthy demo that narrates a rendered screen without touching it.

    Written the way `SKILL.md` tells storyboard authors to write one — *"during
    unavoidable waits, tour what's on screen or swap the caption"* — and it is
    the shape that made the first version of this check wrong. One command puts
    something on screen; after that every beat is a caption or a hold, so the
    measured region legitimately holds one picture for longer than the
    recorder's own limit, with nothing occluded and nothing broken.

    The recorder must say nothing about it. If it warns, its message blames an
    overlay that never existed, in `timeline.json`, which is the failure issue
    #97 was filed to remove.
    """
    from demo_recording import TerminalRecorder

    b = Beats(CONTENT_TOURED)
    caption, command = CONTENT_TOUR_COMMAND

    with TerminalRecorder(
        out_dir, speech=False, strict=True, deterministic=True
    ) as rec:
        start_ticker(b, rec.page)
        rec.caption(caption)
        rec.run(command)
        try:
            rec.wait_for_prompt(timeout_s=15)
        except RuntimeError as exc:
            b.fail_if(True, f"the shell prompt never came back — {exc}")
        rec.shot("01-toured")
        # Everything from here is narration over a screen nobody touches again.
        # `hold()` after each caption so the stretch is made of holds as well as
        # captions — both passive, and a stretch of only one verb would be a
        # thinner claim than the mix a real storyboard produces.
        for line in CONTENT_TOUR_CAPTIONS:
            rec.caption(line)
            rec.hold(CONTENT_TOUR_HOLD_S)
        rec.caption("")

        box = rec.page.locator("#__term_host").bounding_box()
        if box is None:
            raise SmokeFailure(
                f"{CONTENT_TOURED}: #__term_host has no box — nothing rendered"
            )
        app: Rect = (
            int(box["x"]),
            int(box["y"]),
            int(box["width"]),
            int(box["height"]),
        )
        size = (rec._size["width"], rec._size["height"])

    return b.problems, {"app": app, "size": size}


def record_overlay(
    out_dir: Path, base_url: str, cleared: bool
) -> tuple[list[str], dict]:
    """A `light` interlude, taken down with the documented call — or left up.

    The A/B of issues #162 and #163, and the only difference between the two
    takes is the `interlude("")` on the line below.

    **Web rather than terminal, and `light` rather than `card`.** The pair
    above already records a card over a terminal; what neither of them reaches
    is the style whose clear was broken, over an app with enough painted colour
    for a translucent scrim to be measurable at all. A card is opaque, so "the
    card is gone" and "the card is a different picture" are the same reading; a
    scrim is not, which is the case the picture check scores backwards.

    Quiet stretches either side of the scrim rather than beats that act on the
    app: the frames compared below are of *the same screen*, once with the
    scrim over it and once without, so nothing but the scrim can explain a
    difference between them.
    """
    from demo_recording import Recorder

    label = OVERLAY_TAKES[0] if cleared else OVERLAY_TAKES[1]
    b = Beats(label)

    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        # Without it the page goes idle behind the scrim, the screencast stops
        # emitting frames, and every timestamp below drifts (issue #18).
        start_ticker(b, rec.app)
        rec.pause(OVERLAY_QUIET_S)
        rec.interlude(OVERLAY_LABEL, hold=OVERLAY_HOLD_S, style="light")
        if cleared:
            # The call SKILL.md documents, with the default style. Before the
            # fix this cleared the *card* overlay and left the scrim standing.
            rec.interlude("")
        rec.pause(OVERLAY_QUIET_S)

        g = rec._geom
        app: Rect = (g["appx"], g["appy"], g["appw"], g["apph"])

    return b.problems, {"app": app}


def record_entropy(out_dir: Path, base_url: str, deterministic: bool) -> EntropyTake:
    """The shortest storyboard that renders the things determinism controls.

    `?entropy=1` puts four clocks and a spinning shape on the page. Two stills
    a second apart, and nothing else — the point of this take is not what it
    shows but that a second run of it shows exactly the same thing.

    `deterministic=False` is passed by *omitting* the argument, so this take
    grades the recorder's default rather than an explicit opt-out. They are the
    same code path now, and the default is the one every user gets.
    """
    from demo_recording import Recorder

    label = "determinism" if deterministic else "default"
    b = Beats(label)
    kwargs = {"deterministic": True} if deterministic else {}
    # strict=True on all three: `?entropy=1` starts a Worker, and the recorder
    # wraps `Worker` to re-inject the frozen clock into it. A shim that broke
    # worker loading would show up here as a failed request rather than as a
    # page that quietly renders one clock fewer.
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, **kwargs
    ) as rec:
        rec.goto("/?entropy=1")
        # No pointer park, deliberately, where the composite path needed one
        # (#185): the wrapper dot is driven by pointer verbs alone (#361), no
        # event can move it, and this storyboard runs none — so every take of
        # this storyboard agrees the dot is at the chrome's off-screen park,
        # by construction. check_undrawn_pointer below reads that back out of
        # the DOM rather than taking this paragraph's word for it.
        # The worker's answer lands asynchronously and is part of what the
        # stills have to reproduce, so wait for it rather than racing it. A
        # short bound rather than the 60 s default: a Worker wrapper that
        # stops workers loading at all shows up right here, and it should say
        # so in seconds rather than after a minute of nothing.
        rec.wait_for("#entropy-worker.ready", timeout_s=15)
        rec.pause(ENTROPY_SETTLE_S)
        rec.shot(ENTROPY_SHOTS[0])
        check_determinism(b, rec.app, f"in the {label} take", on=deterministic)

        # The worker line, read rather than left to the pixel comparisons.
        # They cannot see this: the fixture falls back to "worker unavailable"
        # if the Worker constructor throws, and *that* reproduces byte for byte
        # across takes just as happily as a frozen timestamp does. A wrapper
        # that broke every worker on the page would pass this whole phase on
        # the strength of failing consistently.
        worker = rec.app.locator("#entropy-worker").inner_text()
        b.fail_if(
            not re.fullmatch(r"worker \d+", worker),
            f"the entropy page's worker reported {worker!r}, not a timestamp — "
            f"the recorder's Worker wrapper stopped workers running at all, "
            f"which every pixel comparison in this phase would call a success",
        )
        if deterministic:
            b.fail_if(
                worker != f"worker {FROZEN_EPOCH_MS}",
                f"the entropy page's worker reported {worker!r}, expected "
                f"'worker {FROZEN_EPOCH_MS}' — a Worker has its own global and "
                f"page init scripts never run in it, so the freeze has to be "
                f"re-injected there and was not",
            )
        # No "and it is not empty" guard here on purpose: `wait_for` above
        # already refuses a clock that is not visible, and three empty clocks
        # would trip the "the escape-hatch take rendered the same clock as the
        # frozen ones" comparison below. An assertion that cannot be made to
        # fail is a comment.
        clock = rec.app.locator("#entropy-readings").inner_text()
        # A second still after long enough for the spinner to be somewhere
        # else entirely (it turns once every 1.7 s).
        rec.pause(ENTROPY_GAP_S)
        rec.shot(ENTROPY_SHOTS[1])
        # After both stills, so it grades the frames that were actually taken.
        check_undrawn_pointer(b, rec.page, f"in the {label} take")

        box = rec.app.locator("#entropy-panel").bounding_box()
        spin = rec.app.locator("#entropy-spinner").bounding_box()
        if box is None or spin is None:
            raise SmokeFailure(
                "#entropy-panel has no box — ?entropy=1 rendered nothing"
            )
        still_rect: Rect = (
            int(box["x"]),
            int(box["y"]),
            int(box["width"]),
            int(box["height"]),
        )
        # The spinner on its own. Over the whole panel a 54 px shape turning
        # moves the mean luma by 0.76 — a number no honest floor can be set
        # against. Measured where the motion actually is, the same turn moves
        # it by tens. Cropping to the thing being asserted about is the
        # difference between an assertion and a decoration.
        spin_rect: Rect = (
            int(spin["x"]),
            int(spin["y"]),
            int(spin["width"]),
            int(spin["height"]),
        )
        # The page is the video at true pixel size (#358/#361), and
        # `bounding_box()` answers in wrapper-page coordinates even for
        # iframe elements — so the panel sits at the same rect in the video
        # as in the still, with nothing left to map.
        video_rect: Rect = still_rect
    return EntropyTake(b.problems, out_dir, clock, still_rect, video_rect, spin_rect)


def record_coverage(out_dir: Path, base_url: str) -> tuple[list[str], dict]:
    """A take recorded against COVERAGE_CRITERIA, with one left undemonstrated.

    Returns the take's chrome geometry as well as the problems: the card
    assertions read pixels of the card and of the window body around it, and
    where either sits in the frame is something only the recorder knows
    (issue #17).
    """
    from demo_recording import Recorder

    b = Beats("coverage")
    with Recorder(
        out_dir,
        base_url=base_url,
        speech=False,
        strict=True,
        deterministic=True,
        criteria=COVERAGE_CRITERIA,
    ) as rec:
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        # The ticket's own sentence, on screen, before the beats that show it
        # (issue #280). Taken down explicitly on the next line: a card left up
        # occludes everything after it and almost nothing notices, which is
        # what `--overlay-only` is about.
        rec.criterion(COVERAGE_CARD)
        rec.interlude("")
        rec.caption("The current figures.", ac="AC-1")
        rec.shot("01-figures", ac="AC-1")
        # Two ids on one beat: a single screen can be the evidence for more
        # than one criterion, and `claimed` has to list it under both.
        rec.caption("Filtered, and still showing figures.", ac=["AC-2", "AC-1"])
        rec.shot("02-filtered", ac="AC-2")
        # Untagged on purpose: most beats claim nothing, and `untagged_beats`
        # has to count them without any of them reaching `claimed`.
        rec.caption("")

        geom = dict(rec._geom)
    return b.problems, geom


def _record_content_take(out_root: Path, name: str, record) -> tuple[list[str], dict]:
    """Record one content take, capturing what it printed.

    The streams are captured rather than merely inspected afterwards, because
    half the acceptance criterion is that the verdict arrives *unasked*: an
    author who never opens timeline.json still has to be told, and — for the
    healthy takes — must not be told something untrue. `print` resolves
    `sys.stderr`/`sys.stdout` at call time, so redirecting here catches the
    recorder's own output and nothing else's.

    **Both streams, and the split is the recorder's, not this file's.**
    `print_content_summary` puts a *warning* on stderr and the healthy
    "demo.mp4 shows a picture" line on stdout. Issue #163's acceptance is that
    an occluded take reports the overlay *rather than* printing that line, so
    grading it needs the stream that line goes to; capturing only stderr made
    "it no longer says it shows a picture" an assertion that could never fail.

    Shared with the overlay pair (#162/#163), which grades the same "it has to
    arrive unasked" half against the other overlay style.
    """
    out_dir = fresh_take_dir(out_root, name)
    err, out = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            found, info = record(out_dir)
    except Exception as exc:  # noqa: BLE001 - a raising take is a failure
        sys.stdout.write(out.getvalue())
        sys.stderr.write(err.getvalue())
        return [f"{name}: the recorder raised {type(exc).__name__}: {exc}"], {}
    # Put them back on the real streams: a run that fails later should not also
    # have swallowed the recorder's own account of itself.
    sys.stdout.write(out.getvalue())
    sys.stderr.write(err.getvalue())
    if not (out_dir / "demo.mp4").is_file():
        found = [*found, f"{name}: demo.mp4 was never written"]
    return found, {
        "out_dir": out_dir,
        "info": info,
        "stderr": err.getvalue(),
        "stdout": out.getvalue(),
    }


@contextmanager
def refusing_fixture_server() -> Iterator[str]:
    """Serve tests/fixture with X-Frame-Options: DENY on every response.

    `python -m http.server` cannot add a header, so this is the same server
    run through `-c` with `end_headers` overridden — the smallest honest way
    to stand up an app that refuses framing.
    """
    handler_code = (
        "import functools, http.server, sys\n"
        "class Handler(http.server.SimpleHTTPRequestHandler):\n"
        "    def end_headers(self):\n"
        "        self.send_header('X-Frame-Options', 'DENY')\n"
        "        super().end_headers()\n"
        "    def log_message(self, *args):\n"
        "        pass\n"
        "http.server.ThreadingHTTPServer(\n"
        "    ('127.0.0.1', int(sys.argv[1])),\n"
        "    functools.partial(Handler, directory=sys.argv[2]),\n"
        ").serve_forever()\n"
    )
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-c", handler_code, str(port), str(FIXTURE_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + SERVER_START_TIMEOUT_S
        while True:
            if proc.poll() is not None:
                raise SmokeFailure(
                    f"refusing fixture server exited immediately "
                    f"(code {proc.returncode})"
                )
            try:
                with urllib.request.urlopen(base_url, timeout=1) as resp:
                    if resp.headers.get("X-Frame-Options") != "DENY":
                        raise SmokeFailure(
                            "the refusing fixture server is not sending "
                            "X-Frame-Options: DENY — the refusal take would "
                            "grade a server that refuses nothing"
                        )
                    break
            except (urllib.error.URLError, OSError):
                pass
            if time.time() > deadline:
                raise SmokeFailure(
                    f"refusing fixture server did not answer on {base_url} "
                    f"within {SERVER_START_TIMEOUT_S:.0f}s"
                )
            time.sleep(0.1)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def record_wrapper(out_dir: Path, base_url: str) -> dict:
    """One wrapper take driving every locator verb through the app frame.

    The storyboard asserts each verb's observable post-condition against
    `rec.app` as it goes — a click that lands in the wrapper chrome instead
    of the iframe advances nothing, and this is where that surfaces.
    """
    from demo_recording import Recorder

    with Recorder(
        out_dir,
        base_url=base_url,
        speech=False,
        strict=True,
        deterministic=True,
        criteria={"AC-1": WRAPPER_CLAUSE},
    ) as rec:
        rec.goto("/")
        rec.wait_for("#kpi-rev")
        # Distance between the opening hold's reveal (the end of the goto,
        # #360) and the first caption: check_wrapper_band reads an app-rect
        # control frame 0.3s before the band lights, and that frame must
        # show the settled app, not the tail of the reveal.
        rec.pause(1.0)
        rec.caption(WRAPPER_CAPTION)
        rec.spotlight("#kpi-rev")
        rec.hold()
        rec.spotlight()
        rec.click("#refresh")
        status = rec.app.locator("#status").inner_text()
        if status != "snapshot 2 of 3":
            raise _StoryboardFailed(
                f"click('#refresh') through the app frame did not advance "
                f"the fixture: #status reads {status!r}"
            )
        rec.type_into("#search", "harbor")
        rows = rec.app.locator("#rows tr").count()
        if rows != 1:
            raise _StoryboardFailed(
                f"type_into('#search') through the app frame did not filter: "
                f"{rows} rows visible, expected 1"
            )
        rec.scroll_to("#rows")
        rec.caption("")
        # A caption the band cannot hold, then the clear again: the take
        # must record caption_clipped for this line and only this line
        # (check_wrapper_clipped), and the band must still end dark for the
        # band sweep's last-frame claim.
        rec.caption(WRAPPER_LONG_CAPTION)
        rec.caption("")
        # The criterion card (#360): over the app rect only, the window
        # frame and the caption band still on screen while it is up, the
        # card and the window one declared colour on one encoder
        # (check_wrapper_card). The pause after the clear is the check's
        # no-card control window.
        rec.criterion("AC-1")
        rec.interlude("")
        rec.pause(1.5)
        # The caption survives a real mid-take goto (#360): the wrapper
        # document holds the line and outlives the app document
        # (check_wrapper_caption_survives).
        rec.caption(WRAPPER_SURVIVES)
        rec.goto("/second.html")
        # 2.5 s, not 1.0: check_wrapper_caption_survives samples the band up
        # to 0.8 s after the second document's pixel-located arrival, and a
        # backward wall-clock step between the load and the clear deletes
        # its own width of video from that gap — measured, a -1.05 s step at
        # 28.1 s of a --cheap run pulled the caption clear to ~0.4 s after
        # arrival and the +0.5/+0.8 samples read a dark band on a healthy
        # take. The margin outlasts one step of this box's ~1 s cadence.
        rec.pause(2.5)
        rec.caption("")
        rec.pause(0.6)
        geom = dict(rec._geom)
        size = (rec._size["width"], rec._size["height"])
    return {"geom": geom, "size": size}


def seed_tts_cache(out_dir: Path) -> dict[str, Path]:
    """Put a clip of known duration where the recorder will look for one.

    The key is computed here rather than imported — see `NARRATION_VOICE_ID`
    for why that separation is the point and not an oversight.
    """
    tts = out_dir / ".tts"
    tts.mkdir(parents=True, exist_ok=True)
    seeded: dict[str, Path] = {}
    for text, seconds in NARRATION_LINES:
        joined = (
            f"{NARRATION_VOICE_ID}|{NARRATION_MODEL_ID}|{text}"
            f"|stability={NARRATION_STABILITY}"
        )
        key = hashlib.sha256(joined.encode()).hexdigest()[:NARRATION_KEY_CHARS]
        clip = tts / f"{key}.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={seconds}",
                "-b:a",
                "128k",
                str(clip),
            ],
            check=True,
        )
        seeded[text] = clip
    return seeded


def record_narration(
    out_dir: Path, base_url: str, clock: HostClock
) -> tuple[list[str], dict]:
    """A take that really narrates, from a cache seeded before it starts."""
    from demo_recording import Recorder, narration

    b = Beats("narration")
    seeded = seed_tts_cache(out_dir)
    before = sorted(p.name for p in (out_dir / ".tts").iterdir())

    # Point a cache miss at a closed local port. Every line here is seeded, so
    # nothing should be requested — this is what makes that "cannot" rather
    # than "should": when a break makes the recorder compute a different key
    # than `seed_tts_cache` did, the miss dies against a dead socket in
    # milliseconds. Before this, that break put NARRATION_KEY on the wire to
    # api.elevenlabs.io and read the 401 back, which is a network dependency
    # and a fabricated credential sent to a third party, on a path a test is
    # *expected* to take while someone is breaking things deliberately.
    real_base = narration.TTS_API_BASE
    narration.TTS_API_BASE = f"http://127.0.0.1:{free_port()}/v1/text-to-speech"

    # The recorder reads this at construction and refuses `speech=True`
    # without it. It is never sent anywhere: every line is a cache hit, and
    # `tts_clip` returns before it builds a request.
    os.environ["ELEVENLABS_API_KEY"] = NARRATION_KEY
    try:
        with Recorder(out_dir, base_url=base_url, speech=True, strict=True) as rec:
            # This harness's own wall-clock reading, put on the take's clock.
            # The mix is corrected by the recorder's `capture_clock` (issue
            # #226), so grading the audio against that record would grade the
            # recorder against itself; `clock.before()` is measured in this
            # process, by code that shares nothing with the recorder's.
            clock.rebase(rec._t0)  # see HostClock
            b.expect("constructing with speech=True", rec._speech, True)
            rec.goto("/")
            rec.wait_for("#kpi-rev")
            rec.interlude(NARRATION_LONG_LINE, hold=NARRATION_HOLD_S)
            # Take the card down before the captions this arm measures are on
            # screen (issue #168). It is opaque at the top of the z-order, so
            # without this every frame from here to the end of the take is the
            # card and not the app — including both captions — and the arm
            # still passed, because pacing is read out of timeline.json and
            # the mix out of the audio track. The take now demonstrates what
            # SKILL.md tells an author to do rather than the thing #162/#163
            # exist to report.
            rec.interlude("")
            rec.caption(NARRATION_SHORT_LINE)
            rec.pause(NARRATION_HOLD_S)
            rec.caption("")
            rec.pause(0.4)
            lines = list(rec._lines)
    finally:
        os.environ.pop("ELEVENLABS_API_KEY", None)
        narration.TTS_API_BASE = real_base

    after = sorted(p.name for p in (out_dir / ".tts").iterdir())
    b.fail_if(
        after != before,
        f"the take wrote to .tts/: {sorted(set(after) - set(before))}. Every "
        f"line was seeded, so a new file means the recorder computed a "
        f"different key than this file did and went to the network for it",
    )
    b.expect("recording two narrated lines", len(lines), len(NARRATION_LINES))
    return b.problems, {"lines": lines, "seeded": seeded}
