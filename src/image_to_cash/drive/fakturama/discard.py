"""After a stop: close what the run left open without saving it, so the next order starts on a
clean Fakturama (README "Unattended: a folder of orders").

Only what the bot itself opens is answered:
- its selectors, and a "Save Parts" an earlier close left open, are cancelled (Cancel saves and
  closes nothing);
- each editor is closed on its own (File > Close). Fakturama then asks about that one editor,
  either with "Save Parts" listing it or with a question naming it. "Save Parts" gets OK only
  once its single box reads back unticked; the question gets No.
Never "Close All", whose list holds several parts at once. Any other window (Fakturama's own
warnings, a list naming another editor) stops the discard and is left to a person.
"""

from __future__ import annotations

from image_to_cash.drive.elements import Element, Role, Window
from image_to_cash.drive.fakturama.debtor import SELECTOR as DEBTOR_SELECTOR
from image_to_cash.drive.fakturama.product import SELECTOR as PRODUCT_SELECTOR
from image_to_cash.drive.fakturama.workbench import MAIN_TITLE_PREFIX, Workbench
from image_to_cash.drive.locate import by_title
from image_to_cash.drive.waits import WaitTimeout, wait_until
from image_to_cash.errors import NeedsReview

SAVE_PARTS = "Save Parts"
CANCEL_FIRST = frozenset({DEBTOR_SELECTOR, PRODUCT_SELECTOR, SAVE_PARTS})
UNTICKED = "0"
MAX_EDITORS = 50
CLOSE_TIMEOUT = 5.0
TICK_TIMEOUT = 2.0
POLL = 0.2


def discard_editors(wb: Workbench) -> tuple[str, ...]:
    """Closes every open editor without saving; returns their names in the order closed."""
    wb.ui.bring_to_front()
    _cancel_left_open(wb)
    closed: list[str] = []
    while tabs := wb.editor_tabs():
        if len(closed) == MAX_EDITORS:  # each close is read back, so this only bounds a surprise
            raise NeedsReview("editors_left_open", {"closed": str(len(closed)), "open": str(len(tabs))})
        closed.append(_close_active(wb, len(tabs)))
    return tuple(closed)


def _cancel_left_open(wb: Workbench) -> None:
    """One at a time: several windows of one title can be open (earlier closes, each unanswered)."""
    for _ in range(MAX_EDITORS):
        dialogs = _dialogs(wb)
        if not dialogs:
            return
        if dialogs[0].title not in CANCEL_FIRST:
            raise NeedsReview("dialog_open", {"dialog": dialogs[0].title})
        wb.ui.press(by_title(wb.ui.tree(dialogs[0]), Role.BUTTON, "Cancel"))
        wait_until(lambda: len(_dialogs(wb)) < len(dialogs), what=f"'{dialogs[0].title}' to close", timeout=CLOSE_TIMEOUT, poll=POLL)
    raise NeedsReview("dialogs_left_open", {"dialogs": str(len(_dialogs(wb)))})


def _close_active(wb: Workbench, open_editors: int) -> str:
    tab = wb.active_editor("the editor to discard")
    name = (tab.title or "").lstrip("*").strip()
    if not name:
        raise NeedsReview("editor_tab", {"tab": "the editor to discard", "found": "a tab without a name"})
    wb.ui.click(tab)  # File > Close acts on the active part, which a list view may hold
    wb.ui.press_menu(("File", "Close"))
    asked = wait_until(
        lambda: _dialogs(wb) or len(wb.editor_tabs()) < open_editors,
        what=f"the {name} editor to close or ask",
        timeout=CLOSE_TIMEOUT,
        poll=POLL,
    )
    if asked is True:  # nothing unsaved: it closed without asking
        return name
    if len(asked) != 1:
        raise NeedsReview("dialog_open", {"dialog": ", ".join(d.title for d in asked)})
    _answer(wb, asked[0], name)
    wait_until(lambda: len(wb.editor_tabs()) < open_editors and not _dialogs(wb), what=f"the {name} editor to close", timeout=CLOSE_TIMEOUT, poll=POLL)
    return name


def _answer(wb: Workbench, dialog: Window, name: str) -> None:
    controls = wb.ui.tree(dialog)
    if dialog.title == SAVE_PARTS:
        _untick_and_confirm(wb, controls, name)
        return
    if any(name in e.text for e in controls if e.role is Role.LABEL) and _has_button(controls, "No"):
        wb.ui.press(by_title(controls, Role.BUTTON, "No"))
        return
    _cancel(wb, controls)
    raise NeedsReview("dialog_open", {"dialog": dialog.title})


def _untick_and_confirm(wb: Workbench, controls: tuple[Element, ...], name: str) -> None:
    """OK saves every ticked part, so it is pressed only after the one box reads back unticked."""
    boxes = [e for e in controls if e.role is Role.CHECKBOX]
    listed = {e.text for e in controls if e.role is Role.LABEL} | {box.title for box in boxes}  # a box's value is its tick
    if len(boxes) != 1 or name not in listed:
        _cancel(wb, controls)
        raise NeedsReview("save_parts_unexpected", {"editor": name, "parts": str(len(boxes))})
    box = boxes[0]
    if box.value != UNTICKED:
        wb.ui.press(box)
    try:
        wait_until(lambda: wb.ui.refresh(box).value == UNTICKED, what=f"{name} to read unticked", timeout=TICK_TIMEOUT, poll=POLL)
    except WaitTimeout:
        _cancel(wb, controls)
        raise NeedsReview("discard_unconfirmed", {"editor": name}) from None
    wb.ui.press(by_title(controls, Role.BUTTON, "OK"))


def _cancel(wb: Workbench, controls: tuple[Element, ...]) -> None:
    if _has_button(controls, "Cancel"):
        wb.ui.press(by_title(controls, Role.BUTTON, "Cancel"))


def _has_button(controls: tuple[Element, ...], title: str) -> bool:
    return any(e.role is Role.BUTTON and e.title == title for e in controls)


def _dialogs(wb: Workbench) -> tuple[Window, ...]:
    """Fakturama's dialogs all have titles; an untitled window is a tooltip."""
    return tuple(w for w in wb.ui.windows() if w.title and not w.title.startswith(MAIN_TITLE_PREFIX))
