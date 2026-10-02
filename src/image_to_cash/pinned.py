"""Percent cells OCR could not see, confirmed by exact arithmetic (design §4, step 4).

Windows OCR leaves out short, isolated table cells such as "10%". Such a cell still counts as
confirmed when it is the only unknown in one of the brief's own sums (§3.16 the line price,
§4.3 the VAT total), every other value in that sum was confirmed by OCR, and no other
percentage to the hundredth gives the same printed cents. A reading is confirmed, never
corrected: one that breaks its sum stays unconfirmed, and the invariants report the sum.

Two unseen VAT rates are never confirmed this way: swapped rates on lines with equal nets give
the same VAT total.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal

from image_to_cash.invariants import expected_line_net, money, vat_total
from image_to_cash.model import Order
from image_to_cash.reconcile import Mismatch

STEP = Decimal("0.01")  # the finest percentage a document prints
PERCENT_CELL = re.compile(r"items\[(\d+)\]\.(discount_percent|vat_percent)")


def pin_by_arithmetic(order: Order, mismatches: tuple[Mismatch, ...]) -> tuple[tuple[Mismatch, ...], tuple[str, ...]]:
    """The mismatches the sums leave unconfirmed, and the fields they confirmed, in order."""
    unseen = frozenset(mismatch.field for mismatch in mismatches)
    pinned = tuple(mismatch.field for mismatch in mismatches if _pinned(order, mismatch.field, unseen))
    return tuple(mismatch for mismatch in mismatches if mismatch.field not in pinned), pinned


def _pinned(order: Order, field: str, unseen: frozenset[str]) -> bool:
    cell = PERCENT_CELL.fullmatch(field)
    if cell is None:
        return False
    index = int(cell.group(1))
    if cell.group(2) == "discount_percent":
        return _discount_pinned(order, index, unseen)
    return _vat_pinned(order, index, unseen)


def _discount_pinned(order: Order, index: int, unseen: frozenset[str]) -> bool:
    """§3.16: quantity × unit price × (1 − discount/100) is the printed line total."""
    if unseen & {f"items[{index}].{part}" for part in ("quantity", "unit_net_price", "line_net_total")}:
        return False
    item = order.items[index]
    return _only_fit(
        lambda percent: expected_line_net(item.quantity, item.unit_net_price, percent),
        item.discount_percent,
        money(item.line_net_total),
    )


def _vat_pinned(order: Order, index: int, unseen: frozenset[str]) -> bool:
    """§4.3: Σ(line net × VAT%) is the printed VAT total."""
    others = {f"items[{other}].vat_percent" for other in range(len(order.items)) if other != index}
    nets = {f"items[{line}].line_net_total" for line in range(len(order.items))}
    if "totals.vat" in unseen or unseen & (others | nets):
        return False

    def total_with(percent: Decimal) -> Decimal:
        rates = (percent if line == index else item.vat_percent for line, item in enumerate(order.items))
        return vat_total((item.line_net_total, rate) for item, rate in zip(order.items, rates, strict=True))

    return _only_fit(total_with, order.items[index].vat_percent, money(order.totals.vat))


def _only_fit(total: Callable[[Decimal], Decimal], percent: Decimal, printed: Decimal) -> bool:
    """`percent` gives the printed cents and its neighbours do not. Each sum moves one way with
    the percentage, so no other value to the hundredth gives them either."""
    return total(percent) == printed and total(percent - STEP) != printed and total(percent + STEP) != printed
