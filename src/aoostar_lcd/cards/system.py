"""Clock and uptime cards."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..i18n import localized_strftime, time_units
from ..units import format_duration
from ..validate import ConfigError, as_bool, as_float, as_str
from ._common import is_num
from .base import Card

SAMPLE_BOOT_AGE = 12 * 86400 + 4 * 3600 + 31 * 60


def _hostname_option(card, options) -> None:
    if options["hostname"] is not None:
        as_str(options["hostname"], f"{card.where}.hostname")


def _collect_host() -> dict[str, Any]:
    from .. import sources

    return {
        "hostname": sources.hostname(),
        "boot_time": sources.boot_time(),
        "load": sources.load_average(),
        "cores": sources.cpu_count(),
    }


def _sample_host(card) -> dict[str, Any]:
    now = card.now.timestamp() if card.now is not None else time.time()
    return {
        "hostname": "my-nas",
        "boot_time": now - SAMPLE_BOOT_AGE,
        "load": [0.42, 0.38, 0.30],
        "cores": 8,
    }


class ClockCard(Card):
    """Big clock with the date; hostname and uptime in the footer.

    The time is taken by the renderer when the frame is drawn, so it is right even
    when the collector runs elsewhere. Frames are re-drawn every
    ``display.frame_interval`` seconds, which is why the default format has no seconds.
    """

    type_name = "clock"
    title_key = None
    refresh = 60.0
    defaults = {
        "time_format": "%H:%M",
        "date_format": "%A %d %B %Y",  # weekday and month names follow `language`
        "timezone": None,  # IANA name such as "Europe/Madrid"; null = system time zone
        "show_hostname": True,
        "show_uptime": True,
        "hostname": None,  # text shown instead of the real host name
    }

    def configure(self, options: dict[str, Any]) -> None:
        as_str(options["time_format"], f"{self.where}.time_format")
        as_str(options["date_format"], f"{self.where}.date_format", allow_empty=True)
        as_bool(options["show_hostname"], f"{self.where}.show_hostname")
        as_bool(options["show_uptime"], f"{self.where}.show_uptime")
        _hostname_option(self, options)
        self.tz = None
        if options["timezone"] is not None:
            name = as_str(options["timezone"], f"{self.where}.timezone")
            try:
                self.tz = ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                raise ConfigError(
                    f"{self.where}.timezone: unknown time zone {name!r} "
                    "(install the tzdata package or use a name like 'America/Bogota')"
                ) from None
        self.now = None  # tests and previews may pin the time

    def collect(self) -> dict[str, Any]:
        return _collect_host()

    def sample(self) -> dict[str, Any]:
        return _sample_host(self)

    def render(self, canvas, theme, data) -> None:
        data = data or {}
        opts = self.options
        moment = self.now or datetime.now(self.tz)
        if self.tz is not None and moment.tzinfo is None:
            moment = moment.replace(tzinfo=self.tz)
        time_s = localized_strftime(moment, opts["time_format"], self.lang)
        date_s = localized_strftime(moment, opts["date_format"], self.lang)
        mid = canvas.width // 2
        top = canvas.top
        canvas.text(
            (mid, top + 175),
            time_s,
            size=170,
            kind="mono",
            anchor="ms",
            max_width=canvas.content_width,
        )
        if date_s:
            canvas.text(
                (mid, top + 240),
                date_s,
                size=44,
                color="muted",
                anchor="ms",
                max_width=canvas.content_width,
            )
        footer = []
        host = opts["hostname"] or data.get("hostname")
        if opts["show_hostname"] and isinstance(host, str):
            footer.append(host[:60])
        boot = data.get("boot_time")
        if opts["show_uptime"] and is_num(boot):
            uptime = format_duration(moment.timestamp() - boot, time_units(self.lang))
            footer.append(f"{self.tr('up')} {uptime}")
        if footer:
            canvas.text(
                (mid, min(canvas.bottom, top + 300)),
                "  ·  ".join(footer),
                size=30,
                color="muted",
                anchor="ms",
                max_width=canvas.content_width,
            )


class UptimeCard(Card):
    """Time since boot, boot date and load averages (colored per core)."""

    type_name = "uptime"
    title_key = "uptime"
    refresh = 30.0
    defaults = {
        "hostname": None,
        "load_warn": 0.7,  # load average per core
        "load_crit": 1.0,
    }

    def configure(self, options: dict[str, Any]) -> None:
        _hostname_option(self, options)
        options["load_warn"] = as_float(options["load_warn"], f"{self.where}.load_warn", 0)
        options["load_crit"] = as_float(options["load_crit"], f"{self.where}.load_crit", 0)
        self.now = None

    def collect(self) -> dict[str, Any]:
        return _collect_host()

    def sample(self) -> dict[str, Any]:
        return _sample_host(self)

    def render(self, canvas, theme, data) -> None:
        data = data or {}
        opts = self.options
        canvas.title(self.display_title())
        host = opts["hostname"] or data.get("hostname")
        if isinstance(host, str):
            canvas.text(
                (canvas.right, canvas.top + 10),
                host[:60],
                size=32,
                color="muted",
                anchor="ra",
                max_width=canvas.content_width * 0.45,
            )
        boot = data.get("boot_time")
        now = (self.now or datetime.now()).timestamp()
        top = canvas.top
        if not is_num(boot):
            canvas.message(self.tr("no_data_card"))
            return
        canvas.text(
            (canvas.left, top + 160),
            format_duration(now - boot, time_units(self.lang)),
            size=120,
            kind="mono",
            anchor="ls",
            max_width=canvas.content_width,
        )
        since = datetime.fromtimestamp(boot).strftime("%Y-%m-%d %H:%M")
        canvas.text(
            (canvas.left, top + 220),
            f"{self.tr('since')} {since}",
            size=36,
            color="muted",
            anchor="ls",
            max_width=canvas.content_width,
        )
        load, cores = data.get("load"), data.get("cores")
        if isinstance(load, list) and load and all(is_num(v) for v in load):
            x = canvas.left
            x += canvas.text(
                (x, top + 285), f"{self.tr('load')} ", size=40, color="muted", anchor="ls"
            )
            per_core = cores if is_num(cores) and cores > 0 else 1
            for value in load[:3]:
                color = canvas.level(value / per_core, opts["load_warn"], opts["load_crit"])
                x += canvas.text(
                    (x, top + 285), f"{value:.2f}  ", size=40, color=color, anchor="ls"
                )
