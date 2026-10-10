"""Turns a state snapshot into frames: alert banner, the active card, page dots."""

from __future__ import annotations

import logging
from typing import Any

from PIL import Image

from .canvas import ALERT_H, DOTS_Y, HEIGHT, WIDTH, Canvas
from .cards.base import Card
from .config import Config
from .i18n import tr

log = logging.getLogger(__name__)


class Rotation:
    """Which card (and which page of it) is on screen."""

    def __init__(self, cards: list[Card]):
        if not cards:
            raise ValueError("no cards to rotate")
        self.cards = cards
        self.index = 0
        self.page = 0
        self.pages = 1

    @property
    def card(self) -> Card:
        return self.cards[self.index]

    def start(self) -> None:
        self.index = 0
        self._begin()

    def _begin(self) -> None:
        card = self.card
        try:
            self.pages = max(1, int(card.visit_pages()))
        except Exception as exc:  # a broken plugin must not stop the rotation
            log.warning("card %s: visit_pages failed: %r", card.id, exc)
            self.pages = 1
        self.page = 0
        card.set_page(0)

    def advance(self) -> None:
        if self.page + 1 < self.pages:
            self.page += 1
            self.card.set_page(self.page)
            return
        self.index = (self.index + 1) % len(self.cards)
        self._begin()


class Renderer:
    def __init__(self, config: Config):
        self.config = config
        self.cards = config.enabled_cards
        self.theme = config.theme
        self.lang = config.language
        self._logged: set[str] = set()

    def _log_once(self, key: str, message: str, *args: Any) -> None:
        if key not in self._logged:
            self._logged.add(key)
            log.error(message, *args)

    def alerts(self, snapshot: dict[str, Any]) -> list[str]:
        if not self.config.alert_banner:
            return []
        cards_data = snapshot.get("cards") or {}
        msgs: list[str] = []
        for card in self.cards:
            try:
                msgs.extend(str(m) for m in card.alerts(cards_data.get(card.id)) or [])
            except Exception as exc:
                self._log_once(f"alerts:{card.id}", "card %s: alerts() failed: %r", card.id, exc)
        return msgs

    def _canvas(self, image: Image.Image, top: int, dots: bool) -> Canvas:
        return Canvas(image, self.theme, self.lang, top=top, dots=dots)

    def _draw_alert(self, canvas: Canvas, msgs: list[str]) -> None:
        canvas.draw.rectangle((0, 0, canvas.width, ALERT_H), fill=canvas.color("crit"))
        text = "  ·  ".join(msgs)
        canvas.draw.text(
            (canvas.width // 2, ALERT_H // 2),
            text,
            font=canvas.fit_font(text, 34, canvas.content_width),
            fill=(255, 255, 255),
            anchor="mm",
        )

    def _draw_dots(self, canvas: Canvas, active: int) -> None:
        count = len(self.cards)
        if count < 2:
            return
        spacing = min(32, (canvas.width - 2 * canvas.left) / count)
        radius = max(3, min(7, spacing / 4))
        for i in range(count):
            cx = canvas.width / 2 + (i - (count - 1) / 2) * spacing
            color = canvas.color("text") if i == active else canvas.color("dim")
            canvas.draw.ellipse(
                (cx - radius, DOTS_Y - radius, cx + radius, DOTS_Y + radius), fill=color
            )

    def no_data_frame(self, reason: str) -> Image.Image:
        image = Image.new("RGB", (WIDTH, HEIGHT), self.theme.color("background"))
        canvas = self._canvas(image, ALERT_H, dots=False)
        title = tr("no_data", self.lang)
        self._draw_alert(canvas, [f"{title} ({reason})" if reason else title])
        canvas.text(
            (WIDTH // 2, 230),
            title,
            size=150,
            color="crit",
            anchor="ms",
            max_width=canvas.content_width,
        )
        if reason:
            canvas.text(
                (WIDTH // 2, 300),
                reason,
                size=40,
                color="muted",
                anchor="ms",
                max_width=canvas.content_width,
            )
        return self._finish(image)

    def frame(self, index: int, snapshot: dict[str, Any] | None, reason: str = "") -> Image.Image:
        """Full frame for card ``index`` (or the NO DATA frame when snapshot is None)."""
        if snapshot is None:
            return self.no_data_frame(reason)
        card = self.cards[index]
        image = Image.new("RGB", (WIDTH, HEIGHT), self.theme.color("background"))
        msgs = self.alerts(snapshot)
        dots = self.config.page_dots and not card.full_bleed
        canvas = self._canvas(image, ALERT_H if msgs else 0, dots)
        data = (snapshot.get("cards") or {}).get(card.id)
        try:
            card.render(canvas, self.theme, data)
        except Exception as exc:
            self._log_once(
                f"render:{card.id}:{type(exc).__name__}", "card %s: render failed: %r", card.id, exc
            )
            image.paste(self.theme.color("background"), (0, 0, WIDTH, HEIGHT))
            canvas = self._canvas(image, canvas.top, dots)
            canvas.title(card.display_title())
            canvas.message(f"{tr('card_failed', self.lang)}: {type(exc).__name__}", color="crit")
        error = (snapshot.get("errors") or {}).get(card.id)
        if error:
            canvas.text(
                (canvas.left, HEIGHT - 6),
                str(error)[:120],
                size=18,
                color="crit",
                anchor="ld",
                max_width=canvas.content_width * 0.6,
            )
        if msgs:
            self._draw_alert(canvas, msgs)
        if dots:
            self._draw_dots(canvas, index)
        return self._finish(image)

    def _finish(self, image: Image.Image) -> Image.Image:
        size = (self.config.display.width, self.config.display.height)
        if image.size != size:
            image = image.resize(size, Image.Resampling.LANCZOS)
        return image
