import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from image_to_cash.ocr import Box, OcrError, build_ocr


def test_box_center():
    assert Box(x=10, y=20, width=30, height=40).center == (25, 40)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="unknown OCR engine"):
        build_ocr("nope")


def test_missing_vision_framework_is_an_ocr_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "Vision", None)
    monkeypatch.delitem(sys.modules, "image_to_cash.ocr.macos_vision", raising=False)
    with pytest.raises(OcrError, match="pyobjc-framework-Vision"):
        build_ocr("macos-vision")


@pytest.mark.macos
@pytest.mark.parametrize(
    ("rect", "expected"),
    [
        ((0.0, 0.0, 1.0, 1.0), Box(0, 0, 200, 100)),
        ((0.1, 0.9, 0.5, 0.1), Box(20, 0, 100, 10)),
        ((0.1, 0.0, 0.5, 0.1), Box(20, 90, 100, 10)),
        ((-0.125, 0.9375, 0.5, 0.125), Box(0, 0, 75, 6)),
        ((0.75, -0.0625, 0.5, 0.125), Box(150, 94, 50, 6)),
    ],
    ids=["whole-image", "top-strip", "bottom-strip", "clamped-top-left", "clamped-bottom-right"],
)
def test_vision_rect_becomes_top_left_pixel_box(rect, expected):
    from image_to_cash.ocr.macos_vision import vision_rect_to_box  # imports Vision: macOS only

    assert vision_rect_to_box(*rect, width=200, height=100) == expected


VISION_PADDING_PX = 10  # Vision's boxes sit a few pixels outside the drawn glyphs


def render(text: str, origin: tuple[int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """A 1000x200 white image with `text` drawn at `origin`, plus the text's true bounding box."""
    image = Image.new("RGB", (1000, 200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text(origin, text, fill="black", font=font)
    return image, draw.textbbox(origin, text, font=font)


@pytest.mark.macos
@pytest.mark.parametrize("origin", [(20, 20), (500, 120)], ids=["top-left", "bottom-right"])
def test_macos_vision_box_matches_drawn_text(origin):
    image, truth = render("WEB-2026-0714-A17", origin)
    boxes = build_ocr("macos-vision").recognize(image)
    assert [box.text for box in boxes] == ["WEB-2026-0714-A17"]
    box = boxes[0].box
    edges = (box.x, box.y, box.x + box.width, box.y + box.height)
    assert all(abs(edge - true) <= VISION_PADDING_PX for edge, true in zip(edges, truth)), (edges, truth)
