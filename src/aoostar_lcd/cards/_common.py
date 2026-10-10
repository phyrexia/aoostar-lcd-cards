"""Option checks shared by the built-in cards (no Pillow imports here)."""

from __future__ import annotations

import math
from typing import Any

from ..history import BucketHistory
from ..validate import ConfigError, as_float, as_int

MAX_GAP_S = 120  # samples further apart than this are not attributed to any bucket


def history_options(card, options: dict[str, Any]) -> BucketHistory | None:
    """Validate history_minutes / bucket_seconds and build the history window."""
    minutes = as_int(options["history_minutes"], f"{card.where}.history_minutes", 0, 24 * 60)
    step = as_int(options["bucket_seconds"], f"{card.where}.bucket_seconds", 10, 3600)
    options["history_minutes"], options["bucket_seconds"] = minutes, step
    if minutes == 0:
        return None
    slots = minutes * 60 / step
    if slots != int(slots) or not 4 <= slots <= 240:
        raise ConfigError(
            f"{card.where}: history_minutes x 60 / bucket_seconds must be a whole number "
            f"between 4 and 240 (got {slots:g} bars)"
        )
    return BucketHistory(step, int(slots))


def thresholds(card, options: dict[str, Any], warn_key="warn", crit_key="crit", maximum=None):
    warn = options.get(warn_key)
    crit = options.get(crit_key)
    if warn is not None:
        warn = as_float(warn, f"{card.where}.{warn_key}", 0, maximum)
    if crit is not None:
        crit = as_float(crit, f"{card.where}.{crit_key}", 0, maximum)
    if warn is not None and crit is not None and warn > crit:
        raise ConfigError(f"{card.where}: {warn_key} ({warn:g}) must be <= {crit_key} ({crit:g})")
    options[warn_key], options[crit_key] = warn, crit
    return warn, crit


def wave(i: int, base: float, amplitude: float, period: float, phase: float = 0.0) -> float:
    """Deterministic smooth value for synthetic preview data."""
    return base + amplitude * (1 + math.sin((i + phase) * 2 * math.pi / period)) / 2


def is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def right_aligned(container: Any, key: str, slots: int) -> list[float | None]:
    """``container[key]`` as exactly ``slots`` non-negative numbers, newest last.

    Shorter lists are padded on the left; anything that is not a non-negative
    number becomes None, so garbage in the state file never breaks a chart.
    """
    out: list[float | None] = [None] * slots
    values = container.get(key) if isinstance(container, dict) else None
    if not isinstance(values, list):
        return out
    values = values[-slots:]
    offset = slots - len(values)
    for i, value in enumerate(values):
        if is_num(value) and value >= 0:
            out[offset + i] = float(value)
    return out
