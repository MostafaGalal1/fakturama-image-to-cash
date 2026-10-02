"""A scripted stand-in for a UI backend: records every call, and shows typed text as a field's value."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from image_to_cash.drive.elements import Element, Rect, Window
from image_to_cash.drive.layout import MAC_LAYOUT


class FakeBackend:
    layout = MAC_LAYOUT

    def __init__(self, display: Callable[[str], str] = lambda typed: typed) -> None:
        """`display` turns what was typed into what the field shows after Tab."""
        self.calls: list[tuple[str, object]] = []
        self._display = display
        self._focused: Element | None = None
        self._typed = ""
        self._values: dict[Rect, str | None] = {}

    def bring_to_front(self) -> None:
        self.calls.append(("front", None))

    def windows(self) -> tuple[Window, ...]:
        return ()

    def press_menu(self, path) -> None:
        self.calls.append(("menu", tuple(path)))

    def tree(self, window: Window) -> tuple[Element, ...]:
        return ()

    def scan(self, area: Rect) -> tuple[Element, ...]:
        return ()

    def refresh(self, element: Element) -> Element:
        return replace(element, value=self._values.get(element.rect, element.value))

    def press(self, element: Element) -> None:
        self.calls.append(("press", element.rect))

    def element_at(self, x: float, y: float) -> Element | None:
        return None

    def focused(self) -> Element | None:
        return self._focused

    def choose(self, popup: Element, option: str) -> None:
        self.calls.append(("choose", option))
        self._values[popup.rect] = option

    def options(self, popup: Element) -> tuple[str, ...]:
        return ()

    def focus(self, element: Element) -> None:
        self.calls.append(("focus", element.rect))
        self._focused, self._typed = element, ""

    def paste_text(self, text: str, into: Element) -> None:
        self.calls.append(("paste", text))
        self._values[into.rect] = text

    def click(self, element: Element, *, at: tuple[float, float] | None = None, count: int = 1) -> None:
        self.calls.append(("click", element.rect) if at is None and count == 1 else ("click", element.rect, at, count))
        self._focused, self._typed = element, ""

    def type_text(self, text: str) -> None:
        self.calls.append(("type", text))
        self._typed += text

    def key(self, chord: str) -> None:
        self.calls.append(("key", chord))
        if chord == "primary+a":
            self._typed = ""
        elif chord == "tab" and self._focused is not None:
            self._values[self._focused.rect] = self._display(self._typed)

    def copy_selection(self) -> str:
        return ""

    def capture(self, area: Rect, path: Path) -> Path:
        return path
