"""Web take for smoke tests."""

from __future__ import annotations

from pathlib import Path

from ..constants import (
    WEB_BEATS,
    WEB_CAPTIONS,
    WEB_SHOTS,
    WEB_DURATION_S,
    PROBE_CAPTION,
    PROBE_QUIET_S,
    ALIGN_POST_S,
    ALIGN_FPS,
    MAX_BASELINE_NOISE_FRACTION,
    CAPTION_FADE_FRAMES,
    MIN_BASELINE_FRAMES,
    ALIGN_PRE_S,
    ALIGN_RESCUE_S,
    ALIGN_ARRIVAL_FRACTION,
    MIN_ALIGN_BAND_DELTA,
    TICKER_JS,
)
from ..utils import (
    Beats,
    fresh_take_dir,
    fixture_server,
    check_caption,
    start_ticker,
    check_determinism,
    check_undrawn_pointer,
    HostClock,
    watch_wall_clock,
)
from ..checks import (
    check_take,
    check_capture_clock,
    check_timeline,
    check_beat_frames,
    check_evidence,
    check_healthy,
)


def run_web(out_root: Path) -> list[str]:
    """Record the web take."""
    failures = []
    out_dir = fresh_take_dir(out_root, "web")
    
    with fixture_server() as base_url:
        with watch_wall_clock() as clock:
            try:
                problems, info = record_web(out_dir, base_url, clock)
            except Exception as exc:
                return [f"web: Recorder raised {type(exc).__name__}: {exc}"]
    
    failures += problems
    failures += check_take("web", out_dir, WEB_SHOTS, WEB_DURATION_S, 0)
    failures += check_capture_clock("web", out_dir, clock)
    failures += check_timeline("web", out_dir, 0, WEB_BEATS, WEB_CAPTIONS, (1280, 720), clock)
    failures += check_beat_frames("web", out_dir, 0, WEB_BEATS, WEB_CAPTIONS, (1280, 720), clock)
    failures += check_evidence("web", out_dir, [])
    failures += check_healthy("web", out_dir)
    
    return failures


def record_web(out_dir: Path, base_url: str, clock: HostClock | None = None):
    """Record a web demo."""
    from demo_recording import Recorder
    
    b = Beats("web")
    
    with Recorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        if clock is not None:
            clock.rebase(rec._t0)
        
        rec.goto("/")
        start_ticker(b, rec.page)
        check_determinism(b, rec.page, "after goto", on=True)
        check_undrawn_pointer(b, rec.page, "after goto")
        
        rec.wait_for("#kpi-rev")
        rec.pause(1.5)
        
        check_caption(b, rec.page, "A small dashboard.")
        rec.shot("01-dashboard")
        
        rec.spotlight("#kpi-rev")
        rec.hold(1.5)
        rec.spotlight(None)
        
        check_caption(b, rec.page, "Filter by city.")
        rec.type_into("#search", "harbor")
        rec.pause(1.5)
        
        check_caption(b, rec.page, "Refresh reloads it.")
        rec.move_to("#refresh")
        rec.click("#refresh")
        rec.pause(1.5)
        
        check_caption(b, rec.page, "Keys, not just clicks.")
        rec.clear("#search")
        rec.shot("04-cleared")
        
        rec.press("Enter")
        rec.press("Tab")
        rec.type_into("#search", "pine")
        rec.pause(1.5)
        rec.press("Escape")
        
        check_caption(b, rec.page, "")
        rec.shot("90-caption-off")
        rec.pause(PROBE_QUIET_S)
        check_caption(b, rec.page, PROBE_CAPTION)
        rec.shot("91-caption-on")
        check_caption(b, rec.page, "")
    
    return b.problems, {"lines": []}