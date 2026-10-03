from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.locate import image_below


def label(text, x, y, width):
    return Element(Role.LABEL, Rect(x, y, width, 15), value=text)


def icon(x, y):
    return Element(Role.IMAGE, Rect(x, y, 16, 16))


# The Order editor at 150 % scaling (points): the address icons sit 47 points in from the left
# edge of "Addresses", under its right half; the Items icons lie further down, nearer its left edge.
ADDRESS_PICKER, NEW_DEBTOR = icon(311, 235), icon(311, 255)
ITEM_PICKER = icon(283, 308)
ORDER_150 = (label("Addresses", 265, 216, 55), ADDRESS_PICKER, NEW_DEBTOR, label("Items", 262, 287, 32), ITEM_PICKER)


def test_the_first_icon_under_a_label_wins_even_well_inside_its_width():
    assert image_below(ORDER_150, "Addresses") == ADDRESS_PICKER


def test_each_section_keeps_its_own_icon():
    assert image_below(ORDER_150, "Items") == ITEM_PICKER


def test_an_icon_beyond_the_label_is_not_its_own():
    beyond = icon(330, 230)  # starts right of the label's end
    assert image_below((label("Addresses", 265, 216, 55), beyond, ADDRESS_PICKER), "Addresses") == ADDRESS_PICKER
