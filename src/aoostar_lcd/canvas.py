"""Drawing helpers handed to ``Card.render``. Wraps a Pillow image of 960x376."""

from __future__ import annotations

import logging
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .i18n import tr
from .theme import RGB, Theme

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 960, 376  # logical design size of the AOOSTAR panel
MARGIN_X = 32
ALERT_H = 48
DOTS_Y = 356

_warned_fonts: set[str] = set()


@lru_cache(maxsize=256)
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """TrueType font at ``size`` px; Pillow's built-in font if the file cannot be read."""
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        if path not in _warned_fonts:
            _warned_fonts.add(path)
            log.warning("font %s not readable; using Pillow's fallback font", path)
        return ImageFont.load_default(size=size)


class Canvas:
    """A frame being drawn, plus the theme and layout box of the card.

    Coordinates are pixels on a 960x376 image. ``left``/``right``/``top``/``bottom``
    delimit the area a card should use: ``top`` moves down when an alert banner is
    shown and ``bottom`` leaves room for the page dots.
    """

    def __init__(
        self, image: Image.Image, theme: Theme, lang: str = "en", top: int = 0, dots: bool = True
    ) -> None:
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.theme = theme
        self.lang = lang
        self.width, self.height = image.size
        self.left = MARGIN_X
        self.right = self.width - MARGIN_X
        self.top = top
        self.bottom = DOTS_Y - 16 if dots else self.height - 12

    @property
    def content_width(self) -> int:
        return self.right - self.left

    def color(self, color: str | RGB) -> RGB:
        return self.theme.color(color)

    def tr(self, key: str) -> str:
        return tr(key, self.lang)

    # -- text ------------------------------------------------------------------------

    def font(self, size: int, kind: str = "sans"):
        path = self.theme.mono if kind == "mono" else self.theme.sans
        return load_font(path, max(1, int(size)))

    def fit_font(self, text: str, size: int, max_width: float, kind: str = "sans", min_size=12):
        """Largest font <= ``size`` with which ``text`` fits in ``max_width`` pixels.

        Shrinks 2 px at a time down to ``min_size`` and then 1 px at a time, so text
        never overflows its box (the last resort is tiny but never overlaps).
        """
        size = max(1, int(size))
        sizes = list(range(size, min_size - 1, -2)) + list(range(min(size, min_size) - 1, 0, -1))
        for candidate in sizes:
            font = self.font(candidate, kind)
            if font.getlength(text) <= max_width:
                return font
        return self.font(1, kind)

    def text(
        self,
        xy: tuple[float, float],
        text: str,
        size: int = 40,
        color: str | RGB = "text",
        kind: str = "sans",
        anchor: str = "la",
        max_width: float | None = None,
    ) -> float:
        """Draw ``text`` and return its width. ``anchor`` follows Pillow (e.g. "la", "rs", "mm")."""
        if max_width is not None:
            font = self.fit_font(text, size, max_width, kind)
        else:
            font = self.font(size, kind)
        self.draw.text(xy, text, font=font, fill=self.color(color), anchor=anchor)
        return font.getlength(text)

    def title(self, text: str, color: str | RGB = "text", size: int = 40) -> int:
        """Card title in the top-left corner. Returns the y just below it."""
        self.text(
            (self.left, self.top + 4),
            text,
            size=size,
            color=color,
            max_width=self.content_width * 0.6,
        )
        return self.top + 4 + size + 8

    def message(self, text: str, color: str | RGB = "muted", size: int = 40) -> None:
        """A centred message in the card area (no data, no images...)."""
        cy = (self.top + self.bottom) // 2
        self.text(
            (self.width // 2, cy),
            text,
            size=size,
            color=color,
            anchor="mm",
            max_width=self.content_width - 40,
        )

    # -- shapes ----------------------------------------------------------------------

    def bar(
        self, x: float, y: float, w: float, h: float, percent: float | None, color: str | RGB
    ) -> None:
        """Thick progress bar with a border; empty when ``percent`` is missing."""
        self.draw.rectangle(
            (x, y, x + w, y + h), fill=self.color("track"), outline=self.color("muted"), width=3
        )
        if isinstance(percent, (int, float)) and not isinstance(percent, bool) and percent > 0:
            fill_w = int((w - 6) * min(percent, 100) / 100)
            if fill_w > 0:
                self.draw.rectangle(
                    (x + 3, y + 3, x + 3 + fill_w, y + h - 3), fill=self.color(color)
                )

    def level(self, value: float | None, warn: float | None, crit: float | None) -> RGB:
        return self.theme.level(value, warn, crit)
