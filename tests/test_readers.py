import json

import pytest
from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers import ReaderError, build_reader
from image_to_cash.readers.base import MAX_ISSUES_SHOWN, describe_validation_error

MAX_MESSAGE_LENGTH = 600


@pytest.fixture
def prepared_image() -> Image.Image:
    return Image.new("RGB", (40, 60), "white")


def test_fixture_reader_replays_recorded_order(sample_order_path, prepared_image, sample_order):
    reader = build_reader("fixture", fixture=sample_order_path)
    assert reader.read(prepared_image) == sample_order


def test_fixture_reader_reads_the_path_it_was_given(tmp_path, prepared_image, sample_order):
    other = tmp_path / "other.json"
    other_order = sample_order.model_copy(update={"external_reference": "OTHER-1"})
    other.write_text(other_order.model_dump_json(), encoding="utf-8")
    assert build_reader("fixture", fixture=other).read(prepared_image).external_reference == "OTHER-1"


def test_fixture_reader_requires_a_path():
    with pytest.raises(ValueError, match="--fixture"):
        build_reader("fixture")


def test_unknown_reader_is_rejected():
    with pytest.raises(ValueError, match="unknown image reader"):
        build_reader("nope")


def test_missing_fixture_raises_reader_error(tmp_path, prepared_image):
    reader = build_reader("fixture", fixture=tmp_path / "missing.json")
    with pytest.raises(ReaderError, match="missing.json"):
        reader.read(prepared_image)


def test_non_utf8_fixture_raises_reader_error(tmp_path, prepared_image):
    latin1 = tmp_path / "latin1.json"
    latin1.write_bytes(b'{"external_reference": "\xe9"}')
    with pytest.raises(ReaderError, match="latin1.json"):
        build_reader("fixture", fixture=latin1).read(prepared_image)


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"surprise": 1}', '{"external_reference": "X"}'])
def test_invalid_fixture_raises_a_short_reader_error(tmp_path, prepared_image, content):
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(ReaderError, match="bad.json") as caught:
        build_reader("fixture", fixture=bad).read(prepared_image)
    assert len(str(caught.value)) < MAX_MESSAGE_LENGTH


def test_invalid_fixture_message_omits_the_offending_value(tmp_path, prepared_image, sample_order):
    fixture = tmp_path / "order.json"
    recorded = sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}
    fixture.write_text(json.dumps(recorded), encoding="utf-8")
    with pytest.raises(ReaderError, match="order_date") as caught:
        build_reader("fixture", fixture=fixture).read(prepared_image)
    assert "SECRET-VALUE" not in str(caught.value)


def test_validation_summary_lists_a_few_problems_and_counts_the_rest():
    with pytest.raises(ValidationError) as caught:
        Order.model_validate({})
    hidden = len(caught.value.errors()) - MAX_ISSUES_SHOWN
    summary = describe_validation_error(caught.value)
    assert hidden > 0
    assert summary.count(";") == MAX_ISSUES_SHOWN - 1
    assert summary.endswith(f"(+{hidden} more)")
