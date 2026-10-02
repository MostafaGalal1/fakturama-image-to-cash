from datetime import date
from decimal import Decimal

import pytest

from image_to_cash.drive.formats import (
    ENGLISH,
    GERMAN,
    format_amount,
    format_percent,
    parse_amount,
    parse_display_date,
    parse_percent,
)


@pytest.mark.parametrize(
    ("value", "style", "typed"),
    [
        (Decimal("250"), GERMAN, "250,00"),
        (Decimal("1234.5"), GERMAN, "1234,50"),
        (Decimal("297.50"), ENGLISH, "297.50"),
    ],
)
def test_amounts_are_typed_with_two_decimals_and_no_grouping(value, style, typed):
    assert format_amount(value, style) == typed


@pytest.mark.parametrize(
    ("shown", "style", "value"),
    [
        ("0,00 €", GERMAN, Decimal("0.00")),
        ("-1.234,57 €", GERMAN, Decimal("-1234.57")),
        ("678,30 €", GERMAN, Decimal("678.30")),
        ("€1,234.57", ENGLISH, Decimal("1234.57")),
        ("0.00", ENGLISH, Decimal("0.00")),
        ("1234", GERMAN, Decimal("1234")),
    ],
)
def test_displayed_amounts_parse_in_their_style(shown, style, value):
    assert parse_amount(shown, style) == value


@pytest.mark.parametrize(("shown", "style"), [("1,234.57", GERMAN), ("12,34,5", GERMAN), ("", GERMAN), ("abc", ENGLISH)])
def test_amount_in_the_wrong_style_is_rejected(shown, style):
    with pytest.raises(ValueError, match="not an amount"):
        parse_amount(shown, style)


@pytest.mark.parametrize(
    ("value", "style", "typed"),
    [(Decimal("19.00"), GERMAN, "19"), (Decimal("10"), GERMAN, "10"), (Decimal("7.5"), GERMAN, "7,5"), (Decimal("0"), ENGLISH, "0")],
)
def test_percentages_are_typed_without_trailing_zeros(value, style, typed):
    assert format_percent(value, style) == typed


@pytest.mark.parametrize(
    ("shown", "style", "value"),
    [("0%", GERMAN, Decimal("0")), ("19 %", GERMAN, Decimal("19")), ("7,5%", GERMAN, Decimal("7.5")), ("10.00%", ENGLISH, Decimal("10"))],
)
def test_displayed_percentages_parse(shown, style, value):
    assert parse_percent(shown, style) == value


def test_percentage_without_a_number_is_rejected():
    with pytest.raises(ValueError, match="not a percentage"):
        parse_percent("%", GERMAN)


@pytest.mark.parametrize(
    ("shown", "value"),
    [("Oct 2, 2026", date(2026, 10, 2)), ("Jul 14, 2026", date(2026, 7, 14)), ("14.07.2026", date(2026, 7, 14)), ("2026-07-14", date(2026, 7, 14))],
)
def test_display_dates_parse(shown, value):
    assert parse_display_date(shown) == value


def test_unknown_date_format_is_rejected():
    with pytest.raises(ValueError, match="not a date"):
        parse_display_date("07/14/2026")
