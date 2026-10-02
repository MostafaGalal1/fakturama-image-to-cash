"""OS-neutral view of on-screen controls: what every UI backend returns (design §3)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    TEXT_FIELD = "text_field"
    TEXT_AREA = "text_area"
    LABEL = "label"
    BUTTON = "button"
    POPUP = "popup"
    COMBO_BOX = "combo_box"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    IMAGE = "image"
    LINK = "link"
    TAB_GROUP = "tab_group"
    WINDOW = "window"
    OTHER = "other"


@dataclass(frozen=True)
class Rect:
    """Screen rectangle in points, origin top-left."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def holds(self, x: float, y: float) -> bool:
        return self.x <= x <= self.right and self.y <= y <= self.bottom

    def contains(self, other: Rect) -> bool:
        return (
            self.x <= other.x and self.y <= other.y and other.right <= self.right and other.bottom <= self.bottom
        )

    def rounded(self) -> tuple[int, int, int, int]:
        """Whole points, so frames read twice compare equal despite sub-point noise."""
        return (round(self.x), round(self.y), round(self.width), round(self.height))


@dataclass(frozen=True)
class Element:
    """One control as last read. `handle` is the backend's live reference, never compared."""

    role: Role
    rect: Rect
    title: str | None = None
    value: str | None = None
    help: str | None = None
    enabled: bool = True
    native_role: str | None = None
    handle: object = field(default=None, compare=False, hash=False, repr=False)

    @property
    def text(self) -> str:
        """What a person reads on it: a label's value, else a button's title."""
        return self.value or self.title or ""


@dataclass(frozen=True)
class Window:
    title: str
    rect: Rect
    handle: object = field(default=None, compare=False, hash=False, repr=False)


def distinct(elements: Iterable[Element]) -> tuple[Element, ...]:
    """Drop repeats of a control reached twice, e.g. a table cell listed under its row and its column."""
    seen: set[tuple[Role, tuple[int, int, int, int]]] = set()
    kept = []
    for element in elements:
        key = (element.role, element.rect.rounded())
        if key not in seen:
            seen.add(key)
            kept.append(element)
    return tuple(kept)
