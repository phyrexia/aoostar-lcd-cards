"""The JSON state file that decouples the collector from the renderer."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def write_atomic(path: str | os.PathLike, data: Any, mode: int = 0o644) -> None:
    """Write JSON to ``path`` through a temporary file and ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_state(path: str | os.PathLike, now: float, max_age: float) -> tuple[dict | None, str]:
    """(snapshot, reason). The snapshot is None when missing, invalid or older than max_age."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None, "no state file"
    except (OSError, ValueError):
        return None, "invalid state file"
    ts = data.get("ts") if isinstance(data, dict) else None
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None, "invalid state file"
    if data.get("version") not in (None, STATE_VERSION):
        return None, f"unsupported state version {data.get('version')!r}"
    age = now - ts
    if age > max_age:
        return None, f"state is {int(age)} s old"
    if not isinstance(data.get("cards"), dict):
        data["cards"] = {}
    return data, ""
