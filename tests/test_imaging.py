import pytest
from PIL import Image

from image_to_cash.imaging import MAX_LONG_EDGE, UPSCALE_FACTOR, for_ocr, load_image, upscale

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
EXIF_ORIENTATION = 0x0112
ROTATED_90_CW = 6


def test_load_image_returns_rgb(tmp_path):
    path = tmp_path / "order.png"
    Image.new("RGBA", (10, 20), "white").save(path)
    image = load_image(path)
    assert image.mode == "RGB"
    assert image.size == (10, 20)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_load_image_flattens_transparency_onto_white(tmp_path, mode):
    # A transparent pixel stored as black, next to an opaque black one.
    source = Image.frombytes("RGBA", (2, 1), bytes([0, 0, 0, 0, 0, 0, 0, 255]))
    path = tmp_path / "transparent.png"
    source.convert(mode).save(path)
    image = load_image(path)
    assert [image.getpixel((0, 0)), image.getpixel((1, 0))] == [WHITE, BLACK]


def test_load_image_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = ROTATED_90_CW
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (40, 20), "white").save(path, exif=exif)
    assert load_image(path).size == (20, 40)


def test_load_image_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "missing.png")


def test_load_image_rejects_non_image(tmp_path):
    path = tmp_path / "order.png"
    path.write_text("not an image", encoding="utf-8")
    with pytest.raises(OSError):
        load_image(path)


def test_load_image_rejects_oversized_image(tmp_path, monkeypatch):
    path = tmp_path / "huge.png"
    Image.new("RGB", (10, 20), "white").save(path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50)
    with pytest.raises(ValueError, match="too large"):
        load_image(path)


def test_upscale_multiplies_size():
    image = Image.new("RGB", (10, 20), "white")
    assert upscale(image).size == (10 * UPSCALE_FACTOR, 20 * UPSCALE_FACTOR)


def test_upscale_interpolates_instead_of_repeating_pixels():
    image = Image.frombytes("L", (2, 1), bytes([0, 255]))
    row = [upscale(image).getpixel((x, 0)) for x in range(2 * UPSCALE_FACTOR)]
    assert any(0 < value < 255 for value in row)


def test_upscale_lowers_factor_to_respect_long_edge_limit():
    image = Image.new("RGB", (MAX_LONG_EDGE // 2, 10), "white")
    assert upscale(image).size == (MAX_LONG_EDGE, 20)


def test_upscale_never_shrinks_large_images():
    image = Image.new("RGB", (MAX_LONG_EDGE + 1, 10), "white")
    assert upscale(image).size == image.size


@pytest.mark.parametrize("factor", [0, -1])
def test_upscale_rejects_factor_below_one(factor):
    with pytest.raises(ValueError, match="factor"):
        upscale(Image.new("RGB", (10, 20), "white"), factor)


def test_for_ocr_returns_new_grayscale_image():
    image = Image.new("RGB", (10, 20), "white")
    prepared = for_ocr(image)
    assert prepared.mode == "L"
    assert prepared is not image
    assert image.mode == "RGB"


def test_for_ocr_sharpens_edges():
    # Five rows of grey 100 above five rows of grey 200: sharpening overshoots both sides.
    image = Image.frombytes("L", (3, 10), bytes([100] * 15 + [200] * 15)).convert("RGB")
    prepared = for_ocr(image)
    assert prepared.getpixel((1, 4)) < 100
    assert prepared.getpixel((1, 5)) > 200
