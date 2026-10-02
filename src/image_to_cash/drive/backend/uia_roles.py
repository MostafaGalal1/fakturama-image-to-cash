"""Windows UI Automation control types mapped to neutral roles. Pure Python, so it runs on any OS.

Values are reported the way the macOS adapter reports them, so the flow reads both alike:
a checkbox is "1" or "0", a tab or radio button "True" or "False", a label's text its value.
"""

from __future__ import annotations

from dataclasses import dataclass

from image_to_cash.drive.backend.win_units import without_mnemonics
from image_to_cash.drive.elements import Element, Rect, Role

UIA_ROLES = {
    "Edit": Role.TEXT_FIELD,
    "Document": Role.TEXT_AREA,
    "Text": Role.LABEL,
    "Button": Role.BUTTON,
    "SplitButton": Role.BUTTON,
    "ComboBox": Role.POPUP,  # an editable one is a COMBO_BOX
    "CheckBox": Role.CHECKBOX,
    "RadioButton": Role.RADIO,
    "TabItem": Role.RADIO,  # SWT's tabs, which macOS reports as radio buttons too
    "Image": Role.IMAGE,
    "Hyperlink": Role.LINK,
    "Tab": Role.TAB_GROUP,
    "Window": Role.WINDOW,
}
FIELD_ROLES = frozenset({Role.TEXT_FIELD, Role.TEXT_AREA, Role.POPUP, Role.COMBO_BOX})


@dataclass(frozen=True)
class UiaRecord:
    """What the Windows adapter reads off one UI Automation element."""

    control_type: str  # ControlTypeName without its "Control" suffix, e.g. "Edit"
    rect: Rect
    name: str | None = None
    value: str | None = None  # the Value pattern, or a combo box's selected item
    help: str | None = None  # HelpText, else the MSAA description or help (SWT tooltips)
    enabled: bool = True
    multiline: bool = False  # an Edit with ES_MULTILINE
    editable: bool = False  # a ComboBox that holds an Edit
    toggled: int | None = None  # Toggle pattern: 0 off, 1 on, 2 indeterminate
    selected: bool | None = None  # SelectionItem pattern, or the MSAA selected/checked state


def element_from_uia(record: UiaRecord, handle: object = None) -> Element:
    native = record.control_type
    role = UIA_ROLES.get(native, Role.OTHER)
    if native == "Edit" and record.multiline:
        role = Role.TEXT_AREA
    if native == "ComboBox" and record.editable:
        role = Role.COMBO_BOX
    title, value = record.name, record.value
    if native == "TabItem" and title:
        title = without_mnemonics(title)  # a tab named "GmbH && Co" shows "GmbH & Co"
    if role is Role.LABEL:
        title, value = None, record.name
    elif role in FIELD_ROLES:
        title = None  # Windows names a field after the label before it; the flow finds that label itself
    if role is Role.CHECKBOX and record.toggled is not None:
        value = str(record.toggled)
    if role is Role.RADIO and record.selected is not None:
        value = str(record.selected)
    return Element(
        role=role,
        rect=record.rect,
        title=title or None,
        value=value,
        help=record.help or None,
        enabled=record.enabled,
        native_role=native,
        handle=handle,
    )
