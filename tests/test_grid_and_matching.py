import pytest

from image_to_cash.drive.grid import parse_rows
from image_to_cash.drive.matching import MatchKind, canonical, classify, edit_distance


def test_clipboard_rows_split_on_tabs_and_line_breaks():
    copied = "true\tTax-free\tFree of Tax\t0.0\r\nfalse\tVAT 19%\tStandard\t0.19\n\n"
    assert parse_rows(copied) == (
        ("true", "Tax-free", "Free of Tax", "0.0"),
        ("false", "VAT 19%", "Standard", "0.19"),
    )


def test_clipboard_cells_keep_empty_columns():
    assert parse_rows("a\t\tc") == (("a", "", "c"),)


def test_empty_clipboard_has_no_rows():
    assert parse_rows("") == ()


@pytest.mark.parametrize(("a", "b", "distance"), [("", "", 0), ("abc", "abc", 0), ("abc", "abd", 1), ("10117", "1017", 1), ("kitten", "sitting", 3)])
def test_edit_distance(a, b, distance):
    assert edit_distance(a, b) == distance


def test_canonical_ignores_case_spacing_and_unicode_form():
    assert canonical("  Northstar   GMBH ") == canonical("northstar gmbh")
    assert canonical("Beusselstraße") == canonical("BEUSSELSTRASSE")
    assert canonical("Café") == canonical("Café")


EXPECTED = ("Northstar Office GmbH", "Marta", "Klein", "10117", "Berlin")


def test_one_exact_row_is_selected():
    rows = (("Other AG", "A", "B", "1", "X"), ("NORTHSTAR OFFICE GMBH", "Marta", "Klein", "10117", "Berlin"))
    result = classify(EXPECTED, rows)
    assert (result.kind, result.index) == (MatchKind.EXACT, 1)


def test_two_exact_rows_are_ambiguous():
    rows = (EXPECTED, EXPECTED)
    assert classify(EXPECTED, rows).kind is MatchKind.AMBIGUOUS


def test_small_difference_is_a_near_miss_not_a_new_record():
    rows = (("Northstar Office GmbH", "Marta", "Klein", "10177", "Berlin"),)
    result = classify(EXPECTED, rows)
    assert (result.kind, result.index) == (MatchKind.NEAR_MISS, 0)


def test_large_difference_means_no_match():
    rows = (("Northstar Office GmbH", "Jonas", "Weber", "80331", "Munich"),)
    assert classify(EXPECTED, rows).kind is MatchKind.NONE


def test_no_rows_means_no_match():
    result = classify(EXPECTED, ())
    assert (result.kind, result.index) == (MatchKind.NONE, None)


def test_exact_row_wins_over_a_near_miss():
    rows = (("Northstar Office GmbH", "Marta", "Klein", "10177", "Berlin"), EXPECTED)
    result = classify(EXPECTED, rows)
    assert (result.kind, result.index) == (MatchKind.EXACT, 1)


def test_row_with_another_width_cannot_match():
    with pytest.raises(ValueError, match="5 fields"):
        classify(EXPECTED, (("Northstar Office GmbH",),))
