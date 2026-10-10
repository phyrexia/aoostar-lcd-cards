"""Number formatting: sizes (SI or IEC), transfer rates (bits or bytes), durations."""

from __future__ import annotations

import math

SIZE_SYSTEMS = ("si", "iec")
RATE_UNITS = ("bits", "bytes")

_SI = ((10**15, "PB"), (10**12, "TB"), (10**9, "GB"), (10**6, "MB"), (10**3, "kB"))
_IEC = ((2**50, "PiB"), (2**40, "TiB"), (2**30, "GiB"), (2**20, "MiB"), (2**10, "KiB"))


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def size_unit(nbytes: float, system: str = "si") -> tuple[float, str]:
    """(divisor, unit) that shows ``nbytes`` with 1-3 integer digits."""
    table = _IEC if system == "iec" else _SI
    for divisor, unit in table:
        if abs(nbytes) >= divisor:
            return divisor, unit
    return 1, "B"


def format_size(nbytes: float | None, system: str = "si", decimals: int = 1) -> str:
    """'9.1 TB', '14.2 GiB'; '-' when the value is missing."""
    if not is_number(nbytes):
        return "-"
    divisor, unit = size_unit(nbytes, system)
    if unit == "B":
        return f"{nbytes:.0f} B"
    value = nbytes / divisor
    return f"{value:.{0 if abs(value) >= 100 else decimals}f} {unit}"


def format_size_in(nbytes: float | None, divisor: float, decimals: int = 1) -> str:
    """Number only, in a unit chosen elsewhere (for 'used / total' pairs)."""
    if not is_number(nbytes):
        return "-"
    return f"{nbytes / divisor:.{decimals}f}"


def rate_unit(bytes_per_s: float, unit: str = "bits") -> tuple[float, str]:
    """(divisor in bytes/s, label) for a scale that reaches ``bytes_per_s``."""
    if unit == "bytes":
        if bytes_per_s >= 1e9:
            return 1e9, "GB/s"
        if bytes_per_s >= 1e6:
            return 1e6, "MB/s"
        return 1e3, "kB/s"
    bits = bytes_per_s * 8
    if bits >= 1e9:
        return 1e9 / 8, "Gbit/s"
    if bits >= 1e6:
        return 1e6 / 8, "Mbit/s"
    return 1e3 / 8, "kbit/s"


def format_rate(bytes_per_s: float | None, unit: str = "bits") -> str:
    """'842 Mbit/s', '1.25 Gbit/s', '105 MB/s'; '-' when missing."""
    if not is_number(bytes_per_s):
        return "-"
    divisor, label = rate_unit(bytes_per_s, unit)
    value = bytes_per_s / divisor
    giga = label[0] == "G"
    if label[0] == "k" or value >= 100:
        decimals = 0
    elif value >= 10:
        decimals = 1 if giga else 0
    else:
        decimals = 2 if giga else 1
    return f"{value:.{decimals}f} {label}"


def nice_ceiling(value: float, floor: float = 0.0) -> float:
    """Smallest 1-2-5 x 10^n that is >= max(value, floor); 1.0 if both are 0."""
    target = max(value, floor)
    if target <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(target))
    for mult in (1, 2, 5, 10):
        if mult * exp >= target * (1 - 1e-12):
            return mult * exp
    return 10 * exp  # pragma: no cover - unreachable


def axis_number(value: float) -> str:
    """'0', '5', '2.5' for chart axes."""
    return f"{value:.0f}" if abs(value - round(value)) < 1e-9 else f"{value:.1f}"


def format_duration(
    seconds: float | None, lang_units: tuple[str, str, str] = ("d", "h", "m")
) -> str:
    """'12d 4h', '3h 12m', '5m' (two most significant parts)."""
    if not is_number(seconds) or seconds < 0:
        return "-"
    d_unit, h_unit, m_unit = lang_units
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}{d_unit} {hours}{h_unit}"
    if hours:
        return f"{hours}{h_unit} {minutes}{m_unit}"
    return f"{minutes}{m_unit}"


def to_display_temp(celsius: float | None, unit: str = "celsius") -> tuple[float | None, str]:
    """Convert a Celsius reading to the configured unit."""
    symbol = "°F" if unit == "fahrenheit" else "°C"
    if not is_number(celsius):
        return None, symbol
    if unit == "fahrenheit":
        return celsius * 9 / 5 + 32, symbol
    return celsius, symbol
