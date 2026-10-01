import pytest
from PIL import Image, ImageDraw, ImageFont

from image_to_cash.ocr import Box, build_ocr


def test_box_center():
    assert Box(x=10, y=20, width=30, height=40).center == (25, 40)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="unknown OCR engine"):
        build_ocr("nope")


def render(text: str) -> Image.Image:
    image = Image.new("RGB", (1000, 200), "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black", font=ImageFont.load_default(size=48))
    return image


@pytest.mark.macos
def test_macos_vision_reads_rendered_text_with_top_left_boxes():
    boxes = build_ocr("macos-vision").recognize(render("WEB-2026-0714-A17"))
    joined = "".join(box.text for box in boxes).replace(" ", "")
    assert "WEB-2026-0714-A17" in joined
    first = boxes[0].box
    assert 0 <= first.x < 1000
    assert first.y < 80, "box must use a top-left origin (text was drawn near the top)"
    assert first.width > 0 and first.height > 0
