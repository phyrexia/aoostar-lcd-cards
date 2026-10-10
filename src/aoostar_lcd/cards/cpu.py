"""CPU card: current load, temperature and an optional history with peaks."""

from __future__ import annotations

import time
from typing import Any

from ..units import to_display_temp
from ..validate import as_choice, as_str
from ._common import MAX_GAP_S, history_options, is_num, right_aligned, thresholds, wave
from .base import Card


class CpuCard(Card):
    type_name = "cpu"
    title_key = "cpu"
    defaults = {
        "temperature_chip": "auto",  # psutil chip name (k10temp, coretemp...), "auto" or null
        "temperature_sensor": None,  # label inside the chip (e.g. "Tctl"); null = first
        "temperature_unit": "celsius",
        "history_minutes": 180,  # 0 hides the chart
        "bucket_seconds": 300,
        "warn": 80,
        "crit": 90,
        "temp_warn": 80,
        "temp_crit": 90,
        "chart_colors": "level",  # level = ok/warn/crit per bar | accent = one color
    }

    def configure(self, options: dict[str, Any]) -> None:
        if options["temperature_chip"] is not None:
            as_str(options["temperature_chip"], f"{self.where}.temperature_chip")
        if options["temperature_sensor"] is not None:
            as_str(options["temperature_sensor"], f"{self.where}.temperature_sensor")
        as_choice(
            options["temperature_unit"], f"{self.where}.temperature_unit", ("celsius", "fahrenheit")
        )
        as_choice(options["chart_colors"], f"{self.where}.chart_colors", ("level", "accent"))
        self.history = history_options(self, options)
        thresholds(self, options, maximum=100)
        thresholds(self, options, "temp_warn", "temp_crit")
        self._prev: tuple[float, float, float] | None = None

    # -- collector -----------------------------------------------------------------

    def collect(self) -> dict[str, Any]:
        from .. import sources

        now = time.time()
        busy, total = sources.cpu_busy_total()
        percent = None
        if self._prev is not None:
            p_busy, p_total, p_ts = self._prev
            d_total = total - p_total
            dt = now - p_ts
            if d_total > 0:
                percent = max(0.0, min(100.0, 100.0 * (busy - p_busy) / d_total))
                if self.history is not None and 0 < dt <= MAX_GAP_S:
                    self.history.add(now, "cpu", percent * dt, dt, percent)
        self._prev = (busy, total, now)
        chip = self.options["temperature_chip"]
        temp = sources.cpu_temperature(chip, self.options["temperature_sensor"]) if chip else None
        data: dict[str, Any] = {
            "percent": None if percent is None else round(percent, 1),
            "temp_c": temp,
            "cores": sources.cpu_count(),
            "load": sources.load_average(),
        }
        if self.history is not None:
            avg, peak = self.history.window(now, "cpu")
            data["history"] = {
                "step_s": self.history.step,
                "slots": self.history.slots,
                "avg": avg,
                "peak": peak,
            }
        return data

    def state(self):
        return self.history.to_dict() if self.history is not None else None

    def restore(self, state):
        if self.history is not None:
            self.history.load_dict(state, time.time())

    # -- renderer ------------------------------------------------------------------

    def sample(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "percent": 37.5,
            "temp_c": 58.0,
            "cores": 16,
            "load": [3.42, 2.87, 2.15],
        }
        if self.history is not None:
            slots = self.history.slots
            avg = [
                round(wave(i, 8, 30, 14) + (35 if slots * 0.55 <= i <= slots * 0.65 else 0), 1)
                for i in range(slots)
            ]
            peak = [round(min(100.0, v + wave(i, 10, 35, 5, 1.5)), 1) for i, v in enumerate(avg)]
            data["history"] = {
                "step_s": self.history.step,
                "slots": slots,
                "avg": avg,
                "peak": peak,
            }
        return data

    def _header(self, canvas, data, avg, peak) -> None:
        """Top right: highest load of the window (colored) and the load average."""
        opts = self.options
        right = canvas.right
        y = canvas.top + 12
        load = data.get("load")
        if isinstance(load, list) and load and is_num(load[0]):
            right -= canvas.text(
                (right, y),
                f"{self.tr('load')} {load[0]:.2f}",
                size=28,
                color="muted",
                anchor="ra",
                max_width=220,
            )
        top = max((v for v in peak + avg if v is not None), default=None)
        if self.history is not None and top is not None:
            if right < canvas.right:
                right -= canvas.text((right, y), "  ·  ", size=28, color="muted", anchor="ra")
            right -= canvas.text(
                (right, y),
                f"{top:.0f} %",
                size=28,
                anchor="ra",
                color=canvas.level(top, opts["warn"], opts["crit"]),
            )
            window = opts["history_minutes"]
            span = f"{window // 60} h" if window % 60 == 0 else f"{window} min"
            canvas.text(
                (right - 8, y), f"{self.tr('peak')} {span}", size=28, color="muted", anchor="ra"
            )

    def render(self, canvas, theme, data) -> None:
        from ..charts import histogram, time_marks

        data = data or {}
        opts = self.options
        percent = data.get("percent") if is_num(data.get("percent")) else None
        canvas.title(self.display_title())
        history = data.get("history") if isinstance(data.get("history"), dict) else None
        slots = self.history.slots if self.history is not None else 0
        avg = right_aligned(history, "avg", slots)
        peak = right_aligned(history, "peak", slots)
        self._header(canvas, data, avg, peak)
        value = "-" if percent is None else f"{percent:.0f} %"
        color = canvas.level(percent, opts["warn"], opts["crit"])
        temp, symbol = to_display_temp(data.get("temp_c"), opts["temperature_unit"])
        temp_s = "-" if temp is None else f"{temp:.0f} {symbol}"
        temp_color = canvas.level(data.get("temp_c"), opts["temp_warn"], opts["temp_crit"])
        show_temp = opts["temperature_chip"] is not None

        if self.history is None:
            top = canvas.top
            canvas.text(
                (canvas.left, top + 140),
                value,
                size=110,
                kind="mono",
                anchor="ls",
                max_width=canvas.content_width,
            )
            canvas.bar(canvas.left, top + 158, canvas.content_width, 40, percent, color)
            if show_temp:
                canvas.text(
                    (canvas.left, top + 240),
                    self.tr("temp"),
                    size=36,
                    color="muted",
                    anchor="ls",
                    max_width=500,
                )
                canvas.text(
                    (canvas.right, top + 240),
                    temp_s,
                    size=44,
                    color=temp_color,
                    anchor="rs",
                    max_width=300,
                )
            return

        col_w = 300
        top = canvas.top
        canvas.text(
            (canvas.left, top + 150), value, size=100, kind="mono", anchor="ls", max_width=col_w
        )
        canvas.bar(canvas.left, top + 168, col_w, 30, percent, color)
        if show_temp:
            canvas.text(
                (canvas.left, top + 236),
                self.tr("temp"),
                size=26,
                color="muted",
                anchor="ls",
                max_width=col_w,
            )
            canvas.text(
                (canvas.left, top + 284),
                temp_s,
                size=46,
                color=temp_color,
                anchor="ls",
                max_width=col_w,
            )
        scale = cpu_scale(peak + avg)
        colors = peak_colors = None
        if opts["chart_colors"] == "level":
            # Each bar by its average, each cap by its peak (green / amber / red).
            colors = [canvas.level(a or 0, opts["warn"], opts["crit"]) for a in avg]
            peak_colors = [canvas.level(p or 0, opts["warn"], opts["crit"]) for p in peak]
        box = (canvas.left + col_w + 90, top + 64, canvas.right, canvas.bottom - 28)
        histogram(
            canvas,
            box,
            avg,
            peak,
            scale,
            time_marks(slots, self.history.step, self.tr("now")),
            color="accent",
            bar_colors=colors,
            peak_colors=peak_colors,
            value_labels=((0, "0"), (scale / 2, f"{scale / 2:g}"), (scale, f"{scale:g}")),
            empty_message=self.tr("collecting") if history else self.tr("no_history"),
        )


def cpu_scale(values) -> float:
    """20, 50 or 100 %: the smallest that holds every value, so a quiet CPU is still visible."""
    top = max((v for v in values if v is not None), default=0)
    return next(s for s in (20.0, 50.0, 100.0) if top <= s or s == 100.0)
