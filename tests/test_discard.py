"""Discarding what a stop left open: nothing is saved, and only the bot's own dialogs are answered."""

import pytest

from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.fakturama.discard import discard_editors
from image_to_cash.errors import NeedsReview

AT = Rect(0, 0, 10, 10)
MAIN = "Fakturama - C:\\FakturamaData"


class Fakturama:
    """Editors (name -> how closing it asks: "clean", "parts" or "question") and open dialogs.
    The first editor is the active one. Records presses and anything saved."""

    def __init__(self, editors, dialogs=(), stuck_tick=False, listed=None):
        self.editors = dict(editors)
        self.dialogs = {title: {} for title in dialogs}
        self.stuck_tick, self.listed = stuck_tick, listed
        self.pressed, self.saved = [], []
        self.ui = self

    # Workbench.

    def editor_tabs(self):
        names = list(self.editors)
        return tuple(Element(Role.RADIO, AT, title=self._tab(name), value=str(i == 0), handle=name) for i, name in enumerate(names))

    def active_editor(self, what):
        return self.editor_tabs()[0]

    def dialog_open(self, title):
        return title in self.dialogs

    def _tab(self, name):
        return name if self.editors[name] == "clean" else f"*{name}"

    # Backend.

    def bring_to_front(self):
        pass

    def click(self, element):
        assert element.handle == next(iter(self.editors)), "only the active editor's tab is clicked"

    def press_menu(self, path):
        assert path == ("File", "Close")
        name = next(iter(self.editors))
        kind = self.editors[name]
        if kind == "clean":
            del self.editors[name]
        elif kind == "parts":
            self.dialogs["Save Parts"] = {"editor": name, "ticked": True}
        else:
            self.dialogs["Save Resource"] = {"editor": name}

    def windows(self):
        return (Window(MAIN, AT), *(Window(title, AT) for title in self.dialogs))

    def tree(self, window):
        state = self.dialogs[window.title]
        if window.title == "Save Parts":
            listed = self.listed or state["editor"]
            box = Element(Role.CHECKBOX, AT, title=listed, value="1" if state["ticked"] else "0", handle="box")
            return (Element(Role.LABEL, AT, value="Select the parts to save:"), box, self._button(window.title, "OK"), self._button(window.title, "Cancel"))
        if window.title == "Save Resource":
            question = Element(Role.LABEL, AT, value=f"'{state['editor']}' has been modified. Save changes?")
            return (question, *(self._button(window.title, title) for title in ("Yes", "No", "Cancel")))
        return (Element(Role.LABEL, AT, value="..."), self._button(window.title, "OK"), self._button(window.title, "Cancel"))

    def refresh(self, element):
        (fresh,) = [e for e in self.tree(Window("Save Parts", AT)) if e.handle == element.handle]
        return fresh

    def press(self, element):
        self.pressed.append(element.title)
        if element.handle == "box":
            self.dialogs["Save Parts"]["ticked"] ^= not self.stuck_tick
            return
        title, button = element.handle
        state = self.dialogs.pop(title)
        if button == "Cancel":
            return
        if title == "Save Parts" and button == "OK" and state["ticked"]:
            self.saved.append(state["editor"])
        if button == "Yes":
            self.saved.append(state["editor"])
        if button in ("OK", "No", "Yes"):
            del self.editors[state["editor"]]

    def _button(self, window, title):
        return Element(Role.BUTTON, AT, title=title, handle=(window, title))


def test_a_stop_is_cleared_without_saving_anything():
    fakturama = Fakturama(
        {"New Order": "parts", "New Debtor": "question", "Product SKU-1": "clean"}, dialogs=("Select the address",)
    )
    assert discard_editors(fakturama) == ("New Order", "New Debtor", "Product SKU-1")
    assert fakturama.saved == [] and not fakturama.editors and not fakturama.dialogs
    assert fakturama.pressed == ["Cancel", "New Order", "OK", "No"]  # the selector, the tick, then the answers


def test_a_tick_that_does_not_clear_is_never_answered_ok():
    fakturama = Fakturama({"New Order": "parts"}, stuck_tick=True)
    with pytest.raises(NeedsReview) as stop:
        discard_editors(fakturama)
    assert stop.value.reason == "discard_unconfirmed"
    assert "OK" not in fakturama.pressed and fakturama.pressed[-1] == "Cancel"
    assert fakturama.saved == [] and "New Order" in fakturama.editors


def test_a_list_naming_another_editor_is_cancelled():
    fakturama = Fakturama({"New Order": "parts"}, listed="Other Order")
    with pytest.raises(NeedsReview) as stop:
        discard_editors(fakturama)
    assert stop.value.reason == "save_parts_unexpected"
    assert fakturama.pressed == ["Cancel"] and fakturama.saved == []


def test_a_dialog_the_bot_did_not_open_is_left_for_a_person():
    fakturama = Fakturama({"New Debtor": "question"}, dialogs=("Duplicate Contact",))
    with pytest.raises(NeedsReview) as stop:
        discard_editors(fakturama)
    assert stop.value.reason == "dialog_open"
    assert fakturama.pressed == [] and "Duplicate Contact" in fakturama.dialogs


def test_nothing_open_is_nothing_to_do():
    assert discard_editors(Fakturama({})) == ()
