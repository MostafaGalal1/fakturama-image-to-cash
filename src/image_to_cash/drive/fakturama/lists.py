"""The Data views below the editors (VATs, terms of payment, Documents): search, then copy rows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

from PIL import Image

from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.grids import SETTLE_SECONDS, copy_all, grid_at, has_rows, row_y
from image_to_cash.drive.locate import LocatorError, by_title, right_of_label
from image_to_cash.drive.waits import wait_until
from image_to_cash.errors import NeedsReview

Row = TypeVar("Row")
GRID_DY = 80  # below the search row, inside the grid
VIEW_TIMEOUT = 15
LIST_ATTEMPTS = 3  # a list can lag a save by a moment
ROW_X = 150  # into a row's text, clear of the grid's left edge
TREE_WIDTH = 170  # Documents' category tree, at the view's left below its tabs


def search_view(
    ctx: Context, menu: Sequence[str], text: str, parse: Callable[[str], tuple[Row, ...]], *, category: str | None = None
) -> tuple[Row, ...]:
    """Open a Data view, search `text`, and return the rows it lists (none when empty). Documents
    keeps the category last picked in its tree ("Invoices/unpaid" hid a saved Order), so a
    `category` is picked first."""
    ui = ctx.ui
    ui.press_menu(menu)
    search = wait_until(
        lambda: right_of_label(ui.scan(ctx.wb.view_area()), "Search:"),
        what=f"the {menu[-1]} list",
        timeout=VIEW_TIMEOUT,
        poll=0.5,
        ignoring=(LocatorError,),
    )
    if category is not None:
        pick_category(ctx, category)
    ui.click(search)
    ui.key("primary+a")
    ui.key("delete")  # emptied first: pasting the text already there would not filter again
    ctx.sleep(SETTLE_SECONDS)
    ui.paste_text(text, search)
    ctx.sleep(SETTLE_SECONDS)
    ctx.wb.check_errors()
    view = ctx.wb.view_area()
    grid = grid_at(ui, view.center[0], view.y + GRID_DY, menu[-1])
    if not has_rows(ui, ctx.ocr, grid):
        return ()
    return parse(copy_all(ui, grid))


def search_until(
    ctx: Context,
    menu: Sequence[str],
    text: str,
    parse: Callable[[str], tuple[Row, ...]],
    found: Callable[[tuple[Row, ...]], bool],
    *,
    category: str | None = None,
) -> tuple[Row, ...]:
    """search_view, repeated after a pause while `found` says the rows are not there yet. Returns
    the last search's rows either way; the caller decides what a miss means."""
    rows = search_view(ctx, menu, text, parse, category=category)
    for _ in range(LIST_ATTEMPTS - 1):
        if found(rows):
            break
        ctx.sleep(SETTLE_SECONDS)
        rows = search_view(ctx, menu, text, parse, category=category)
    return rows


def pick_category(ctx: Context, name: str) -> None:
    """Clicks `name` in the view's category tree, found by OCR (the tree's items are not listed
    to accessibility), and waits for the view's filter label to show it."""
    view = ctx.wb.view_area()
    strip = ctx.ui.layout.tab_strip
    tree = Rect(view.x, view.y + strip, TREE_WIDTH, view.height - strip)
    with TemporaryDirectory() as scratch:
        shot = ctx.ui.capture(tree, Path(scratch) / "tree.png")
        with Image.open(shot) as image:
            scale = image.width / tree.width
            boxes = [box for box in ctx.ocr.recognize(image.convert("RGB")) if box.text.strip() == name]
    if len(boxes) != 1:
        raise NeedsReview("category_not_found", {"category": name})
    x = tree.x + (boxes[0].box.x + boxes[0].box.width / 2) / scale
    y = tree.y + (boxes[0].box.y + boxes[0].box.height / 2) / scale
    item = ctx.ui.element_at(x, y)
    if item is None:
        raise NeedsReview("category_not_found", {"category": name})
    ctx.ui.click(item, at=(x, y))
    wait_until(
        lambda: any(e.role is Role.LABEL and e.value == name for e in ctx.ui.scan(ctx.wb.view_area())),
        what=f"the {name} category",
        timeout=5,
        poll=0.3,
    )


def view_button(ctx: Context, help_text: str) -> Element:
    """A button in the view's own toolbar, such as the green + ("Create a new tax rate")."""
    try:
        return by_title(ctx.wb.view_toolbar(), Role.BUTTON, help_text)
    except LocatorError:
        raise NeedsReview("control_not_found", {"control": help_text}) from None



def open_row(ctx: Context, index: int, what: str) -> None:
    """Double-clicks row `index` of the list the last search_view showed, which opens its editor."""
    view = ctx.wb.view_area()
    grid = grid_at(ctx.ui, view.center[0], view.y + GRID_DY, what)
    ctx.ui.click(grid, at=(grid.rect.x + ROW_X, row_y(ctx.ui.layout, grid, index)), count=2)
