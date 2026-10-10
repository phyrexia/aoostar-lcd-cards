#!/usr/bin/env python3
"""Generate the example images in examples/images/ (original artwork, MIT like the repo).

    python3 scripts/make-example-images.py

* landscape.png: a flat illustration (sky gradient, sun, mountains), 1200x600, so the
  `contain` / `cover` / `fit-width` modes differ visibly on the 960x376 panel.
* logo.png: a transparent logo (a tiny bar chart in a rounded screen + text), to show
  how transparency is composed over the card's background.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "examples" / "images"
FONT = ROOT / "src" / "aoostar_lcd" / "fonts" / "DejaVuSans-Bold.ttf"


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def ridge(width, base, amplitude, seed, roughness=7):
    rng = random.Random(seed)
    points = []
    phase = rng.uniform(0, math.tau)
    for x in range(0, width + 40, 40):
        y = base - amplitude * (0.55 + 0.45 * math.sin(x / 210 + phase))
        y += rng.uniform(-roughness, roughness) * 4
        points.append((x, y))
    return points


def landscape(path: Path) -> None:
    w, h = 1200, 600
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    top, mid, low = (22, 24, 64), (122, 64, 140), (255, 158, 94)
    for y in range(h):
        t = y / (h * 0.75)
        color = lerp(top, mid, min(t, 1) * 2) if t < 0.5 else lerp(mid, low, min(1, (t - 0.5) * 2))
        d.line((0, y, w, y), fill=color)
    rng = random.Random(7)
    for _ in range(90):
        x, y = rng.randrange(w), rng.randrange(int(h * 0.4))
        r = rng.choice((1, 1, 1, 2))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 240))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    sx, sy = 820, 330
    gd.ellipse((sx - 170, sy - 170, sx + 170, sy + 170), fill=(255, 210, 140, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    d = ImageDraw.Draw(img)
    d.ellipse((sx - 95, sy - 95, sx + 95, sy + 95), fill=(255, 226, 160))
    layers = [((92, 58, 120), 420, 140, 1), ((60, 40, 96), 480, 110, 2), ((34, 26, 64), 540, 80, 3)]
    for color, base, amp, seed in layers:
        d.polygon([(0, h), *ridge(w, base, amp, seed), (w, h)], fill=color)
    img.convert("RGB").save(path, optimize=True)


def logo(path: Path) -> None:
    w, h = 640, 240
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (10, 30, 230, 210), radius=32, fill=(36, 40, 52, 255), outline=(70, 200, 255, 255), width=8
    )
    for i, (height, color) in enumerate(
        ((60, (70, 200, 255)), (110, (150, 120, 255)), (85, (255, 140, 40)))
    ):
        x = 50 + i * 55
        d.rounded_rectangle((x, 180 - height, x + 36, 180), radius=8, fill=(*color, 255))
    font = ImageFont.truetype(str(FONT), 76)
    d.text((262, 120), "homelab", font=font, fill=(255, 255, 255, 255), anchor="lm")
    small = ImageFont.truetype(str(FONT), 30)
    d.text((266, 182), "status panel", font=small, fill=(205, 210, 220, 255), anchor="lm")
    img.save(path, optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    landscape(OUT / "landscape.png")
    logo(OUT / "logo.png")
    print(f"wrote {OUT / 'landscape.png'} and {OUT / 'logo.png'}")


if __name__ == "__main__":
    main()
