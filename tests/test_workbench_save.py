"""Save makes the open editor the active part first: Eclipse saves the active part, and a search in
the Documents list leaves that list active (seen on Windows: the Invoice did not save)."""

from dataclasses import replace
from pathlib import Path

from fake_backend import FakeBackend

from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.fakturama.workbench import Workbench

MAIN = Window("Fakturama - C:\\FakturamaData", Rect(0, 0, 1512, 786))
EDITORS = Element(Role.TAB_GROUP, Rect(203, 63, 797, 297))
VIEWS = Element(Role.TAB_GROUP, Rect(203, 359, 797, 236))
SAVE = Element(Role.BUTTON, Rect(106, 49, 35, 51), title="Save", help="Save the current contents")
ORDER_TAB = Element(Role.RADIO, Rect(210, 65, 80, 20), title="PO000001", value="False")
INVOICE_TAB = Element(Role.RADIO, Rect(295, 65, 100, 20), title="*New Invoice", value="True")


class Screen(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.saved = False

    def windows(self):
        return (MAIN,)

    def tree(self, window):
        return (EDITORS, VIEWS, SAVE)

    def scan(self, area):
        return (ORDER_TAB, INVOICE_TAB)

    def press(self, element):
        super().press(element)
        self.saved = self.saved or (element == SAVE and ("click", INVOICE_TAB.rect) in self.calls)

    def refresh(self, element):
        return replace(element, enabled=not self.saved) if element == SAVE else super().refresh(element)


def test_save_clicks_the_open_editors_tab_before_pressing_save():
    screen = Screen()
    Workbench(screen, Path("unused")).save("Invoice")
    assert screen.calls.index(("click", INVOICE_TAB.rect)) < screen.calls.index(("press", SAVE.rect))
