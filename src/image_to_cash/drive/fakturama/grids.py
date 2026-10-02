"""Fakturama's NatTable grids, which show no rows to accessibility.

What the live app taught (docs/spike-macos-ax.md):
- Rows are read by copying them: Cmd+C puts the stored values on the clipboard.
- Copying when nothing is selected makes Fakturama show an "Internal Error", so a grid is only
  copied after its first row shows something (OCR alone missed rows in the VATs list).
- Clicking an already-selected cell opens its editor, so a whole row is selected by clicking its
  row header, and a row in a selector dialog by arrow keys (each leaves exactly one row selected).
- A cell editor opens when the cell is clicked and a character is typed with its real key code.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from image_to_cash.drive.backend.base import UiBackend
from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.waits import wait_until
from image_to_cash.errors import NeedsReview
from image_to_cash.ocr.base import OcrEngine

HEADER_HEIGHT = 15
ROW_HEIGHT = 15
FIRST_ROW_DY = HEADER_HEIGHT + ROW_HEIGHT // 2
ROW_HEADER_DX = 12  # the row-number column of the order items grid
SETTLE_SECONDS = 1.5  # a search filter or an added line redraws the grid
EDITOR_SECONDS = 1.0
ROW_INSET = 3  # keeps the row's own borders out of the strip
DARK_LEVEL = 110  # text is near black; column lines are light grey
SELECTED_BLUE_MARGIN = 40  # a selected row is light blue
MIN_MARKED_PIXELS = 20
MIN_MARKED_SHARE = 0.0005


def grid_at(ui: UiBackend, x: float, y: float, what: str) -> Element:
    grid = ui.element_at(x, y)
    if grid is None or grid.native_role != "AXScrollArea":
        raise NeedsReview("grid_not_found", {"grid": what})
    return grid


def row_y(grid: Element, index: int) -> float:
    return grid.rect.y + FIRST_ROW_DY + index * ROW_HEIGHT


def has_rows(ui: UiBackend, ocr: OcrEngine, grid: Element) -> bool:
    """True when the first row shows anything: dark text, the blue of a selected row, or text that
    OCR reads. An empty row is white with light grey column lines."""
    strip = Rect(grid.rect.x, grid.rect.y + HEADER_HEIGHT + ROW_INSET, grid.rect.width, ROW_HEIGHT - 2 * ROW_INSET)
    with TemporaryDirectory() as scratch:
        shot = ui.capture(strip, Path(scratch) / "row.png")
        with Image.open(shot) as image:
            pixels = image.convert("RGB")
    if row_drawn(pixels):
        return True
    return any(box.text.strip() for box in ocr.recognize(pixels))


def row_drawn(pixels: Image.Image) -> bool:
    """Dark text, or a selected row's blue, covering more than a speck of the strip."""
    marked = sum(
        1 for red, green, blue in pixels.getdata() if (red + green + blue) / 3 < DARK_LEVEL or (blue > 180 and blue - red > SELECTED_BLUE_MARGIN)
    )
    return marked > max(MIN_MARKED_PIXELS, pixels.width * pixels.height * MIN_MARKED_SHARE)


def copy_all(ui: UiBackend, grid: Element, *, x_offset: float = 150) -> str:
    """Every row of a grid that has rows: click into it, select all, copy."""
    ui.click(grid, at=(grid.rect.x + x_offset, row_y(grid, 0)))
    ui.key("primary+a")
    return ui.copy_selection()


def select_row(ui: UiBackend, grid: Element, index: int, rows: int, *, x_offset: float = 150) -> str:
    """Leave exactly row `index` selected and return its copy, for the caller to confirm."""
    ui.click(grid, at=(grid.rect.x + x_offset, row_y(grid, 0)))
    for _ in range(rows):
        ui.key("up")
    for _ in range(index):
        ui.key("down")
    return ui.copy_selection()


def copy_line(ui: UiBackend, grid: Element, index: int) -> str:
    """One whole row of the order items grid, selected by its row header."""
    ui.click(grid, at=(grid.rect.x + ROW_HEADER_DX, row_y(grid, index)))
    return ui.copy_selection()


def column_centres(ui: UiBackend, ocr: OcrEngine, grid: Element, names: tuple[str, ...]) -> Mapping[str, float]:
    """Screen x of each named column, from OCR of the header row."""
    header = Rect(grid.rect.x, grid.rect.y, grid.rect.width, HEADER_HEIGHT)
    with TemporaryDirectory() as scratch:
        shot = ui.capture(header, Path(scratch) / "header.png")
        with Image.open(shot) as image:
            scale = image.width / header.width
            boxes = ocr.recognize(image.convert("RGB"))
    centres = {}
    for name in names:
        found = [box for box in boxes if box.text.strip() == name]
        if len(found) != 1:
            raise NeedsReview("grid_column_not_found", {"column": name})
        centres[name] = header.x + (found[0].box.x + found[0].box.width / 2) / scale
    return centres


def edit_cell(ui: UiBackend, grid: Element, *, x: float, index: int, text: str) -> None:
    """Type `text` into one cell and commit it with Return."""

    def editor_open() -> bool:
        focused = ui.focused()
        return focused is not None and focused.role is Role.TEXT_FIELD and grid.rect.contains(focused.rect)

    ui.click(grid, at=(x, row_y(grid, index)))
    if editor_open():  # the cell was already selected, so the click opened its editor
        ui.key("primary+a")
        ui.type_text(text)
    else:
        ui.key(text[0])  # a real key code opens the editor holding this character
        wait_until(editor_open, what="the cell editor", timeout=EDITOR_SECONDS, poll=0.1)
        ui.type_text(text[1:])
    ui.key("return")
