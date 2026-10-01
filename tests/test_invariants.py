from decimal import Decimal

from image_to_cash.invariants import check_invariants, expected_line_net
from image_to_cash.model import PaidStatus


def codes(order):
    return {issue.code for issue in check_invariants(order)}


def test_sample_order_passes(sample_order):
    assert check_invariants(sample_order) == ()


def test_expected_line_net_applies_discount():
    assert expected_line_net(Decimal("2"), Decimal("250.00"), Decimal("10")) == Decimal("450.00")


def test_expected_line_net_rounds_half_up():
    assert expected_line_net(Decimal("1"), Decimal("0.125"), Decimal("0")) == Decimal("0.13")


def test_line_net_mismatch_is_reported(sample_order):
    first, *rest = sample_order.items
    broken_first = first.model_copy(update={"line_net_total": Decimal("500.00")})
    order = sample_order.model_copy(update={"items": (broken_first, *rest)})
    assert "line_net_mismatch" in codes(order)


def test_net_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"net": Decimal("571.00")})
    assert "net_total_mismatch" in codes(sample_order.model_copy(update={"totals": totals}))


def test_vat_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"vat": Decimal("100.00")})
    assert "vat_total_mismatch" in codes(sample_order.model_copy(update={"totals": totals}))


def test_gross_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("678.31")})
    assert codes(sample_order.model_copy(update={"totals": totals})) == {"gross_total_mismatch"}


def test_paid_without_date_is_reported(sample_order):
    payment = sample_order.payment.model_copy(update={"payment_date": None})
    assert codes(sample_order.model_copy(update={"payment": payment})) == {"paid_without_date"}


def test_unpaid_without_date_is_fine(sample_order):
    payment = sample_order.payment.model_copy(
        update={"status": PaidStatus.UNPAID, "payment_date": None}
    )
    assert codes(sample_order.model_copy(update={"payment": payment})) == set()


def test_unpaid_with_date_is_reported(sample_order):
    payment = sample_order.payment.model_copy(update={"status": PaidStatus.UNPAID})
    assert codes(sample_order.model_copy(update={"payment": payment})) == {"unpaid_with_date"}


def test_unsupported_currency_is_reported(sample_order):
    assert codes(sample_order.model_copy(update={"currency": "USD"})) == {"unsupported_currency"}


def test_invalid_email_is_reported(sample_order):
    customer = sample_order.customer.model_copy(update={"email": "marta.klein"})
    assert codes(sample_order.model_copy(update={"customer": customer})) == {"invalid_email"}
