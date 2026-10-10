"""Temperature card: up to six readings as colored tiles.

Each entry of ``sensors`` reads from exactly one source:

* ``chip``: a hwmon chip as psutil names it (``k10temp``, ``coretemp``, ``nvme``,
  ``drivetemp``...). ``sensor`` picks a label inside the chip; several chips with the
  same name are merged with ``aggregate`` (max, avg, first).
* ``smart``: drives read with ``smartctl`` (needs root): ``rotational`` (all spinning
  disks), ``all`` or a list such as ``[sda, sdb]``. The hottest one is shown and disks in
  standby are not woken up.
* ``file``: a text file with a number, e.g. ``/sys/class/thermal/thermal_zone0/temp``
  (``scale`` converts it to °C; 0.001 for millidegrees).

Without ``sensors`` the card shows every chip psutil finds (up to six).
Thresholds are always in °C.
"""

from __future__ import annotations

import time
from typing import Any

from ..units import to_display_temp
from ..validate import (
    ConfigError,
    as_choice,
    as_float,
    as_int,
    as_mapping,
    as_str,
    as_str_list,
    check_keys,
)
from ._common import is_num
from .base import Card

MAX_SENSORS = 6
SENSOR_KEYS = ("label", "chip", "sensor", "aggregate", "smart", "file", "scale", "warn", "crit")


class TemperatureCard(Card):
    type_name = "temperature"
    title_key = "temperature"
    refresh = 10.0
    defaults = {
        "sensors": None,  # list of sensor entries; null = every chip found
        "units": "celsius",  # celsius | fahrenheit (thresholds stay in °C)
        "warn": 70,
        "crit": 85,
        "smart_refresh": 300,  # seconds between smartctl reads
    }

    def configure(self, options: dict[str, Any]) -> None:
        where = self.where
        as_choice(options["units"], f"{where}.units", ("celsius", "fahrenheit"))
        options["warn"] = as_float(options["warn"], f"{where}.warn")
        options["crit"] = as_float(options["crit"], f"{where}.crit")
        options["smart_refresh"] = as_int(
            options["smart_refresh"], f"{where}.smart_refresh", 10, 86400
        )
        sensors = options["sensors"]
        if sensors is None:
            self.sensors = None
        else:
            if not isinstance(sensors, list) or not sensors:
                raise ConfigError(f"{where}.sensors: must be a non-empty list")
            if len(sensors) > MAX_SENSORS:
                raise ConfigError(f"{where}.sensors: at most {MAX_SENSORS} sensors per card")
            self.sensors = [self._sensor(s, f"{where}.sensors[{i}]") for i, s in enumerate(sensors)]
        self._smart_cache: dict[int, tuple[float, float | None]] = {}

    def _sensor(self, raw: Any, where: str) -> dict[str, Any]:
        entry = as_mapping(raw, where)
        check_keys(where, entry, SENSOR_KEYS)
        sources = [k for k in ("chip", "smart", "file") if k in entry]
        if len(sources) != 1:
            raise ConfigError(f"{where}: set exactly one of chip, smart or file")
        out: dict[str, Any] = {
            "label": as_str(entry.get("label", entry.get("chip", "")) or "?", f"{where}.label"),
            "warn": as_float(entry.get("warn", self.options["warn"]), f"{where}.warn"),
            "crit": as_float(entry.get("crit", self.options["crit"]), f"{where}.crit"),
        }
        if "chip" in entry:
            out["chip"] = as_str(entry["chip"], f"{where}.chip")
            out["sensor"] = (
                as_str(entry["sensor"], f"{where}.sensor")
                if entry.get("sensor") is not None
                else None
            )
            out["aggregate"] = as_choice(
                entry.get("aggregate", "max"), f"{where}.aggregate", ("max", "avg", "first")
            )
        elif "smart" in entry:
            smart = entry["smart"]
            if smart not in ("rotational", "all"):
                smart = as_str_list(smart, f"{where}.smart")
            out["smart"] = smart
            if "label" not in entry:
                out["label"] = "HDD"
        else:
            out["file"] = str(self.resolve_path(as_str(entry["file"], f"{where}.file")))
            out["scale"] = as_float(entry.get("scale", 0.001), f"{where}.scale")
        return out

    # -- collector -----------------------------------------------------------------

    def _auto_sensors(self) -> list[dict[str, Any]]:
        from .. import sources

        found = []
        for chip in sources.available_chips()[:MAX_SENSORS]:
            found.append(
                {
                    "label": sources.CHIP_LABELS.get(chip, chip),
                    "chip": chip,
                    "sensor": None,
                    "aggregate": "max",
                    "warn": self.options["warn"],
                    "crit": self.options["crit"],
                }
            )
        return found

    def _read(self, index: int, sensor: dict[str, Any]) -> float | None:
        from .. import sources

        if "chip" in sensor:
            return sources.chip_temperature(sensor["chip"], sensor["sensor"], sensor["aggregate"])
        if "file" in sensor:
            return sources.file_temperature(sensor["file"], sensor["scale"])
        now = time.monotonic()
        cached = self._smart_cache.get(index)
        if cached and now - cached[0] < self.options["smart_refresh"]:
            return cached[1]
        devices = sensor["smart"]
        if devices == "rotational":
            devices = sources.rotational_disks()
        elif devices == "all":
            devices = sorted(set(sources.rotational_disks()) | set(_nvme_devices()))
        temps = []
        for dev in devices:
            try:
                value = sources.smart_temperature(dev)
            except (OSError, ValueError):
                value = None
            if value is not None:
                temps.append(value)
        # Keep the last good value when every disk is asleep.
        value = max(temps) if temps else (cached[1] if cached else None)
        self._smart_cache[index] = (now, value)
        return value

    def collect(self) -> dict[str, Any]:
        sensors = self.sensors if self.sensors is not None else self._auto_sensors()
        out = []
        for index, sensor in enumerate(sensors):
            try:
                value = self._read(index, sensor)
            except (OSError, ValueError):
                value = None
            out.append(
                {
                    "label": sensor["label"],
                    "value": value,
                    "warn": sensor["warn"],
                    "crit": sensor["crit"],
                }
            )
        return {"sensors": out}

    # -- renderer ------------------------------------------------------------------

    def sample(self) -> dict[str, Any]:
        if self.sensors is not None:
            values = [52.0, 41.0, 47.0, 36.0, 64.0, 29.0]
            return {
                "sensors": [
                    {
                        "label": s["label"],
                        "value": values[i % len(values)],
                        "warn": s["warn"],
                        "crit": s["crit"],
                    }
                    for i, s in enumerate(self.sensors)
                ]
            }
        return {
            "sensors": [
                {"label": "CPU", "value": 58.0, "warn": 80, "crit": 90},
                {"label": "NVMe", "value": 41.0, "warn": 60, "crit": 70},
                {"label": "HDD", "value": 46.0, "warn": 45, "crit": 50},
                {"label": "GPU", "value": 37.0, "warn": 80, "crit": 90},
            ]
        }

    def render(self, canvas, theme, data) -> None:
        canvas.title(self.display_title())
        sensors = [s for s in (data or {}).get("sensors") or [] if isinstance(s, dict)]
        sensors = sensors[:MAX_SENSORS]
        if not sensors:
            canvas.message(self.tr("no_data_card"))
            return
        count = len(sensors)
        cols = count if count <= 3 else (2 if count == 4 else 3)
        rows = 1 if count <= 3 else 2
        gap = 16
        area_top = canvas.top + 64
        cell_w = (canvas.content_width - gap * (cols - 1)) / cols
        cell_h = (canvas.bottom - area_top - gap * (rows - 1)) / rows
        value_size = 96 if rows == 1 else 60
        for i, sensor in enumerate(sensors):
            r, c = divmod(i, cols)
            x0 = canvas.left + c * (cell_w + gap)
            y0 = area_top + r * (cell_h + gap)
            canvas.draw.rounded_rectangle(
                (x0, y0, x0 + cell_w, y0 + cell_h), radius=14, fill=canvas.color("track")
            )
            label = str(sensor.get("label", "?"))[:40]
            canvas.text((x0 + 18, y0 + 14), label, size=28, color="muted", max_width=cell_w - 36)
            value_c = sensor.get("value") if is_num(sensor.get("value")) else None
            shown, symbol = to_display_temp(value_c, self.options["units"])
            text = "-" if shown is None else f"{shown:.0f} {symbol}"
            warn = sensor.get("warn") if is_num(sensor.get("warn")) else self.options["warn"]
            crit = sensor.get("crit") if is_num(sensor.get("crit")) else self.options["crit"]
            canvas.text(
                (x0 + 18, y0 + cell_h - 14),
                text,
                size=value_size,
                kind="mono",
                color=canvas.level(value_c, warn, crit),
                anchor="ls",
                max_width=cell_w - 36,
            )


def _nvme_devices() -> list[str]:
    import os

    try:
        return sorted(d for d in os.listdir("/sys/block") if d.startswith("nvme"))
    except OSError:
        return []
