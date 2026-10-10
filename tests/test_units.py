import pytest

from aoostar_lcd import units


@pytest.mark.parametrize(
    "value,system,expected",
    [
        (9.1e12, "si", "9.1 TB"),
        (5.2e12, "si", "5.2 TB"),
        (780e9, "si", "780 GB"),
        (14.2 * 2**30, "iec", "14.2 GiB"),
        (5 * 2**40, "iec", "5.0 TiB"),
        (512, "si", "512 B"),
        (None, "si", "-"),
        (float("nan"), "si", "-"),
    ],
)
def test_format_size(value, system, expected):
    assert units.format_size(value, system) == expected


def test_tb_versus_tib_differ():
    assert units.format_size(10**12, "si") == "1.0 TB"
    assert units.format_size(10**12, "iec") == "931 GiB"


@pytest.mark.parametrize(
    "bytes_per_s,unit,expected",
    [
        (842e6 / 8, "bits", "842 Mbit/s"),
        (1.25e9 / 8, "bits", "1.25 Gbit/s"),
        (5e3 / 8, "bits", "5 kbit/s"),
        (8.4e6 / 8, "bits", "8.4 Mbit/s"),
        (105e6, "bytes", "105 MB/s"),
        (1.25e9, "bytes", "1.25 GB/s"),
        (None, "bits", "-"),
    ],
)
def test_format_rate(bytes_per_s, unit, expected):
    assert units.format_rate(bytes_per_s, unit) == expected


@pytest.mark.parametrize(
    "peak,floor,expected",
    [
        (0, 10, 10),
        (3, 10, 10),
        (11, 10, 20),
        (45, 0, 50),
        (51, 0, 100),
        (850, 0, 1000),
        (1200, 0, 2000),
        (4.9e9, 0, 5e9),
        (0, 0, 1.0),
    ],
)
def test_nice_ceiling_is_1_2_5_and_covers_the_peak(peak, floor, expected):
    result = units.nice_ceiling(peak, floor)
    assert result == pytest.approx(expected)
    assert result >= peak


def test_duration_and_temperature():
    assert units.format_duration(12 * 86400 + 4 * 3600 + 31 * 60) == "12d 4h"
    assert units.format_duration(3 * 3600 + 12 * 60) == "3h 12m"
    assert units.format_duration(59) == "0m"
    assert units.format_duration(None) == "-"
    assert units.to_display_temp(100, "fahrenheit") == (212, "°F")
    assert units.to_display_temp(None, "celsius") == (None, "°C")


def test_localized_dates():
    from datetime import datetime

    from aoostar_lcd.i18n import localized_strftime

    moment = datetime(2026, 1, 15, 10, 24)
    assert localized_strftime(moment, "%A %d %B %Y", "en") == "Thursday 15 January 2026"
    assert localized_strftime(moment, "%A %d %B %Y", "es") == "jueves 15 enero 2026"
    assert localized_strftime(moment, "%H:%M 100%%", "es") == "10:24 100%"
