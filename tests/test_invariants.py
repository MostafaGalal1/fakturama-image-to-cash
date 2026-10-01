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


def test_mixed_vat_rates_are_applied_per_line(sample_order):
    first, second = sample_order.items
    items = (first, second.model_copy(update={"vat_percent": Decimal("7")}))
    totals = sample_order.totals.model_copy(
        update={"vat": Decimal("93.90"), "gross": Decimal("663.90")}
    )
    order = sample_order.model_copy(update={"items": items, "totals": totals})
    assert check_invariants(order) == ()


def test_vat_is_rounded_once_on_the_sum(sample_order):
    # 2 lines of 0.50 at 19%: rounding per line gives 0.10 + 0.10 = 0.20; the convention gives 0.19.
    line = sample_order.items[1].model_copy(
        update={"quantity": Decimal("1"), "unit_net_price": Decimal("0.50"), "line_net_total": Decimal("0.50")}
    )
    totals = sample_order.totals.model_copy(
        update={"net": Decimal("1.00"), "vat": Decimal("0.19"), "gross": Decimal("1.19")}
    )
    clean = sample_order.model_copy(update={"items": (line, line), "totals": totals})
    assert check_invariants(clean) == ()
    per_line = totals.model_copy(update={"vat": Decimal("0.20"), "gross": Decimal("1.20")})
    assert codes(clean.model_copy(update={"totals": per_line})) == {"vat_total_mismatch"}


def test_one_cent_line_difference_names_line_and_sku(sample_order):
    first, *rest = sample_order.items
    off_by_cent = first.model_copy(update={"line_net_total": Decimal("450.01")})
    order = sample_order.model_copy(update={"items": (off_by_cent, *rest)})
    line_issues = [i for i in check_invariants(order) if i.code == "line_net_mismatch"]
    assert len(line_issues) == 1
    assert line_issues[0].message.startswith("line 1 (CHR-ERGO-01):")


def test_total_messages_name_what_they_compare(sample_order):
    totals = sample_order.totals.model_copy(update={"net": Decimal("571")})
    order = sample_order.model_copy(update={"totals": totals})
    messages = {issue.code: issue.message for issue in check_invariants(order)}
    assert messages["net_total_mismatch"] == (
        "net total: printed line nets sum to 570.00, printed total is 571.00"
    )
