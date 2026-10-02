import pytest

from image_to_cash.drive.backend.ax_roles import element_from_record
from image_to_cash.drive.elements import Element, Rect, Role, distinct


def test_rect_edges_and_centre():
    rect = Rect(10, 20, 30, 40)
    assert (rect.right, rect.bottom) == (40, 60)
    assert rect.center == (25, 40)


def test_rect_rounds_to_whole_points_for_comparison():
    assert Rect(605.2, 271.6, 14.4, 13.5).rounded() == (605, 272, 14, 14)


def test_element_text_prefers_value_then_title():
    rect = Rect(0, 0, 1, 1)
    assert Element(Role.LABEL, rect, title="T", value="V").text == "V"
    assert Element(Role.BUTTON, rect, title="Save").text == "Save"
    assert Element(Role.IMAGE, rect).text == ""


def test_element_handle_is_ignored_in_equality():
    rect = Rect(0, 0, 1, 1)
    assert Element(Role.BUTTON, rect, handle=object()) == Element(Role.BUTTON, rect, handle=object())


@pytest.mark.parametrize(
    ("native", "neutral"),
    [
        ("AXTextField", Role.TEXT_FIELD),
        ("AXTextArea", Role.TEXT_AREA),
        ("AXStaticText", Role.LABEL),
        ("AXButton", Role.BUTTON),
        ("AXPopUpButton", Role.POPUP),
        ("AXComboBox", Role.COMBO_BOX),
        ("AXCheckBox", Role.CHECKBOX),
        ("AXRadioButton", Role.RADIO),
        ("AXImage", Role.IMAGE),
        ("AXLink", Role.LINK),
        ("AXTabGroup", Role.TAB_GROUP),
        ("AXWindow", Role.WINDOW),
        ("SWTComposite", Role.OTHER),
    ],
)
def test_ax_roles_map_to_neutral_roles(native, neutral):
    element = element_from_record({"role": native, "rect": [1, 2, 3, 4]})
    assert element.role is neutral
    assert element.native_role == native
    assert element.rect == Rect(1, 2, 3, 4)


@pytest.mark.parametrize(("raw", "enabled"), [(None, True), ("True", True), ("1", True), ("False", False), ("0", False)])
def test_enabled_flag_is_read_from_text(raw, enabled):
    assert element_from_record({"role": "AXButton", "rect": [0, 0, 1, 1], "enabled": raw}).enabled is enabled


def test_record_without_a_rect_is_rejected():
    with pytest.raises(ValueError, match="rect"):
        element_from_record({"role": "AXButton"})


def test_recorded_vat_editor_loads_with_its_fields(ax_snapshot):
    elements = ax_snapshot("vat_editor")
    labels = {element.text for element in elements if element.role is Role.LABEL}
    assert {"Name", "Category", "Description", "Value"} <= labels
    assert any(element.role is Role.POPUP and element.value == "S (Standard rate)" for element in elements)


def test_distinct_drops_the_same_control_reached_twice():
    box = Element(Role.CHECKBOX, Rect(605, 272, 14, 14), value="1")
    again = Element(Role.CHECKBOX, Rect(605.2, 271.9, 14, 14), value="1")  # via the table's column
    label = Element(Role.LABEL, Rect(620, 272, 79, 14), value="New TAX Rate")
    assert distinct((box, label, again)) == (box, label)


def test_distinct_keeps_different_roles_on_the_same_frame():
    rect = Rect(0, 0, 10, 10)
    elements = (Element(Role.LABEL, rect), Element(Role.TEXT_FIELD, rect))
    assert distinct(elements) == elements
