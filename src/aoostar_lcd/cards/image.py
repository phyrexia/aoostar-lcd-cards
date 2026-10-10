"""Image card: your own logos, photos or illustrations.

``path`` is a file or a folder. With a folder the card shows every image in name
order, each for ``duration`` seconds (``per_visit: all``), or one new image each time
the rotation comes back (``per_visit: one``). The folder is listed again at the start
of every pass, so you can drop or remove files without restarting.

Supported: PNG, JPEG, WebP and GIF (first frame). Transparency is composed over
``background``. Files that are too big, have too many pixels or cannot be decoded are
skipped with a warning in the log. The card runs only in the renderer, so the
images must be readable where the display process runs.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..validate import ConfigError, as_bool, as_choice, as_color, as_float, as_int, as_str
from .base import Card

log = logging.getLogger(__name__)

EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MODES = ("contain", "cover", "fit-width")
CACHE_SIZE = 8


class ImageCard(Card):
    type_name = "image"
    title_key = None
    full_bleed = True
    defaults = {
        "path": None,  # image file or folder (relative paths: next to the config file)
        "mode": "contain",  # contain | cover | fit-width
        "background": None,  # color behind the image; null = theme background
        "per_visit": "all",  # all | one (folder mode)
        "upscale": True,  # enlarge small images (contain / fit-width)
        "max_file_mb": 20,
        "max_pixels": 40_000_000,
        "max_files": 500,
    }

    def configure(self, options: dict[str, Any]) -> None:
        where = self.where
        if options["path"] is None:
            raise ConfigError(f"{where}.path: required (an image file or a folder)")
        self.path = self.resolve_path(as_str(options["path"], f"{where}.path"))
        as_choice(options["mode"], f"{where}.mode", MODES)
        if options["background"] is not None:
            options["background"] = as_color(options["background"], f"{where}.background")
        as_choice(options["per_visit"], f"{where}.per_visit", ("all", "one"))
        as_bool(options["upscale"], f"{where}.upscale")
        options["max_file_mb"] = as_float(options["max_file_mb"], f"{where}.max_file_mb", 0.01, 200)
        options["max_pixels"] = as_int(options["max_pixels"], f"{where}.max_pixels", 1, 200_000_000)
        options["max_files"] = as_int(options["max_files"], f"{where}.max_files", 1, 10_000)
        self.files: list[Path] = []
        self.cursor = 0
        self.current: Path | None = None
        self._bad: dict[Path, tuple[int, int]] = {}  # path -> (mtime_ns, size) that failed
        self._warned: set[str] = set()
        self._cache: OrderedDict[tuple, Any] = OrderedDict()

    # -- folder handling -----------------------------------------------------------

    def _warn_once(self, key: str, message: str, *args) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(message, *args)

    def _signature(self, path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def scan(self) -> list[Path]:
        """List the images to show (re-read on every pass)."""
        path = self.path
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            try:
                names = sorted(os.listdir(path), key=str.casefold)
            except OSError as exc:
                self._warn_once(
                    f"list:{path}", "image card %s: cannot list %s: %s", self.id, path, exc
                )
                names = []
            candidates = [
                path / n
                for n in names
                if not n.startswith(".") and n.lower().endswith(EXTENSIONS) and (path / n).is_file()
            ]
            limit = self.options["max_files"]
            if len(candidates) > limit:
                self._warn_once(
                    f"limit:{path}",
                    "image card %s: %d images in %s, showing the first %d (max_files)",
                    self.id,
                    len(candidates),
                    path,
                    limit,
                )
                candidates = candidates[:limit]
        else:
            self._warn_once(f"missing:{path}", "image card %s: %s does not exist", self.id, path)
            candidates = []
        files = []
        for candidate in candidates:
            sig = self._signature(candidate)
            if sig is None or self._bad.get(candidate) == sig:
                continue  # unreadable, or failed before and unchanged since
            files.append(candidate)
        self.files = files
        return files

    def visit_pages(self) -> int:
        files = self.scan()
        if self.options["per_visit"] == "one" or not files:
            return 1
        return len(files)

    def set_page(self, page: int) -> None:
        self.page = page
        if not self.files:
            self.current = None
            return
        if self.options["per_visit"] == "one":
            self.current = self.files[self.cursor % len(self.files)]
            self.cursor += 1
        else:
            self.current = self.files[page % len(self.files)]

    # -- decoding ------------------------------------------------------------------

    def _background(self, canvas) -> tuple[int, int, int]:
        return self.options["background"] or canvas.color("background")

    def load_frame(self, path: Path, size: tuple[int, int], background):
        """Decoded, scaled RGB frame for ``path``; None (and a warning) if unusable."""
        from PIL import Image, UnidentifiedImageError

        sig = self._signature(path)
        if sig is None:
            return None
        key = (path, sig, size, background, self.options["mode"], self.options["upscale"])
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        if sig[1] > self.options["max_file_mb"] * 1024 * 1024:
            self._mark_bad(path, sig, "larger than max_file_mb")
            return None
        try:
            with Image.open(path) as img:
                if img.width * img.height > self.options["max_pixels"]:
                    self._mark_bad(path, sig, f"{img.width}x{img.height} exceeds max_pixels")
                    return None
                img.seek(0)  # first frame of animated GIF/WebP
                rgba = img.convert("RGBA")
        except (
            OSError,
            ValueError,
            SyntaxError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ) as exc:
            self._mark_bad(path, sig, f"cannot decode ({type(exc).__name__})")
            return None
        frame = compose(rgba, size, self.options["mode"], background, self.options["upscale"])
        self._cache[key] = frame
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return frame

    def _mark_bad(self, path: Path, sig, reason: str) -> None:
        self._bad[path] = sig
        log.warning("image card %s: skipping %s: %s", self.id, path, reason)

    # -- renderer ------------------------------------------------------------------

    def render(self, canvas, theme, data) -> None:
        background = self._background(canvas)
        canvas.draw.rectangle((0, 0, canvas.width, canvas.height), fill=background)
        if self.current is None and not self.files:
            self.scan()
            self.set_page(self.page)
        size = (canvas.width, canvas.height)
        candidates = [self.current] if self.current else []
        if self.files:
            start = self.files.index(self.current) if self.current in self.files else 0
            candidates += self.files[start + 1 :] + self.files[:start]
        for path in candidates:
            frame = self.load_frame(path, size, background)
            if frame is not None:
                canvas.image.paste(frame, (0, 0))
                return
        canvas.message(self.tr("no_images"))


def compose(rgba, size: tuple[int, int], mode: str, background, upscale: bool = True):
    """Scale ``rgba`` into ``size`` according to ``mode`` and flatten it on ``background``."""
    from PIL import Image

    width, height = size
    w, h = rgba.size
    if mode == "cover":
        scale = max(width / w, height / h)
    elif mode == "fit-width":
        scale = width / w
    else:
        scale = min(width / w, height / h)
    if not upscale and mode != "cover":
        scale = min(scale, 1.0)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    if (new_w, new_h) != (w, h):
        rgba = rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
    # Crop what overflows, centred, then paste centred.
    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)
    rgba = rgba.crop((left, top, left + min(new_w, width), top + min(new_h, height)))
    base = Image.new("RGBA", size, (*background, 255))
    base.alpha_composite(rgba, ((width - rgba.width) // 2, (height - rgba.height) // 2))
    return base.convert("RGB")
