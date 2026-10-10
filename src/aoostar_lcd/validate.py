"""Small validation helpers that turn bad configuration into clear messages.

Every helper takes the value, a ``where`` string that names the setting
(``"cards[2] (network).units"``) and raises :class:`ConfigError` with that
prefix, so the user sees exactly which line of the YAML file is wrong.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from typing import Any

_HEX_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")


class ConfigError(ValueError):
    """Raised for any invalid configuration value."""


def suggest(name: str, choices: Iterable[str]) -> str:
    """' Did you mean "x"?' when a close match exists, else ''."""
    match = difflib.get_close_matches(name, list(choices), n=1, cutoff=0.6)
    return f' Did you mean "{match[0]}"?' if match else ""


def check_keys(where: str, data: Mapping[str, Any], allowed: Iterable[str]) -> None:
    """Reject keys that are not in ``allowed``."""
    allowed = list(allowed)
    for key in data:
        if key not in allowed:
            raise ConfigError(
                f"{where}: unknown option '{key}'.{suggest(str(key), allowed)} "
                f"Allowed: {', '.join(sorted(allowed))}"
            )


def as_mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where}: must be a mapping (key: value), got {type(value).__name__}")
    return dict(value)


def as_bool(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{where}: must be true or false, got {value!r}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_float(
    value: Any, where: str, minimum: float | None = None, maximum: float | None = None
) -> float:
    if not _is_number(value):
        raise ConfigError(f"{where}: must be a number, got {value!r}")
    value = float(value)
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where}: must be >= {minimum:g}, got {value:g}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{where}: must be <= {maximum:g}, got {value:g}")
    return value


def as_int(value: Any, where: str, minimum: int | None = None, maximum: int | None = None) -> int:
    if not _is_number(value) or float(value) != int(value):
        raise ConfigError(f"{where}: must be a whole number, got {value!r}")
    return int(as_float(value, where, minimum, maximum))


def as_str(value: Any, where: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where}: must be text, got {value!r}")
    if not allow_empty and not value.strip():
        raise ConfigError(f"{where}: must not be empty")
    return value


def as_choice(value: Any, where: str, choices: Iterable[str]) -> str:
    choices = list(choices)
    if value not in choices:
        hint = suggest(str(value), choices)
        raise ConfigError(f"{where}: must be one of {', '.join(choices)}, got {value!r}.{hint}")
    return value


def as_str_list(value: Any, where: str, max_items: int | None = None) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{where}: must be a list of text values, got {value!r}")
    if max_items is not None and len(value) > max_items:
        raise ConfigError(f"{where}: at most {max_items} items, got {len(value)}")
    return list(value)


def as_color(value: Any, where: str) -> tuple[int, int, int]:
    """Accept "#rrggbb", "rrggbb" or [r, g, b]."""
    if isinstance(value, str):
        match = _HEX_COLOR.match(value.strip())
        if match:
            hex_value = match.group(1)
            return tuple(int(hex_value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    elif (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_is_number(v) and 0 <= v <= 255 and int(v) == v for v in value)
    ):
        return tuple(int(v) for v in value)  # type: ignore[return-value]
    raise ConfigError(f'{where}: must be a color like "#3cc8ff" or [60, 200, 255], got {value!r}')
