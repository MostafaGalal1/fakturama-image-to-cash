"""The Windows backend's click timing, with the Win32 calls replaced (runs on Windows only)."""

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("the UI Automation backend runs on Windows only", allow_module_level=True)

from image_to_cash.drive.backend import windows_uia as uia  # noqa: E402
from image_to_cash.drive.backend.win_units import DoubleClick, Scale  # noqa: E402
from image_to_cash.drive.elements import Element, Rect, Role  # noqa: E402

ROW = Element(Role.OTHER, Rect(0, 0, 400, 200), handle="grid")


@pytest.fixture
def backend(monkeypatch):
    clock = {"now": 100.0}
    events = []
    monkeypatch.setattr(uia.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(uia.time, "sleep", lambda seconds: events.append(("sleep", round(seconds, 2))))
    monkeypatch.setattr(uia.win32, "click_at", lambda x, y, count: events.append(("click", x, y, count)))
    monkeypatch.setattr(uia, "_native", lambda handle: "Pane")
    ui = object.__new__(uia.WindowsUiaBackend)
    ui._scale = Scale(1.0)
    ui._double_click = DoubleClick(seconds=0.5, reach=2)
    ui._last_click = None
    ui._clicked = None
    monkeypatch.setattr(ui, "_rect", lambda handle: ROW.rect)
    monkeypatch.setattr(ui, "_on_top", lambda handle, x, y: True)
    monkeypatch.setattr(ui, "_guard", lambda: None)
    return ui, clock, events


def test_a_double_click_waits_out_an_earlier_click_on_the_same_spot(backend):
    """Else Windows pairs that click with the first half: the grid saw one click, and the VAT row
    it should have opened was only selected (100 % scaling, right after copying the list)."""
    ui, clock, events = backend
    ui.click(ROW, at=(150, 30))
    clock["now"] += 0.2
    ui.click(ROW, at=(150, 30), count=2)
    assert events == [("sleep", 0.0), ("click", 150, 30, 1), ("sleep", 0.3), ("click", 150, 30, 2)]


def test_a_double_click_elsewhere_does_not_wait(backend):
    ui, clock, events = backend
    ui.click(ROW, at=(150, 30))
    clock["now"] += 0.2
    ui.click(ROW, at=(150, 90), count=2)
    assert events[-2:] == [("sleep", 0.0), ("click", 150, 90, 2)]
