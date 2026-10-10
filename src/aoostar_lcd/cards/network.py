"""Network card: mirrored histogram of inbound (up) and outbound (down) traffic.

``mode: aggregate`` sums the selected interfaces into one chart (what matters at a
glance is how much enters and leaves the machine); ``mode: split`` draws one small
chart per interface (up to 4). Rates are averages per bucket; the lighter cap on
each bar is the highest rate seen inside that bucket.
"""

from __future__ import annotations

import time
from typing import Any

from ..units import RATE_UNITS, format_rate, nice_ceiling, rate_unit
from ..validate import ConfigError, as_bool, as_choice, as_float, as_mapping, as_str, as_str_list
from ._common import MAX_GAP_S, history_options, right_aligned, wave
from .base import Card

TOTAL = "*"
MAX_SPLIT = 4


class NetworkCard(Card):
    type_name = "network"
    title_key = "network"
    defaults = {
        "interfaces": "auto",  # "auto" (physical NICs) or a list of names
        "exclude": None,  # extra glob patterns ignored by "auto" (e.g. ["enp7s0"])
        "mode": "aggregate",  # aggregate | split
        "units": "bits",  # bits = Mbit/s, bytes = MB/s
        "history_minutes": 180,
        "bucket_seconds": 300,
        "min_scale": 10,  # lowest full scale, in Mbit/s (bits) or MB/s (bytes)
        "show_peaks": True,
        "labels": {},  # interface -> label shown in split mode
    }

    def configure(self, options: dict[str, Any]) -> None:
        where = self.where
        if options["interfaces"] != "auto":
            options["interfaces"] = as_str_list(options["interfaces"], f"{where}.interfaces")
        if options["exclude"] is not None:
            options["exclude"] = as_str_list(options["exclude"], f"{where}.exclude")
        as_choice(options["mode"], f"{where}.mode", ("aggregate", "split"))
        as_choice(options["units"], f"{where}.units", RATE_UNITS)
        as_float(options["min_scale"], f"{where}.min_scale", 0)
        as_bool(options["show_peaks"], f"{where}.show_peaks")
        labels = as_mapping(options["labels"], f"{where}.labels")
        for key, value in labels.items():
            as_str(value, f"{where}.labels.{key}")
        options["labels"] = labels
        if (
            options["mode"] == "split"
            and isinstance(options["interfaces"], list)
            and len(options["interfaces"]) > MAX_SPLIT
        ):
            raise ConfigError(f"{where}: mode split shows at most {MAX_SPLIT} interfaces")
        self.history = history_options(self, options)
        if self.history is None:
            raise ConfigError(f"{where}.history_minutes: the network card needs a history (> 0)")
        self._prev: dict[str, tuple[int, int]] | None = None
        self._prev_ts = 0.0

    def _selected(self, names) -> list[str]:
        from .. import sources

        wanted = self.options["interfaces"]
        if wanted == "auto":
            exclude = sources.VIRTUAL_IFACES + tuple(self.options["exclude"] or ())
            return sources.physical_interfaces(names, exclude)
        return [n for n in wanted if n in names]

    # -- collector -----------------------------------------------------------------

    def collect(self) -> dict[str, Any]:
        from .. import sources

        now = time.time()
        counters = sources.net_counters()
        names = self._selected(counters)
        dt = now - self._prev_ts
        current: dict[str, dict[str, float]] = {}
        if self._prev is not None and 0 < dt <= MAX_GAP_S:
            total_rx = total_tx = 0
            measured = False
            for name in names:
                if name not in self._prev:
                    continue
                d_rx = counters[name][0] - self._prev[name][0]
                d_tx = counters[name][1] - self._prev[name][1]
                if d_rx < 0 or d_tx < 0:  # counter reset: no valid base for this sample
                    continue
                measured = True
                total_rx += d_rx
                total_tx += d_tx
                self.history.add(now, f"{name}:rx", d_rx, dt, d_rx / dt)
                self.history.add(now, f"{name}:tx", d_tx, dt, d_tx / dt)
                current[name] = {"rx": round(d_rx / dt, 1), "tx": round(d_tx / dt, 1)}
            if measured:
                self.history.add(now, f"{TOTAL}:rx", total_rx, dt, total_rx / dt)
                self.history.add(now, f"{TOTAL}:tx", total_tx, dt, total_tx / dt)
        self._prev = {name: counters[name] for name in names}
        self._prev_ts = now
        series = {}
        for name in [*names, TOTAL]:
            rx, rx_peak = self.history.window(now, f"{name}:rx")
            tx, tx_peak = self.history.window(now, f"{name}:tx")
            series[name] = {"rx": rx, "tx": tx, "rx_peak": rx_peak, "tx_peak": tx_peak}
        return {
            "step_s": self.history.step,
            "slots": self.history.slots,
            "names": names,
            "series": series,
            "current": current,
        }

    def state(self):
        return self.history.to_dict()

    def restore(self, state):
        self.history.load_dict(state, time.time())

    # -- renderer ------------------------------------------------------------------

    def sample(self) -> dict[str, Any]:
        slots = self.history.slots
        wanted = self.options["interfaces"]
        names = list(wanted) if isinstance(wanted, list) else ["eth0", "eth1"]
        series: dict[str, dict[str, list]] = {}
        total = {k: [0.0] * slots for k in ("rx", "tx", "rx_peak", "tx_peak")}
        for n, name in enumerate(names):
            burst = 5.5e7 if n == 0 else 0.0
            rx = [
                wave(i, 2e5, 5e6 / (n + 1), 17 - n, n) + (burst if 20 <= i <= 23 else 0)
                for i in range(slots)
            ]
            tx = [
                wave(i, 1e5, 2e6 / (n + 1), 11 + n, n) + (1.8e7 if n == 0 and 28 <= i <= 30 else 0)
                for i in range(slots)
            ]
            rx_peak = [v * (1.3 + 0.4 * wave(i, 0, 1, 5)) for i, v in enumerate(rx)]
            tx_peak = [v * (1.3 + 0.4 * wave(i, 0, 1, 7)) for i, v in enumerate(tx)]
            entry = {"rx": rx, "tx": tx, "rx_peak": rx_peak, "tx_peak": tx_peak}
            series[name] = entry
            for key in total:
                total[key] = [a + b for a, b in zip(total[key], entry[key], strict=True)]
        series[TOTAL] = total
        return {
            "step_s": self.history.step,
            "slots": slots,
            "names": names,
            "series": series,
            "current": {},
        }

    def _scale_floor(self) -> float:
        unit_bytes = 1e6 / 8 if self.options["units"] == "bits" else 1e6
        return self.options["min_scale"] * unit_bytes

    def render(self, canvas, theme, data) -> None:
        data = data or {}
        series = data.get("series") if isinstance(data.get("series"), dict) else {}
        names = [n for n in data.get("names") or [] if isinstance(n, str) and n in series]
        if self.options["mode"] == "split" and names:
            self._render_split(canvas, series, names[:MAX_SPLIT], bool(data))
        else:
            self._render_one(canvas, series.get(TOTAL), bool(data))

    def _values(self, entry) -> tuple[list, list, list | None, list | None]:
        slots = self.history.slots
        rx = right_aligned(entry, "rx", slots)
        tx = right_aligned(entry, "tx", slots)
        if not self.options["show_peaks"]:
            return rx, tx, None, None
        return (
            rx,
            tx,
            right_aligned(entry, "rx_peak", slots),
            right_aligned(entry, "tx_peak", slots),
        )

    def _scale(self, *lists) -> float:
        """Full scale in bytes/s, rounded to 1-2-5 in the unit shown (bits or bytes)."""
        peak = max((v for values in lists if values for v in values if v is not None), default=0)
        factor = 8 if self.options["units"] == "bits" else 1
        return nice_ceiling(peak * factor, self._scale_floor() * factor) / factor

    def _render_one(self, canvas, entry, has_data: bool) -> None:
        from ..charts import mirror_histogram, time_marks

        rx, tx, rx_peak, tx_peak = self._values(entry)
        scale = self._scale(rx, tx, rx_peak, tx_peak)
        units = self.options["units"]
        divisor, label = rate_unit(scale, units)
        top = canvas.top
        title = self.display_title()
        x = canvas.left + canvas.text(
            (canvas.left, top + 4), title, size=40, max_width=canvas.content_width * 0.4
        )
        x += 12 + canvas.text((x + 12, top + 16), label, size=26, color="muted")
        # Header: highest rate of the window in each direction, in its color.
        top_rx = max((v for v in (rx_peak or rx) if v is not None), default=None)
        top_tx = max((v for v in (tx_peak or tx) if v is not None), default=None)
        room = (canvas.right - x - 40) / 2
        tx_s = f"↑ {format_rate(top_tx, units)}"
        width = canvas.text(
            (canvas.right, top + 8), tx_s, size=32, color="tx", anchor="ra", max_width=room
        )
        rx_s = f"↓ {format_rate(top_rx, units)}"
        width += 20 + canvas.text(
            (canvas.right - width - 20, top + 8),
            rx_s,
            size=32,
            color="rx",
            anchor="ra",
            max_width=room,
        )
        canvas.text(
            (canvas.right - width - 14, top + 16),
            self.tr("peak"),
            size=24,
            color="muted",
            anchor="ra",
        )
        box = (canvas.left + 104, canvas.top + 60, canvas.right, canvas.bottom - 28)
        mirror_histogram(
            canvas,
            box,
            rx,
            tx,
            scale,
            divisor,
            time_marks(self.history.slots, self.history.step, self.tr("now")),
            rx_peak,
            tx_peak,
            empty_message=self.tr("collecting") if has_data else self.tr("no_history"),
        )

    def _render_split(self, canvas, series, names, has_data: bool) -> None:
        from ..charts import mirror_histogram, time_marks

        canvas.title(self.display_title())
        cols = 1 if len(names) == 1 else 2
        rows = 1 if len(names) <= 2 else 2
        area_top = canvas.top + 56
        area_h = canvas.bottom - area_top
        cell_w = canvas.content_width / cols
        cell_h = area_h / rows
        units = self.options["units"]
        for i, name in enumerate(names):
            r, c = divmod(i, cols)
            x0 = canvas.left + c * cell_w
            y0 = area_top + r * cell_h
            rx, tx, rx_peak, tx_peak = self._values(series.get(name))
            scale = self._scale(rx, tx, rx_peak, tx_peak)
            divisor, unit_label = rate_unit(scale, units)
            label = f"{self.options['labels'].get(name, name)} {unit_label}"
            canvas.text((x0, y0), label, size=24, color="text", max_width=cell_w * 0.42)
            top_rx = max((v for v in (rx_peak or rx) if v is not None), default=None)
            top_tx = max((v for v in (tx_peak or tx) if v is not None), default=None)
            summary = f"↓ {format_rate(top_rx, units)}  ↑ {format_rate(top_tx, units)}"
            canvas.text(
                (x0 + cell_w - 16, y0),
                summary,
                size=22,
                color="muted",
                anchor="ra",
                max_width=cell_w * 0.55,
            )
            last_row = r == rows - 1
            plot_bottom = y0 + cell_h - (30 if last_row else 10)
            box = (x0 + 64, y0 + 42, x0 + cell_w - 16, plot_bottom)
            marks = (
                time_marks(self.history.slots, self.history.step, self.tr("now"))
                if last_row
                else []
            )
            mirror_histogram(
                canvas,
                box,
                rx,
                tx,
                scale,
                divisor,
                marks,
                rx_peak,
                tx_peak,
                empty_message=self.tr("collecting") if has_data else self.tr("no_history"),
                label_size=18,
            )
