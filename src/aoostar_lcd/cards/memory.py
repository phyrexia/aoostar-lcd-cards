"""Memory card: used / total RAM, plus ZFS ARC and swap when present."""

from __future__ import annotations

from typing import Any

from ..units import SIZE_SYSTEMS, format_size, format_size_in, size_unit
from ..validate import as_bool, as_choice
from ._common import is_num, thresholds
from .base import Card

GIB = 2**30


class MemoryCard(Card):
    type_name = "memory"
    title_key = "memory"
    defaults = {
        "units": "iec",  # iec = GiB (how RAM is sized), si = GB
        "zfs_arc": "auto",  # auto | true | false
        "swap": True,
        "warn": 80,
        "crit": 90,
    }

    def configure(self, options: dict[str, Any]) -> None:
        as_choice(options["units"], f"{self.where}.units", SIZE_SYSTEMS)
        if options["zfs_arc"] != "auto":
            as_bool(options["zfs_arc"], f"{self.where}.zfs_arc")
        as_bool(options["swap"], f"{self.where}.swap")
        thresholds(self, options, maximum=100)

    def collect(self) -> dict[str, Any]:
        from .. import sources

        vm = sources.psutil.virtual_memory()
        data: dict[str, Any] = {
            "total": vm.total,
            "used": vm.total - vm.available,
            "available": vm.available,
            "arc": sources.zfs_arc_bytes() if self.options["zfs_arc"] is not False else None,
        }
        if self.options["swap"]:
            swap = sources.psutil.swap_memory()
            data["swap_total"], data["swap_used"] = swap.total, swap.used
        return data

    def sample(self) -> dict[str, Any]:
        return {
            "total": 64 * GIB,
            "used": 21.4 * GIB,
            "available": 42.6 * GIB,
            "arc": 14.2 * GIB if self.options["zfs_arc"] is not False else None,
            "swap_total": 8 * GIB,
            "swap_used": 0.3 * GIB,
        }

    def render(self, canvas, theme, data) -> None:
        data = data or {}
        opts = self.options
        system = opts["units"]
        used, total = data.get("used"), data.get("total")
        percent = used / total * 100 if is_num(used) and is_num(total) and total > 0 else None
        color = canvas.level(percent, opts["warn"], opts["crit"])
        canvas.title(self.display_title())
        if percent is not None:
            canvas.text(
                (canvas.right, canvas.top + 4),
                f"{percent:.0f} %",
                size=40,
                color=color,
                anchor="ra",
            )

        divisor, unit = size_unit(total if is_num(total) else 0, system)
        top = canvas.top
        used_s = format_size_in(used, divisor)
        big = canvas.fit_font(used_s, 110, 460, kind="mono")
        canvas.draw.text(
            (canvas.left, top + 140), used_s, font=big, fill=canvas.color("text"), anchor="ls"
        )
        x = canvas.left + big.getlength(used_s) + 16
        rest = f"/ {format_size_in(total, divisor)} {unit}"
        canvas.text((x, top + 140), rest, size=56, anchor="ls", max_width=canvas.right - x)
        canvas.bar(canvas.left, top + 158, canvas.content_width, 40, percent, color)

        parts = []
        arc = data.get("arc")
        if is_num(arc) and opts["zfs_arc"] is not False:
            parts.append(f"{self.tr('arc')} {format_size(arc, system)}")
        swap_total = data.get("swap_total")
        if opts["swap"] and is_num(swap_total) and swap_total > 0:
            swap_div, swap_unit = size_unit(swap_total, system)
            parts.append(
                f"{self.tr('swap')} {format_size_in(data.get('swap_used'), swap_div)}"
                f" / {format_size_in(swap_total, swap_div)} {swap_unit}"
            )
        available = data.get("available")
        if is_num(available):
            parts.append(f"{self.tr('available')} {format_size(available, system)}")
        if parts:
            canvas.text(
                (canvas.left, top + 250),
                "  ·  ".join(parts),
                size=36,
                color="muted",
                anchor="ls",
                max_width=canvas.content_width,
            )
