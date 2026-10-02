"""Fakturama's main window: toolbar, the editor folder on top, the list views below, dialogs.

Every wait has a timeout and every action is read back by the caller. Anything unexpected on
screen, such as Fakturama's "Internal Error" dialog, stops the run with NeedsReview after the
dialog is acknowledged, so a person finds Fakturama in a clean state.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from image_to_cash.drive.backend.base import UiBackend
from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.locate import LocatorError, by_title, label
from image_to_cash.drive.waits import WaitTimeout, wait_until
from image_to_cash.errors import NeedsReview

T = TypeVar("T")

MAIN_TITLE_PREFIX = "Fakturama - "
ERROR_DIALOG = "Internal Error"
REVIEW_DIALOGS = {ERROR_DIALOG: "fakturama_internal_error", "Duplicate Contact": "duplicate_contact"}
OPEN_TIMEOUT = 30
SAVE_TIMEOUT = 15
DIALOG_TIMEOUT = 10
POLL = 0.5


TOOLBAR_ROW = 10.0  # points: buttons of one toolbar row share their top

class Workbench:
    def __init__(self, backend: UiBackend, shots: Path) -> None:
        self.ui = backend
        self._shots = shots
        self._shot_count = 0

    # Windows and areas.

    def main_window(self) -> Window:
        found = [w for w in self.ui.windows() if w.title.startswith(MAIN_TITLE_PREFIX)]
        if len(found) != 1:
            raise NeedsReview("fakturama_main_window", {"windows": str(len(found))})
        return found[0]

    def _folders(self) -> tuple[Rect, Rect]:
        """The editor folder on top and the list views below. Tab folders inside an editor (a
        Debtor's "Addresses") are left out: they start within one of these two, right of its
        left edge, and may reach past it (scrolled below the visible editor)."""
        found = [e.rect for e in self.ui.tree(self.main_window()) if e.role is Role.TAB_GROUP]
        groups = [rect for rect in found if not any(_inner(rect, other) for other in found)]
        if len(groups) != 2:
            raise NeedsReview("fakturama_layout", {"tab_folders": str(len(groups))})
        top, bottom = sorted(groups, key=lambda rect: rect.y)
        return top, bottom

    def editor_area(self) -> Rect:
        top, _ = self._folders()
        return Rect(top.x, top.y + self.ui.layout.tab_strip, top.width, top.height - self.ui.layout.tab_strip)

    def view_area(self) -> Rect:
        _, bottom = self._folders()
        return Rect(bottom.x, bottom.y + self.ui.layout.tab_strip, bottom.width, bottom.height - self.ui.layout.tab_strip)

    def view_toolbar(self) -> tuple[Element, ...]:
        _, bottom = self._folders()
        return self.ui.scan(Rect(bottom.x, bottom.y, bottom.width, self.ui.layout.tab_strip))

    def editor_tabs(self) -> tuple[Element, ...]:
        top, _ = self._folders()
        return tuple(e for e in self.ui.scan(Rect(top.x, top.y, top.width, self.ui.layout.tab_strip)) if e.role is Role.RADIO)

    # Toolbar, tabs and navigation.

    def toolbar_button(self, help_text: str) -> Element:
        """A main-toolbar button by its tooltip. Buttons inside editors share some tooltips
        (an Order's follow-up "Create: New Invoice"), so only the topmost row counts: the main
        toolbar lies above every editor, and this works with no editor open."""
        found = [e for e in self.ui.tree(self.main_window()) if e.role is Role.BUTTON and e.help == help_text]
        top = min((e.rect.y for e in found), default=0.0)
        buttons = [e for e in found if e.rect.y <= top + TOOLBAR_ROW]
        if len(buttons) != 1:
            raise NeedsReview("toolbar_button", {"help": help_text, "found": str(len(buttons))})
        return buttons[0]

    def activate_editor(self, matches: Callable[[str], bool], what: str) -> Element:
        tabs = [tab for tab in self.editor_tabs() if matches(tab.title or "")]
        if len(tabs) != 1:
            raise NeedsReview("editor_tab", {"tab": what, "found": str(len(tabs))})
        tab = tabs[0]
        if not _selected(tab):
            self.ui.click(tab)
            wait_until(lambda: _selected(self.ui.refresh(tab)), what=f"the {what} tab", timeout=5, poll=0.2)
        return tab

    def active_editor_title(self) -> str:
        selected = [tab.title or "" for tab in self.editor_tabs() if _selected(tab)]
        return selected[0] if len(selected) == 1 else ""

    def wait_for_editor_tab(self, matches: Callable[[str], bool], what: str, timeout: float = OPEN_TIMEOUT) -> str:
        return wait_until(
            lambda: _require(next((t.title for t in self.editor_tabs() if _selected(t) and matches(t.title or "")), None)),
            what=f"the {what} editor",
            timeout=timeout,
            poll=POLL,
            ignoring=(LookupError,),
        )

    def click_nav(self, text: str, opened: Callable[[], bool]) -> None:
        """A link in the left panel. Its first click can go to activating the panel, so one
        more click is allowed when nothing opened."""
        for _ in range(2):
            item = wait_until(
                lambda: label(self.ui.scan(self._nav_area()), text), what=f"'{text}'", timeout=10, poll=POLL, ignoring=(LocatorError,)
            )
            self.ui.click(item)
            try:
                wait_until(opened, what=f"'{text}' to open", timeout=8, poll=POLL)
                return
            except WaitTimeout:
                self.check_errors()
        raise NeedsReview("navigation_failed", {"item": text})

    def _nav_area(self) -> Rect:
        window, nav = self.main_window().rect, self.ui.layout.nav_area
        return Rect(window.x + nav.x, window.y + nav.y, nav.width, nav.height)

    # Editors.

    def scan_editor(self, ready: Callable[[tuple[Element, ...]], object], what: str) -> tuple[Element, ...]:
        """Scan the editor area until `ready` accepts the controls (it raises LocatorError until then)."""

        def attempt() -> tuple[Element, ...]:
            found = self.ui.scan(self.editor_area())
            ready(found)
            return found

        return wait_until(attempt, what=what, timeout=OPEN_TIMEOUT, poll=POLL, ignoring=(LocatorError,))

    def save(self, what: str) -> None:
        """The toolbar Save, once; done when Save turns grey again. Eclipse saves the active part,
        which a search in the Documents list leaves on that list: a click on the editor's own tab
        makes the editor active again first."""
        self._focus_open_editor(what)
        save = self.toolbar_button("Save the current contents")
        if not save.enabled:
            raise NeedsReview("nothing_to_save", {"editor": what})
        self.ui.press(save)
        try:
            wait_until(lambda: not self.ui.refresh(save).enabled, what=f"{what} to save", timeout=SAVE_TIMEOUT, poll=0.3)
        except WaitTimeout:
            self.check_errors()
            raise NeedsReview("save_failed", {"editor": what}) from None
        self.check_errors()

    # Dialogs.

    def wait_dialog(self, title: str) -> Window:
        return wait_until(
            lambda: _require(next((w for w in self.ui.windows() if w.title == title), None)),
            what=f"the '{title}' dialog",
            timeout=DIALOG_TIMEOUT,
            poll=0.3,
            ignoring=(LookupError,),
        )

    def dialog_open(self, title: str) -> bool:
        return any(w.title == title for w in self.ui.windows())

    def _focus_open_editor(self, what: str) -> None:
        selected = [tab for tab in self.editor_tabs() if _selected(tab)]
        if len(selected) != 1:
            raise NeedsReview("editor_tab", {"tab": what, "found": str(len(selected))})
        self.ui.click(selected[0])

    def close_unchanged_editor(self, what: str) -> None:
        """File > Close on the open editor, which must hold no changes: then no dialog asks."""
        before = self.editor_tabs()
        selected = [tab for tab in before if _selected(tab)]
        if len(selected) != 1 or (selected[0].title or "").startswith("*"):
            raise NeedsReview("editor_changed", {"editor": what})
        self.ui.press_menu(("File", "Close"))
        wait_until(lambda: len(self.editor_tabs()) < len(before), what=f"the {what} editor to close", timeout=5, poll=0.3)

    def check_errors(self) -> None:
        """Stops on Fakturama's own warnings. An internal error is acknowledged; a duplicate
        warning stays open for the person who reviews the stop."""
        errors = [w for w in self.ui.windows() if w.title in REVIEW_DIALOGS]
        if not errors:
            return
        message = next((e.title or e.value or "" for e in self.ui.tree(errors[0]) if e.role is Role.LABEL and e.text), "")
        if errors[0].title == ERROR_DIALOG:
            self.ui.press(by_title(self.ui.tree(errors[0]), Role.BUTTON, "OK"))
        raise NeedsReview(REVIEW_DIALOGS[errors[0].title], {"message": message.replace("\n", " ")[:200]})

    # Evidence.

    def shot(self, name: str) -> Path:
        self._shot_count += 1
        return self.ui.capture(self.main_window().rect, self._shots / f"{self._shot_count:02d}-{name}.png")


def _inner(rect: Rect, outer: Rect) -> bool:
    return rect != outer and (outer.contains(rect) or (outer.holds(rect.x, rect.y) and rect.x > outer.x))


def _selected(tab: Element) -> bool:
    return tab.value in (True, "True", "1", 1)


def _require(value: T | None) -> T:
    if value is None:
        raise LookupError("not there yet")
    return value
