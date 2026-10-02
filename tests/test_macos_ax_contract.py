"""Backend contract against the running Fakturama (design §8). Opt-in: FAKTURAMA_LIVE=1.

It needs the Mac to itself, because it brings Fakturama to the front, clicks and types. It saves
nothing: each editor it opens is closed with every "Save Parts" box unticked.
"""

import os
import time

import pytest

from image_to_cash.drive.elements import Rect, Role
from image_to_cash.drive.locate import LocatorError, by_title, right_of_label

pytestmark = [
    pytest.mark.macos,
    pytest.mark.skipif(
        os.environ.get("FAKTURAMA_LIVE") != "1",
        reason="set FAKTURAMA_LIVE=1, with Fakturama running and nobody using the Mac",
    ),
]

TAB_STRIP = 26  # points of tab buttons above an editor's contents
WAIT_SECONDS = 5.0


@pytest.fixture
def backend():
    from image_to_cash.drive.backend.macos_ax import MacAxBackend

    backend = MacAxBackend.attach()
    yield backend
    close_all_without_saving(backend)


def main_window(backend):
    (window,) = [w for w in backend.windows() if w.title.startswith("Fakturama - ")]
    return window


def editor_area(backend) -> Rect:
    groups = [e for e in backend.tree(main_window(backend)) if e.role is Role.TAB_GROUP]
    top = min(groups, key=lambda group: group.rect.y).rect
    return Rect(top.x, top.y + TAB_STRIP, top.width, top.height - TAB_STRIP)


def open_vat_editor(backend):
    backend.press_menu(("New", "New VAT"))
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        elements = backend.scan(editor_area(backend))
        try:
            right_of_label(elements, "Value")
            return elements
        except LocatorError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def close_all_without_saving(backend):
    backend.press_menu(("File", "Close All"))
    for _ in range(10):
        time.sleep(1.0)
        dialogs = [w for w in backend.windows() if w.title == "Save Parts"]
        if not dialogs:
            return
        elements = backend.tree(dialogs[0])
        boxes = [e for e in elements if e.role is Role.CHECKBOX]
        for box in boxes:
            if backend.refresh(box).value == "1":
                backend.press(box)
        assert all(backend.refresh(box).value == "0" for box in boxes), "a part is still ticked: not pressing OK"
        backend.press(by_title(elements, Role.BUTTON, "OK"))
    pytest.fail("Save Parts dialogs kept appearing")


def test_main_window_is_listed(backend):
    assert main_window(backend).rect.width > 0


def test_text_is_typed_and_read_back(backend):
    name = right_of_label(open_vat_editor(backend), "Name")
    backend.bring_to_front()
    backend.click(name)
    backend.type_text("contract test ü")
    backend.key("tab")
    assert backend.refresh(name).value == "contract test ü"


def test_popup_option_is_chosen(backend):
    code = right_of_label(open_vat_editor(backend), "VAT code (E-Invoice)", role=Role.POPUP)
    backend.choose(code, "S (Standard rate)")
    assert backend.refresh(code).value == "S (Standard rate)"


def test_area_is_captured(backend, tmp_path):
    shot = backend.capture(main_window(backend).rect, tmp_path / "main.png")
    assert shot.stat().st_size > 0
