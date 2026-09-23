"""The edit list: holds, retimed stretches and the reverse mapping."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/demo-video/helpers"))

from demo_recording.clock import Clock, SourceMap, ff_duration  # noqa: E402
from demo_recording.overlays import geometry  # noqa: E402


def test_short_waits_play_at_normal_speed():
    assert ff_duration(1.0) == 1.0


def test_long_waits_are_squeezed_but_capped():
    assert ff_duration(5) == 1.5
    assert ff_duration(60) == 3.0
    assert ff_duration(600) == 3.0


def test_insert_adds_video_time_without_wall_clock():
    clock = Clock()
    before = clock.now()
    clock.insert(2.0)
    assert clock.now() - before >= 2.0
    assert clock.now() - before < 2.1


def test_source_map_freezes_on_the_inserted_frame():
    pieces = [("real", 10.0, 11.0, 1.0), ("insert", 11.0, 2.0), ("real", 11.0, 21.0, 2.0)]
    source = SourceMap(pieces)
    assert source.total == 5.0
    assert source(0.5) == 10.5
    assert source(1.5) == 11.0
    assert source(2.9) == 11.0
    assert abs(source(4.0) - 16.0) < 1e-9  # halfway through the squeezed wait


def test_retime_squeezes_the_stretch_since_a_moment():
    clock = Clock()
    start = time.time()
    time.sleep(0.2)
    a, b = clock.retime(start, 0.05)
    assert abs((b - a) - 0.05) < 1e-9
    assert clock.pieces[-1][0] == "real"


def test_geometry_keeps_the_app_aspect_and_fits_the_frame():
    g = geometry((1920, 1080), (1440, 810))
    x, y, w, h = g["content"]
    assert abs(w / h - 1440 / 810) < 0.01
    assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080
    assert abs(g["scale"] - w / 1440) < 0.01
