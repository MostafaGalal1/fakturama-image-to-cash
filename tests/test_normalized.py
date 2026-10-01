from decimal import Decimal

import pytest
from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.model import PaymentMethod
from image_to_cash.normalized import NormalizedOrder, gross_price, normalize, split_contact_name


def test_split_contact_name():
    assert split_contact_name("Marta Klein") == ("Marta", "Klein")


def test_split_contact_name_accepts_last_comma_first():
    assert split_contact_name("Klein, Anna Maria") == ("Anna Maria", "Klein")


@pytest.mark.parametrize("name", ["Anna Maria Klein", "Dr. Klein", "Marta K.", "Klein,", "Marta"])
def test_split_contact_name_refuses_to_guess(name):
    with pytest.raises(NeedsReview) as excinfo:
        split_contact_name(name)
    assert excinfo.value.reason == "contact_name_ambiguous"
    assert excinfo.value.details == {"contact_name": name}


def test_needs_review_message_includes_details():
    assert str(NeedsReview("conflicting_sku_lines", {"sku": "X-1"})) == "conflicting_sku_lines: sku=X-1"


def test_gross_price_for_sample_products():
    assert gross_price(Decimal("250.00"), Decimal("19")) == Decimal("297.50")
    assert gross_price(Decimal("40.00"), Decimal("19")) == Decimal("47.60")


def test_gross_price_rounds_half_up_on_ties():
    # 1.50 × 1.19 = 1.785: half-up gives 1.79, banker's rounding would give 1.78.
    assert gross_price(Decimal("1.50"), Decimal("19")) == Decimal("1.79")


def test_normalize_sample(sample_order):
    normalized = normalize(sample_order)
    debtor = normalized.debtor
    assert (debtor.first_name, debtor.last_name) == ("Marta", "Klein")
    assert debtor.delivery_differs is True
    assert normalized.source_customer_id == "CUST-1007"
    assert normalized.payment.method is PaymentMethod.BANK_TRANSFER
    assert normalized.totals == sample_order.totals
    assert [(p.sku, p.gross_price, p.vat_percent) for p in normalized.products] == [
        ("CHR-ERGO-01", Decimal("297.50"), Decimal("19")),
        ("MAT-DESK-02", Decimal("47.60"), Decimal("19")),
    ]
    assert [
        (line.sku, line.quantity, line.discount_percent, line.line_net_total)
        for line in normalized.lines
    ] == [
        ("CHR-ERGO-01", Decimal("2"), Decimal("10"), Decimal("450.00")),
        ("MAT-DESK-02", Decimal("3"), Decimal("0"), Decimal("120.00")),
    ]


def test_normalized_order_json_round_trip(sample_order):
    normalized = normalize(sample_order)
    assert NormalizedOrder.model_validate_json(normalized.model_dump_json()) == normalized


def test_same_billing_and_delivery_is_not_flagged(sample_order):
    order = sample_order.model_copy(update={"delivery_address": sample_order.billing_address})
    assert normalize(order).debtor.delivery_differs is False


def test_name_line_difference_alone_counts_as_different(sample_order):
    delivery = sample_order.billing_address.model_copy(update={"name": "Northstar Office Warehouse"})
    order = sample_order.model_copy(update={"delivery_address": delivery})
    assert normalize(order).debtor.delivery_differs is True


def test_same_sku_lines_with_different_quantity_share_one_product(sample_order):
    first = sample_order.items[0]
    second = first.model_copy(
        update={"quantity": Decimal("1"), "discount_percent": Decimal("0"), "line_net_total": Decimal("250.00")}
    )
    normalized = normalize(sample_order.model_copy(update={"items": (first, second)}))
    assert len(normalized.products) == 1
    assert [line.discount_percent for line in normalized.lines] == [Decimal("10"), Decimal("0")]


@pytest.mark.parametrize(
    "change",
    [{"unit_net_price": Decimal("260.00")}, {"description": "Other Chair"}, {"vat_percent": Decimal("7")}],
    ids=["price", "description", "vat"],
)
def test_conflicting_sku_lines_need_review(sample_order, change):
    first = sample_order.items[0]
    items = (first, first.model_copy(update=change))
    with pytest.raises(NeedsReview) as excinfo:
        normalize(sample_order.model_copy(update={"items": items}))
    assert excinfo.value.reason == "conflicting_sku_lines"
    assert excinfo.value.details == {"sku": "CHR-ERGO-01"}


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d | {"lines": [d["lines"][0] | {"sku": "UNKNOWN"}, d["lines"][1]]},
        lambda d: d | {"products": [d["products"][0], d["products"][0]]},
        lambda d: d | {"lines": [d["lines"][0] | {"vat_percent": "7"}, d["lines"][1]]},
        lambda d: d | {"debtor": d["debtor"] | {"first_name": " "}},
        lambda d: d | {"products": [d["products"][0] | {"gross_price": "-1.00"}, d["products"][1]]},
    ],
    ids=["line-sku-without-product", "duplicate-product", "line-vat-differs", "blank-name", "negative-gross"],
)
def test_edited_order_json_is_validated(sample_order, edit):
    data = edit(normalize(sample_order).model_dump(mode="json"))
    with pytest.raises(ValidationError):
        NormalizedOrder.model_validate(data)
