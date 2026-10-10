"""Thin wrapper around the external ``asterctl`` binary (https://github.com/zehnm/aoostar-rs).

asterctl is an independent project (MIT OR Apache-2.0) that speaks the LCD's
reverse-engineered serial protocol. This package never bundles it: install it with
``scripts/install-asterctl.sh`` (pinned in ``asterctl.version``) or with Docker.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Release this project is tested against (same value as ASTERCTL_TAG in asterctl.version).
PINNED_TAG = "v0.2.0"
#: Oldest asterctl whose command line (--image, --device, --usb, --simulate) we rely on.
MIN_VERSION = (0, 2, 0)
INSTALL_HINT = (
    "install it with scripts/install-asterctl.sh (or see the README, section 'asterctl'), "
    "or set display.asterctl to its full path"
)
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class AsterctlError(RuntimeError):
    """asterctl failed, timed out or produced unexpected output."""


class AsterctlNotFoundError(AsterctlError):
    """The asterctl binary does not exist or is not executable."""


class AsterctlVersionError(AsterctlError):
    """The installed asterctl is older than MIN_VERSION."""


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.search(text or "")
    return tuple(int(g) for g in match.groups()) if match else None  # type: ignore[return-value]


def format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(v) for v in version)


@dataclass
class Asterctl:
    binary: str = "asterctl"
    device: str | None = None
    usb: str | None = None
    timeout: float = 20.0
    simulate: bool = False
    min_version: tuple[int, int, int] = MIN_VERSION

    def path(self) -> str:
        """Absolute path of the binary, or AsterctlNotFoundError with an install hint."""
        if os.sep in self.binary or "/" in self.binary:
            candidate = Path(self.binary)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
            raise AsterctlNotFoundError(
                f"asterctl not found or not executable at {self.binary}; {INSTALL_HINT}"
            )
        found = shutil.which(self.binary)
        if not found:
            raise AsterctlNotFoundError(f"'{self.binary}' is not in PATH; {INSTALL_HINT}")
        return found

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [self.path(), *args]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise AsterctlError(
                f"asterctl timed out after {self.timeout:g} s ({' '.join(args)})"
            ) from None
        except OSError as exc:
            raise AsterctlNotFoundError(f"cannot run {cmd[0]}: {exc}; {INSTALL_HINT}") from None
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-400:]
            raise AsterctlError(f"asterctl exited with {result.returncode}: {detail}")
        return result

    def version(self) -> tuple[int, int, int]:
        result = self._run(["--version"])
        version = parse_version(result.stdout)
        if version is None:
            raise AsterctlError(f"cannot read the asterctl version from {result.stdout!r}")
        return version

    def check(self) -> tuple[int, int, int]:
        """Return the installed version; raise if missing or older than ``min_version``."""
        version = self.version()
        if version < self.min_version:
            raise AsterctlVersionError(
                f"asterctl {format_version(version)} is too old; this project needs "
                f">= {format_version(self.min_version)} (pinned: {PINNED_TAG}); {INSTALL_HINT}"
            )
        return version

    def target_args(self) -> list[str]:
        if self.simulate:
            return ["--simulate"]
        if self.device:
            return ["--device", self.device]
        if self.usb:
            return ["--usb", self.usb]
        return []  # asterctl looks for the default USB id 416:90A1

    def send_image(self, image: str | os.PathLike) -> None:
        """Show a PNG/JPEG on the panel (asterctl scales other sizes to 960x376)."""
        path = Path(image)
        if not path.is_file():
            raise AsterctlError(f"image not found: {path}")
        self._run([*self.target_args(), "--image", str(path)])

    def on(self) -> None:
        self._run([*self.target_args(), "--on"])

    def off(self) -> None:
        self._run([*self.target_args(), "--off"])
