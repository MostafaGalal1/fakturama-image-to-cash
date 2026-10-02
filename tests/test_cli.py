import json
from decimal import Decimal

import pytest

from image_to_cash import cli


@pytest.fixture
def use_ocr(monkeypatch):
    def install(fake):
        monkeypatch.setattr(cli, "build_ocr", lambda name: fake)

    return install


def run_extract(order_image, sample_order_path, out_dir):
    return cli.main(
        ["extract", str(order_image), "--fixture", str(sample_order_path), "--out", str(out_dir)]
    )


def test_extract_clean_writes_order(tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything):
    use_ocr(ocr_seeing_everything)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_unconfirmed_writes_review(tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku):
    use_ocr(ocr_missing_first_sku)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_REVIEW
    assert (tmp_path / "review.json").is_file()


def test_approve_turns_review_draft_into_order(tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path / "x")
    code = cli.main(["approve", str(tmp_path / "x" / "review.json"), "--out", str(tmp_path / "ok")])
    assert code == cli.EXIT_OK
    order = json.loads((tmp_path / "ok" / "order.json").read_text())
    assert order["external_reference"] == "WEB-2026-0714-A17"


def test_approve_refuses_draft_that_breaks_invariants(tmp_path, sample_order):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "ok" / "order.json").exists()


def test_missing_image_is_a_clear_error(tmp_path, sample_order_path, capsys):
    code = run_extract(tmp_path / "missing.png", sample_order_path, tmp_path)
    assert code == cli.EXIT_ERROR
    assert "image not found" in capsys.readouterr().err


def test_failed_extract_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert run_extract(order_image, tmp_path / "missing.json", tmp_path) == cli.EXIT_ERROR
    assert not (tmp_path / "order.json").exists()


def test_refused_approve_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, sample_order
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path / "out")
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "out")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "out" / "order.json").exists()


def test_invalid_draft_is_refused_briefly_without_echoing_values(tmp_path, sample_order, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}))
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    error = capsys.readouterr().err
    assert "order_date" in error
    assert "SECRET-VALUE" not in error


def test_approve_refuses_an_ambiguous_contact_name(tmp_path, sample_order, capsys):
    customer = sample_order.customer.model_copy(update={"contact_name": "Anna Maria Klein"})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"customer": customer}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "contact_name_ambiguous" in capsys.readouterr().err
    assert not (tmp_path / "ok" / "order.json").exists()


def test_approve_refuses_a_draft_that_is_not_an_object(tmp_path, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text("[]")
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "not approved" in capsys.readouterr().err


def test_approve_in_the_extract_folder_keeps_the_review_as_a_record(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()
    assert (tmp_path / "review.json").is_file()


def test_approve_refuses_order_json_as_a_draft_and_keeps_it(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, capsys
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "order.json"), "--out", str(tmp_path)]) == cli.EXIT_ERROR
    assert "Stage 2's input" in capsys.readouterr().err
    assert (tmp_path / "order.json").is_file()
