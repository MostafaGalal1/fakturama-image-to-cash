import json
from pathlib import Path

import pytest

from image_to_cash import cli

SAMPLE_IMAGE = Path(__file__).parent.parent / "samples" / "sales-order-input.png"
# Not legible at 385x530 even to a person (see tests/fixtures/sample_order.NOTES.md).
ILLEGIBLE_FIELDS = {"items[0].sku", "billing_address.street", "delivery_address.street", "customer.phone"}


@pytest.mark.macos
def test_supplied_image_goes_to_review_with_the_illegible_fields_flagged(tmp_path, sample_order_path):
    argv = ["extract", str(SAMPLE_IMAGE), "--fixture", str(sample_order_path), "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_REVIEW
    assert not (tmp_path / "order.json").exists()
    review = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert ILLEGIBLE_FIELDS <= {mismatch["field"] for mismatch in review["mismatches"]}
    assert review["issues"] == []
