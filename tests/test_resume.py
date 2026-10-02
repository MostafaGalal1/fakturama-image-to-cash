"""A re-run never enters an order twice: what is already saved for its reference decides."""

from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.drive.fakturama.copied import DocumentRow, DocumentState
from image_to_cash.drive.fakturama.resume import decide_earlier
from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import normalize

REF = "WEB-2026-0714-A17"


@pytest.fixture
def order(sample_order):
    return normalize(sample_order)


def row(kind, number, state, total="678.30", reference=REF):
    return DocumentRow(kind, number, date(2026, 7, 14), "Northstar Office GmbH", reference, state, Decimal(total))


ORDER = row("ORDER", "PO000002", DocumentState.OPEN)
INVOICE = row("INVOICE", "INV000002", DocumentState.PAID)
OTHER = row("ORDER", "PO000009", DocumentState.OPEN, reference="WEB-2026-0714-A170")  # the search matched it too


def test_nothing_saved_starts_fresh(order):
    earlier = decide_earlier((OTHER,), order)
    assert earlier.order is None and earlier.invoice is None


def test_a_saved_order_without_invoice_resumes_at_the_invoice(order):
    earlier = decide_earlier((OTHER, ORDER), order)
    assert earlier.order == ORDER and earlier.invoice is None and earlier.order_row == 1


def test_order_and_paid_invoice_mean_already_entered(order):
    earlier = decide_earlier((ORDER, INVOICE), order)
    assert (earlier.order, earlier.invoice) == (ORDER, INVOICE)


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ((ORDER, row("ORDER", "PO000003", DocumentState.OPEN)), "already_entered"),
        ((INVOICE,), "already_entered"),
        ((ORDER, row("INVOICE", "INV000002", DocumentState.UNPAID)), "already_entered_differently"),
        ((row("ORDER", "PO000002", DocumentState.OPEN, total="700.00"),), "already_entered_differently"),
    ],
)
def test_anything_else_goes_to_a_person(order, rows, reason):
    with pytest.raises(NeedsReview) as stop:
        decide_earlier(rows, order)
    assert stop.value.reason == reason
