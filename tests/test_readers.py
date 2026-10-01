import pytest
from PIL import Image

from image_to_cash.readers import ReaderError, build_reader


@pytest.fixture
def prepared_image() -> Image.Image:
    return Image.new("RGB", (40, 60), "white")


def test_fixture_reader_replays_recorded_order(sample_order_path, prepared_image, sample_order):
    reader = build_reader("fixture", fixture=sample_order_path)
    assert reader.read(prepared_image) == sample_order


def test_fixture_reader_requires_a_path():
    with pytest.raises(ValueError, match="--fixture"):
        build_reader("fixture")


def test_unknown_reader_is_rejected():
    with pytest.raises(ValueError, match="unknown image reader"):
        build_reader("nope")


def test_missing_fixture_raises_reader_error(tmp_path, prepared_image):
    reader = build_reader("fixture", fixture=tmp_path / "missing.json")
    with pytest.raises(ReaderError):
        reader.read(prepared_image)


def test_invalid_fixture_raises_reader_error(tmp_path, prepared_image):
    bad = tmp_path / "bad.json"
    bad.write_text('{"external_reference": "X"}', encoding="utf-8")
    with pytest.raises(ReaderError):
        build_reader("fixture", fixture=bad).read(prepared_image)
