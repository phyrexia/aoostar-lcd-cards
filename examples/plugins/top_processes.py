"""Example plugin: the processes using the most CPU (or memory) right now.

- type: plugin
  plugin: examples/plugins/top_processes.py:TopProcessesCard
  count: 4          # 1-5 rows
  sort: cpu         # cpu | memory
"""

from __future__ import annotations

import psutil

from aoostar_lcd import Card
from aoostar_lcd.units import format_size
from aoostar_lcd.validate import as_choice, as_int


class TopProcessesCard(Card):
    type_name = "top-processes"
    defaults = {"count": 4, "sort": "cpu", "warn": 50, "crit": 90}

    def configure(self, options):
        # Validate with the helpers so mistakes point at the right YAML line.
        options["count"] = as_int(options["count"], f"{self.where}.count", 1, 5)
        as_choice(options["sort"], f"{self.where}.sort", ("cpu", "memory"))
        self._procs: dict[int, psutil.Process] = {}

    def display_title(self):
        return self.title or ("TOP CPU" if self.options["sort"] == "cpu" else "TOP MEMORY")

    def collect(self):
        rows = []
        seen = set()
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            pid = proc.info["pid"]
            seen.add(pid)
            # Keep the Process object: cpu_percent() measures since its previous call.
            cached = self._procs.setdefault(pid, proc)
            try:
                cpu = cached.cpu_percent(None)
                rss = proc.info["memory_info"].rss if proc.info["memory_info"] else 0
            except psutil.Error:
                continue
            rows.append({"name": (proc.info["name"] or "?")[:32], "cpu": round(cpu, 1), "rss": rss})
        for pid in list(self._procs):
            if pid not in seen:
                del self._procs[pid]
        key = "cpu" if self.options["sort"] == "cpu" else "rss"
        rows.sort(key=lambda r: r[key], reverse=True)
        return {"processes": rows[: self.options["count"]]}

    def sample(self):
        names = [
            ("postgres", 41.5, 2.1e9),
            ("python3", 23.0, 4.8e8),
            ("smbd", 12.4, 9.6e7),
            ("node", 6.8, 3.3e8),
            ("sshd", 0.4, 1.1e7),
        ]
        rows = [{"name": n, "cpu": c, "rss": m} for n, c, m in names]
        return {"processes": rows[: self.options["count"]]}

    def render(self, canvas, theme, data):
        canvas.title(self.display_title())
        rows = (data or {}).get("processes") or []
        if not rows:
            canvas.message("No data yet")
            return
        area_top = canvas.top + 64
        row_h = (canvas.bottom - area_top) / len(rows)
        size = int(min(48, row_h * 0.62))
        for i, row in enumerate(rows):
            y = area_top + i * row_h + row_h * 0.72
            canvas.text(
                (canvas.left, y),
                str(row.get("name", "?")),
                size=size,
                anchor="ls",
                max_width=canvas.content_width * 0.5,
            )
            cpu = row.get("cpu")
            canvas.text(
                (canvas.right - 260, y),
                f"{cpu:.0f} %" if cpu is not None else "-",
                size=size,
                kind="mono",
                anchor="rs",
                color=canvas.level(cpu, self.options["warn"], self.options["crit"]),
            )
            canvas.text(
                (canvas.right, y),
                format_size(row.get("rss"), "iec"),
                size=size - 8,
                color="muted",
                anchor="rs",
                max_width=230,
            )
