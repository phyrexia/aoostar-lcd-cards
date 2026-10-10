"""Custom card: show what a command prints or what a JSON file contains.

The collector runs ``command`` (no shell; a list or a string split like a shell
would) or reads ``file`` every ``refresh`` seconds. The output can be:

* **JSON** with any of these keys::

      {"title": "Backups", "value": "OK", "unit": "", "label": "last run 03:10",
       "percent": 64, "status": "ok", "lines": ["12 snapshots", "next 03:10"],
       "rows": [{"label": "Queue", "value": 3, "status": "warn"}]}

  ``status`` is ok, warn or crit and colors the value. With ``fields`` in the YAML,
  any JSON document works: each field picks a value by dotted path (``a.b.0.c``).
* **Plain text**: the first line is the big value, up to three more lines below.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from typing import Any

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

MAX_ROWS = 4
MAX_LINES = 3
STATUSES = ("ok", "warn", "crit")
FIELD_KEYS = ("label", "key", "unit", "decimals", "warn", "crit")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean(value: Any, limit: int = 80) -> str:
    """Printable, single-line, length-limited text from untrusted output."""
    if is_num(value):
        text = f"{value:g}" if isinstance(value, float) else str(value)
    else:
        text = str(value)
    return _CONTROL.sub(" ", text).strip()[:limit]


def dig(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


class CustomCard(Card):
    type_name = "custom"
    title_key = None
    refresh = 30.0
    defaults = {
        "command": None,  # ["/usr/local/bin/backup-status", "--json"] or a string
        "file": None,  # path to a JSON or text file
        "format": "auto",  # auto | json | text
        "timeout": 10,
        "fields": None,  # [{label, key, unit, decimals, warn, crit}]
        "max_bytes": 65536,
    }

    def configure(self, options: dict[str, Any]) -> None:
        where = self.where
        has_cmd, has_file = options["command"] is not None, options["file"] is not None
        if has_cmd == has_file:
            raise ConfigError(f"{where}: set exactly one of command or file")
        if has_cmd:
            command = options["command"]
            if isinstance(command, str):
                try:
                    command = shlex.split(command)
                except ValueError as exc:
                    raise ConfigError(f"{where}.command: {exc}") from None
            options["command"] = as_str_list(command, f"{where}.command")
            if not options["command"]:
                raise ConfigError(f"{where}.command: must not be empty")
        else:
            options["file"] = str(self.resolve_path(as_str(options["file"], f"{where}.file")))
        as_choice(options["format"], f"{where}.format", ("auto", "json", "text"))
        options["timeout"] = as_float(options["timeout"], f"{where}.timeout", 1, 300)
        options["max_bytes"] = as_int(options["max_bytes"], f"{where}.max_bytes", 64, 10**7)
        fields = options["fields"]
        if fields is not None:
            if not isinstance(fields, list) or not fields:
                raise ConfigError(f"{where}.fields: must be a non-empty list")
            if len(fields) > MAX_ROWS:
                raise ConfigError(f"{where}.fields: at most {MAX_ROWS} fields")
            parsed = []
            for i, raw in enumerate(fields):
                w = f"{where}.fields[{i}]"
                entry = as_mapping(raw, w)
                check_keys(w, entry, FIELD_KEYS)
                if "key" not in entry:
                    raise ConfigError(f"{w}: 'key' is required (dotted path into the JSON)")
                parsed.append(
                    {
                        "label": as_str(entry.get("label", entry["key"]), f"{w}.label"),
                        "key": as_str(entry["key"], f"{w}.key"),
                        "unit": as_str(entry.get("unit", ""), f"{w}.unit", allow_empty=True),
                        "decimals": as_int(entry.get("decimals", 1), f"{w}.decimals", 0, 6),
                        "warn": None
                        if entry.get("warn") is None
                        else as_float(entry["warn"], f"{w}.warn"),
                        "crit": None
                        if entry.get("crit") is None
                        else as_float(entry["crit"], f"{w}.crit"),
                    }
                )
            options["fields"] = parsed

    # -- collector -----------------------------------------------------------------

    def _read_raw(self) -> str:
        limit = self.options["max_bytes"]
        if self.options["command"]:
            result = subprocess.run(
                self.options["command"],
                capture_output=True,
                timeout=self.options["timeout"],
                check=False,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", "replace").strip()[-200:]
                raise RuntimeError(f"command exited with {result.returncode}: {err}")
            return result.stdout[:limit].decode("utf-8", "replace")
        with open(self.options["file"], "rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")

    def collect(self) -> dict[str, Any]:
        return self.parse(self._read_raw())

    def parse(self, raw: str) -> dict[str, Any]:
        fmt = self.options["format"]
        doc: Any = None
        if fmt in ("auto", "json"):
            try:
                doc = json.loads(raw)
            except ValueError:
                if fmt == "json":
                    raise ValueError("output is not valid JSON") from None
        if doc is None and fmt != "json":
            lines = [clean(line) for line in raw.splitlines() if line.strip()]
            return {"value": lines[0] if lines else "-", "lines": lines[1 : 1 + MAX_LINES]}
        if self.options["fields"]:
            return {
                "rows": [self._field_row(f, dig(doc, f["key"])) for f in self.options["fields"]]
            }
        if not isinstance(doc, dict):
            return {"value": clean(doc)}
        out: dict[str, Any] = {}
        for key in ("title", "value", "unit", "label"):
            if doc.get(key) is not None:
                out[key] = clean(doc[key], 60)
        if is_num(doc.get("percent")):
            out["percent"] = max(0.0, min(100.0, float(doc["percent"])))
        if doc.get("status") in STATUSES:
            out["status"] = doc["status"]
        if isinstance(doc.get("lines"), list):
            out["lines"] = [clean(line) for line in doc["lines"][:MAX_LINES]]
        if isinstance(doc.get("rows"), list):
            rows = []
            for row in doc["rows"][:MAX_ROWS]:
                if isinstance(row, dict):
                    rows.append(
                        {
                            "label": clean(row.get("label", ""), 40),
                            "value": clean(row.get("value", "-"), 40),
                            "status": row.get("status") if row.get("status") in STATUSES else None,
                        }
                    )
            out["rows"] = rows
        return out

    @staticmethod
    def _field_row(field: dict[str, Any], value: Any) -> dict[str, Any]:
        status = None
        if is_num(value):
            text = f"{value:.{field['decimals']}f}"
            if field["crit"] is not None and value >= field["crit"]:
                status = "crit"
            elif field["warn"] is not None and value >= field["warn"]:
                status = "warn"
            else:
                status = "ok" if field["warn"] is not None or field["crit"] is not None else None
        else:
            text = "-" if value is None else clean(value, 40)
        if field["unit"] and text != "-":
            text = f"{text} {field['unit']}"
        return {"label": field["label"], "value": text, "status": status}

    # -- renderer ------------------------------------------------------------------

    def sample(self) -> dict[str, Any]:
        if self.options["fields"]:
            values = [87, 23, "online", 41.5]
            return {
                "rows": [
                    self._field_row(f, values[i % len(values)])
                    for i, f in enumerate(self.options["fields"])
                ]
            }
        return {
            "title": "BACKUPS",
            "value": "OK",
            "label": "last run 03:10 · 12 snapshots",
            "percent": 64,
            "status": "ok",
            "lines": ["repository 64 % full"],
        }

    def render(self, canvas, theme, data) -> None:
        data = data or {}
        title = self.title or data.get("title") or "CUSTOM"
        canvas.title(str(title)[:40])
        rows = [r for r in data.get("rows") or [] if isinstance(r, dict)][:MAX_ROWS]
        if rows:
            self._render_rows(canvas, rows)
            return
        if data.get("value") is None and not data.get("lines"):
            canvas.message(self.tr("no_data_card"))
            return
        top = canvas.top
        status = data.get("status")
        color = status if status in STATUSES else "text"
        value = clean(data.get("value", "-"), 30)
        font = canvas.fit_font(value, 110, canvas.content_width * 0.75, kind="mono")
        canvas.draw.text(
            (canvas.left, top + 150), value, font=font, fill=canvas.color(color), anchor="ls"
        )
        unit = data.get("unit")
        if unit:
            x = canvas.left + font.getlength(value) + 14
            canvas.text(
                (x, top + 150),
                clean(unit, 20),
                size=56,
                anchor="ls",
                max_width=max(10, canvas.right - x),
            )
        y = top + 172
        percent = data.get("percent")
        if is_num(percent):
            canvas.bar(
                canvas.left,
                y,
                canvas.content_width,
                30,
                percent,
                color if color != "text" else "ok",
            )
            y += 46
        if data.get("label"):
            canvas.text(
                (canvas.left, y + 30),
                clean(data["label"]),
                size=34,
                color="muted",
                anchor="ls",
                max_width=canvas.content_width,
            )
            y += 44
        for line in (data.get("lines") or [])[:MAX_LINES]:
            if y + 28 > canvas.bottom:
                break
            canvas.text(
                (canvas.left, y + 28),
                clean(line),
                size=28,
                color="muted",
                anchor="ls",
                max_width=canvas.content_width,
            )
            y += 36

    def _render_rows(self, canvas, rows) -> None:
        area_top = canvas.top + 64
        row_h = (canvas.bottom - area_top) / len(rows)
        size = max(28, min(56, int(row_h * 0.6)))
        for i, row in enumerate(rows):
            baseline = area_top + i * row_h + row_h * 0.7
            canvas.text(
                (canvas.left, baseline),
                clean(row.get("label", ""), 40),
                size=size - 10,
                color="muted",
                anchor="ls",
                max_width=canvas.content_width * 0.5,
            )
            status = row.get("status")
            canvas.text(
                (canvas.right, baseline),
                clean(row.get("value", "-"), 40),
                size=size,
                color=status if status in STATUSES else "text",
                kind="mono",
                anchor="rs",
                max_width=canvas.content_width * 0.48,
            )
