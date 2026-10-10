"""Histogram helpers shared by the CPU and network cards."""

from __future__ import annotations

from collections.abc import Sequence

from .canvas import Canvas
from .theme import RGB
from .units import axis_number


def blend(color: RGB, background: RGB, amount: float) -> RGB:
    """Mix ``amount`` (0-1) of ``color`` into ``background``."""
    return tuple(
        round(c * amount + b * (1 - amount)) for c, b in zip(color, background, strict=True)
    )  # type: ignore[return-value]


def time_marks(slots: int, step_s: int, now_label: str) -> list[tuple[float, str]]:
    """Labels at 0, 1/3, 2/3 and the end of the window: '-3 h', '-2 h', '-1 h', 'now'."""
    window = slots * step_s
    marks = []
    for frac in (0.0, 1 / 3, 2 / 3):
        ago = round(window * (1 - frac))
        if ago % 3600 == 0:
            marks.append((frac, f"-{ago // 3600} h"))
        else:
            marks.append((frac, f"-{round(ago / 60)} min"))
    marks.append((1.0, now_label))
    return marks


def _bar_x(x0: float, bar_w: float, i: int) -> tuple[int, int]:
    left = round(x0 + i * bar_w) + 1
    right = round(x0 + (i + 1) * bar_w) - 2
    return left, max(left, right)


def _draw_time_axis(canvas: Canvas, x0: float, x1: float, y: float, marks, size: int) -> None:
    for frac, label in marks:
        x = x0 + (x1 - x0) * frac
        anchor = "la" if frac == 0 else "ra" if frac == 1 else "ma"
        canvas.text((x, y), label, size=size, color="muted", anchor=anchor)


def mirror_histogram(
    canvas: Canvas,
    box: tuple[float, float, float, float],
    up: Sequence[float | None],
    down: Sequence[float | None],
    scale: float,
    divisor: float,
    marks: list[tuple[float, str]],
    up_peaks: Sequence[float | None] | None = None,
    down_peaks: Sequence[float | None] | None = None,
    empty_message: str | None = None,
    label_size: int = 24,
) -> None:
    """Bars growing up (``up``, rx color) and down (``down``, tx color) from a centre line.

    ``box`` is the plot area; value labels go to the left of it and time labels below.
    """
    x0, y0, x1, y1 = box
    slots = max(len(up), len(down), 1)
    mid = (y0 + y1) // 2
    half = (y1 - y0) // 2 - 2
    bar_w = (x1 - x0) / slots
    grid = canvas.color("grid")
    for frac in (1.0, 0.5):
        for sign in (-1, 1):
            y = mid + sign * int(half * frac)
            canvas.draw.line((x0, y, x1, y), fill=grid, width=1)
    for frac in (1 / 3, 2 / 3):
        x = round(x0 + (x1 - x0) * frac)
        canvas.draw.line((x, y0, x, y1), fill=grid, width=1)
    for value, y in (
        (scale, mid - half),
        (scale / 2, mid - half // 2),
        (0, mid),
        (scale / 2, mid + half // 2),
        (scale, mid + half),
    ):
        canvas.text(
            (x0 - 8, y), axis_number(value / divisor), size=label_size, color="muted", anchor="rm"
        )

    has_data = any(v is not None for v in list(up) + list(down))
    if not has_data and empty_message:
        canvas.text(
            ((x0 + x1) / 2, mid - half // 2),
            empty_message,
            size=36,
            color="muted",
            anchor="mm",
            max_width=x1 - x0 - 40,
        )
    background = canvas.color("background")
    series = (
        (up, up_peaks, -1, canvas.color("rx")),
        (down, down_peaks, 1, canvas.color("tx")),
    )
    for values, peaks, sign, color in series:
        peak_color = blend(color, background, 0.45)
        for i, value in enumerate(values):
            left, right = _bar_x(x0, bar_w, i)
            peak = peaks[i] if peaks is not None and i < len(peaks) else None
            if peak is not None and value is not None and peak > value and scale > 0:
                ph = min(half, round(peak / scale * half))
                if ph > 0:
                    if sign < 0:
                        canvas.draw.rectangle((left, mid - ph, right, mid - 1), fill=peak_color)
                    else:
                        canvas.draw.rectangle((left, mid + 1, right, mid + ph), fill=peak_color)
            if value is None or scale <= 0:
                continue
            h = min(half, max(2 if value > 0 else 0, round(value / scale * half)))
            if h <= 0:
                continue
            if sign < 0:
                canvas.draw.rectangle((left, mid - h, right, mid - 1), fill=color)
            else:
                canvas.draw.rectangle((left, mid + 1, right, mid + h), fill=color)
    canvas.draw.line((x0, mid, x1, mid), fill=canvas.color("muted"), width=2)
    _draw_time_axis(canvas, x0, x1, y1 + 4, marks, label_size)


def histogram(
    canvas: Canvas,
    box: tuple[float, float, float, float],
    values: Sequence[float | None],
    peaks: Sequence[float | None] | None,
    scale: float,
    marks: list[tuple[float, str]],
    color: str | RGB = "accent",
    value_labels: Sequence[tuple[float, str]] = (),
    empty_message: str | None = None,
    label_size: int = 22,
) -> None:
    """Bars growing up from the bottom of ``box``; ``peaks`` drawn as a lighter cap."""
    x0, y0, x1, y1 = box
    slots = max(len(values), 1)
    bar_w = (x1 - x0) / slots
    height = y1 - y0
    grid = canvas.color("grid")
    for value, label in value_labels:
        y = y1 - round(value / scale * height) if scale > 0 else y1
        canvas.draw.line((x0, y, x1, y), fill=grid, width=1)
        canvas.text((x0 - 8, y), label, size=label_size, color="muted", anchor="rm")
    for frac in (1 / 3, 2 / 3):
        x = round(x0 + (x1 - x0) * frac)
        canvas.draw.line((x, y0, x, y1), fill=grid, width=1)
    bar_color = canvas.color(color)
    peak_color = blend(bar_color, canvas.color("background"), 0.45)
    if not any(v is not None for v in values) and empty_message:
        canvas.text(
            ((x0 + x1) / 2, (y0 + y1) / 2),
            empty_message,
            size=32,
            color="muted",
            anchor="mm",
            max_width=x1 - x0 - 20,
        )
    for i, value in enumerate(values):
        if value is None or scale <= 0:
            continue
        left, right = _bar_x(x0, bar_w, i)
        peak = peaks[i] if peaks is not None and i < len(peaks) else None
        if peak is not None and peak > value:
            ph = min(height, round(peak / scale * height))
            canvas.draw.rectangle((left, y1 - ph, right, y1), fill=peak_color)
        h = min(height, max(2 if value > 0 else 0, round(value / scale * height)))
        if h > 0:
            canvas.draw.rectangle((left, y1 - h, right, y1), fill=bar_color)
    canvas.draw.line((x0, y1, x1, y1), fill=canvas.color("muted"), width=2)
    _draw_time_axis(canvas, x0, x1, y1 + 4, marks, label_size)
