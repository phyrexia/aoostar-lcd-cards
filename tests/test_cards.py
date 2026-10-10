"""Each built-in card with synthetic data, missing data, garbage and real collection."""

import json
import sys
import time

import pytest
from PIL import Image

from aoostar_lcd import sources
from aoostar_lcd.canvas import Canvas
from aoostar_lcd.cards.cpu import CpuCard
from aoostar_lcd.cards.custom import CustomCard
from aoostar_lcd.cards.memory import MemoryCard
from aoostar_lcd.cards.network import TOTAL, NetworkCard
from aoostar_lcd.cards.storage import StorageCard
from aoostar_lcd.cards.system import ClockCard, UptimeCard
from aoostar_lcd.cards.temperature import TemperatureCard
from aoostar_lcd.renderer import Renderer
from aoostar_lcd.validate import ConfigError

from .conftest import FIXED_TIME

BUILTIN_SPECS = [
    {"type": "cpu"},
    {"type": "cpu", "history_minutes": 0},
    {"type": "memory"},
    {"type": "memory", "units": "si", "zfs_arc": False, "swap": False},
    {"type": "network"},
    {"type": "network", "mode": "split", "interfaces": ["a", "b", "c"], "units": "bytes"},
    {"type": "temperature"},
    {
        "type": "temperature",
        "units": "fahrenheit",
        "sensors": [{"label": "CPU", "chip": "k10temp"}, {"label": "HDD", "smart": ["sda"]}],
    },
    {"type": "storage"},
    {
        "type": "storage",
        "units": "iec",
        "volumes": [{"zfs": "tank"}, {"mount": "/"}, {"mount": "/boot", "label": "Boot"}],
    },
    {"type": "clock", "timezone": "UTC"},
    {"type": "uptime"},
    {"type": "custom", "command": "echo hi"},
    {"type": "custom", "file": "status.json", "fields": [{"key": "a.b", "unit": "%"}]},
]


def render_one(make_config, spec, data="sample", lang="en"):
    config = make_config({"language": lang, "cards": [spec]})
    card = config.cards[0]
    if hasattr(card, "now"):
        card.now = FIXED_TIME
    payload = card.sample() if data == "sample" else data
    # Call render() directly first: the Renderer would hide an exception behind an
    # error frame, and these tests must fail on any crash.
    canvas = Canvas(Image.new("RGB", (960, 376)), config.theme, lang)
    card.render(canvas, config.theme, payload)
    snapshot = {"ts": time.time(), "cards": {card.id: payload} if payload is not None else {}}
    return card, Renderer(config).frame(0, snapshot)


@pytest.mark.parametrize("spec", BUILTIN_SPECS, ids=lambda s: f"{s['type']}-{len(s)}")
@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_card_renders_960x376_with_sample_data(make_config, spec, lang):
    card, image = render_one(make_config, spec, lang=lang)
    assert image.size == (960, 376)
    assert image.mode == "RGB"
    # Something was drawn besides the background.
    assert len(image.getcolors(maxcolors=1 << 20)) > 2


@pytest.mark.parametrize("spec", BUILTIN_SPECS, ids=lambda s: f"{s['type']}-{len(s)}")
@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {
            "history": "x",
            "series": 3,
            "volumes": [1, None],
            "sensors": "hot",
            "rows": [{"value": None}],
            "percent": "lots",
            "load": ["a"],
            "names": [7],
        },
    ],
)
def test_cards_survive_missing_and_garbage_data(make_config, spec, data):
    _, image = render_one(make_config, spec, data=data)
    assert image.size == (960, 376)


def test_cpu_collects_percent_and_history(monkeypatch):
    card = CpuCard("cpu", {"history_minutes": 20, "bucket_seconds": 60})
    samples = iter([(100.0, 1000.0), (150.0, 1100.0), (150.0, 1200.0)])
    clock = iter([1_800_000_000.0, 1_800_000_005.0, 1_800_000_010.0])
    monkeypatch.setattr(sources, "cpu_busy_total", lambda: next(samples))
    monkeypatch.setattr(sources, "cpu_temperature", lambda chip, sensor: 55.0)
    monkeypatch.setattr(time, "time", lambda: next(clock))
    assert card.collect()["percent"] is None  # first sample has no base
    second = card.collect()
    assert second["percent"] == 50.0
    third = card.collect()
    assert third["percent"] == 0.0
    history = third["history"]
    assert history["slots"] == 20 and len(history["avg"]) == 20
    assert history["avg"][-1] == pytest.approx(25.0)  # time-weighted average of 50 and 0
    assert history["peak"][-1] == 50.0
    json.dumps(third)


def test_cpu_history_survives_restart(monkeypatch):
    card = CpuCard("cpu", {"history_minutes": 20, "bucket_seconds": 60})
    now = time.time()
    card.history.add(now, "cpu", 300.0, 10.0, 40.0)
    restored = CpuCard("cpu", {"history_minutes": 20, "bucket_seconds": 60})
    restored.restore(json.loads(json.dumps(card.state())))
    assert restored.history.window(now, "cpu") == card.history.window(now, "cpu")


def test_network_aggregates_interfaces_and_ignores_counter_resets(monkeypatch):
    card = NetworkCard(
        "net", {"interfaces": ["a", "b"], "history_minutes": 20, "bucket_seconds": 60}
    )
    counters = iter(
        [
            {"a": (0, 0), "b": (0, 0), "lo": (0, 0)},
            {"a": (5_000, 1_000), "b": (10_000, 0), "lo": (99, 99)},
            {"a": (100, 100), "b": (20_000, 500)},  # "a" was reset
        ]
    )
    clock = iter([1_800_000_000.0, 1_800_000_005.0, 1_800_000_010.0])
    monkeypatch.setattr(sources, "net_counters", lambda: next(counters))
    monkeypatch.setattr(time, "time", lambda: next(clock))
    card.collect()
    second = card.collect()
    assert second["names"] == ["a", "b"]
    assert second["current"] == {"a": {"rx": 1000.0, "tx": 200.0}, "b": {"rx": 2000.0, "tx": 0.0}}
    third = card.collect()
    assert "a" not in third["current"]
    total = third["series"][TOTAL]
    # bucket: 15 kB in 5 s, then (only b) 10 kB in 5 s -> 25 kB / 10 s
    assert total["rx"][-1] == pytest.approx(2500.0)
    assert total["rx_peak"][-1] == pytest.approx(3000.0)
    json.dumps(third)


def test_network_auto_skips_virtual_interfaces(monkeypatch, tmp_path):
    names = ["lo", "eth0", "veth1a2b", "docker0", "vmbr0", "enp3s0", "tap100i0", "wg0"]
    monkeypatch.setattr(sources, "SYS_NET", tmp_path / "none")
    card = NetworkCard("net", {"exclude": ["enp3s0"]})
    assert card._selected(names) == ["eth0"]


def test_network_scale_uses_1_2_5_in_bits():
    card = NetworkCard("net", {})
    assert card._scale([845e6 / 8]) == pytest.approx(1e9 / 8)
    assert card._scale([0.0]) == pytest.approx(10e6 / 8)  # min_scale 10 Mbit/s
    card_bytes = NetworkCard("net", {"units": "bytes", "min_scale": 1})
    assert card_bytes._scale([120e6]) == pytest.approx(200e6)


def test_memory_collect_has_consistent_numbers():
    data = MemoryCard("mem", {}).collect()
    assert data["total"] > 0 and 0 <= data["used"] <= data["total"]
    json.dumps(data)


def test_storage_reads_mounts_and_zfs(monkeypatch):
    outputs = {
        ("zpool", "list", "-H", "-o", "health", "tank"): "DEGRADED\n",
        ("zfs", "list", "-Hp", "-o", "used,avail", "tank"): "100\t300\n",
    }
    monkeypatch.setattr(sources, "run_command", lambda argv, timeout: outputs[tuple(argv)])
    card = StorageCard(
        "st",
        {
            "volumes": [
                {"zfs": "tank"},
                {"mount": "/", "label": "Root"},
                {"mount": "/definitely/not/here"},
            ]
        },
    )
    data = card.collect()
    tank, root, missing = data["volumes"]
    assert (tank["used"], tank["free"], tank["health"]) == (100, 300, "DEGRADED")
    assert root["total"] > 0 and root["label"] == "Root"
    assert missing["error"] == "not found"
    assert card.alerts(data) == ["POOL tank: DEGRADED"]


def test_storage_without_zfs_tools_reports_an_error(monkeypatch):
    def missing(argv, timeout):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(sources, "run_command", missing)
    data = StorageCard("st", {"volumes": [{"zfs": "tank"}]}).collect()
    assert data["volumes"][0]["error"] == "zfs tools not found"


def test_temperature_file_source(tmp_path):
    sensor = tmp_path / "temp"
    sensor.write_text("48500\n")
    card = TemperatureCard(
        "t", {"sensors": [{"label": "Board", "file": str(sensor)}]}, base_dir=tmp_path
    )
    assert card.collect()["sensors"][0] == {
        "label": "Board",
        "value": 48.5,
        "warn": 70.0,
        "crit": 85.0,
    }


def test_temperature_smart_keeps_last_value_when_disks_sleep(monkeypatch):
    values = iter([41.0, None])
    monkeypatch.setattr(sources, "smart_temperature", lambda dev: next(values))
    card = TemperatureCard("t", {"sensors": [{"smart": ["sda"]}], "smart_refresh": 10})
    assert card.collect()["sensors"][0]["value"] == 41.0
    card._smart_cache[0] = (time.monotonic() - 60, 41.0)  # refresh is due
    assert card.collect()["sensors"][0]["value"] == 41.0  # asleep -> keep 41


def test_clock_and_uptime_collect_real_host_data():
    for card in (ClockCard("c", {}), UptimeCard("u", {})):
        data = card.collect()
        assert data["boot_time"] < time.time()
        assert isinstance(data["hostname"], str)


def test_custom_command_json(tmp_path):
    script = (
        "import json; print(json.dumps({'title': 'T', 'value': 42, 'unit': 'jobs', "
        "'percent': 150, 'status': 'warn', 'lines': ['a\\x1bb', 'c'], 'evil': 1}))"
    )
    card = CustomCard("c", {"command": [sys.executable, "-c", script]})
    data = card.collect()
    assert data == {
        "title": "T",
        "value": "42",
        "unit": "jobs",
        "percent": 100.0,
        "status": "warn",
        "lines": ["a b", "c"],
    }


def test_custom_text_file_and_fields(tmp_path):
    (tmp_path / "out.txt").write_text("OK\nline 2\n\nline 3\nline 4\nline 5\n")
    text = CustomCard("c", {"file": "out.txt"}, base_dir=tmp_path).collect()
    assert text == {"value": "OK", "lines": ["line 2", "line 3", "line 4"]}
    (tmp_path / "ups.json").write_text('{"battery": {"charge": 87.4}, "load": [10, 95]}')
    card = CustomCard(
        "c",
        {
            "file": "ups.json",
            "fields": [
                {"label": "Battery", "key": "battery.charge", "unit": "%", "decimals": 0},
                {"label": "Load", "key": "load.1", "warn": 70, "crit": 90},
                {"label": "Missing", "key": "nope.x"},
            ],
        },
        base_dir=tmp_path,
    )
    rows = card.collect()["rows"]
    assert rows[0] == {"label": "Battery", "value": "87 %", "status": None}
    assert rows[1] == {"label": "Load", "value": "95.0", "status": "crit"}
    assert rows[2]["value"] == "-"


def test_custom_command_errors_are_raised():
    failing = CustomCard(
        "c",
        {"command": [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]},
    )
    with pytest.raises(RuntimeError, match="exited with 3: boom"):
        failing.collect()
    slow = CustomCard(
        "c", {"command": [sys.executable, "-c", "import time; time.sleep(5)"], "timeout": 1}
    )
    with pytest.raises(Exception, match="timed out"):
        slow.collect()
    strict = CustomCard("c", {"command": "echo not-json", "format": "json"})
    with pytest.raises(ValueError, match="not valid JSON"):
        strict.collect()


def test_custom_command_string_is_split_without_a_shell():
    card = CustomCard("c", {"command": "printf '%s' 'a b'"})
    assert card.options["command"] == ["printf", "%s", "a b"]
    with pytest.raises(ConfigError, match="command"):
        CustomCard("c", {"command": "echo 'unterminated"})


def test_alert_banner_is_drawn_on_every_card(make_config):
    config = make_config(
        {"cards": [{"type": "cpu"}, {"type": "storage", "volumes": [{"zfs": "tank"}]}]}
    )
    snapshot = {
        "ts": time.time(),
        "cards": {
            "cpu": config.cards[0].sample(),
            "storage": {"volumes": [{"label": "tank", "used": 1, "free": 1, "health": "FAULTED"}]},
        },
    }
    image = Renderer(config).frame(0, snapshot)
    assert image.getpixel((5, 5)) == config.theme.color("crit")
    clean = Renderer(config).frame(0, {"ts": time.time(), "cards": {}})
    assert clean.getpixel((5, 5)) == config.theme.color("background")


def test_png_sizes_with_custom_resolution(make_config):
    config = make_config(
        {"display": {"backend": "none", "width": 480, "height": 188}, "cards": [{"type": "memory"}]}
    )
    image = Renderer(config).frame(0, {"ts": 0, "cards": {"memory": config.cards[0].sample()}})
    assert image.size == (480, 188)
    assert isinstance(image, Image.Image)
