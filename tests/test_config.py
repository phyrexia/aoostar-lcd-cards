import pytest

from aoostar_lcd.cards.cpu import CpuCard
from aoostar_lcd.config import default_config, load_config, parse_config
from aoostar_lcd.validate import ConfigError

from .conftest import EXAMPLES, ROOT


def test_example_config_is_valid():
    config = load_config(ROOT / "config.example.yaml")
    types = [c.type_name for c in config.cards]
    assert types[:7] == ["cpu", "memory", "network", "temperature", "storage", "clock", "uptime"]
    assert "custom" in types and "image" in types
    assert config.display.device == "/dev/ttyACM0"
    assert [c.id for c in config.enabled_cards] == [
        "cpu",
        "memory",
        "network",
        "temperature",
        "storage",
        "clock",
    ]


def test_gallery_config_is_valid_and_loads_plugins():
    config = load_config(EXAMPLES / "gallery.yaml")
    ids = [c.id for c in config.cards]
    assert len(ids) == len(set(ids)) == 15
    assert {"plugin-top", "plugin-hello", "image-logo"} <= set(ids)


def test_defaults_order_and_durations(make_config):
    config = make_config(
        {
            "rotation": {"default_duration": 6},
            "cards": [{"type": "memory"}, {"type": "cpu", "duration": 3}, {"type": "memory"}],
        }
    )
    assert [c.id for c in config.cards] == ["memory", "cpu", "memory-2"]
    assert [c.duration for c in config.cards] == [6, 3, 6]
    assert isinstance(config.cards[1], CpuCard)


def test_enabled_false_keeps_the_card_out_of_the_rotation(make_config):
    config = make_config({"cards": [{"type": "cpu"}, {"type": "clock", "enabled": False}]})
    assert [c.id for c in config.enabled_cards] == ["cpu"]


@pytest.mark.parametrize(
    "data,message",
    [
        ({"cards": []}, "cards: must be a non-empty list"),
        ({"cards": [{"type": "cpu"}], "colour": 1}, "unknown option 'colour'"),
        ({"cards": [{"duration": 3}]}, "'type' is required"),
        ({"cards": [{"type": "netwrk"}]}, 'Did you mean "network"?'),
        ({"cards": [{"type": "network", "interface": ["eth0"]}]}, 'Did you mean "interfaces"?'),
        ({"cards": [{"type": "cpu", "duration": 0}]}, "cards[0] (cpu).duration: must be >= 1"),
        ({"cards": [{"type": "cpu", "warn": 95, "crit": 90}]}, "warn (95) must be <= crit (90)"),
        ({"cards": [{"type": "network", "units": "bauds"}]}, "must be one of bits, bytes"),
        ({"cards": [{"type": "cpu", "id": "a"}, {"type": "memory", "id": "a"}]}, "duplicate id"),
        ({"cards": [{"type": "cpu", "id": "Bad Id"}]}, "use lowercase letters"),
        ({"cards": [{"type": "cpu", "enabled": False}]}, "every card is disabled"),
        ({"cards": [{"type": "cpu"}], "theme": {"colors": {"rx": "blue"}}}, 'like "#3cc8ff"'),
        (
            {"cards": [{"type": "cpu"}], "theme": {"colors": {"bakground": "#000000"}}},
            'Did you mean "background"?',
        ),
        ({"cards": [{"type": "cpu"}], "display": {"usb": "0416-90a1"}}, "vid:pid"),
        ({"cards": [{"type": "cpu"}], "display": {"backend": "lcd"}}, "must be one of asterctl"),
        (
            {"cards": [{"type": "cpu"}], "collector": {"interval": 20, "max_age": 30}},
            "at least twice",
        ),
        ({"cards": [{"type": "cpu", "history_minutes": 7}]}, "whole number between 4 and 240"),
        (
            {"cards": [{"type": "storage", "volumes": [{"mount": "/", "zfs": "tank"}]}]},
            "exactly one of mount or zfs",
        ),
        ({"cards": [{"type": "storage", "volumes": [{"mount": "/"}] * 5}]}, "at most 4"),
        (
            {"cards": [{"type": "temperature", "sensors": [{"label": "x"}]}]},
            "exactly one of chip, smart or file",
        ),
        ({"cards": [{"type": "custom"}]}, "exactly one of command or file"),
        ({"cards": [{"type": "image"}]}, "path: required"),
        ({"cards": [{"type": "image", "path": "x.png", "mode": "stretch"}]}, "contain, cover"),
        ({"cards": [{"type": "clock", "timezone": "Mars/Base"}]}, "unknown time zone"),
        ({"cards": [{"type": "plugin"}]}, "'plugin' is required"),
        ({"cards": [{"type": "cpu", "plugin": "x.py:Y"}]}, "only valid with 'type: plugin'"),
        ({"language": "fr", "cards": [{"type": "cpu"}]}, "must be one of en, es"),
    ],
)
def test_invalid_configs_have_clear_messages(tmp_path, data, message):
    with pytest.raises(ConfigError) as err:
        parse_config(data, tmp_path)
    assert message in str(err.value)


def test_load_config_reports_yaml_and_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("cards: [type: cpu\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(bad)


def test_relative_paths_resolve_next_to_the_config(write_config, tmp_path):
    path = write_config(
        {
            "display": {"backend": "png", "png_dir": "frames"},
            "collector": {"state_file": "run/state.json", "history_file": "hist.json"},
            "cards": [{"type": "image", "path": "pics"}],
        }
    )
    config = load_config(path)
    assert config.display.png_dir == str(tmp_path / "frames")
    assert config.collector.state_file == str(tmp_path / "run" / "state.json")
    assert config.cards[0].path == tmp_path / "pics"


def test_theme_preset_and_overrides(make_config):
    config = make_config(
        {"theme": {"preset": "light", "colors": {"rx": [1, 2, 3]}}, "cards": [{"type": "cpu"}]}
    )
    assert config.theme.color("rx") == (1, 2, 3)
    assert config.theme.color("background") == (245, 246, 248)


def test_theme_font_must_exist(make_config):
    with pytest.raises(ConfigError, match="font file not found"):
        make_config({"theme": {"fonts": {"sans": "missing.ttf"}}, "cards": [{"type": "cpu"}]})


def test_default_config_has_every_metric_card():
    assert [c.type_name for c in default_config().cards] == [
        "cpu",
        "memory",
        "network",
        "temperature",
        "storage",
        "clock",
        "uptime",
    ]
