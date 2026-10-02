import json
from decimal import Decimal

import httpx
import pytest

from image_to_cash import cli
from image_to_cash.readers import OpenRouterReader, ReaderError
from image_to_cash.readers.openrouter import API_KEY_ENV, DEFAULT_MODEL


@pytest.fixture
def use_ocr(monkeypatch):
    def install(fake):
        monkeypatch.setattr(cli, "build_ocr", lambda name: fake)

    return install


def run_extract(order_image, sample_order_path, out_dir):
    return cli.main(
        ["extract", str(order_image), "--fixture", str(sample_order_path), "--out", str(out_dir)]
    )


def test_extract_clean_writes_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_unconfirmed_writes_review(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
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


def test_help_lists_the_exit_codes(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())  # argparse wraps to the terminal width
    assert "3 needs review" in help_text


def test_exit_codes_are_the_documented_contract():
    assert (cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_REVIEW) == (0, 1, 3)


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as stop:
        cli.main(["extract"])
    assert stop.value.code == 2


def test_review_message_names_the_next_step(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    out = capsys.readouterr().out
    assert "needs review: 1 unconfirmed field(s), 0 issue(s)" in out
    assert f"image-to-cash approve {tmp_path / 'review.json'}" in out


def test_approve_says_what_it_approved(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    capsys.readouterr()
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    approved = "approved WEB-2026-0714-A17: Northstar Office GmbH, 2 line(s), gross 678.30 EUR, PAID"
    assert approved in capsys.readouterr().out


@pytest.mark.parametrize("draft_name", ["missing.json", "binary.json", "broken.json"])
def test_unreadable_draft_leaves_no_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, draft_name
):
    use_ocr(ocr_seeing_everything)
    out = tmp_path / "out"
    run_extract(order_image, sample_order_path, out)
    (tmp_path / "binary.json").write_bytes(b"\x89PNG\xff")
    (tmp_path / "broken.json").write_text("{oops")
    assert cli.main(["approve", str(tmp_path / draft_name), "--out", str(out)]) != cli.EXIT_OK
    assert not (out / "order.json").exists()


def test_broken_json_draft_names_the_file(tmp_path, capsys):
    draft = tmp_path / "review.json"
    draft.write_text('{"draft_order": {},}')
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert f"{draft} is not valid JSON" in capsys.readouterr().err


def test_openrouter_without_a_key_is_a_clear_error(tmp_path, order_image, monkeypatch, capsys):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert API_KEY_ENV in capsys.readouterr().err


def test_extract_passes_the_model_to_the_reader(tmp_path, order_image, monkeypatch):
    requested = {}

    def build_reader(name, *, fixture=None, model=None):
        requested.update(name=name, fixture=fixture, model=model)
        raise ReaderError("stop before reading")

    monkeypatch.setattr(cli, "build_reader", build_reader)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--model", "vendor/model", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_ERROR
    assert requested == {"name": "openrouter", "fixture": None, "model": "vendor/model"}


def test_extract_with_openrouter_writes_order(
    tmp_path, order_image, sample_order, monkeypatch, use_ocr, ocr_seeing_everything
):
    reply = {"choices": [{"finish_reason": "stop", "message": {"content": sample_order.model_dump_json()}}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply))
    reader = OpenRouterReader("vendor/model", "test-key", transport=transport)
    monkeypatch.setattr(cli, "build_reader", lambda name, **options: reader)
    use_ocr(ocr_seeing_everything)
    argv = ["extract", str(order_image), "--reader", "openrouter", "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_help_names_the_default_model(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["extract", "--help"])
    assert exit_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--model" in help_text
    assert DEFAULT_MODEL in help_text


@pytest.mark.parametrize(
    ("platform", "path", "shown"),
    [
        ("darwin", "/tmp/out dir/review.json", "'/tmp/out dir/review.json'"),
        ("darwin", "/tmp/out/review.json", "/tmp/out/review.json"),
        ("win32", r"C:\Users\me\out\review.json", r"C:\Users\me\out\review.json"),
        ("win32", r"C:\Users\my name\review.json", r'"C:\Users\my name\review.json"'),
    ],
)
def test_paths_in_commands_are_quoted_for_the_platforms_shell(platform, path, shown):
    assert cli.shell_arg(path, platform) == shown
