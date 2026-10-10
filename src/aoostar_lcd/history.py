"""Fixed time window of buckets used by the CPU and network histograms.

Each bucket covers ``step`` seconds and accumulates, per series, an amount,
the seconds actually measured and the highest instantaneous value seen.
The published average is ``amount / seconds``, so a bucket that was only
partly measured (start-up, gaps) is not under-reported.
"""

from __future__ import annotations

import math
from typing import Any


def _valid(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


class BucketHistory:
    def __init__(self, step: int = 300, slots: int = 36):
        if step <= 0 or slots <= 0:
            raise ValueError("step and slots must be positive")
        self.step = int(step)
        self.slots = int(slots)
        # bucket index -> series name -> [amount, seconds, peak]
        self.buckets: dict[int, dict[str, list[float]]] = {}

    def index(self, ts: float) -> int:
        return int(ts // self.step)

    def add(
        self, ts: float, series: str, amount: float, seconds: float, peak: float | None = None
    ) -> None:
        """Add ``amount`` measured over ``seconds`` to the bucket that contains ``ts``."""
        if not (_valid(amount) and _valid(seconds)) or seconds <= 0:
            return
        idx = self.index(ts)
        slot = self.buckets.setdefault(idx, {}).setdefault(series, [0.0, 0.0, 0.0])
        slot[0] += amount
        slot[1] += seconds
        if peak is not None and _valid(peak):
            slot[2] = max(slot[2], peak)
        self.prune(idx)

    def prune(self, now_idx: int) -> None:
        """Keep only the window (now_idx - slots, now_idx]."""
        for idx in [i for i in self.buckets if i > now_idx or i <= now_idx - self.slots]:
            del self.buckets[idx]

    def names(self) -> list[str]:
        return sorted({name for bucket in self.buckets.values() for name in bucket})

    def window(self, ts: float, series: str) -> tuple[list[float | None], list[float | None]]:
        """(averages, peaks), oldest first; None where the bucket was not measured."""
        now_idx = self.index(ts)
        self.prune(now_idx)
        avg: list[float | None] = []
        peak: list[float | None] = []
        for idx in range(now_idx - self.slots + 1, now_idx + 1):
            slot = self.buckets.get(idx, {}).get(series)
            if slot and slot[1] > 0:
                avg.append(round(slot[0] / slot[1], 3))
                peak.append(round(slot[2], 3))
            else:
                avg.append(None)
                peak.append(None)
        return avg, peak

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "slots": self.slots,
            "buckets": {str(i): b for i, b in self.buckets.items()},
        }

    def load_dict(self, raw: Any, now: float) -> int:
        """Load a saved window; skips anything malformed. Returns buckets kept."""
        if not isinstance(raw, dict) or raw.get("step") != self.step:
            return 0
        loaded: dict[int, dict[str, list[float]]] = {}
        buckets = raw.get("buckets")
        if not isinstance(buckets, dict):
            return 0
        for key, series in buckets.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            if not isinstance(series, dict):
                continue
            for name, slot in series.items():
                if isinstance(slot, list) and len(slot) == 3 and all(_valid(v) for v in slot):
                    loaded.setdefault(idx, {})[str(name)] = [float(v) for v in slot]
        self.buckets = loaded
        self.prune(self.index(now))
        return len(self.buckets)
