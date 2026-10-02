from decimal import Decimal

from image_to_cash.extract import extract
from image_to_cash.ocr import Box, TextBox
from image_to_cash.outputs import write_result
from image_to_cash.pinned import pin_by_arithmetic
from image_to_cash.readers import FixtureReader
from image_to_cash.reconcile import Mismatch, critical_fields

# What Windows OCR left out of the clean sample: two discount cells and one of the two "19%".
WINDOWS_MISSES = (
    Mismatch("items[0].discount_percent", "10%"),
    Mismatch("items[1].discount_percent", "0%"),
    Mismatch("items[1].vat_percent", "19%"),
)


def with_item(order, index, **changes):
    items = list(order.items)
    items[index] = items[index].model_copy(update=changes)
    return order.model_copy(update={"items": tuple(items)})


def test_the_sums_confirm_every_cell_windows_ocr_missed(sample_order):
    left, pinned = pin_by_arithmetic(sample_order, WINDOWS_MISSES)
    assert left == ()
    assert pinned == tuple(m.field for m in WINDOWS_MISSES)


def test_a_discount_needs_its_line_total_confirmed(sample_order):
    missed = (Mismatch("items[0].discount_percent", "10%"), Mismatch("items[0].line_net_total", "450.00"))
    left, pinned = pin_by_arithmetic(sample_order, missed)
    assert left == missed
    assert pinned == ()


def test_two_unseen_vat_rates_stay_unconfirmed(sample_order):
    """Swapped rates on lines with equal nets would give the same VAT total."""
    missed = (Mismatch("items[0].vat_percent", "19%"), Mismatch("items[1].vat_percent", "19%"))
    assert pin_by_arithmetic(sample_order, missed) == (missed, ())


def test_a_vat_rate_needs_the_vat_total_confirmed(sample_order):
    missed = (Mismatch("items[1].vat_percent", "19%"), Mismatch("totals.vat", "108.30"))
    assert pin_by_arithmetic(sample_order, missed)[1] == ()


def test_a_reading_that_breaks_the_sum_is_not_confirmed(sample_order):
    order = with_item(sample_order, 0, discount_percent=Decimal("11"))
    missed = (Mismatch("items[0].discount_percent", "11%"),)
    assert pin_by_arithmetic(order, missed) == (missed, ())


def test_a_sum_that_other_percentages_also_fit_confirms_nothing(sample_order):
    """1 × 0.10 less 10% is 0.09 to the cent, and so is less 10.01%."""
    order = with_item(sample_order, 0, quantity=Decimal("1"), unit_net_price=Decimal("0.10"), line_net_total=Decimal("0.09"))
    missed = (Mismatch("items[0].discount_percent", "10%"),)
    assert pin_by_arithmetic(order, missed) == (missed, ())


def test_other_fields_are_left_alone(sample_order):
    missed = (Mismatch("items[0].sku", "CHR-ERG-01"), Mismatch("totals.vat", "108.30"))
    assert pin_by_arithmetic(sample_order, missed) == (missed, ())


class Ocr:
    def __init__(self, texts):
        self._boxes = tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)

    def recognize(self, image):
        return self._boxes


def windows_ocr(order):
    """Every critical value once, except the percent cells Windows OCR left out."""
    seen = [expected for field, expected in critical_fields(order) if field not in {m.field for m in WINDOWS_MISSES}]
    return Ocr(tuple(seen))


def test_extract_writes_order_json_when_the_sums_confirm_the_missing_cells(tmp_path, sample_order_path, sample_order, order_image):
    result = extract(order_image, FixtureReader(sample_order_path), windows_ocr(sample_order))
    assert result.needs_review is False
    assert result.pinned == tuple(m.field for m in WINDOWS_MISSES)
    assert write_result(result, tmp_path / "out").name == "order.json"
