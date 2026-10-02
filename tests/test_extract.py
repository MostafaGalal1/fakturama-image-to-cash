import json
import os
from decimal import Decimal

import pytest

from image_to_cash.extract import extract
from image_to_cash.imaging import UPSCALE_FACTOR
from image_to_cash.ocr import Box, TextBox
from image_to_cash.outputs import write_result
from image_to_cash.readers import FixtureReader
from image_to_cash.reconcile import critical_fields


class RecordingOcr:
    """Sees exactly the given texts and keeps a copy of the image it was handed."""

    def __init__(self, texts):
        self._boxes = tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)
        self.seen = None

    def recognize(self, image):
        self.seen = image.copy()
        return self._boxes


class PaintingReader:
    """Paints the image it is handed black, then replays the fixture."""

    def __init__(self, fixture_path):
        self._inner = FixtureReader(fixture_path)
        self.seen_size = None

    def read(self, image):
        self.seen_size = image.size
        image.paste((0, 0, 0), (0, 0, *image.size))
        return self._inner.read(image)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def write_fixture(path, order):
    path.write_text(order.model_dump_json(), encoding="utf-8")
    return path


def output_names(out_dir):
    return sorted(path.name for path in out_dir.iterdir())


def test_clean_extraction(sample_order_path, order_image, ocr_seeing_everything):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything)
    assert result.needs_review is False
    assert result.normalized is not None
    assert result.normalized.external_reference == "WEB-2026-0714-A17"


def test_unconfirmed_field_needs_review(sample_order_path, order_image, ocr_missing_first_sku):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku)
    assert result.needs_review is True
    assert [m.field for m in result.mismatches] == ["items[0].sku"]


def test_normalisation_failure_needs_review(tmp_path, sample_order, order_image, ocr_seeing_everything):
    customer = sample_order.customer.model_copy(update={"contact_name": "Anna Maria Klein"})
    fixture = write_fixture(tmp_path / "order.json", sample_order.model_copy(update={"customer": customer}))
    result = extract(order_image, FixtureReader(fixture), ocr_seeing_everything)
    assert result.needs_review is True
    assert result.normalized is None
    assert "contact_name_ambiguous" in {issue.code for issue in result.issues}


def test_arithmetic_issue_alone_needs_review(tmp_path, sample_order, order_image):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("679.30")})
    tampered = sample_order.model_copy(update={"totals": totals})
    fixture = write_fixture(tmp_path / "order.json", tampered)
    result = extract(order_image, FixtureReader(fixture), RecordingOcr(expected_texts(tampered)))
    assert result.mismatches == ()
    target = write_result(result, tmp_path / "out")
    assert target.name == "review.json"
    assert [issue["code"] for issue in json.loads(target.read_text())["issues"]] == ["gross_total_mismatch"]


def test_reader_gets_a_copy_and_ocr_gets_the_clean_greyscale_upscale(sample_order_path, sample_order, order_image):
    reader = PaintingReader(sample_order_path)
    ocr = RecordingOcr(expected_texts(sample_order))
    extract(order_image, reader, ocr)
    upscaled = (40 * UPSCALE_FACTOR, 60 * UPSCALE_FACTOR)
    assert reader.seen_size == upscaled
    assert (ocr.seen.mode, ocr.seen.size) == ("L", upscaled)
    assert ocr.seen.getpixel((0, 0)) == 255, "the reader's paint must not reach OCR"


def test_write_result_writes_order_json(tmp_path, sample_order_path, order_image, ocr_seeing_everything):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything)
    target = write_result(result, tmp_path / "out")
    assert target.name == "order.json"
    assert json.loads(target.read_text())["debtor"]["first_name"] == "Marta"


def test_write_result_writes_review_json(tmp_path, sample_order_path, order_image, ocr_missing_first_sku):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku)
    target = write_result(result, tmp_path / "out")
    payload = json.loads(target.read_text())
    assert target.name == "review.json"
    assert payload["reason"] == "1 field(s) not confirmed by OCR, 0 issue(s)"
    assert payload["source_image"] == str(order_image)
    assert payload["mismatches"] == [{"field": "items[0].sku", "expected": "CHR-ERG-01"}]
    assert payload["draft_order"]["external_reference"] == "WEB-2026-0714-A17"


def test_review_json_keeps_non_ascii_readable(tmp_path, sample_order, order_image):
    customer = sample_order.customer.model_copy(update={"company": "Müller & Söhne GmbH"})
    fixture = write_fixture(tmp_path / "order.json", sample_order.model_copy(update={"customer": customer}))
    target = write_result(extract(order_image, FixtureReader(fixture), RecordingOcr(())), tmp_path / "out")
    assert "Müller & Söhne GmbH" in target.read_text(encoding="utf-8")


def test_review_run_removes_an_earlier_order_json(
    tmp_path, sample_order_path, order_image, ocr_seeing_everything, ocr_missing_first_sku
):
    out = tmp_path / "out"
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything), out)
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku), out)
    assert output_names(out) == ["review.json"]


def test_clean_run_removes_an_earlier_review_json(
    tmp_path, sample_order_path, order_image, ocr_seeing_everything, ocr_missing_first_sku
):
    out = tmp_path / "out"
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku), out)
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything), out)
    assert output_names(out) == ["order.json"]


@pytest.mark.parametrize(
    "ocr_fixture", ["ocr_seeing_everything", "ocr_missing_first_sku"], ids=["order", "review"]
)
def test_failed_write_leaves_neither_file(
    tmp_path, monkeypatch, request, sample_order_path, order_image, ocr_fixture
):
    out = tmp_path / "out"
    result = extract(order_image, FixtureReader(sample_order_path), request.getfixturevalue(ocr_fixture))
    write_result(result, out)

    def disk_full(*_):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError):
        write_result(result, out)
    assert output_names(out) == []
