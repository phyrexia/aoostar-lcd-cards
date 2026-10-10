"""The custom-card API: subclassing Card and loading plugins from YAML."""

import sys
import textwrap
import time

import pytest
from PIL import Image

from aoostar_lcd import Card, ConfigError
from aoostar_lcd.canvas import Canvas
from aoostar_lcd.cards import load_plugin
from aoostar_lcd.collector import Collector
from aoostar_lcd.renderer import Renderer
from aoostar_lcd.theme import Theme

from .conftest import EXAMPLES

PLUGIN = textwrap.dedent("""
    from aoostar_lcd import Card

    class Counter(Card):
        type_name = "counter"
        defaults = {"start": 10}

        def configure(self, options):
            self.value = options["start"]

        def collect(self):
            self.value += 1
            return {"value": self.value}

        def render(self, canvas, theme, data):
            canvas.title("COUNTER")
            canvas.text((canvas.left, canvas.top + 150), str((data or {}).get("value", "-")),
                        size=100, anchor="ls")

    class NotACard:
        pass
""")


@pytest.fixture
def plugin_file(tmp_path):
    path = tmp_path / "counter.py"
    path.write_text(PLUGIN)
    return path


def test_plugin_from_a_file_relative_to_the_config(make_config, plugin_file):
    config = make_config(
        {
            "cards": [
                {"type": "plugin", "plugin": "counter.py:Counter", "start": 5, "title": "Count"}
            ]
        }
    )
    card = config.cards[0]
    assert card.id == "counter" and card.options == {"start": 5} and card.title == "Count"
    collector = Collector(config.cards)
    assert collector.tick()["cards"]["counter"] == {"value": 6}
    image = Renderer(config).frame(0, collector.tick())
    assert image.size == (960, 376)


def test_plugin_from_an_importable_module(make_config, plugin_file, monkeypatch):
    monkeypatch.syspath_prepend(str(plugin_file.parent))
    config = make_config({"cards": [{"type": "plugin", "plugin": "counter:Counter"}]})
    assert config.cards[0].type_name == "counter"
    sys.modules.pop("counter", None)


@pytest.mark.parametrize(
    "ref,message",
    [
        ("counter.py", "use 'module.path:ClassName'"),
        ("missing.py:Counter", "file not found"),
        ("counter.py:NotACard", "is not a subclass of aoostar_lcd.Card"),
        ("counter.py:Nope", "is not a subclass"),
        ("no_such_module_xyz:Card", "cannot import"),
        ("counter.py:1bad", "invalid reference"),
    ],
)
def test_plugin_errors(plugin_file, ref, message):
    with pytest.raises(ConfigError, match=message):
        load_plugin(ref, plugin_file.parent, "cards[0] (plugin)")


def test_plugin_import_error_is_reported(tmp_path):
    (tmp_path / "broken.py").write_text("raise RuntimeError('oops')\n")
    with pytest.raises(ConfigError, match="error while importing .*RuntimeError: oops"):
        load_plugin("broken.py:X", tmp_path, "cards[0] (plugin)")


def test_unknown_plugin_option_is_rejected(make_config, plugin_file):
    with pytest.raises(ConfigError, match="unknown option 'stat'.*Did you mean \"start\""):
        make_config({"cards": [{"type": "plugin", "plugin": "counter.py:Counter", "stat": 1}]})


def test_minimal_subclass_api():
    class Hello(Card):
        defaults = {"name": "world"}

        def render(self, canvas, theme, data):
            canvas.text((canvas.left, canvas.top), f"hello {self.options['name']}")

    card = Hello("hello", {"name": "LCD"})
    assert card.collect() is None and card.sample() is None and card.alerts(None) == []
    assert card.visit_pages() == 1 and card.duration == 8.0 and card.enabled
    image = Image.new("RGB", (960, 376))
    card.render(Canvas(image, Theme()), Theme(), None)
    assert image.getbbox() is not None
    with pytest.raises(NotImplementedError):
        Card("base").render(Canvas(image, Theme()), Theme(), None)


@pytest.mark.parametrize(
    "ref", ["plugins/hello_card.py:HelloCard", "plugins/top_processes.py:TopProcessesCard"]
)
def test_example_plugins(ref):
    cls = load_plugin(ref, EXAMPLES, "example")
    card = cls("example", {})
    first = card.collect()
    time.sleep(0.05)
    data = card.collect()
    assert first is not None and data is not None
    for payload in (data, card.sample(), None):
        image = Image.new("RGB", (960, 376))
        card.render(Canvas(image, Theme()), Theme(), payload)
        assert image.size == (960, 376)
