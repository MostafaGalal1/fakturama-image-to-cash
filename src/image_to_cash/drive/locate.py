"""Semantic locators over scanned elements: by label, help text or title, never by position (design §5).

A field belongs to the label on its left: same row, starting just after the label, and before the
next label on that row. Some labels own several fields ("First Name Last Name", "ZIP - City");
`nth` picks among them, left to right.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from image_to_cash.drive.elements import Element, Rect, Role

ROW_TOLERANCE = 6.0  # points between vertical centres that still count as one row
MAX_LABEL_GAP = 20.0  # points from a label's right edge to its first field
LABEL_OVERLAP = 2.0  # a field may start this far inside the label's frame


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
    anchor = label(elements, text).rect
    boundary = min(
        (e.rect.x for e in elements if e.role is Role.LABEL and _same_row(e.rect, anchor) and e.rect.x > anchor.right),
        default=math.inf,
    )
    fields = sorted(
        (
            e
            for e in elements
            if e.role is role
            and _same_row(e.rect, anchor)
            and anchor.right - LABEL_OVERLAP <= e.rect.x < boundary
        ),
        key=lambda e: e.rect.x,
    )
    if not fields or fields[0].rect.x - anchor.right > MAX_LABEL_GAP:
        raise LocatorError(f"no {role} right of label {text!r}")
    if nth >= len(fields):
        raise LocatorError(f"label {text!r} has {len(fields)} {role}(s), not {nth + 1}")
    return fields[nth]


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


def _same_row(a: Rect, b: Rect) -> bool:
    return abs(a.center[1] - b.center[1]) <= ROW_TOLERANCE


def _squash(text: str) -> str:
    return " ".join(text.split())
