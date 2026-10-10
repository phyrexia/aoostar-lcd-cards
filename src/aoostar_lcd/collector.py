"""Runs ``collect()`` on every enabled card and builds the state snapshot."""

from __future__ import annotations

import json
import logging
import socket
import time
from collections.abc import Callable
from typing import Any

from .cards.base import Card
from .state import STATE_VERSION, write_atomic

log = logging.getLogger(__name__)
HISTORY_SAVE_S = 60


class Collector:
    def __init__(
        self,
        cards: list[Card],
        history_file: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cards = [c for c in cards if c.enabled]
        self.history_file = history_file
        self.clock = clock
        self.last: dict[str, tuple[float, Any]] = {}
        self.errors: dict[str, str] = {}
        self._saved_at: float | None = None
        self._logged: dict[str, str] = {}
        self.load_history()

    def _log_error(self, card_id: str, message: str) -> None:
        # Log a failing card once per distinct message, not on every tick.
        if self._logged.get(card_id) != message:
            self._logged[card_id] = message
            log.error("card %s: collect failed: %s", card_id, message)

    def tick(self) -> dict[str, Any]:
        now = self.clock()
        for card in self.cards:
            last = self.last.get(card.id)
            if last is not None and now - last[0] < card.collect_every:
                continue
            try:
                data = card.collect()
                json.dumps(data)  # must survive the trip through the state file
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[:200]
                self.errors[card.id] = message
                self._log_error(card.id, message)
                # Keep the last good data; retry at the next refresh.
                self.last[card.id] = (now, last[1] if last else None)
                continue
            self.errors.pop(card.id, None)
            self._logged.pop(card.id, None)
            self.last[card.id] = (now, data)
        self.save_history_if_due(now)
        try:
            host = socket.gethostname()
        except OSError:
            host = None
        return {
            "version": STATE_VERSION,
            "ts": now,
            "host": host,
            "cards": {cid: data for cid, (_, data) in self.last.items() if data is not None},
            "errors": dict(self.errors),
        }

    def warm_up(self, seconds: float = 1.0) -> dict[str, Any]:
        """Two ticks a moment apart, so rate-based values (CPU %, network) exist."""
        self.tick()
        time.sleep(seconds)
        return self.tick()  # cards with refresh 0 collect again; slower ones keep their data

    # -- history persistence -------------------------------------------------------

    def load_history(self) -> None:
        if not self.history_file:
            return
        try:
            with open(self.history_file, encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("history file %s unreadable, starting empty: %r", self.history_file, exc)
            return
        states = raw.get("cards") if isinstance(raw, dict) else None
        if not isinstance(states, dict):
            return
        for card in self.cards:
            if card.id in states:
                try:
                    card.restore(states[card.id])
                except Exception as exc:
                    log.warning("card %s: cannot restore history: %r", card.id, exc)

    def save_history(self) -> None:
        if not self.history_file:
            return
        states = {}
        for card in self.cards:
            try:
                state = card.state()
            except Exception as exc:
                log.warning("card %s: state() failed: %r", card.id, exc)
                continue
            if state is not None:
                states[card.id] = state
        write_atomic(self.history_file, {"version": 1, "cards": states}, mode=0o600)
        self._saved_at = self.clock()

    def save_history_if_due(self, now: float) -> None:
        if self.history_file and (self._saved_at is None or now - self._saved_at >= HISTORY_SAVE_S):
            try:
                self.save_history()
            except OSError as exc:
                log.error("cannot save history to %s: %r", self.history_file, exc)
                self._saved_at = now
