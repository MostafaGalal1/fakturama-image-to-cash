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
