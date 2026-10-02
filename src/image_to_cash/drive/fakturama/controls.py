"""Fakturama controls found by tooltip on macOS. Windows shows no tooltips on fields, pop-ups and
icons to UI Automation, so each one also has a second, still semantic way to be found: its
label, the values it can show, or its place as a section's first icon (frames in
tests/test_controls_without_tooltips.py)."""

from __future__ import annotations

from collections.abc import Sequence

from image_to_cash.drive.elements import Element, Role
from image_to_cash.drive.locate import by_help_or, by_title, by_value, image_below, right_of_label

PRICE_MODE_HELP = "Specify whether the prices"
VAT_MODE_HELP = "If this document is set to a tax rate"
PRICE_MODES = frozenset({"Gross", "Net", "---"})

Controls = Sequence[Element]


def document_number(controls: Controls) -> Element:
    return by_help_or(controls, Role.TEXT_FIELD, "Reference number of this document", lambda c: right_of_label(c, "No."))


def price_mode(controls: Controls) -> Element:
    return by_help_or(controls, Role.POPUP, PRICE_MODE_HELP, lambda c: by_value(c, Role.POPUP, PRICE_MODES))


def vat_mode(controls: Controls) -> Element:
    return by_help_or(controls, Role.POPUP, VAT_MODE_HELP, lambda c: right_of_label(c, "VAT", role=Role.POPUP))


def address_picker(controls: Controls) -> Element:
    return by_help_or(controls, Role.IMAGE, "Pick an address from the list", lambda c: image_below(c, "Addresses"))


def item_picker(controls: Controls) -> Element:
    return by_help_or(controls, Role.IMAGE, "Pick an item from the list", lambda c: image_below(c, "Items"))


def paid_box(controls: Controls) -> Element:
    return by_help_or(controls, Role.CHECKBOX, "Check this, if the invoice is paid", lambda c: by_title(c, Role.CHECKBOX, "paid"))


def payment_date(row: Controls) -> Element:
    return by_help_or(row, Role.TEXT_FIELD, "Date of the payment", lambda c: right_of_label(c, "at"))


def paid_value(row: Controls) -> Element:
    return by_help_or(row, Role.TEXT_FIELD, "The paid value", lambda c: right_of_label(c, "Value"))


def product_description(fields: Controls) -> Element:
    return by_help_or(
        fields, Role.TEXT_AREA, "Additional description", lambda c: right_of_label(c, "Description", role=Role.TEXT_AREA)
    )


def add_address_button(controls: Controls) -> Element:
    return by_help_or(controls, Role.BUTTON, "add a new address", lambda c: by_title(c, Role.BUTTON, "+"))
