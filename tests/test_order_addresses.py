from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.order import DocumentEditor

TEXTS = {"Invoice address": "Mac Recheck GmbH\nFriedrichstrasse 88", "Delivery address": "Mac Recheck Warehouse\nBeusselstrasse 44"}


class Ui:
    """An address tab folder that redraws a moment after a tab is clicked: the click takes
    effect only after `lag` more scans, as Fakturama's tabs did on macOS."""

    def __init__(self, lag):
        self.lag, self.selected, self.pending, self.countdown, self.clicks = lag, "Invoice address", None, 0, []

    def scan(self, area):
        if self.pending is not None:
            if self.countdown == 0:
                self.selected, self.pending = self.pending, None
            else:
                self.countdown -= 1
        tabs = tuple(
            Element(Role.RADIO, Rect(388 + 90 * i, 248, 90, 17), title=tab, value=str(tab == self.selected))
            for i, tab in enumerate(TEXTS)
        )
        return (
            *tabs,
            Element(Role.IMAGE, Rect(300, 270, 16, 16), help="Pick an address from the list"),
            Element(Role.TEXT_AREA, Rect(330, 270, 300, 50), value=TEXTS[self.selected]),
        )

    def refresh(self, element):
        return next(e for e in self.scan(None) if e.role is element.role and e.title == element.title)

    def click(self, element, *, at=None, count=1):
        self.clicks.append(element.title)
        self.pending, self.countdown = element.title, self.lag


class Wb:
    def __init__(self, ui):
        self.ui = ui

    def editor_area(self):
        return Rect(0, 0, 1000, 800)


def test_each_address_is_read_once_its_tab_shows_selected():
    ui = Ui(lag=2)
    editor = DocumentEditor(Context(Wb(ui), None, None, sleep=lambda seconds: None), "PO000004")
    assert editor.address_texts() == (TEXTS["Invoice address"], TEXTS["Delivery address"])
    assert ui.clicks == ["Delivery address", "Invoice address"]
