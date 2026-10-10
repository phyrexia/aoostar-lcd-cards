"""Load and validate the YAML configuration (one file for collector and renderer)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .cards import BUILTIN, Card, load_plugin
from .i18n import LANGUAGES
from .theme import Theme, parse_theme
from .validate import (
    ConfigError,
    as_bool,
    as_choice,
    as_float,
    as_int,
    as_mapping,
    as_str,
    check_keys,
    suggest,
)

DEFAULT_CONFIG_PATH = "/etc/aoostar-lcd/config.yaml"
CARD_COMMON_KEYS = ("type", "id", "title", "duration", "enabled", "refresh", "plugin")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_USB_ID = re.compile(r"^[0-9a-fA-F]{1,4}:[0-9a-fA-F]{1,4}$")


@dataclass
class DisplayConfig:
    backend: str = "asterctl"  # asterctl | png | none
    device: str | None = None  # serial device, e.g. /dev/ttyACM0
    usb: str | None = None  # "vid:pid" for asterctl --usb
    asterctl: str = "asterctl"  # binary name (looked up in PATH) or absolute path
    timeout: float = 20.0
    simulate: bool = False  # asterctl --simulate: no hardware touched
    width: int = 960
    height: int = 376
    frame_interval: float = 5.0
    png_dir: str = "frames"
    check_version: bool = True


@dataclass
class CollectorConfig:
    interval: float = 5.0
    state_file: str = "/run/aoostar-lcd/state.json"
    history_file: str | None = None
    max_age: float = 30.0


@dataclass
class Config:
    language: str = "en"
    display: DisplayConfig = field(default_factory=DisplayConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    theme: Theme = field(default_factory=Theme)
    page_dots: bool = True
    alert_banner: bool = True
    cards: list[Card] = field(default_factory=list)
    base_dir: Path = field(default_factory=Path.cwd)
    source: str = "<built-in>"

    @property
    def enabled_cards(self) -> list[Card]:
        return [c for c in self.cards if c.enabled]


def _path(value: Any, where: str, base_dir: Path) -> str:
    path = Path(os.path.expanduser(as_str(value, where)))
    return str(path if path.is_absolute() else base_dir / path)


def _display(raw: Any, base_dir: Path) -> DisplayConfig:
    data = as_mapping(raw, "display")
    check_keys("display", data, DisplayConfig.__dataclass_fields__)
    cfg = DisplayConfig()
    if "backend" in data:
        cfg.backend = as_choice(data["backend"], "display.backend", ("asterctl", "png", "none"))
    if data.get("device") is not None:
        cfg.device = as_str(data["device"], "display.device")
    if data.get("usb") is not None:
        cfg.usb = as_str(data["usb"], "display.usb")
        if not _USB_ID.match(cfg.usb):
            raise ConfigError(f"display.usb: use 'vid:pid' in hex like '416:90A1', got {cfg.usb!r}")
    if "asterctl" in data:
        value = as_str(data["asterctl"], "display.asterctl")
        cfg.asterctl = value if "/" not in value else _path(value, "display.asterctl", base_dir)
    if "timeout" in data:
        cfg.timeout = as_float(data["timeout"], "display.timeout", 1, 300)
    if "simulate" in data:
        cfg.simulate = as_bool(data["simulate"], "display.simulate")
    if "width" in data:
        cfg.width = as_int(data["width"], "display.width", 64, 4096)
    if "height" in data:
        cfg.height = as_int(data["height"], "display.height", 32, 4096)
    if "frame_interval" in data:
        cfg.frame_interval = as_float(data["frame_interval"], "display.frame_interval", 1, 3600)
    if "png_dir" in data:
        cfg.png_dir = _path(data["png_dir"], "display.png_dir", base_dir)
    else:
        cfg.png_dir = str(base_dir / cfg.png_dir)
    if "check_version" in data:
        cfg.check_version = as_bool(data["check_version"], "display.check_version")
    return cfg


def _collector(raw: Any, base_dir: Path) -> CollectorConfig:
    data = as_mapping(raw, "collector")
    check_keys("collector", data, CollectorConfig.__dataclass_fields__)
    cfg = CollectorConfig()
    if "interval" in data:
        cfg.interval = as_float(data["interval"], "collector.interval", 1, 60)
    if "state_file" in data:
        cfg.state_file = _path(data["state_file"], "collector.state_file", base_dir)
    if data.get("history_file") is not None:
        cfg.history_file = _path(data["history_file"], "collector.history_file", base_dir)
    if "max_age" in data:
        cfg.max_age = as_float(data["max_age"], "collector.max_age", 5, 3600)
    if cfg.max_age < 2 * cfg.interval:
        raise ConfigError(
            f"collector.max_age ({cfg.max_age:g}) must be at least twice "
            f"collector.interval ({cfg.interval:g})"
        )
    return cfg


def build_card(
    entry: Any,
    index: int,
    base_dir: Path,
    lang: str,
    default_duration: float,
    used_ids: set[str],
) -> Card:
    where = f"cards[{index}]"
    data = as_mapping(entry, where)
    if "type" not in data:
        raise ConfigError(f"{where}: 'type' is required (one of {', '.join(BUILTIN)}, plugin)")
    card_type = as_str(data["type"], f"{where}.type")
    where = f"cards[{index}] ({card_type})"
    if card_type == "plugin":
        if "plugin" not in data:
            raise ConfigError(f"{where}: 'plugin' is required, e.g. 'plugin: ./my_card.py:MyCard'")
        cls = load_plugin(data["plugin"], base_dir, where)
    else:
        if "plugin" in data:
            raise ConfigError(f"{where}: 'plugin' is only valid with 'type: plugin'")
        cls = BUILTIN.get(card_type)
        if cls is None:
            hint = suggest(card_type, [*BUILTIN, "plugin"])
            raise ConfigError(
                f"{where}: unknown card type {card_type!r}.{hint} "
                f"Available: {', '.join([*BUILTIN, 'plugin'])}"
            )
    base_id = card_type if card_type != "plugin" else (cls.type_name or "plugin")
    if "id" in data:
        card_id = as_str(data["id"], f"{where}.id")
        if not _ID.match(card_id):
            raise ConfigError(
                f"{where}.id: use lowercase letters, digits, '-' or '_' (max 40), got {card_id!r}"
            )
        if card_id in used_ids:
            raise ConfigError(f"{where}.id: duplicate id {card_id!r}")
    else:
        card_id, n = base_id, 2
        while card_id in used_ids:
            card_id, n = f"{base_id}-{n}", n + 1
    used_ids.add(card_id)
    options = {k: v for k, v in data.items() if k not in CARD_COMMON_KEYS}
    title = as_str(data["title"], f"{where}.title") if data.get("title") is not None else None
    card = cls(card_id, options, title=title, lang=lang, base_dir=base_dir, where=where)
    card.duration = as_float(data.get("duration", default_duration), f"{where}.duration", 1, 3600)
    card.enabled = as_bool(data.get("enabled", True), f"{where}.enabled")
    card.collect_every = as_float(data.get("refresh", cls.refresh), f"{where}.refresh", 0, 86400)
    return card


def parse_config(raw: Any, base_dir: Path | None = None, source: str = "<memory>") -> Config:
    base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
    data = as_mapping(raw, "config")
    check_keys("config", data, ("language", "display", "collector", "rotation", "theme", "cards"))
    cfg = Config(base_dir=base_dir, source=source)
    cfg.language = as_choice(data.get("language", "en"), "language", LANGUAGES)
    cfg.display = _display(data.get("display"), base_dir)
    cfg.collector = _collector(data.get("collector"), base_dir)
    rotation = as_mapping(data.get("rotation"), "rotation")
    check_keys("rotation", rotation, ("default_duration", "page_dots", "alert_banner"))
    default_duration = as_float(
        rotation.get("default_duration", 8), "rotation.default_duration", 1, 3600
    )
    cfg.page_dots = as_bool(rotation.get("page_dots", True), "rotation.page_dots")
    cfg.alert_banner = as_bool(rotation.get("alert_banner", True), "rotation.alert_banner")
    cfg.theme = parse_theme(data.get("theme"), base_dir)
    cards = data.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ConfigError("cards: must be a non-empty list of cards")
    used_ids: set[str] = set()
    cfg.cards = [
        build_card(entry, i, base_dir, cfg.language, default_duration, used_ids)
        for i, entry in enumerate(cards)
    ]
    if not cfg.enabled_cards:
        raise ConfigError("cards: every card is disabled (enabled: false)")
    return cfg


def load_config(path: str | os.PathLike) -> Config:
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from None
    return parse_config(raw, path.resolve().parent, str(path))


def default_config(base_dir: Path | None = None) -> Config:
    """Every built-in card except custom/image, for previews without a config file."""
    return parse_config(
        {
            "cards": [
                {"type": t}
                for t in ("cpu", "memory", "network", "temperature", "storage", "clock", "uptime")
            ]
        },
        base_dir,
        "<built-in>",
    )
