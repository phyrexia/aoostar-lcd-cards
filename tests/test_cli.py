"""The `aoostar-lcd` command line."""

import json

from PIL import Image

from aoostar_lcd import __version__
from aoostar_lcd.cli import main

from .conftest import EXAMPLES


def test_preview_folder_and_single_png(tmp_path, capsys):
    out = tmp_path / "out"
    assert (
        main(
            [
                "preview",
                "-c",
                str(EXAMPLES / "gallery.yaml"),
                "--out",
                str(out),
                "--at",
                "2026-01-15T10:24",
                "--no-data-frame",
            ]
        )
        == 0
    )
    files = sorted(out.glob("*.png"))
    assert len(files) == 16  # 15 cards + no-data
    single = tmp_path / "net.png"
    assert (
        main(
            [
                "preview",
                "-c",
                str(EXAMPLES / "gallery.yaml"),
                "--png",
                str(single),
                "--card",
                "network-split",
            ]
        )
        == 0
    )
    with Image.open(single) as image:
        assert image.size == (960, 376)


def test_preview_without_config_uses_the_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("AOOSTAR_LCD_CONFIG", str(tmp_path / "missing.yaml"))
    assert main(["preview", "--out", str(tmp_path)]) == 0
    assert len(list(tmp_path.glob("*.png"))) == 7


def test_preview_live_uses_this_machine(tmp_path, write_config):
    path = write_config(
        {
            "display": {"backend": "none"},
            "cards": [{"type": "cpu"}, {"type": "memory"}, {"type": "uptime"}],
        }
    )
    assert main(["preview", "-c", str(path), "--out", str(tmp_path / "live"), "--live"]) == 0
    assert len(list((tmp_path / "live").glob("*.png"))) == 3


def test_collect_once_then_preview_from_state(tmp_path, write_config):
    path = write_config(
        {
            "display": {"backend": "none"},
            "collector": {"state_file": "state.json"},
            "cards": [{"type": "memory"}, {"type": "storage"}],
        }
    )
    assert main(["collect", "-c", str(path), "--once"]) == 0
    state = json.loads((tmp_path / "state.json").read_text())
    assert set(state["cards"]) == {"memory", "storage"} and state["version"] == 1
    assert (
        main(
            [
                "preview",
                "-c",
                str(path),
                "--state",
                str(tmp_path / "state.json"),
                "--png",
                str(tmp_path / "from-state.png"),
            ]
        )
        == 0
    )


def test_check_and_errors(tmp_path, write_config, capsys):
    good = write_config({"display": {"backend": "none"}, "cards": [{"type": "cpu"}]})
    assert main(["check", "-c", str(good)]) == 0
    assert "cpu" in capsys.readouterr().out
    bad = write_config({"cards": [{"type": "cpu", "warn": "high"}]}, "bad.yaml")
    assert main(["check", "-c", str(bad)]) == 2
    assert "cards[0] (cpu).warn: must be a number" in capsys.readouterr().err
    missing_asterctl = write_config(
        {"display": {"asterctl": str(tmp_path / "nope")}, "cards": [{"type": "cpu"}]}, "a.yaml"
    )
    assert main(["check", "-c", str(missing_asterctl)]) == 2
    assert "install-asterctl.sh" in capsys.readouterr().err
    assert (
        main(["preview", "-c", str(good), "--png", str(tmp_path / "x.png"), "--card", "nope"]) == 2
    )


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert __version__ in capsys.readouterr().out
