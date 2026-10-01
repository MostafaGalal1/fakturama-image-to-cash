from decimal import Decimal

import pytest

from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import gross_price, normalize, split_contact_name


def test_split_contact_name():
    assert split_contact_name("Marta Klein") == ("Marta", "Klein")


def test_split_contact_name_rejects_ambiguous_names():
    with pytest.raises(NeedsReview) as excinfo:
        split_contact_name("Anna Maria Klein")
    assert excinfo.value.reason == "contact_name_ambiguous"


def test_gross_price_for_sample_products():
    assert gross_price(Decimal("250.00"), Decimal("19")) == Decimal("297.50")
    assert gross_price(Decimal("40.00"), Decimal("19")) == Decimal("47.60")


def test_gross_price_rounds_half_up():
    assert gross_price(Decimal("1.25"), Decimal("19")) == Decimal("1.49")


def test_normalize_sample(sample_order):
    normalized = normalize(sample_order)
    assert (normalized.debtor.first_name, normalized.debtor.last_name) == ("Marta", "Klein")
    assert normalized.debtor.delivery_differs is True
    assert normalized.source_customer_id == "CUST-1007"
    assert [p.gross_price for p in normalized.products] == [Decimal("297.50"), Decimal("47.60")]
    assert [line.sku for line in normalized.lines] == ["CHR-ERGO-01", "MAT-DESK-02"]


def test_same_billing_and_delivery_is_not_flagged(sample_order):
    order = sample_order.model_copy(update={"delivery_address": sample_order.billing_address})
    assert normalize(order).debtor.delivery_differs is False


def test_repeated_sku_lines_share_one_product(sample_order):
    first = sample_order.items[0]
    normalized = normalize(sample_order.model_copy(update={"items": (first, first)}))
    assert len(normalized.products) == 1
    assert len(normalized.lines) == 2


def test_conflicting_sku_lines_need_review(sample_order):
    first = sample_order.items[0]
    other_price = first.model_copy(update={"unit_net_price": Decimal("260.00")})
    with pytest.raises(NeedsReview) as excinfo:
        normalize(sample_order.model_copy(update={"items": (first, other_price)}))
    assert excinfo.value.reason == "conflicting_sku_lines"
