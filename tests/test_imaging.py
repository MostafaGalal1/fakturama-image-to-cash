import pytest
from PIL import Image

from image_to_cash.imaging import UPSCALE_FACTOR, for_ocr, load_image, upscale


def test_load_image_returns_rgb(tmp_path):
    path = tmp_path / "order.png"
    Image.new("RGBA", (10, 20), "white").save(path)
    image = load_image(path)
    assert image.mode == "RGB"
    assert image.size == (10, 20)


def test_load_image_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "missing.png")


def test_upscale_multiplies_size():
    image = Image.new("RGB", (10, 20), "white")
    assert upscale(image).size == (10 * UPSCALE_FACTOR, 20 * UPSCALE_FACTOR)


def test_for_ocr_returns_new_grayscale_image():
    image = Image.new("RGB", (10, 20), "white")
    prepared = for_ocr(image)
    assert prepared.mode == "L"
    assert image.mode == "RGB"
