"""Where frames go: the LCD (through asterctl), a PNG folder, or nowhere."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image

from .asterctl import Asterctl, AsterctlError
from .config import DisplayConfig

log = logging.getLogger(__name__)
ERROR_LOG_EVERY_S = 60


class Sink:
    def show(self, image: Image.Image) -> bool:
        """Show a frame. Return True if it reached its destination."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullSink(Sink):
    def show(self, image: Image.Image) -> bool:
        return True


class PngSink(Sink):
    """Writes ``latest.png`` (atomically) into a folder; handy without hardware."""

    def __init__(self, directory: str | os.PathLike):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image) -> bool:
        tmp = self.directory / ".latest.png.tmp"
        image.save(tmp, format="PNG")
        os.replace(tmp, self.directory / "latest.png")
        return True


class AsterctlSink(Sink):
    """Saves the frame in a private temporary folder and runs ``asterctl --image``."""

    def __init__(self, asterctl: Asterctl):
        self.asterctl = asterctl
        self.tmpdir = tempfile.mkdtemp(prefix="aoostar-lcd-")  # mode 0700
        self.frame = Path(self.tmpdir) / "frame.png"
        self._last_error = ("", 0.0)

    def show(self, image: Image.Image) -> bool:
        image.save(self.frame, format="PNG")
        started = time.monotonic()
        try:
            self.asterctl.send_image(self.frame)
        except AsterctlError as exc:
            message, logged_at = self._last_error
            now = time.monotonic()
            if str(exc) != message or now - logged_at > ERROR_LOG_EVERY_S:
                log.error("%s", exc)
                self._last_error = (str(exc), now)
            return False
        log.debug("frame sent in %.1f s", time.monotonic() - started)
        return True

    def close(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def make_asterctl(cfg: DisplayConfig) -> Asterctl:
    return Asterctl(
        binary=cfg.asterctl,
        device=cfg.device,
        usb=cfg.usb,
        timeout=cfg.timeout,
        simulate=cfg.simulate,
    )


def make_sink(cfg: DisplayConfig) -> Sink:
    if cfg.backend == "png":
        return PngSink(cfg.png_dir)
    if cfg.backend == "none":
        return NullSink()
    asterctl = make_asterctl(cfg)
    if cfg.check_version:
        version = asterctl.check()  # raises with a clear message if missing or too old
        log.info("using asterctl %s at %s", ".".join(map(str, version)), asterctl.path())
    return AsterctlSink(asterctl)
