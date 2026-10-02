"""Backend contract against the running Fakturama on Windows (design §8). Opt-in: FAKTURAMA_LIVE=1.

The Windows twin of test_macos_ax_contract.py. It brings Fakturama to the front, clicks and types,
so nobody may use the PC (or the VM's window) while it runs. It saves nothing: each editor it opens
is closed on its own, answering No to "Save changes?".

`test_print_calibration` prints what the flow assumes about Fakturama's layout (tab folders, the
main toolbar's tooltips, the list rows): run it with `-s` and compare with WINDOWS_LAYOUT.
"""

import os
import time

import pytest

from image_to_cash.drive.elements import Role
from image_to_cash.drive.fakturama.workbench import Workbench
from image_to_cash.drive.locate import LocatorError, by_title, right_of_label

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        os.environ.get("FAKTURAMA_LIVE") != "1",
        reason="set FAKTURAMA_LIVE=1, with Fakturama running and nobody using the PC",
    ),
]

WAIT_SECONDS = 5.0
FLOW_TOOLTIPS = ("Create: New Order", "Save the current contents")  # main-toolbar buttons the flow presses


@pytest.fixture
def backend():
    from image_to_cash.drive.backend.windows_uia import WindowsUiaBackend

    backend = WindowsUiaBackend.attach()
    backend.bring_to_front()
    yield backend
    close_all_without_saving(backend)


@pytest.fixture
def workbench(backend, tmp_path):
    return Workbench(backend, tmp_path)


def open_vat_editor(backend, workbench):
    backend.press_menu(("New", "New VAT"))
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        elements = backend.scan(workbench.editor_area())
        try:
            right_of_label(elements, "Value")
            return elements
        except LocatorError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def close_all_without_saving(backend):
    """Closes one editor at a time and answers No to "Save changes?". Never "Close All": its
    "Save Parts" list hides on Windows which parts are ticked, so its OK could save them."""
    workbench = Workbench(backend, None)
    for _ in range(10):
        if not workbench.editor_tabs():
            return
        backend.press_menu(("File", "Close"))
        time.sleep(1.0)
        for dialog in (w for w in backend.windows() if not w.title.startswith("Fakturama - ")):
            buttons = [e for e in backend.tree(dialog) if e.role is Role.BUTTON]
            assert any(b.title == "No" for b in buttons), f"unexpected dialog {dialog.title!r}: not answering it"
            backend.bring_to_front()
            backend.press(by_title(buttons, Role.BUTTON, "No"))
            time.sleep(1.0)
    pytest.fail("editors kept open after ten closes")


def test_main_window_is_listed(workbench):
    assert workbench.main_window().rect.width > 0


def test_editor_and_list_folders_are_found(workbench):
    editors, views = workbench.editor_area(), workbench.view_area()
    assert editors.height > 0 and views.height > 0
    assert editors.bottom <= views.y


@pytest.mark.parametrize("tooltip", FLOW_TOOLTIPS)
def test_main_toolbar_buttons_carry_their_tooltips(workbench, tooltip):
    assert workbench.toolbar_button(tooltip).role is Role.BUTTON  # Save stays disabled until an editor changes


def test_text_is_typed_and_read_back(backend, workbench):
    name = right_of_label(open_vat_editor(backend, workbench), "Name")
    backend.click(name)
    backend.type_text("contract test ü")
    backend.key("tab")
    assert backend.refresh(name).value == "contract test ü"


def test_popup_option_is_chosen(backend, workbench):
    code = right_of_label(open_vat_editor(backend, workbench), "VAT code (E-Invoice)", role=Role.POPUP)
    backend.choose(code, "S (Standard rate)")
    assert backend.refresh(code).value == "S (Standard rate)"


def test_tab_is_clicked(backend, workbench):
    """A tab has no window of its own: the hit test finds its folder, which must count as the tab."""
    backend.press_menu(("New", "New Debtor"))
    tab = wait_for(lambda: by_title(backend.scan(workbench.editor_area()), Role.RADIO, "Miscellaneous"))
    backend.click(tab)
    assert wait_for(lambda: backend.refresh(tab).value == "True" or None)


def wait_for(probe):
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        try:
            found = probe()
            if found:
                return found
        except LookupError:
            pass
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.2)


def test_area_is_captured(backend, workbench, tmp_path):
    shot = backend.capture(workbench.main_window().rect, tmp_path / "main.png")
    assert shot.stat().st_size > 0


def test_print_calibration(backend, workbench):
    main = workbench.main_window()
    elements = backend.tree(main)
    print(f"\nlayout in use: {backend.layout}")
    print(f"main window (points): {main.rect}")
    for group in (e for e in elements if e.role is Role.TAB_GROUP):
        print(f"tab folder: {group.rect}")
    for button in (e for e in elements if e.role is Role.BUTTON and e.help):
        print(f"button {button.rect} help={button.help!r} title={button.title!r}")
    for other in (e for e in elements if e.role is Role.OTHER):
        print(f"other {other.native_role} {other.rect}")
