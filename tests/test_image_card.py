"""The image card: folders, re-scanning, modes, transparency and bad files."""

import logging
import os
import shutil

import pytest
from PIL import Image

from aoostar_lcd.canvas import Canvas
from aoostar_lcd.cards.image import ImageCard, compose
from aoostar_lcd.theme import Theme

from .conftest import EXAMPLES

RED, BLUE, GREEN = (255, 0, 0), (0, 0, 255), (0, 200, 0)


def solid(path, color, size=(200, 100), mode="RGB", fmt=None):
    Image.new(mode, size, color).save(path, format=fmt)
    return path


def draw(card):
    image = Image.new("RGB", (960, 376))
    card.render(Canvas(image, Theme()), Theme(), None)
    return image


def visit(card):
    """Pages of one visit, as the rotation would show them."""
    frames = []
    for page in range(card.visit_pages()):
        card.set_page(page)
        frames.append(draw(card).getpixel((480, 188)))
    return frames


def test_folder_shows_every_image_in_name_order(tmp_path):
    solid(tmp_path / "b.png", BLUE)
    solid(tmp_path / "a.jpg", RED)
    solid(tmp_path / "c.webp", GREEN)
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / ".hidden.png").write_bytes(b"")
    card = ImageCard("img", {"path": str(tmp_path), "mode": "cover"})
    frames = visit(card)
    assert len(frames) == 3
    assert frames[0][0] > 200 and frames[1][2] > 200 and frames[2][1] > 150  # red, blue, green


def test_folder_is_rescanned_on_every_pass(tmp_path):
    solid(tmp_path / "a.png", RED)
    card = ImageCard("img", {"path": str(tmp_path), "mode": "cover"})
    assert card.visit_pages() == 1
    solid(tmp_path / "b.png", BLUE)
    assert card.visit_pages() == 2
    (tmp_path / "a.png").unlink()
    assert card.visit_pages() == 1
    card.set_page(0)
    assert draw(card).getpixel((480, 188)) == BLUE


def test_per_visit_one_advances_between_visits(tmp_path):
    solid(tmp_path / "1.png", RED)
    solid(tmp_path / "2.png", BLUE)
    card = ImageCard("img", {"path": str(tmp_path), "mode": "cover", "per_visit": "one"})
    shown = [visit(card) for _ in range(3)]
    assert [len(v) for v in shown] == [1, 1, 1]
    assert [v[0] for v in shown] == [RED, BLUE, RED]


def test_corrupt_image_is_skipped_with_a_warning(tmp_path, caplog):
    (tmp_path / "a-broken.png").write_bytes(b"\x89PNG\r\n\x1a\nthis is not a png")
    solid(tmp_path / "b-good.png", BLUE)
    card = ImageCard("img", {"path": str(tmp_path), "mode": "cover"})
    card.visit_pages()
    card.set_page(0)
    with caplog.at_level(logging.WARNING):
        frame = draw(card)
    assert frame.getpixel((480, 188)) == BLUE  # falls through to the next good image
    assert "skipping" in caplog.text and "a-broken.png" in caplog.text
    assert card.visit_pages() == 1  # known-bad file left out of the next pass
    # Replacing the file gives it another chance.
    solid(tmp_path / "a-broken.png", RED)
    assert card.visit_pages() == 2


def test_limits_skip_big_files_and_too_many_pixels(tmp_path, caplog):
    solid(tmp_path / "huge.png", RED, size=(3000, 2000))
    card = ImageCard("img", {"path": str(tmp_path / "huge.png"), "max_pixels": 1_000_000})
    card.visit_pages()
    card.set_page(0)
    with caplog.at_level(logging.WARNING):
        draw(card)
    assert "exceeds max_pixels" in caplog.text
    noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
    noise.save(tmp_path / "noise.png")  # ~120 kB, incompressible
    small = ImageCard("img", {"path": str(tmp_path / "noise.png"), "max_file_mb": 0.01})
    small.visit_pages()
    small.set_page(0)
    with caplog.at_level(logging.WARNING):
        draw(small)
    assert "larger than max_file_mb" in caplog.text


def test_max_files_limits_a_folder(tmp_path, caplog):
    for i in range(5):
        solid(tmp_path / f"{i}.png", RED)
    card = ImageCard("img", {"path": str(tmp_path), "max_files": 3})
    with caplog.at_level(logging.WARNING):
        assert card.visit_pages() == 3
    assert "max_files" in caplog.text


def test_missing_path_shows_a_message_instead_of_crashing(tmp_path, caplog):
    card = ImageCard("img", {"path": str(tmp_path / "nowhere")})
    with caplog.at_level(logging.WARNING):
        assert card.visit_pages() == 1
        card.set_page(0)
        frame = draw(card)
    assert frame.size == (960, 376)
    assert "does not exist" in caplog.text


def test_transparency_is_composed_over_the_background():
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    rgba.paste((255, 0, 0, 255), (25, 25, 75, 75))
    frame = compose(rgba, (960, 376), "contain", (10, 20, 30))
    assert frame.getpixel((480, 188)) == RED
    assert frame.getpixel((480 - 180, 188 - 180 + 5)) == (10, 20, 30)  # transparent corner
    assert frame.getpixel((5, 5)) == (10, 20, 30)  # letterbox


@pytest.mark.parametrize(
    "mode,size,inside,outside",
    [
        ("contain", (200, 200), (480, 188), (100, 188)),  # square -> 376x376, bars left/right
        ("cover", (200, 200), (5, 188), None),  # fills everything
        ("fit-width", (400, 100), (480, 188), (480, 10)),  # 960x240 centred, bars top/bottom
    ],
)
def test_modes(mode, size, inside, outside):
    frame = compose(Image.new("RGBA", size, (*BLUE, 255)), (960, 376), mode, (0, 0, 0))
    assert frame.size == (960, 376)
    assert frame.getpixel(inside) == BLUE
    if outside:
        assert frame.getpixel(outside) == (0, 0, 0)


def test_no_upscale_keeps_small_images_small():
    frame = compose(
        Image.new("RGBA", (50, 50), (*RED, 255)), (960, 376), "contain", (0, 0, 0), upscale=False
    )
    assert frame.getpixel((480, 188)) == RED
    assert frame.getpixel((480, 188 + 30)) == (0, 0, 0)


def test_gif_first_frame(tmp_path):
    first = Image.new("P", (40, 20), 0)
    first.putpalette([255, 0, 0] + [0, 0, 255] * 255)
    second = first.copy()
    second.paste(1, (0, 0, 40, 20))
    first.save(tmp_path / "anim.gif", save_all=True, append_images=[second], duration=100)
    card = ImageCard("img", {"path": str(tmp_path / "anim.gif"), "mode": "cover"})
    card.visit_pages()
    card.set_page(0)
    assert draw(card).getpixel((480, 188)) == RED


def test_example_images_render(tmp_path):
    shutil.copy(EXAMPLES / "images" / "logo.png", tmp_path / "logo.png")
    shutil.copy(EXAMPLES / "images" / "landscape.png", tmp_path / "landscape.png")
    card = ImageCard("img", {"path": str(tmp_path), "background": "#101218"})
    assert card.visit_pages() == 2
    with Image.open(tmp_path / "logo.png") as logo:
        assert logo.mode == "RGBA"  # the example really has transparency
    for page in range(2):
        card.set_page(page)
        assert draw(card).size == (960, 376)


def test_image_cards_keep_showing_without_collector_data(tmp_path, make_config):
    from aoostar_lcd.renderer import Renderer

    solid(tmp_path / "pic.png", BLUE)
    config = make_config(
        {"cards": [{"type": "cpu"}, {"type": "image", "path": "pic.png", "mode": "cover"}]}
    )
    renderer = Renderer(config)
    config.cards[1].visit_pages()
    config.cards[1].set_page(0)
    assert renderer.frame(1, None, "state is 99 s old").getpixel((480, 188)) == BLUE
    no_data = renderer.frame(0, None, "state is 99 s old")
    assert no_data.getpixel((5, 5)) == config.theme.color("crit")
