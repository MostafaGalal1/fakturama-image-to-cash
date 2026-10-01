import json

from image_to_cash.extract import extract
from image_to_cash.outputs import write_result
from image_to_cash.readers import FixtureReader


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
    fixture = tmp_path / "order.json"
    fixture.write_text(sample_order.model_copy(update={"customer": customer}).model_dump_json())
    result = extract(order_image, FixtureReader(fixture), ocr_seeing_everything)
    assert result.normalized is None
    assert "contact_name_ambiguous" in {issue.code for issue in result.issues}


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
    assert payload["mismatches"] == [{"field": "items[0].sku", "expected": "CHR-ERGO-01"}]
    assert payload["draft_order"]["external_reference"] == "WEB-2026-0714-A17"
