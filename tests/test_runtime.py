"""Collector, state file, history window, rotation and the display loop."""

import json
import os
import stat
import subprocess
import sys
import time

import pytest
from PIL import Image

from aoostar_lcd import Card
from aoostar_lcd.app import file_source, preview, run_display
from aoostar_lcd.collector import Collector
from aoostar_lcd.config import load_config
from aoostar_lcd.display import NullSink, PngSink
from aoostar_lcd.history import BucketHistory
from aoostar_lcd.renderer import Renderer, Rotation
from aoostar_lcd.state import read_state, write_atomic

from .conftest import EXAMPLES, FIXED_TIME, ROOT

T0 = 1_800_000_000 // 300 * 300


# -- history ------------------------------------------------------------------------


def test_history_average_is_amount_over_measured_seconds():
    hist = BucketHistory(300, 36)
    for i in range(1, 13):
        hist.add(T0 + 5 * i, "eth0", 5_000_000, 5.0, 1_000_000 + i)
    avg, peak = hist.window(T0 + 60, "eth0")
    assert len(avg) == 36 and avg[:-1] == [None] * 35
    assert avg[-1] == 1_000_000.0 and peak[-1] == 1_000_012.0


def test_history_drops_old_buckets_and_rejects_garbage():
    hist = BucketHistory(300, 36)
    hist.add(T0, "a", 1, 1)
    hist.add(T0, "a", -5, 1)  # negative amounts are ignored
    hist.add(T0, "a", float("nan"), 1)
    assert hist.buckets[T0 // 300]["a"][:2] == [1.0, 1.0]
    assert hist.window(T0 + 36 * 300 + 10, "a")[0] == [None] * 36
    assert hist.buckets == {}


def test_history_load_skips_corrupt_and_foreign_data():
    idx = T0 // 300
    good = {
        "step": 300,
        "slots": 36,
        "buckets": {
            str(idx): {"a": [10, 2, 7]},
            str(idx + 9): {"a": [1, 1, 1]},  # future
            str(idx - 99): {"a": [1, 1, 1]},  # expired
            "x": {"a": [1, 1, 1]},
            str(idx - 1): {"a": [-1, 1, 1], "b": "x"},
        },
    }
    hist = BucketHistory(300, 36)
    assert hist.load_dict(good, T0 + 10) == 1
    assert hist.window(T0 + 10, "a")[0][-1] == 5.0
    for bad in ("nope", [], {"step": 60, "buckets": {}}, {"step": 300, "buckets": "x"}):
        assert BucketHistory(300, 36).load_dict(bad, T0) == 0


# -- state file ---------------------------------------------------------------------


def test_state_file_is_atomic_and_world_readable(tmp_path):
    path = tmp_path / "sub" / "state.json"
    write_atomic(path, {"ts": 1})
    write_atomic(path, {"ts": 2})
    assert json.loads(path.read_text()) == {"ts": 2}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_read_state_reasons(tmp_path):
    path = tmp_path / "state.json"
    assert read_state(path, 100, 30) == (None, "no state file")
    path.write_text("{not json")
    assert read_state(path, 100, 30) == (None, "invalid state file")
    path.write_text(json.dumps({"ts": 10, "cards": {}}))
    assert read_state(path, 100, 30) == (None, "state is 90 s old")
    path.write_text(json.dumps({"ts": 90, "version": 99}))
    assert read_state(path, 100, 30)[1] == "unsupported state version 99"
    path.write_text(json.dumps({"ts": 90, "cards": "x"}))
    assert read_state(path, 100, 30) == ({"ts": 90, "cards": {}}, "")


# -- collector ----------------------------------------------------------------------


class Ticker(Card):
    type_name = "ticker"
    refresh = 30.0

    def configure(self, options):
        self.calls = 0

    def collect(self):
        self.calls += 1
        if self.calls == 3:
            raise RuntimeError("flaky")
        if self.calls == 4:
            return {"bad": object()}
        return {"calls": self.calls}

    def render(self, canvas, theme, data):
        pass


def test_collector_respects_refresh_and_keeps_last_good_data():
    now = [1000.0]
    card = Ticker("t")
    collector = Collector([card], clock=lambda: now[0])
    assert collector.tick()["cards"] == {"t": {"calls": 1}}
    now[0] += 10
    assert collector.tick()["cards"] == {"t": {"calls": 1}}  # refresh not due
    now[0] += 30
    assert collector.tick()["cards"] == {"t": {"calls": 2}}
    now[0] += 30
    snap = collector.tick()  # raises -> keep previous data and report the error
    assert snap["cards"] == {"t": {"calls": 2}} and snap["errors"] == {"t": "RuntimeError: flaky"}
    now[0] += 30
    snap = collector.tick()  # not JSON serialisable
    assert "TypeError" in snap["errors"]["t"]
    now[0] += 30
    snap = collector.tick()
    assert snap["cards"] == {"t": {"calls": 5}} and snap["errors"] == {}
    json.dumps(snap)


def test_collector_persists_history(tmp_path, make_config):
    config = make_config(
        {
            "collector": {"history_file": "hist.json"},
            "cards": [{"type": "cpu", "history_minutes": 20, "bucket_seconds": 60}],
        }
    )
    first = Collector(config.cards, config.collector.history_file)
    first.cards[0].history.add(time.time(), "cpu", 100.0, 10.0, 30.0)
    first.save_history()
    path = tmp_path / "hist.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = make_config(
        {
            "collector": {"history_file": "hist.json"},
            "cards": [{"type": "cpu", "history_minutes": 20, "bucket_seconds": 60}],
        }
    )
    Collector(again.cards, again.collector.history_file)
    assert again.cards[0].history.window(time.time(), "cpu")[0][-1] == 10.0
    path.write_text("{garbage")
    Collector(again.cards, str(path))  # corrupt file: logged, not fatal


def test_collector_runs_without_pillow():
    code = (
        "import sys; sys.modules['PIL'] = None\n"
        "from aoostar_lcd.config import default_config\n"
        "from aoostar_lcd.collector import Collector\n"
        "import json; snap = Collector(default_config().cards).tick()\n"
        "json.dumps(snap); print(sorted(snap['cards']))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert "cpu" in result.stdout and "memory" in result.stdout


# -- rotation and rendering ------------------------------------------------------------


class Pages(Card):
    type_name = "pages"

    def visit_pages(self):
        return 3

    def render(self, canvas, theme, data):
        pass


def test_rotation_walks_cards_and_pages():
    a, b = Pages("a"), Ticker("b")
    rotation = Rotation([a, b])
    rotation.start()
    seen = []
    for _ in range(9):
        seen.append((rotation.card.id, rotation.page))
        rotation.advance()
    assert seen == [
        ("a", 0),
        ("a", 1),
        ("a", 2),
        ("b", 0),
        ("a", 0),
        ("a", 1),
        ("a", 2),
        ("b", 0),
        ("a", 0),
    ]


def test_no_data_frame_and_render_failures(make_config, caplog):
    class Broken(Card):
        def render(self, canvas, theme, data):
            raise ZeroDivisionError

    config = make_config({"cards": [{"type": "cpu"}]})
    config.cards.append(Broken("broken"))
    renderer = Renderer(config)
    no_data = renderer.frame(0, None, "state is 95 s old")
    assert no_data.size == (960, 376)
    assert no_data.getpixel((5, 5)) == config.theme.color("crit")
    frame = renderer.frame(1, {"ts": 0, "cards": {}})
    assert frame.size == (960, 376)
    assert "render failed" in caplog.text


def test_every_gallery_card_png_is_960x376(tmp_path):
    config = load_config(EXAMPLES / "gallery.yaml")
    written = preview(config, out_dir=str(tmp_path), at=FIXED_TIME, no_data=True)
    assert len(written) == len(config.enabled_cards) + 1
    for path in written:
        with Image.open(path) as image:
            assert image.size == (960, 376), path.name


def test_display_loop_from_state_file(tmp_path, make_config):
    config = make_config(
        {
            "display": {"backend": "png", "frame_interval": 1},
            "collector": {"state_file": "state.json"},
            "cards": [{"type": "memory", "duration": 1}, {"type": "clock"}],
        }
    )
    write_atomic(
        tmp_path / "state.json",
        {"version": 1, "ts": time.time(), "cards": {"memory": config.cards[0].sample()}},
    )
    sink = PngSink(config.display.png_dir)
    run_display(config, sink, source=file_source(config.collector.state_file, 30), max_frames=2)
    with Image.open(tmp_path / "frames" / "latest.png") as image:
        assert image.size == (960, 376)


def test_single_process_loop_collects_and_renders(make_config, tmp_path):
    config = make_config({"cards": [{"type": "cpu"}, {"type": "memory"}]})
    shown = []

    class Recorder(NullSink):
        def show(self, image):
            shown.append(image.size)
            return True

    state_out = tmp_path / "out.json"
    run_display(
        config,
        Recorder(),
        collector=Collector(config.cards),
        max_frames=1,
        state_out=str(state_out),
    )
    assert shown == [(960, 376)]


def test_run_display_needs_exactly_one_source(make_config):
    config = make_config({"cards": [{"type": "cpu"}]})
    with pytest.raises(ValueError):
        run_display(config, NullSink())
