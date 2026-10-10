"""Colors and fonts shared by every card."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .validate import ConfigError, as_choice, as_color, as_mapping, as_str, check_keys

RGB = tuple[int, int, int]

FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT_SANS = str(FONT_DIR / "DejaVuSans-Bold.ttf")
DEFAULT_MONO = str(FONT_DIR / "DejaVuSansMono-Bold.ttf")

COLOR_NAMES = (
    "background",  # card background
    "text",  # primary text and big numbers
    "muted",  # labels and secondary text
    "dim",  # inactive page dots, peak markers
    "track",  # empty part of bars
    "grid",  # chart grid lines
    "ok",  # value below the warning threshold
    "warn",  # value at or above the warning threshold
    "crit",  # value at or above the critical threshold, alert banner
    "rx",  # inbound traffic
    "tx",  # outbound traffic
    "accent",  # charts without a direction (CPU history)
)

PRESETS: dict[str, dict[str, RGB]] = {
    "dark": {
        "background": (0, 0, 0),
        "text": (255, 255, 255),
        "muted": (205, 210, 220),
        "dim": (120, 125, 135),
        "track": (30, 33, 40),
        "grid": (70, 75, 88),
        "ok": (60, 230, 110),
        "warn": (255, 190, 0),
        "crit": (255, 60, 70),
        "rx": (70, 200, 255),
        "tx": (255, 140, 40),
        "accent": (150, 120, 255),
    },
    "light": {
        "background": (245, 246, 248),
        "text": (20, 22, 28),
        "muted": (70, 76, 90),
        "dim": (150, 155, 165),
        "track": (215, 218, 225),
        "grid": (190, 194, 204),
        "ok": (20, 150, 70),
        "warn": (200, 130, 0),
        "crit": (210, 30, 45),
        "rx": (0, 120, 200),
        "tx": (220, 90, 0),
        "accent": (100, 70, 210),
    },
}


@dataclass(frozen=True)
class Theme:
    """Resolved colors (RGB tuples) and font file paths."""

    colors: dict[str, RGB] = field(default_factory=lambda: dict(PRESETS["dark"]))
    sans: str = DEFAULT_SANS
    mono: str = DEFAULT_MONO

    def color(self, name_or_rgb: str | RGB) -> RGB:
        """Theme color by name, or pass an RGB tuple through."""
        if isinstance(name_or_rgb, tuple):
            return name_or_rgb
        try:
            return self.colors[name_or_rgb]
        except KeyError:
            raise KeyError(
                f"unknown theme color {name_or_rgb!r}; use one of {', '.join(COLOR_NAMES)}"
            ) from None

    def level(self, value: float | None, warn: float | None, crit: float | None) -> RGB:
        """ok / warn / crit color for ``value``; muted when the value is missing."""
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return self.colors["muted"]
        if crit is not None and value >= crit:
            return self.colors["crit"]
        if warn is not None and value >= warn:
            return self.colors["warn"]
        return self.colors["ok"]


def parse_theme(raw: Any, base_dir: Path, where: str = "theme") -> Theme:
    data = as_mapping(raw, where)
    check_keys(where, data, ("preset", "colors", "fonts"))
    preset = as_choice(data.get("preset", "dark"), f"{where}.preset", PRESETS)
    colors = dict(PRESETS[preset])
    color_data = as_mapping(data.get("colors"), f"{where}.colors")
    check_keys(f"{where}.colors", color_data, COLOR_NAMES)
    for name, value in color_data.items():
        colors[name] = as_color(value, f"{where}.colors.{name}")
    fonts = as_mapping(data.get("fonts"), f"{where}.fonts")
    check_keys(f"{where}.fonts", fonts, ("sans", "mono"))
    paths = {}
    for kind, default in (("sans", DEFAULT_SANS), ("mono", DEFAULT_MONO)):
        if kind not in fonts:
            paths[kind] = default
            continue
        path = Path(os.path.expanduser(as_str(fonts[kind], f"{where}.fonts.{kind}")))
        if not path.is_absolute():
            path = base_dir / path
        if not path.is_file():
            raise ConfigError(f"{where}.fonts.{kind}: font file not found: {path}")
        paths[kind] = str(path)
    return Theme(colors=colors, sans=paths["sans"], mono=paths["mono"])
