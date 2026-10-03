"""Semantic locators over scanned elements: by label, help text or title, never by position (design §5).

A field belongs to the label on its left: same row, starting just after the label's column, and
before the next label on that row. A column is the labels sharing a left edge: on Windows a label
is only as wide as its text, so a short one ends well before its field. Some labels own several
fields ("First Name Last Name", "ZIP - City"); `nth` picks among them, left to right.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

from image_to_cash.drive.elements import Element, Rect, Role

ROW_TOLERANCE = 6.0  # points between vertical centres that still count as one row
MAX_LABEL_GAP = 30.0  # points from a label's column to its first field (Price (gross) sits 22 off at 100 % on Windows)
LABEL_OVERLAP = 2.0  # a field may start this far inside the label's frame
ICON_COLUMN = 40.0  # points an icon may sit right of the label it belongs under


class LocatorError(LookupError):
    """No single element matches; the caller must stop instead of guessing."""


def label(elements: Sequence[Element], text: str) -> Element:
    wanted = _squash(text)
    found = [e for e in elements if e.role is Role.LABEL and _squash(e.text) == wanted]
    if len(found) != 1:
        raise LocatorError(f"{len(found)} labels {text!r}" if found else f"no label {text!r}")
    return found[0]


def right_of_label(
    elements: Sequence[Element], text: str, *, role: Role = Role.TEXT_FIELD, nth: int = 0
) -> Element:
    """The field of `role` right of the label `text`. Some screens repeat a label ("VAT" beside a
    pop-up and beside a total): then exactly one of them may have such a field."""
    anchors = labels(elements, text)
    owned = [fields for fields in (_fields_right_of(elements, a.rect, role) for a in anchors) if fields]
    if len(owned) > 1:
        raise LocatorError(f"{len(owned)} labels {text!r} have a {role} on their right")
    if not owned:
        raise LocatorError(f"no {role} right of label {text!r}")
    if nth >= len(owned[0]):
        raise LocatorError(f"label {text!r} has {len(owned[0])} {role}(s), not {nth + 1}")
    return owned[0][nth]


def labels(elements: Sequence[Element], text: str) -> list[Element]:
    wanted = _squash(text)
    found = [e for e in elements if e.role is Role.LABEL and _squash(e.text) == wanted]
    if not found:
        raise LocatorError(f"no label {text!r}")
    return found


def _fields_right_of(elements: Sequence[Element], anchor: Rect, role: Role) -> list[Element]:
    boundary = min(
        (e.rect.x for e in elements if e.role is Role.LABEL and _same_row(e.rect, anchor) and e.rect.x > anchor.right),
        default=math.inf,
    )
    fields = sorted(
        (
            e
            for e in elements
            if e.role is role and _same_row(e.rect, anchor) and anchor.right - LABEL_OVERLAP <= e.rect.x < boundary
        ),
        key=lambda e: e.rect.x,
    )
    if not fields or fields[0].rect.x - _column_right(elements, anchor) > MAX_LABEL_GAP:
        return []
    return fields


def by_help_or(
    elements: Sequence[Element], role: Role, help_prefix: str, otherwise: Callable[[Sequence[Element]], Element]
) -> Element:
    """By tooltip where the OS shows it to accessibility (macOS); otherwise by `otherwise`, which
    finds it by label, value or place (Windows shows no tooltips on fields and icons)."""
    if any(e.role is role and (e.help or "").startswith(help_prefix) for e in elements):
        return by_help(elements, role, help_prefix)
    return otherwise(elements)


def by_value(elements: Sequence[Element], role: Role, values: frozenset[str]) -> Element:
    found = [e for e in elements if e.role is role and e.value in values]
    if len(found) != 1:
        raise LocatorError(f"{len(found) or 'no'} {role} elements showing one of {sorted(values)}")
    return found[0]


def image_below(elements: Sequence[Element], text: str) -> Element:
    """The first icon under the label `text`, in its column: a section's first action."""
    anchor = label(elements, text).rect
    below = sorted(
        (
            e
            for e in elements
            if e.role is Role.IMAGE and e.rect.y >= anchor.bottom - LABEL_OVERLAP and abs(e.rect.x - anchor.x) <= ICON_COLUMN
        ),
        key=lambda e: e.rect.y,
    )
    if not below:
        raise LocatorError(f"no icon under label {text!r}")
    return below[0]


def by_help(elements: Sequence[Element], role: Role, help_prefix: str) -> Element:
    found = [e for e in elements if e.role is role and (e.help or "").startswith(help_prefix)]
    if len(found) != 1:
        raise LocatorError(f"{len(found) or 'no'} {role} elements with help starting {help_prefix!r}")
    return found[0]


def by_title(elements: Sequence[Element], role: Role, title: str) -> Element:
    found = [e for e in elements if e.role is role and e.title == title]
    if len(found) != 1:
        raise LocatorError(f"{len(found) or 'no'} {role} titled {title!r}")
    return found[0]


def _column_right(elements: Sequence[Element], anchor: Rect) -> float:
    """The right edge of the widest label left-aligned with `anchor`."""
    return max(
        (e.rect.right for e in elements if e.role is Role.LABEL and abs(e.rect.x - anchor.x) <= LABEL_OVERLAP),
        default=anchor.right,
    )


def _same_row(a: Rect, b: Rect) -> bool:
    return abs(a.center[1] - b.center[1]) <= ROW_TOLERANCE


def _squash(text: str) -> str:
    return " ".join(text.split())
