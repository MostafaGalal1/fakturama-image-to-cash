"""The Debtor selector may accept its single hit late, by itself, while the bot copies its grid."""

from types import SimpleNamespace

import pytest

from image_to_cash.drive.backend.base import UnsafeToAct
from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama import debtor

GRID = Element(Role.OTHER, Rect(100, 100, 600, 300))


def context(dialog_open: bool) -> SimpleNamespace:
    return SimpleNamespace(ui=None, ocr=None, wb=SimpleNamespace(dialog_open=lambda title: dialog_open))


@pytest.fixture
def grid_with_rows(monkeypatch):
    monkeypatch.setattr(debtor, "has_rows", lambda ui, ocr, grid: True)
    monkeypatch.setattr(debtor, "measure_rows", lambda ui, ocr, grid: None)

    def copy_all(ui, grid, rows=None):
        raise UnsafeToAct("the control that was clicked has gone; refusing to send keys")

    monkeypatch.setattr(debtor, "copy_all", copy_all)


def test_a_selector_that_closed_by_itself_counts_as_picked(grid_with_rows):
    assert debtor._pick_row(context(dialog_open=False), (GRID,), debtor=None) is True


def test_a_copy_failure_with_the_selector_still_open_stops(grid_with_rows):
    with pytest.raises(UnsafeToAct):
        debtor._pick_row(context(dialog_open=True), (GRID,), debtor=None)
