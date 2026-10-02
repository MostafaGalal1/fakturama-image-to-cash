import pytest
from pathlib import Path

from fake_backend import FakeBackend

from image_to_cash.drive.elements import Element, Rect, Role, Window
from image_to_cash.drive.fakturama.grids import row_y
from image_to_cash.drive.fakturama.workbench import Workbench
from image_to_cash.drive.layout import MAC_LAYOUT, WINDOWS_LAYOUT

MAIN = Window("Fakturama - /Users/someone/Desktop", Rect(12, 33, 1500, 870))
EDITORS = Element(Role.TAB_GROUP, Rect(203, 63, 797, 297))
VIEWS = Element(Role.TAB_GROUP, Rect(203, 359, 797, 236))
ADDRESSES = Element(Role.TAB_GROUP, Rect(212, 180, 780, 120))  # inside the Debtor editor


class Screen(FakeBackend):
    def __init__(self, groups):
        super().__init__()
        self.groups = groups
        self.scanned = []

    def windows(self):
        return (MAIN,)

    def tree(self, window):
        return self.groups

    def scan(self, area):
        self.scanned.append(area)
        return ()


def test_mac_grid_rows_keep_the_measured_geometry():
    grid = Element(Role.OTHER, Rect(100, 200, 500, 300))
    assert row_y(MAC_LAYOUT, grid, 0) == 222
    assert row_y(MAC_LAYOUT, grid, 2) == 252


def test_windows_rows_use_their_own_height():
    grid = Element(Role.OTHER, Rect(100, 200, 500, 300))
    assert row_y(WINDOWS_LAYOUT, grid, 1) == 200 + 20 + 10 + 20


def test_the_left_panel_area_follows_the_main_window():
    bench = Workbench(Screen((EDITORS, VIEWS)), Path("unused"))
    assert bench._nav_area() == Rect(20, 560, 280, 100)  # where it was measured on the Mac


def test_tab_folders_inside_an_editor_are_not_the_main_folders():
    bench = Workbench(Screen((EDITORS, ADDRESSES, VIEWS)), Path("unused"))
    assert bench.editor_area() == Rect(203, 63 + 26, 797, 297 - 26)
    assert bench.view_area() == Rect(203, 359 + 26, 797, 236 - 26)


def test_the_error_log_beside_the_navigation_is_not_a_main_folder():
    # Windows: after an internal error Fakturama opens its Error log view below the left panel.
    error_log = Element(Role.TAB_GROUP, Rect(0, 500, 190, 135))
    bench = Workbench(Screen((error_log, EDITORS, VIEWS)), Path("unused"))
    assert bench.editor_area() == Rect(203, 63 + 26, 797, 297 - 26)
    assert bench.view_area() == Rect(203, 359 + 26, 797, 236 - 26)


def test_an_editor_folder_reaching_past_the_visible_editor_is_still_inner():
    # Windows: a Debtor's Addresses folder scrolls on below the editor area.
    reaching = Element(Role.TAB_GROUP, Rect(260, 200, 600, 400))
    bench = Workbench(Screen((EDITORS, reaching, VIEWS)), Path("unused"))
    assert bench.editor_area() == Rect(203, 63 + 26, 797, 297 - 26)


def test_a_selector_grid_is_the_pane_below_its_search_row():
    from image_to_cash.drive.fakturama.debtor import _selector_grid

    outer = Element(Role.OTHER, Rect(362, 56, 780, 466))
    grid = Element(Role.OTHER, Rect(362, 90, 780, 432))
    assert _selector_grid((Element(Role.OTHER, Rect(362, 56, 787, 515)), outer, grid)) is grid


def test_rows_are_measured_from_the_text_lines_below_the_header():
    from image_to_cash.drive.fakturama.grids import Rows, rows_from_text

    centres = (9.0, 10.0, 31.0, 31.5, 53.25, 75.25)  # header, then three rows 22 apart
    assert rows_from_text(centres, WINDOWS_LAYOUT) == Rows(31.25, 22.0)


def test_too_little_text_keeps_the_layouts_rows():
    from image_to_cash.drive.fakturama.grids import Rows, rows_from_text

    assert rows_from_text((9.0,), WINDOWS_LAYOUT) == Rows.assumed(WINDOWS_LAYOUT)
    assert rows_from_text((9.0, 31.0), WINDOWS_LAYOUT) == Rows(31.0, WINDOWS_LAYOUT.row_height)
    assert rows_from_text((9.0, 31.0, 131.0), WINDOWS_LAYOUT).pitch == WINDOWS_LAYOUT.row_height  # 100 apart: noise


def test_text_below_the_rows_does_not_stretch_the_pitch():
    """Live, Windows VM: the order grid's frame reaches into the totals beside it ("Total Net"),
    whose line came 56 points below the second row. The median gap (38) put row 2 in the wrong place."""
    from image_to_cash.drive.fakturama.grids import Rows, rows_from_text

    centres = (9.8, 11.2, 29.8, 30.5, 31.2, 49.8, 50.5, 51.2, 105.5, 106.2, 107.0)
    rows = rows_from_text(centres, WINDOWS_LAYOUT)
    assert rows.pitch == pytest.approx(20.0, abs=0.5) and rows.first_dy == pytest.approx(30.5, abs=0.5)


class Redrawing(Screen):
    """Live, Windows VM: opening an editor from a list left only one main folder for a moment."""

    def __init__(self):
        super().__init__((VIEWS,))
        self.polls = 0

    def tree(self, window):
        self.polls += 1
        return self.groups if self.polls < 3 else (EDITORS, VIEWS)

    def scan(self, area):
        tab = Element(Role.RADIO, Rect(203, 63, 100, 20), title="PO000005", value="True")
        return (tab,) if area.y == EDITORS.rect.y else ()


def test_an_editor_folder_being_redrawn_is_waited_for():
    bench = Workbench(Redrawing(), Path("unused"))
    assert bench.wait_for_editor_tab(lambda title: title == "PO000005", "Order PO000005", timeout=5) == "PO000005"


def test_a_lasting_odd_layout_still_stops():
    from image_to_cash.errors import NeedsReview

    with pytest.raises(NeedsReview, match="fakturama_layout"):
        Workbench(Screen((VIEWS,)), Path("unused")).editor_area()
