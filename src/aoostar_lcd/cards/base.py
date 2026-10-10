"""The :class:`Card` base class: the whole public API for built-in and custom cards.

A card has two halves that may run in different processes:

* ``collect()`` runs in the **collector**, next to the metrics (usually the
  host). It returns a JSON-serialisable ``dict`` (or ``None``) that is stored
  in the state file under the card's id.
* ``render(canvas, theme, data)`` runs in the **renderer**, next to the LCD.
  It receives that ``dict`` back (``None`` if nothing was collected yet) and
  draws one frame on a 960x376 canvas.

Minimal custom card::

    from aoostar_lcd import Card

    class HelloCard(Card):
        type_name = "hello"
        defaults = {"greeting": "Hello"}

        def collect(self):
            return {"answer": 42}

        def render(self, canvas, theme, data):
            canvas.title("HELLO")
            value = "-" if data is None else str(data["answer"])
            canvas.text((canvas.left, canvas.top + 160), self.options["greeting"] + " " + value,
                        size=90)

Load it from YAML with ``type: plugin`` and ``plugin: path/to/file.py:HelloCard``.
This module must not import Pillow: the collector side runs without it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from ..i18n import tr
from ..validate import check_keys

if TYPE_CHECKING:  # pragma: no cover
    from ..canvas import Canvas
    from ..theme import Theme


class Card:
    """Base class for every card. Subclass it and override what you need."""

    #: Name used in ``type:`` for built-in cards (plugins may leave the default).
    type_name: ClassVar[str] = "card"
    #: Translation key (see ``i18n.py``) or literal text for the default title.
    title_key: ClassVar[str | None] = None
    #: Option names and their defaults. Unknown options in the YAML are rejected.
    defaults: ClassVar[dict[str, Any]] = {}
    #: Minimum seconds between two ``collect()`` calls. 0 = every collector tick.
    refresh: ClassVar[float] = 0.0
    #: True if the card paints the whole screen (no page dots on top).
    full_bleed: ClassVar[bool] = False

    def __init__(
        self,
        card_id: str = "card",
        options: dict[str, Any] | None = None,
        *,
        title: str | None = None,
        lang: str = "en",
        base_dir: str | Path | None = None,
        where: str | None = None,
    ) -> None:
        self.id = card_id
        self.lang = lang
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.where = where or f"card '{card_id}'"
        given = dict(options or {})
        check_keys(self.where, given, self.defaults)
        #: Defaults merged with the YAML values; ``configure`` may normalise them.
        self.options: dict[str, Any] = {**self.defaults, **given}
        self.title = title
        self.page = 0
        #: Seconds on screen per visit, whether it rotates, seconds between collects.
        #: The YAML keys ``duration``, ``enabled`` and ``refresh`` override them.
        self.duration = 8.0
        self.enabled = True
        self.collect_every = float(type(self).refresh)
        self.configure(self.options)

    # -- configuration ---------------------------------------------------------------

    def configure(self, options: dict[str, Any]) -> None:
        """Validate and normalise ``self.options``. Raise ``ConfigError`` on bad values."""

    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.title_key:
            return tr(self.title_key, self.lang)
        return self.type_name.upper()

    def tr(self, key: str) -> str:
        return tr(key, self.lang)

    def resolve_path(self, value: str) -> Path:
        """Paths in the YAML are relative to the config file's directory."""
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.base_dir / path

    # -- collector side --------------------------------------------------------------

    def collect(self) -> dict[str, Any] | None:
        """Measure and return JSON-serialisable data. Runs in the collector."""
        return None

    def state(self) -> dict[str, Any] | None:
        """Data to persist across collector restarts (e.g. a history window)."""
        return None

    def restore(self, state: dict[str, Any]) -> None:
        """Receive what ``state()`` returned in a previous run."""

    # -- renderer side ---------------------------------------------------------------

    def render(self, canvas: Canvas, theme: Theme, data: dict[str, Any] | None) -> None:
        """Draw one frame. ``data`` is what ``collect()`` returned, or None."""
        raise NotImplementedError(f"{type(self).__name__} must implement render()")

    def sample(self) -> dict[str, Any] | None:
        """Synthetic data for ``aoostar-lcd preview`` and tests (no hardware needed)."""
        return None

    def alerts(self, data: dict[str, Any] | None) -> list[str]:
        """Short messages for the red banner shown on top of every card."""
        return []

    def visit_pages(self) -> int:
        """How many frames this card shows each time the rotation reaches it."""
        return 1

    def set_page(self, page: int) -> None:
        self.page = page
