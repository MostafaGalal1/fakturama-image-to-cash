"""Fakturama's on-screen geometry, which differs by OS (fonts, row heights, panel positions).

Each backend carries the layout of the OS it drives, so the flow never hard-codes one. All values
are in screen points: macOS points, or 96-dpi logical pixels on Windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from image_to_cash.drive.elements import Rect


@dataclass(frozen=True)
class Layout:
    header_height: float  # a grid's column-header row
    row_height: float  # one grid row
    row_header_dx: float  # from a grid's left edge into the order grid's row-number column
    tab_strip: float  # a tab folder's row of tabs; its view toolbar sits at its right end
    nav_area: Rect  # the left panel's "New" links, relative to the main window's top-left corner
    grid_roles: frozenset[str]  # native roles of the custom-drawn grids, which expose no rows

    @property
    def first_row_dy(self) -> float:
        """From a grid's top edge to the middle of its first row."""
        return self.header_height + self.row_height // 2


MAC_LAYOUT = Layout(
    header_height=15,
    row_height=15,
    row_header_dx=12,
    tab_strip=26,
    nav_area=Rect(8, 527, 280, 100),  # measured with the main window at (12, 33)
    grid_roles=frozenset({"AXScrollArea"}),
)

# First values for Windows, not yet measured on a live Fakturama: NatTable's default row is 20 px,
# SWT tab rows are a little taller than on macOS, and the whole left panel is scanned for the "New"
# links (UI Automation lists every control, so a large area costs little). Calibrate them with
# tests/test_windows_uia_contract.py; a wrong value stops the run, because every grid selection
# is copied back and compared.
WINDOWS_LAYOUT = Layout(
    header_height=20,
    row_height=20,
    row_header_dx=12,
    tab_strip=28,
    nav_area=Rect(0, 0, 330, 4000),
    grid_roles=frozenset({"Pane"}),
)
