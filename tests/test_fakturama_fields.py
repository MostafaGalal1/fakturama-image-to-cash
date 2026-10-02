from datetime import date
from decimal import Decimal

import pytest
from fake_backend import FakeBackend

from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama.fields import amount_holds, button_inside, choose_option, percent_holds, set_amount, set_date
from image_to_cash.errors import NeedsReview

ADDRESS_TYPE = Element(Role.TEXT_FIELD, Rect(463, 514, 458, 21), None, "", None)
TOGGLE = Element(Role.BUTTON, Rect(919, 514, 16, 21), None, None, None)  # measured live: overhangs the field


def test_the_button_at_a_fields_right_end_is_found_even_where_it_overhangs():
    others = (Element(Role.BUTTON, Rect(1450, 338, 33, 20), "+", None, None),)
    assert button_inside((*others, TOGGLE, ADDRESS_TYPE), ADDRESS_TYPE) is TOGGLE


def test_no_button_at_the_fields_end_stops_the_run():
    with pytest.raises(NeedsReview, match="control_not_found"):
        button_inside((ADDRESS_TYPE,), ADDRESS_TYPE)


def test_amounts_hold_in_the_german_currency_style_only():
    holds = amount_holds(Decimal("297.50"))
    assert holds("297,50\xa0€")
    assert not holds("29.750,00\xa0€")  # what typing "297.50" produces
    assert not holds("")


def test_percentages_hold_with_or_without_a_space():
    assert percent_holds(Decimal(19))("19%")
    assert percent_holds(Decimal(0))("0 %")
    assert not percent_holds(Decimal(19))("1,9%")


def test_an_amount_is_typed_with_a_decimal_comma():
    ui = FakeBackend(display=lambda typed: f"{typed}\xa0€")
    field = Element(Role.TEXT_FIELD, Rect(455, 390, 126, 21), None, "0,00\xa0€", None)
    set_amount(ui, field, Decimal("297.50"), label="gross_price")
    assert ("type", "297,50") in ui.calls


def test_a_date_is_typed_month_day_year_from_the_month_segment():
    ui = FakeBackend(display=lambda typed: "Jul 14, 2026" if typed == "07142026" else typed)
    field = Element(Role.TEXT_FIELD, Rect(746, 163, 133, 21), None, "Oct 2, 2026", None)
    set_date(ui, field, date(2026, 7, 14), label="order_date")
    assert ui.calls[0] == ("click", field.rect, (758, field.rect.center[1]), 1)
    assert [call for call in ui.calls if call[0] == "type"] == [("type", "07"), ("type", "14"), ("type", "2026")]


def test_a_date_that_does_not_hold_stops_the_run():
    ui = FakeBackend(display=lambda typed: "Oct 2, 1420")
    field = Element(Role.TEXT_FIELD, Rect(746, 163, 133, 21), None, "Oct 2, 2026", None)
    with pytest.raises(NeedsReview, match="field_wont_hold"):
        set_date(ui, field, date(2026, 7, 14), label="order_date")


def test_a_missing_option_stops_the_run_instead_of_picking_another():
    class NoBankTransfer(FakeBackend):
        def options(self, popup):
            return ("Pay Cash",)

    popup = Element(Role.POPUP, Rect(1021, 424, 469, 20), None, "Pay Cash", None)
    with pytest.raises(NeedsReview, match="option_missing"):
        choose_option(NoBankTransfer(), popup, "Bank Transfer", label="payment_method")
