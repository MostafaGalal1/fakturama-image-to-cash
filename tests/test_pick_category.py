from types import SimpleNamespace

from PIL import Image

from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama import lists
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.ocr import Box, TextBox

VIEW = Rect(200, 400, 800, 100)
STRIP = 20


class Ui:
    def __init__(self):
        self.layout = SimpleNamespace(tab_strip=STRIP)
        self.calls = []
        self.picked = None

    def capture(self, area, path):
        Image.new("RGB", (int(area.width), int(area.height)), "white").save(path)
        return path

    def element_at(self, x, y):
        return Element(Role.OTHER, Rect(x - 1, y - 1, 2, 2))

    def click(self, element, *, at=None, count=1):
        self.calls.append(("click", at))

    def key(self, chord):
        self.calls.append(("key", chord))
        typed = "".join(chord for kind, chord in self.calls if kind == "key")
        self.picked = "Orders" if typed == "orders" else None

    def scan(self, area):
        return (Element(Role.LABEL, Rect(0, 0, 1, 1), value=self.picked),)


class Wb:
    def __init__(self, ui):
        self.ui = ui

    def view_area(self):
        return VIEW


class Ocr:
    def __init__(self, ui, texts):
        self.ui, self.texts = ui, texts

    def recognize(self, image):
        """`texts` at 10 % steps down the enlarged capture, each 30 pixels wide."""
        return tuple(TextBox(text, Box(30, i * image.height // 10, 30, 10)) for i, text in enumerate(self.texts))


def run(texts):
    ui = Ui()
    ocr = Ocr(ui, texts)
    original = ui.click

    def click(element, *, at=None, count=1):
        original(element, at=at, count=count)
        if ui.picked is None and any("Orders" in text for text in texts):
            ui.picked = "Orders"  # a click on the read item selects it

    ui.click = click
    lists.pick_category(Context(Wb(ui), ocr, None), "Orders")
    return ui.calls


def test_a_category_ocr_can_see_is_clicked():
    calls = run(("Invoices", "› Orders"))
    assert [kind for kind, _ in calls] == ["click"]
    assert calls[0][1][1] > VIEW.y + STRIP  # inside the tree, on the second line


def test_a_category_scrolled_out_of_a_short_view_is_typed_into_the_tree():
    """At 150 % the Documents view showed two rows of its tree; "Invoices" was out of sight."""
    calls = run(("paid",))
    assert calls == [
        ("click", None),
        *(("key", char) for char in "orders"),
    ]
