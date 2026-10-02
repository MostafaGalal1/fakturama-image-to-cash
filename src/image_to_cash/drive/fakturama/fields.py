"""Typed field writes for Fakturama's editors, each read back before the run moves on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.backend.base import UiBackend
from image_to_cash.drive.elements import Element, Role
from image_to_cash.drive.fakturama.rules import date_keys
from image_to_cash.drive.formats import GERMAN, format_amount, parse_amount, parse_display_date, parse_percent
from image_to_cash.errors import NeedsReview

DATE_ATTEMPTS = 2
MONTH_SEGMENT_DX = 12  # the date field reads "Jul 14, 2026": its month segment comes first


def amount_holds(expected: Decimal):
    def holds(shown: str) -> bool:
        try:
            return parse_amount(shown, GERMAN) == expected
        except ValueError:
            return False

    return holds


def percent_holds(expected: Decimal):
    def holds(shown: str) -> bool:
        try:
            return parse_percent(shown, GERMAN) == expected
        except ValueError:
            return False

    return holds


def set_amount(ui: UiBackend, field: Element, value: Decimal, *, label: str) -> Element:
    """Money in the currency locale's style: 297.50 is typed as '297,50' (a '.' would be read as
    a grouping mark and give 29.750,00)."""
    return set_text(ui, field, format_amount(value, GERMAN), label=label, holds=amount_holds(value))


def set_date(ui: UiBackend, field: Element, when: date, *, label: str) -> Element:
    """Fakturama's date field edits one segment at a time and moves on by itself after each
    complete segment, so the month, day and year digits are typed from the month segment."""
    for _ in range(DATE_ATTEMPTS):
        ui.click(field, at=(field.rect.x + MONTH_SEGMENT_DX, field.rect.center[1]))
        for chunk in date_keys(when):
            ui.type_text(chunk)
        ui.key("tab")
        current = ui.refresh(field)
        try:
            if parse_display_date(current.value or "") == when:
                return current
        except ValueError:
            pass
    raise NeedsReview("field_wont_hold", {"field": label})


def choose_option(ui: UiBackend, popup: Element, option: str, *, label: str) -> None:
    """Pick an option that must exist; a missing one stops the run rather than picking another."""
    offered = ui.options(popup)
    if option not in offered:
        raise NeedsReview("option_missing", {"field": label, "option": option})
    ui.choose(popup, option)


def shown(ui: UiBackend, element: Element) -> str:
    return (ui.refresh(element).value or "").strip()


def button_inside(elements: Sequence[Element], field: Element) -> Element:
    """The small button drawn at the right end of a field (the address type's ▶)."""
    found = [
        e
        for e in elements
        if e.role is Role.BUTTON
        and abs(e.rect.y - field.rect.y) <= 2
        and field.rect.center[0] < e.rect.x <= field.rect.right  # drawn over the field's right end
    ]
    if len(found) != 1:
        raise NeedsReview("control_not_found", {"control": "button inside a field"})
    return found[0]
