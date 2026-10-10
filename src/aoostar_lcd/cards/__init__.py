"""Built-in card types and the loader for custom (plugin) cards."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

from ..validate import ConfigError
from .base import Card
from .cpu import CpuCard
from .custom import CustomCard
from .image import ImageCard
from .memory import MemoryCard
from .network import NetworkCard
from .storage import StorageCard
from .system import ClockCard, UptimeCard
from .temperature import TemperatureCard

BUILTIN: dict[str, type[Card]] = {
    cls.type_name: cls
    for cls in (
        CpuCard,
        MemoryCard,
        NetworkCard,
        TemperatureCard,
        StorageCard,
        ClockCard,
        UptimeCard,
        CustomCard,
        ImageCard,
    )
}


def load_plugin(ref: str, base_dir: Path, where: str) -> type[Card]:
    """Load ``"module.path:Class"`` or ``"path/to/file.py:Class"`` and check it is a Card.

    Loading a plugin runs its code with the permissions of the process, exactly like
    any other Python module: only point it at files you trust.
    """
    if not isinstance(ref, str) or ":" not in ref:
        raise ConfigError(
            f"{where}.plugin: use 'module.path:ClassName' or "
            f"'path/to/file.py:ClassName', got {ref!r}"
        )
    target, _, class_name = ref.rpartition(":")
    if not target or not class_name.isidentifier():
        raise ConfigError(f"{where}.plugin: invalid reference {ref!r}")
    if target.endswith(".py") or "/" in target or "\\" in target:
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        if not path.is_file():
            raise ConfigError(f"{where}.plugin: file not found: {path}")
        digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]
        module_name = f"aoostar_lcd_plugin_{path.stem}_{digest}"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ConfigError(f"{where}.plugin: cannot load {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                del sys.modules[module_name]
                raise ConfigError(
                    f"{where}.plugin: error while importing {path}: {type(exc).__name__}: {exc}"
                ) from exc
    else:
        try:
            module = importlib.import_module(target)
        except Exception as exc:
            raise ConfigError(
                f"{where}.plugin: cannot import {target!r}: {type(exc).__name__}: {exc}"
            ) from exc
    cls = getattr(module, class_name, None)
    if not (isinstance(cls, type) and issubclass(cls, Card)):
        raise ConfigError(
            f"{where}.plugin: {class_name!r} in {target!r} is not a subclass of aoostar_lcd.Card"
        )
    return cls


__all__ = ["BUILTIN", "Card", "load_plugin"]
