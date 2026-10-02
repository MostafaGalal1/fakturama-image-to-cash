"""Fakturama's own warnings stop the run for review, with their message."""

from pathlib import Path

import pytest
from fake_backend import FakeBackend

from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.fakturama.workbench import Workbench
from image_to_cash.errors import NeedsReview

TEXT = Element(Role.LABEL, Rect(340, 380, 400, 30), value="There is already a contact with the same name and street:")
OK = Element(Role.BUTTON, Rect(1030, 445, 115, 22), title="OK")


class Warning(FakeBackend):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title

    def windows(self):
        return (Window(self.title, Rect(500, 320, 650, 160)),)

    def tree(self, window):
        return (TEXT, OK)


def test_a_duplicate_contact_warning_stops_for_review_and_stays_open():
    ui = Warning("Duplicate Contact")
    with pytest.raises(NeedsReview) as stop:
        Workbench(ui, Path("unused")).check_errors()
    assert stop.value.reason == "duplicate_contact" and "same name and street" in str(stop.value.details)
    assert ("press", OK.rect) not in ui.calls


def test_an_internal_error_is_acknowledged_then_stops():
    ui = Warning("Internal Error")
    with pytest.raises(NeedsReview):
        Workbench(ui, Path("unused")).check_errors()
    assert ("press", OK.rect) in ui.calls
