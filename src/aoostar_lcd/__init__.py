"""Configurable rotating status cards for the AOOSTAR 960x376 USB LCD.

The public API for custom cards is :class:`aoostar_lcd.Card`; see ``docs/CUSTOM_CARDS.md``.
"""

from .cards.base import Card
from .validate import ConfigError

__version__ = "0.1.0"

__all__ = ["Card", "ConfigError", "__version__"]
