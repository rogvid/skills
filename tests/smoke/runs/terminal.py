"""Terminal take for smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

from ..constants import (
    TERMINAL_BEATS,
    TERMINAL_CAPTIONS,
    TERMINAL_SHOTS,
    TERMINAL_DURATION_S,
    PROBE_CAPTION,
    PROBE_QUIET_S,
)
from ..utils import (
    Beats,
    fresh_take_dir,
    fixture_server,
    check_caption,
    start_ticker,
    check_determinism,
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


def run_terminal(out_root: Path) -> list[str]:
    """Record the terminal take."""
    if os.name != "posix":
        print(
            "smoke: SKIPPING the terminal take — TerminalRecorder needs a PTY "
            f"and this is {os.name!r}, not a Unix platform.",
            file=__import__("sys").stderr,
        )
        return []
    
    failures = []
    out_dir = fresh_take_dir(out_root, "terminal")
    
    import os as _os
    previous = Path.cwd()
    _os.chdir(__import__("..constants", fromlist=["REPO_ROOT"]).REPO_ROOT)
    
    try:
        with fixture_server() as base_url:
            with watch_wall_clock() as clock:
                try:
                    problems, info = record_terminal(out_dir, base_url, clock)
                except Exception as exc:
                    return [f"terminal: TerminalRecorder raised {type(exc).__name__}: {exc}"]
    finally:
        _os.chdir(previous)
    
    failures += problems
    failures += check_take("terminal", out_dir, TERMINAL_SHOTS, TERMINAL_DURATION_S, 0)
    failures += check_capture_clock("terminal", out_dir, clock)
    failures += check_timeline("terminal", out_dir, 0, TERMINAL_BEATS, TERMINAL_CAPTIONS, (1280, 720), clock)
    failures += check_beat_frames("terminal", out_dir, 0, TERMINAL_BEATS, TERMINAL_CAPTIONS, (1280, 720), clock)
    failures += check_evidence("terminal", out_dir, [])
    failures += check_healthy("terminal", out_dir)
    
    return failures


def record_terminal(out_dir: Path, base_url: str, clock: HostClock | None = None):
    """Record a terminal demo."""
    from demo_recording import TerminalRecorder
    
    b = Beats("terminal")
    
    with TerminalRecorder(
        out_dir, base_url=base_url, speech=False, strict=True, deterministic=True
    ) as rec:
        if clock is not None:
            clock.rebase(rec._t0)
        
        # TerminalRecorder starts at about:blank with xterm.js
        rec.pause(1.0)
        start_ticker(b, rec.page)
        check_determinism(b, rec.page, "after startup", on=True)
        
        check_caption(b, rec.page, "A real shell, recorded.")
        rec.run("echo hello from demo-video")
        rec.wait_for_prompt()
        rec.wait_for_text(r"^hello from demo-video$")
        
        check_caption(b, rec.page, "Any command works.")
        rec.shot("01-echo")
        
        rec.run("ls -1")
        rec.wait_for_prompt()
        rec.wait_for_text(r"^skills$")
        rec.pause(1.0)
        
        check_caption(b, rec.page, "")
        rec.shot("90-caption-off")
        rec.pause(PROBE_QUIET_S)
        check_caption(b, rec.page, PROBE_CAPTION)
        rec.shot("91-caption-on")
        check_caption(b, rec.page, "")
    
    return b.problems, {"lines": []}