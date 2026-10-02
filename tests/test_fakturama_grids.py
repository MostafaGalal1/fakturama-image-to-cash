from PIL import Image, ImageDraw

from image_to_cash.drive.fakturama.grids import row_drawn

WIDTH, HEIGHT = 3400, 18  # a first-row strip at 2x


def empty_row() -> Image.Image:
    strip = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(strip)
    for x in range(0, WIDTH, 200):  # light grey column lines
        draw.line([(x, 0), (x, HEIGHT)], fill=(215, 215, 215), width=2)
    return strip


def test_an_empty_row_is_not_drawn():
    assert not row_drawn(empty_row())


def test_dark_text_counts_as_a_row():
    strip = empty_row()
    ImageDraw.Draw(strip).rectangle([(210, 4), (330, 14)], fill=(20, 20, 20))
    assert row_drawn(strip)


def test_a_selected_row_counts_even_with_white_text():
    strip = empty_row()
    ImageDraw.Draw(strip).rectangle([(0, 0), (1200, HEIGHT)], fill=(179, 215, 255))
    assert row_drawn(strip)
