"""macOS accessibility roles mapped to neutral ones. Pure Python, so snapshots load on any OS."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from image_to_cash.drive.elements import Element, Rect, Role

AX_ROLES = {
    "AXTextField": Role.TEXT_FIELD,
    "AXTextArea": Role.TEXT_AREA,
    "AXStaticText": Role.LABEL,
    "AXButton": Role.BUTTON,
    "AXPopUpButton": Role.POPUP,
    "AXComboBox": Role.COMBO_BOX,
    "AXCheckBox": Role.CHECKBOX,
    "AXRadioButton": Role.RADIO,
    "AXImage": Role.IMAGE,
    "AXLink": Role.LINK,
    "AXTabGroup": Role.TAB_GROUP,
    "AXWindow": Role.WINDOW,
}
DISABLED = frozenset({"False", "0"})


def element_from_record(record: Mapping[str, object], handle: object = None) -> Element:
    """Build an Element from attribute values read off one AX element (or a recorded snapshot)."""
    rect = record.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError(f"element record needs a rect [x, y, width, height], got {rect!r}")
    native = str(record.get("role"))
    return Element(
        role=AX_ROLES.get(native, Role.OTHER),
        rect=Rect(*(float(part) for part in rect)),
        title=_text(record.get("title")),
        value=_text(record.get("value")),
        help=_text(record.get("help")),
        enabled=str(record.get("enabled")) not in DISABLED,
        native_role=native,
        handle=handle,
    )


def elements_from_records(records: Iterable[Mapping[str, object]]) -> tuple[Element, ...]:
    return tuple(element_from_record(record) for record in records)


def _text(value: object) -> str | None:
    return None if value is None else str(value)
