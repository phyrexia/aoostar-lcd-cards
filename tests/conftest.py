"""Shared fixtures. Nothing here needs the LCD, asterctl or root."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
FIXED_TIME = datetime(2026, 1, 15, 10, 24)

sys.path.insert(0, str(ROOT / "src"))  # allow running without `pip install -e .`


@pytest.fixture
def write_config(tmp_path):
    """Write a YAML config into tmp_path and return its path."""

    def _write(data: dict, name: str = "config.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def make_config(tmp_path):
    """Parsed Config from a dict (paths relative to tmp_path)."""
    from aoostar_lcd.config import parse_config

    def _make(data: dict):
        data = {"display": {"backend": "none"}, **data}
        return parse_config(data, tmp_path)

    return _make
