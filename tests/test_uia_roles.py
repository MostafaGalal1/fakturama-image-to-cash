from image_to_cash.drive.backend.uia_roles import UiaRecord, element_from_uia
from image_to_cash.drive.elements import Rect, Role

FRAME = Rect(10, 20, 100, 21)


def element(control_type, **fields):
    return element_from_uia(UiaRecord(control_type, FRAME, **fields))


def test_a_label_reads_as_its_text():
    label = element("Text", name="Cust.Ref.")
    assert (label.role, label.text, label.title) == (Role.LABEL, "Cust.Ref.", None)


def test_a_field_keeps_its_value_but_not_the_name_windows_gives_it():
    field = element("Edit", name="Cust.Ref.", value="WEB-2026-0714-A17")
    assert (field.role, field.value, field.title) == (Role.TEXT_FIELD, "WEB-2026-0714-A17", None)


def test_a_multiline_edit_is_a_text_area():
    assert element("Edit", multiline=True).role is Role.TEXT_AREA


def test_combo_boxes_are_pop_ups_unless_editable():
    assert element("ComboBox", value="Net").role is Role.POPUP
    assert element("ComboBox", editable=True).role is Role.COMBO_BOX


def test_checkboxes_and_tabs_report_their_state_like_macos():
    assert element("CheckBox", name="paid", toggled=1).value == "1"
    assert element("CheckBox", name="paid", toggled=0).value == "0"
    tab = element("TabItem", name="Miscellaneous", selected=True)
    assert (tab.role, tab.title, tab.value) == (Role.RADIO, "Miscellaneous", "True")


def test_a_button_is_found_by_its_tooltip():
    button = element("Button", name="Save", help="Save the current contents")
    assert (button.role, button.title, button.help) == (Role.BUTTON, "Save", "Save the current contents")


def test_other_controls_keep_their_native_type():
    grid = element("Pane")
    assert (grid.role, grid.native_role) == (Role.OTHER, "Pane")


def test_disabled_and_empty_texts():
    field = element("Edit", enabled=False, help="")
    assert not field.enabled and field.help is None
