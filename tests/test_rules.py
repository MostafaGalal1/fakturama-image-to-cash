from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.drive.fakturama.copied import AddressRow, DocumentRow, DocumentState, LineRow, PaymentRow, ProductRow, VatRow
from image_to_cash.drive.fakturama.rules import (
    PAYMENT_CODES,
    Decision,
    address_lines_match,
    check_document,
    check_line,
    date_keys,
    decide_debtor,
    decide_payment,
    decide_product,
    decide_vat,
    vat_name,
)
from image_to_cash.errors import NeedsReview
from image_to_cash.model import Address, PaymentMethod
from image_to_cash.normalized import Debtor, OrderLine, Product

BILLING = Address(name="Northstar Office GmbH", street="Friedrichstrasse 88", zip="10117", city="Berlin", country="Germany")
DELIVERY = Address(name="Northstar Office Warehouse", street="Beusselstrasse 44", zip="10553", city="Berlin", country="Germany")
DEBTOR = Debtor(
    company="Northstar Office GmbH",
    first_name="Marta",
    last_name="Klein",
    alias="NORTHSTAR-BERLIN",
    email="marta.klein@example.test",
    phone="+49 30 5550 1420",
    billing_address=BILLING,
    delivery_address=DELIVERY,
)
CHAIR = Product(sku="CHR-ERG-01", description="Ergonomic Desk Chair", gross_price=Decimal("297.50"), vat_percent=Decimal("19"))


def address(**changes):
    values = dict(
        customer_id="CUST000001",
        first_name="Marta",
        last_name="Klein",
        company="Northstar Office GmbH",
        zip="10117",
        city="Berlin",
        address_type="BILLING",
    )
    return AddressRow(**{**values, **changes})


def product(**changes):
    values = dict(
        sku="CHR-ERG-01",
        name="Ergonomic Desk Chair",
        description="Ergonomic Desk Chair",
        gross_price=Decimal("297.5"),
        vat_name="VAT 19%",
        vat_percent=Decimal("19"),
    )
    return ProductRow(**{**values, **changes})


# Names and keys


def test_vat_name_follows_the_brief():
    assert vat_name(Decimal("19")) == "VAT 19%"
    assert vat_name(Decimal("7.50")) == "VAT 7.5%"


def test_payment_codes_follow_the_brief_mapping():
    assert PAYMENT_CODES == {
        PaymentMethod.BANK_TRANSFER: "Credit transfer",
        PaymentMethod.CREDIT_CARD: "Credit card",
        PaymentMethod.SEPA_DIRECT_DEBIT: "SEPA direct debit",
    }


def test_date_keys_are_month_day_year_digits_for_the_segmented_date_field():
    assert date_keys(date(2026, 7, 4)) == ("07", "04", "2026")


# Debtor


def test_one_exact_debtor_row_is_reused():
    rows = (address(company="Other GmbH"), address())
    assert decide_debtor(rows, DEBTOR) == Decision.reuse(1)


def test_no_debtor_rows_means_create():
    assert decide_debtor((), DEBTOR) == Decision.create()


def test_a_debtor_with_another_zip_is_not_ours():
    assert decide_debtor((address(zip="80331", city="Munich"),), DEBTOR) == Decision.create()


def test_two_exact_debtor_rows_stop_the_run():
    with pytest.raises(NeedsReview, match="debtor_ambiguous"):
        decide_debtor((address(), address(customer_id="CUST000002")), DEBTOR)


def test_a_debtor_one_letter_off_stops_the_run_instead_of_creating_a_duplicate():
    with pytest.raises(NeedsReview, match="debtor_near_miss"):
        decide_debtor((address(last_name="Kleín"),), DEBTOR)


def test_address_text_must_show_street_zip_city_and_country():
    text = "Northstar Office GmbH\nMarta Klein\nFriedrichstrasse 88\nDE-10117 Berlin\nGermany"
    assert address_lines_match(text, DEBTOR, BILLING)
    assert not address_lines_match(text, DEBTOR, DELIVERY)
    assert not address_lines_match(text.replace("Marta Klein", "Marta Klain"), DEBTOR, BILLING)


# Products


def test_one_exact_sku_with_the_same_master_data_is_reused():
    assert decide_product((product(sku="CHR-ERG-010"), product()), CHAIR) == Decision.reuse(1)


def test_a_missing_sku_means_create():
    assert decide_product((product(sku="CHR-ERG-010"),), CHAIR) == Decision.create()


def test_an_existing_sku_with_another_price_stops_the_run():
    with pytest.raises(NeedsReview, match="product_conflict"):
        decide_product((product(gross_price=Decimal("300")),), CHAIR)


def test_an_existing_sku_with_another_vat_stops_the_run():
    with pytest.raises(NeedsReview, match="product_conflict"):
        decide_product((product(vat_name="VAT 7%", vat_percent=Decimal("7")),), CHAIR)


def test_two_rows_with_the_sku_stop_the_run():
    with pytest.raises(NeedsReview, match="product_ambiguous"):
        decide_product((product(), product()), CHAIR)


# VAT


def test_an_exact_vat_row_is_reused():
    rows = (VatRow(True, "Tax-free", "Free of Tax", Decimal("0")), VatRow(False, "VAT 19%", "VAT 19%", Decimal("19")))
    assert decide_vat(rows, Decimal("19")) == Decision.reuse(1)


def test_a_missing_vat_means_create():
    assert decide_vat((VatRow(True, "Tax-free", "Free of Tax", Decimal("0")),), Decimal("19")) == Decision.create()


def test_a_vat_named_right_with_another_rate_stops_the_run():
    with pytest.raises(NeedsReview, match="vat_conflict"):
        decide_vat((VatRow(False, "VAT 19%", "VAT 19%", Decimal("16")),), Decimal("19"))


def test_two_vat_rows_with_the_name_stop_the_run():
    row = VatRow(False, "VAT 19%", "VAT 19%", Decimal("19"))
    with pytest.raises(NeedsReview, match="vat_ambiguous"):
        decide_vat((row, row), Decimal("19"))


# Payment method


def test_an_exact_payment_method_is_reused():
    rows = (PaymentRow(False, "Bank Transfer", "Bank Transfer", Decimal("0"), 0, 0),)
    assert decide_payment(rows, PaymentMethod.BANK_TRANSFER) == Decision.reuse(0)


def test_a_missing_payment_method_means_create():
    rows = (PaymentRow(True, "Cash", "Pay Cash", Decimal("0"), 0, 0),)
    assert decide_payment(rows, PaymentMethod.BANK_TRANSFER) == Decision.create()


def test_a_payment_method_with_other_terms_stops_the_run():
    rows = (PaymentRow(False, "Bank Transfer", "Bank Transfer", Decimal("2"), 10, 30),)
    with pytest.raises(NeedsReview, match="payment_conflict"):
        decide_payment(rows, PaymentMethod.BANK_TRANSFER)


def test_two_payment_methods_with_the_name_stop_the_run():
    row = PaymentRow(False, "Bank Transfer", "Bank Transfer", Decimal("0"), 0, 0)
    with pytest.raises(NeedsReview, match="payment_ambiguous"):
        decide_payment((row, row), PaymentMethod.BANK_TRANSFER)


# Lines and documents

LINE = OrderLine(
    sku="CHR-ERG-01",
    quantity=Decimal("2"),
    unit_net_price=Decimal("250.00"),
    discount_percent=Decimal("10"),
    vat_percent=Decimal("19"),
    line_net_total=Decimal("450.00"),
)


def line_row(**changes):
    values = dict(
        quantity=Decimal("2"),
        sku="CHR-ERG-01",
        name="Ergonomic Desk Chair",
        vat_percent=Decimal("19"),
        unit_net_price=Decimal("250"),
        discount_percent=Decimal("10"),
        line_net_total=Decimal("450"),
    )
    return LineRow(**{**values, **changes})


def test_a_matching_line_passes():
    check_line(line_row(), LINE, position=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sku", "CHR-ERG-02"),
        ("quantity", Decimal("1")),
        ("unit_net_price", Decimal("249")),
        ("discount_percent", Decimal("0")),
        ("vat_percent", Decimal("7")),
        ("line_net_total", Decimal("500")),
    ],
)
def test_a_line_that_differs_anywhere_stops_the_run(field, value):
    with pytest.raises(NeedsReview, match="line_mismatch") as stop:
        check_line(line_row(**{field: value}), LINE, position=1)
    assert stop.value.details == {"position": "1", "field": field}


ORDER_ROW = DocumentRow(
    kind="ORDER",
    number="PO000001",
    date=date(2026, 7, 14),
    name="Northstar Office GmbH, Marta Klein",
    reference="WEB-2026-0714-A17",
    state=DocumentState.OPEN,
    total=Decimal("678.3"),
)


def test_the_saved_order_row_is_found_and_checked():
    check_document((ORDER_ROW,), number="PO000001", kind="ORDER", reference="WEB-2026-0714-A17", state=DocumentState.OPEN, total=Decimal("678.30"))


def test_a_missing_document_row_stops_the_run():
    with pytest.raises(NeedsReview, match="document_missing"):
        check_document((), number="PO000001", kind="ORDER", reference="R", state=DocumentState.OPEN, total=Decimal("1"))


def test_a_document_row_with_another_total_stops_the_run():
    with pytest.raises(NeedsReview, match="document_mismatch") as stop:
        check_document(
            (ORDER_ROW,), number="PO000001", kind="ORDER", reference="WEB-2026-0714-A17", state=DocumentState.OPEN, total=Decimal("600")
        )
    assert stop.value.details["field"] == "total"
