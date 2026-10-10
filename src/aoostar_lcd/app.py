"""Long-running loops (collector, display, both) and the PNG preview."""

from __future__ import annotations

import hashlib
import logging
import math
import signal
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import Collector
from .config import Config
from .state import STATE_VERSION, read_state, write_atomic

log = logging.getLogger(__name__)

SnapshotSource = Callable[[], tuple[dict[str, Any] | None, str]]


def _exit_on_sigterm() -> None:
    # SystemExit unwinds through the finally blocks below (history is saved).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def run_collector(config: Config, once: bool = False, state_file: str | None = None) -> int:
    """Collector process: tick every ``collector.interval`` seconds and write the state file."""
    path = state_file or config.collector.state_file
    collector = Collector(config.cards, config.collector.history_file)
    _exit_on_sigterm()
    try:
        if once:
            write_atomic(path, collector.warm_up())
            return 0
        log.info(
            "collector: %d cards, writing %s every %g s",
            len(collector.cards),
            path,
            config.collector.interval,
        )
        while True:
            started = time.monotonic()
            try:
                write_atomic(path, collector.tick())
            except OSError as exc:
                log.error("cannot write %s: %r", path, exc)
            time.sleep(max(0.1, config.collector.interval - (time.monotonic() - started)))
    finally:
        try:
            collector.save_history()
        except OSError as exc:
            log.error("cannot save history: %r", exc)


def run_display(
    config: Config,
    sink,
    source: SnapshotSource | None = None,
    collector: Collector | None = None,
    max_frames: int | None = None,
    state_out: str | None = None,
) -> int:
    """Rotate the cards, render a frame every ``frame_interval`` and send it if it changed.

    With ``collector`` everything runs in this process (no state file needed);
    otherwise ``source`` returns the snapshot written by a separate collector.
    """
    from .renderer import Renderer, Rotation

    if (source is None) == (collector is None):
        raise ValueError("pass exactly one of source or collector")
    latest = collector.warm_up() if collector is not None else None

    renderer = Renderer(config)
    rotation = Rotation(renderer.cards)
    rotation.start()
    interval = config.collector.interval
    frame_interval = config.display.frame_interval
    last_digest = None
    frames = 0
    now = time.monotonic()
    card_until = now + rotation.card.duration
    next_frame = now
    next_collect = now + interval
    _exit_on_sigterm()
    try:
        while max_frames is None or frames < max_frames:
            now = time.monotonic()
            if collector is not None and now >= next_collect:
                latest = collector.tick()
                if state_out:
                    try:
                        write_atomic(state_out, latest)
                    except OSError as exc:
                        log.error("cannot write %s: %r", state_out, exc)
                next_collect = now + interval
            if now >= card_until:
                rotation.advance()
                card_until = now + rotation.card.duration
                next_frame = now
            if now >= next_frame:
                try:
                    if collector is not None:
                        snapshot, reason = latest, ""
                    else:
                        snapshot, reason = source()
                    image = renderer.frame(rotation.index, snapshot, reason)
                    digest = hashlib.sha256(image.tobytes()).hexdigest()
                    if digest != last_digest and sink.show(image):
                        last_digest = digest
                except Exception as exc:  # the loop must survive anything a card does
                    log.exception("render cycle failed: %r", exc)
                frames += 1
                next_frame = min(now + frame_interval, card_until)
            wake = min(card_until, next_frame, next_collect if collector else math.inf)
            time.sleep(max(0.05, wake - time.monotonic()))
    finally:
        sink.close()
        if collector is not None:
            try:
                collector.save_history()
            except OSError as exc:
                log.error("cannot save history: %r", exc)
    return 0


def file_source(path: str, max_age: float) -> SnapshotSource:
    return lambda: read_state(path, time.time(), max_age)


def sample_snapshot(config: Config) -> dict[str, Any]:
    cards = {}
    for card in config.enabled_cards:
        data = card.sample()
        if data is not None:
            cards[card.id] = data
    return {
        "version": STATE_VERSION,
        "ts": time.time(),
        "host": "my-nas",
        "cards": cards,
        "errors": {},
    }


def preview(
    config: Config,
    out_dir: str | None = None,
    png: str | None = None,
    card_id: str | None = None,
    source: str = "sample",
    state_path: str | None = None,
    at: datetime | None = None,
    no_data: bool = False,
) -> list[Path]:
    """Render cards to PNG files without touching any hardware."""
    from .renderer import Renderer

    cards = config.enabled_cards
    if card_id is not None and card_id not in [c.id for c in cards]:
        raise ValueError(
            f"no enabled card with id {card_id!r}; ids: {', '.join(c.id for c in cards)}"
        )
    if at is not None:
        for card in cards:
            if hasattr(card, "now"):
                card.now = at
    if source == "live":
        snapshot = Collector(cards).warm_up()
    elif source == "state":
        snapshot, reason = read_state(
            state_path or config.collector.state_file, time.time(), math.inf
        )
        if snapshot is None:
            raise ValueError(f"cannot read state: {reason}")
    else:
        snapshot = sample_snapshot(config)
    renderer = Renderer(config)
    written: list[Path] = []
    for index, card in enumerate(cards):
        if card_id is not None and card.id != card_id:
            continue
        card.visit_pages()
        card.set_page(0)
        image = renderer.frame(index, snapshot)
        target = Path(png) if png else Path(out_dir or ".") / f"{index + 1:02d}-{card.id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG")
        written.append(target)
        if png:
            break
    if no_data and not png:
        target = Path(out_dir or ".") / "no-data.png"
        renderer.frame(0, None, "state is 95 s old").save(target, format="PNG")
        written.append(target)
    return written
