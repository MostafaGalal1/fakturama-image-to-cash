from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.drive.fakturama.copied import (
    AddressRow,
    DocumentRow,
    DocumentState,
    LineRow,
    PaymentRow,
    ProductRow,
    VatRow,
    parse_address_rows,
    parse_document_rows,
    parse_line_rows,
    parse_payment_rows,
    parse_product_rows,
    parse_vat_rows,
)

VAT_19 = (
    "VAT taxValue: [0.19] salesEqualizationTax: [null] description: [VAT 19%] name: [VAT 19%] "
    "dateAdded: [Fri Oct 02 00:00:00 EEST 2026] modifiedBy: [someone] modified: [null] id: [2] "
    "deleted: [false] validFrom: [Fri Oct 02 00:00:00 EEST 2026] validTo: [null]"
)


def test_vat_list_rows_hold_name_description_and_rate_as_a_fraction():
    rows = parse_vat_rows("true\tTax-free\tFree of Tax\t0.0\nfalse\tVAT 19%\tVAT 19%\t0.19")
    assert rows == (
        VatRow(standard=True, name="Tax-free", description="Free of Tax", percent=Decimal("0")),
        VatRow(standard=False, name="VAT 19%", description="VAT 19%", percent=Decimal("19")),
    )


def test_payment_list_rows():
    rows = parse_payment_rows("true\tCash\tPay Cash\t0.0\t0\t0\nfalse\tBank Transfer\tBank Transfer\t0.0\t0\t0")
    assert rows[1] == PaymentRow(
        standard=False,
        name="Bank Transfer",
        description="Bank Transfer",
        discount_percent=Decimal("0"),
        discount_days=0,
        net_days=0,
    )


def test_address_selector_rows():
    copied = "CUST000001\tMarta\tKlein\tNorthstar Office GmbH\t10117\tBerlin\tBILLING\tnull\tnull"
    assert parse_address_rows(copied) == (
        AddressRow(
            customer_id="CUST000001",
            first_name="Marta",
            last_name="Klein",
            company="Northstar Office GmbH",
            zip="10117",
            city="Berlin",
            address_type="BILLING",
        ),
    )


def test_address_selector_reads_null_as_blank():
    (row,) = parse_address_rows("CUST000002\tnull\tKlein\tnull\t10117\tBerlin\tBILLING\tnull\tnull")
    assert (row.first_name, row.company) == ("", "")


def test_product_selector_rows_carry_gross_price_and_vat():
    copied = f"CHR-ERG-01\tErgonomic Desk Chair\tErgonomic Desk Chair\tnull\t297.5\t{VAT_19}"
    assert parse_product_rows(copied) == (
        ProductRow(
            sku="CHR-ERG-01",
            name="Ergonomic Desk Chair",
            description="Ergonomic Desk Chair",
            gross_price=Decimal("297.5"),
            vat_name="VAT 19%",
            vat_percent=Decimal("19"),
        ),
    )


def test_order_line_rows_turn_the_stored_discount_fraction_into_a_percentage():
    copied = (
        f"2.00\tCHR-ERG-01\tnull\tErgonomic Desk Chair\t\t{VAT_19}\tEUR 250\t-0.1\tEUR 450\n"
        f"3.00\tMAT-DESK-02\tnull\tAnti-Fatigue Desk Mat\t\t{VAT_19}\tEUR 40\t0.0\tEUR 120"
    )
    first, second = parse_line_rows(copied)
    assert first == LineRow(
        quantity=Decimal("2"),
        sku="CHR-ERG-01",
        name="Ergonomic Desk Chair",
        vat_percent=Decimal("19"),
        unit_net_price=Decimal("250"),
        discount_percent=Decimal("10"),
        line_net_total=Decimal("450"),
    )
    assert second.discount_percent == Decimal("0")


def test_document_rows():
    copied = (
        "ICON_INVOICE\tINV000001\tFri Oct 02 00:00:00 EEST 2026\tNorthstar Office GmbH, Marta Klein\t"
        "WEB-2026-0714-A17\tCOMMAND_CHECKED\t678.3\tnull\n"
        "ICON_ORDER\tPO000001\tTue Jul 14 00:00:00 EEST 2026\tNorthstar Office GmbH, Marta Klein\t"
        "WEB-2026-0714-A17\tCOMMAND_ORDER_PENDING\t678.3\tnull"
    )
    invoice, order = parse_document_rows(copied)
    assert order == DocumentRow(
        kind="ORDER",
        number="PO000001",
        date=date(2026, 7, 14),
        name="Northstar Office GmbH, Marta Klein",
        reference="WEB-2026-0714-A17",
        state=DocumentState.OPEN,
        total=Decimal("678.3"),
    )
    assert (invoice.kind, invoice.state) == ("INVOICE", DocumentState.PAID)


def test_an_unknown_document_state_is_kept_raw_rather_than_guessed():
    (row,) = parse_document_rows("ICON_INVOICE\tINV9\tFri Oct 02 00:00:00 EEST 2026\tX\tR\tCOMMAND_SOMETHING\t1.0\tnull")
    assert row.state == "COMMAND_SOMETHING"


@pytest.mark.parametrize(
    ("parse", "copied"),
    [
        (parse_vat_rows, "true\tTax-free\tFree of Tax"),
        (parse_payment_rows, "true\tCash\tPay Cash\t0.0\t0"),
        (parse_address_rows, "CUST1\tMarta"),
        (parse_product_rows, "CHR\tName\tDesc\tnull\t297.5"),
        (parse_line_rows, "2.00\tCHR"),
        (parse_document_rows, "ICON_ORDER\tPO1"),
    ],
)
def test_a_row_with_missing_columns_is_rejected(parse, copied):
    with pytest.raises(ValueError, match="columns"):
        parse(copied)


def test_a_vat_cell_without_a_rate_is_rejected():
    copied = "2.00\tCHR\tnull\tName\t\tVAT name: [VAT 19%]\tEUR 250\t0.0\tEUR 250"
    with pytest.raises(ValueError, match="VAT"):
        parse_line_rows(copied)


def test_a_price_in_another_currency_is_rejected():
    copied = f"2.00\tCHR\tnull\tName\t\t{VAT_19}\tUSD 250\t0.0\tUSD 250"
    with pytest.raises(ValueError, match="EUR"):
        parse_line_rows(copied)
