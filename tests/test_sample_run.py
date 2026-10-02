import json
from pathlib import Path

import pytest

from image_to_cash import cli

SAMPLES = Path(__file__).parent.parent / "samples"
ORIGINAL_IMAGE = SAMPLES / "sales-order-input-clean.png"
PIXELATED_IMAGE = SAMPLES / "sales-order-input.png"
# Not legible on the pixelated 385x530 copy, even to a person (see tests/fixtures/sample_order.NOTES.md).
ILLEGIBLE_FIELDS = {"items[0].sku", "billing_address.street", "delivery_address.street", "customer.phone"}
# Best readings taken from the pixelated copy; the original prints something else.
MISREADINGS = {
    "customer.phone": "+49 30 3550 1420",
    "delivery_address.street": "Huttenstrasse 41",
    "items[0].sku": "CHR-ERGO-01",
}


def extract(image: Path, fixture: Path, out: Path) -> int:
    return cli.main(["extract", str(image), "--fixture", str(fixture), "--out", str(out)])


@pytest.mark.macos
def test_original_image_confirms_every_critical_field(tmp_path, sample_order_path):
    assert extract(ORIGINAL_IMAGE, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()
    assert not (tmp_path / "review.json").exists()


@pytest.mark.macos
def test_original_image_catches_the_misreadings_of_the_pixelated_copy(tmp_path, sample_order):
    recorded = sample_order.model_dump(mode="json")
    misread = recorded | {
        "customer": recorded["customer"] | {"phone": MISREADINGS["customer.phone"]},
        "delivery_address": recorded["delivery_address"] | {"street": MISREADINGS["delivery_address.street"]},
        "items": [recorded["items"][0] | {"sku": MISREADINGS["items[0].sku"]}, *recorded["items"][1:]],
    }
    fixture = tmp_path / "misread.json"
    fixture.write_text(json.dumps(misread), encoding="utf-8")
    out = tmp_path / "out"
    assert extract(ORIGINAL_IMAGE, fixture, out) == cli.EXIT_REVIEW
    review = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert {mismatch["field"]: mismatch["expected"] for mismatch in review["mismatches"]} == MISREADINGS


@pytest.mark.macos
def test_pixelated_copy_goes_to_review_with_the_illegible_fields_flagged(tmp_path, sample_order_path):
    assert extract(PIXELATED_IMAGE, sample_order_path, tmp_path) == cli.EXIT_REVIEW
    assert not (tmp_path / "order.json").exists()
    review = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert ILLEGIBLE_FIELDS <= {mismatch["field"] for mismatch in review["mismatches"]}
    assert review["issues"] == []
