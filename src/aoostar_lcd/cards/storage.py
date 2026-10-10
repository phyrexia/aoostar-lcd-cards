"""Storage card: free/used space of mount points and ZFS pools (health included).

One volume gets a large layout; two to four volumes are drawn as rows. A ZFS pool
whose health is not ONLINE raises the red alert banner on every card.
"""

from __future__ import annotations

from typing import Any

from ..units import SIZE_SYSTEMS, format_size, format_size_in, size_unit
from ..validate import ConfigError, as_choice, as_mapping, as_str, check_keys
from ._common import is_num, thresholds
from .base import Card

MAX_VOLUMES = 4
TB = 10**12


class StorageCard(Card):
    type_name = "storage"
    title_key = "storage"
    refresh = 30.0
    defaults = {
        "volumes": [{"mount": "/"}],  # entries: {mount: /path} or {zfs: pool}, optional label
        "units": "si",  # si = TB (how disks are sold), iec = TiB
        "warn": 80,  # percent used
        "crit": 90,
        "big": "free",  # free | used: the large number in the one-volume layout
    }

    def configure(self, options: dict[str, Any]) -> None:
        where = self.where
        as_choice(options["units"], f"{where}.units", SIZE_SYSTEMS)
        as_choice(options["big"], f"{where}.big", ("free", "used"))
        thresholds(self, options, maximum=100)
        volumes = options["volumes"]
        if not isinstance(volumes, list) or not volumes:
            raise ConfigError(f"{where}.volumes: must be a non-empty list")
        if len(volumes) > MAX_VOLUMES:
            raise ConfigError(
                f"{where}.volumes: at most {MAX_VOLUMES} per card "
                "(add another storage card for more)"
            )
        parsed = []
        for i, raw in enumerate(volumes):
            w = f"{where}.volumes[{i}]"
            entry = as_mapping(raw, w)
            check_keys(w, entry, ("mount", "zfs", "label"))
            kinds = [k for k in ("mount", "zfs") if k in entry]
            if len(kinds) != 1:
                raise ConfigError(f"{w}: set exactly one of mount or zfs")
            kind = kinds[0]
            target = as_str(entry[kind], f"{w}.{kind}")
            label = as_str(entry.get("label", target), f"{w}.label")
            parsed.append({"kind": kind, "target": target, "label": label})
        self.volumes = parsed

    # -- collector -----------------------------------------------------------------

    def collect(self) -> dict[str, Any]:
        from .. import sources

        out = []
        for vol in self.volumes:
            item: dict[str, Any] = {"label": vol["label"], "kind": vol["kind"]}
            try:
                if vol["kind"] == "zfs":
                    item.update(sources.zfs_pool(vol["target"]))
                else:
                    item.update(sources.mount_usage(vol["target"]))
            except FileNotFoundError:
                item["error"] = "zfs tools not found" if vol["kind"] == "zfs" else "not found"
            except Exception as exc:  # report and keep the other volumes
                item["error"] = f"{type(exc).__name__}"
            out.append(item)
        return {"volumes": out}

    def alerts(self, data):
        msgs = []
        for vol in (data or {}).get("volumes") or []:
            if not isinstance(vol, dict):
                continue
            health = vol.get("health")
            if isinstance(health, str) and health != "ONLINE":
                msgs.append(f"POOL {vol.get('label', '?')}: {health}")
        return msgs

    # -- renderer ------------------------------------------------------------------

    def sample(self) -> dict[str, Any]:
        examples = [
            (9.1 * TB, 5.2 * TB),
            (0.12 * TB, 0.78 * TB),
            (2.9 * TB, 1.1 * TB),
            (0.4 * TB, 3.6 * TB),
        ]
        out = []
        for i, vol in enumerate(self.volumes):
            used, free = examples[i % len(examples)]
            out.append(
                {
                    "label": vol["label"],
                    "kind": vol["kind"],
                    "used": used,
                    "free": free,
                    "total": used + free,
                    "health": "ONLINE" if vol["kind"] == "zfs" else None,
                }
            )
        return {"volumes": out}

    def render(self, canvas, theme, data) -> None:
        volumes = [v for v in (data or {}).get("volumes") or [] if isinstance(v, dict)]
        volumes = volumes[:MAX_VOLUMES]
        if len(volumes) == 1:
            self._render_big(canvas, volumes[0])
            return
        canvas.title(self.display_title())
        if not volumes:
            canvas.message(self.tr("no_data_card"))
            return
        self._render_rows(canvas, volumes)

    def _numbers(self, vol):
        used, free = vol.get("used"), vol.get("free")
        if not (is_num(used) and is_num(free)) or used + free <= 0:
            return None, None, None
        return used, free, used / (used + free) * 100

    def _health(self, canvas, vol, xy, size, anchor):
        health = vol.get("health")
        if vol.get("error"):
            canvas.text(
                xy, str(vol["error"])[:40], size=size, color="crit", anchor=anchor, max_width=320
            )
        elif isinstance(health, str):
            canvas.text(
                xy,
                health[:20],
                size=size,
                color="ok" if health == "ONLINE" else "crit",
                anchor=anchor,
                max_width=320,
            )

    def _render_big(self, canvas, vol) -> None:
        opts = self.options
        system = opts["units"]
        used, free, percent = self._numbers(vol)
        top = canvas.top
        canvas.title(f"{self.display_title()} · {vol.get('label', '?')}")
        self._health(canvas, vol, (canvas.right, top + 4), 40, "ra")
        big_value, other_value = (free, used) if opts["big"] == "free" else (used, free)
        big_word = self.tr(opts["big"])
        other_word = self.tr("used" if opts["big"] == "free" else "free")
        divisor, unit = size_unit(max(used or 0, free or 0), system)
        big_s = format_size_in(big_value, divisor)
        font = canvas.fit_font(big_s, 110, 420, kind="mono")
        canvas.draw.text(
            (canvas.left, top + 140), big_s, font=font, fill=canvas.color("text"), anchor="ls"
        )
        x = canvas.left + font.getlength(big_s) + 14
        unit_s = f" {unit} {big_word}"
        x_end = x + canvas.text(
            (x, top + 140), unit_s, size=56, anchor="ls", max_width=canvas.right - x
        )
        right = f"{other_word} {format_size(other_value, system)}"
        canvas.text(
            (canvas.right, top + 140),
            right,
            size=40,
            color="muted",
            anchor="rs",
            max_width=max(10, canvas.right - x_end - 24),
        )
        color = canvas.level(percent, opts["warn"], opts["crit"])
        canvas.bar(canvas.left, top + 158, canvas.content_width, 44, percent, color)
        if percent is not None:
            canvas.text(
                (canvas.width // 2, top + 180),
                f"{percent:.0f} %",
                size=32,
                color="background" if percent >= 55 else "text",
                anchor="mm",
            )
        total = vol.get("total")
        if is_num(total):
            canvas.text(
                (canvas.left, top + 260),
                f"{format_size(total, system)} {self.tr('total')}",
                size=36,
                color="muted",
                anchor="ls",
            )

    def _render_rows(self, canvas, volumes) -> None:
        opts = self.options
        system = opts["units"]
        area_top = canvas.top + 60
        row_h = (canvas.bottom - area_top) / len(volumes)
        bar_h = max(14, min(34, int(row_h * 0.32)))
        text_size = max(20, min(34, int(row_h * 0.36)))
        health_room = 200 if any(v.get("health") or v.get("error") for v in volumes) else 0
        for i, vol in enumerate(volumes):
            y = area_top + i * row_h
            used, free, percent = self._numbers(vol)
            canvas.text(
                (canvas.left, y + text_size),
                str(vol.get("label", "?"))[:40],
                size=text_size,
                anchor="ls",
                max_width=canvas.content_width * 0.35,
            )
            if percent is not None:
                total = used + free
                summary = (
                    f"{format_size(free, system)} {self.tr('free')} "
                    f"{self.tr('of')} {format_size(total, system)}  ·  {percent:.0f} %"
                )
            else:
                summary = ""
            if summary:
                canvas.text(
                    (canvas.right - health_room, y + text_size),
                    summary,
                    size=text_size - 4,
                    color="muted",
                    anchor="rs",
                    max_width=canvas.content_width * 0.62 - health_room,
                )
            self._health(canvas, vol, (canvas.right, y + text_size), text_size - 4, "rs")
            canvas.bar(
                canvas.left,
                y + text_size + 10,
                canvas.content_width,
                bar_h,
                percent,
                canvas.level(percent, opts["warn"], opts["crit"]),
            )
