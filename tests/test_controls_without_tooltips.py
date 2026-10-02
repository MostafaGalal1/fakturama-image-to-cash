"""Windows exposes no tooltips on Fakturama's fields, pop-ups and icons: each control the flow
finds by tooltip on macOS is found by its label, value or place instead. Frames from Windows 11."""

import pytest

from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama import controls
from image_to_cash.drive.locate import LocatorError

ORDER = (
    Element(Role.LABEL, Rect(319, 147, 19, 16), value="No."),
    Element(Role.TEXT_FIELD, Rect(345, 145, 200, 19), value="PO000001"),
    Element(Role.POPUP, Rect(914, 144, 239, 20), value="Gross"),
    Element(Role.LABEL, Rect(315, 233, 54, 16), value="Addresses"),
    Element(Role.TEXT_AREA, Rect(376, 256, 410, 47), value=""),
    Element(Role.IMAGE, Rect(349, 257, 20, 20)),
    Element(Role.IMAGE, Rect(349, 285, 20, 20)),
    Element(Role.LABEL, Rect(842, 276, 20, 16), value="VAT"),
    Element(Role.POPUP, Rect(869, 274, 268, 20), value="With VAT"),
    Element(Role.LABEL, Rect(309, 322, 29, 16), value="Items"),
    Element(Role.IMAGE, Rect(318, 346, 20, 20)),
    Element(Role.IMAGE, Rect(322, 374, 16, 16)),
    Element(Role.LABEL, Rect(1215, 450, 20, 16), value="VAT"),
    Element(Role.TEXT_FIELD, Rect(1240, 449, 247, 19), value="0,00 €"),
    Element(Role.CHECKBOX, Rect(309, 462, 42, 16), title="paid", value="1"),
    Element(Role.LABEL, Rect(468, 462, 15, 16), value="at"),
    Element(Role.TEXT_FIELD, Rect(487, 461, 120, 19), value="Oct 2, 2026"),
    Element(Role.LABEL, Rect(624, 462, 30, 16), value="Value"),
    Element(Role.TEXT_FIELD, Rect(660, 459, 120, 19), value="0,00 €"),
)


@pytest.mark.parametrize(
    ("find", "index"),
    [
        (controls.document_number, 1),
        (controls.price_mode, 2),
        (controls.address_picker, 5),
        (controls.vat_mode, 8),
        (controls.item_picker, 10),
        (controls.paid_box, 14),
        (controls.payment_date, 16),
        (controls.paid_value, 18),
    ],
)
def test_order_and_invoice_controls_are_found_without_tooltips(find, index):
    assert find(ORDER) is ORDER[index]


def test_a_tooltip_wins_where_the_os_shows_one():
    with_help = (*ORDER, Element(Role.TEXT_FIELD, Rect(0, 0, 9, 9), help="Reference number of this document. Next"))
    assert controls.document_number(with_help) is with_help[-1]


def test_product_description_is_right_of_its_label():
    fields = (
        Element(Role.TEXT_AREA, Rect(430, 282, 565, 83)),
        Element(Role.LABEL, Rect(364, 315, 61, 16), value="Description"),
    )
    assert controls.product_description(fields) is fields[0]


def test_a_missing_control_still_stops():
    with pytest.raises(LocatorError):
        controls.paid_box(ORDER[:3])
