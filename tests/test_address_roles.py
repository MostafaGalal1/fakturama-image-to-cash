"""Closing the "address type" role window: ▶ closes it on macOS, Escape on Windows."""

from types import SimpleNamespace

from fake_backend import FakeBackend

from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.fakturama.debtor import (
    DELIVERY_ROLE,
    INVOICE_ROLE,
    _close_role_boxes,
)

TOGGLE = Element(Role.BUTTON, Rect(934, 505, 17, 19))
ROLE_WINDOW = Window("", Rect(946, 521, 248, 28))
BOXES = (
    Element(Role.CHECKBOX, Rect(950, 525, 100, 20), INVOICE_ROLE, "1"),
    Element(Role.CHECKBOX, Rect(1060, 525, 100, 20), DELIVERY_ROLE, "0"),
)


class RoleWindowBackend(FakeBackend):
    def __init__(self, closes_on: str) -> None:
        super().__init__()
        self.closes_on = closes_on
        self.open = True

    def windows(self):
        return (ROLE_WINDOW,) if self.open else ()

    def tree(self, window):
        return BOXES

    def press(self, element):
        super().press(element)
        self.open = self.open and self.closes_on != "press"

    def key(self, chord):
        super().key(chord)
        self.open = self.open and not (self.closes_on == "escape" and chord == "escape")


def test_the_toggle_closes_the_role_window_on_macos():
    ui = RoleWindowBackend(closes_on="press")
    _close_role_boxes(SimpleNamespace(ui=ui), TOGGLE)
    assert ("key", "escape") not in ui.calls and not ui.open


def test_escape_closes_the_role_window_when_the_toggle_reopens_it():
    ui = RoleWindowBackend(closes_on="escape")
    _close_role_boxes(SimpleNamespace(ui=ui), TOGGLE)
    assert ui.calls[-1] == ("key", "escape") and not ui.open
