"""Products: selected into the open Order by SKU, created when missing (brief §3.2-3.12)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.elements import Element, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import parse_product_rows
from image_to_cash.drive.fakturama.fields import choose_option, set_amount, shown
from image_to_cash.drive.fakturama.grids import SETTLE_SECONDS, copy_all, has_rows, measure_rows, select_row
from image_to_cash.drive.fakturama.order import OrderEditor
from image_to_cash.drive.fakturama.rules import decide_product, vat_name
from image_to_cash.drive.fakturama import controls as find
from image_to_cash.drive.locate import by_title, right_of_label
from image_to_cash.drive.report import Outcome
from image_to_cash.drive.waits import wait_until
from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import Product

SELECTOR = "Select a product"
NEW_PRODUCT = "New Product"


class Picked(StrEnum):
    SELECTED = "selected"
    MISSING = "missing"


def select_product(ctx: Context, order: OrderEditor, product: Product, *, lines_before: int) -> Picked:
    """Brief §3.2-3.3. On SELECTED the Order has exactly one more line, holding this SKU."""
    order.activate()
    ctx.ui.click(find.item_picker(order.scan()))
    dialog = ctx.wb.wait_dialog(SELECTOR)
    controls = ctx.ui.tree(dialog)
    search = right_of_label(controls, "Search:")
    ctx.ui.focus(search)  # it sits under the dialog's title bar, where a click would land on the title
    ctx.ui.key("primary+a")
    ctx.ui.paste_text(product.sku, search)  # whole: the selector accepts by itself once one row is left
    ctx.sleep(SETTLE_SECONDS)
    ctx.wb.check_errors()
    if ctx.wb.dialog_open(SELECTOR) and not _pick_row(ctx, controls, product):
        ctx.ui.press(by_title(controls, Role.BUTTON, "Cancel"))
        wait_until(lambda: not ctx.wb.dialog_open(SELECTOR), what="the selector to close", timeout=5)
        return Picked.MISSING
    ctx.sleep(SETTLE_SECONDS)
    lines = order.lines()
    if len(lines) != lines_before + 1 or lines[-1].sku != product.sku:
        # e.g. the selector accepted a single hit whose SKU only contains this one
        raise NeedsReview("product_selection_unexpected", {"sku": product.sku, "lines": str(len(lines))})
    return Picked.SELECTED


def _pick_row(ctx: Context, controls: tuple[Element, ...], product: Product) -> bool:
    grids = sorted((e for e in controls if e.role is Role.OTHER and e.rect.height > 200), key=lambda e: (e.rect.width, e.rect.height))  # the innermost: a grid sits below its search row
    if not grids:
        raise NeedsReview("grid_not_found", {"grid": SELECTOR})
    grid = grids[0]
    if not has_rows(ctx.ui, ctx.ocr, grid):
        return False
    measured = measure_rows(ctx.ui, ctx.ocr, grid)
    rows = parse_product_rows(copy_all(ctx.ui, grid, rows=measured))
    decision = decide_product(rows, product)
    if decision.creates:
        return False
    if parse_product_rows(select_row(ctx.ui, grid, decision.index, len(rows), measured=measured)) != (rows[decision.index],):
        raise NeedsReview("selector_row_not_selected", {"selector": SELECTOR})
    ctx.ui.press(by_title(controls, Role.BUTTON, "OK"))
    wait_until(lambda: not ctx.wb.dialog_open(SELECTOR), what="the selector to close", timeout=5)
    return True


def create_product(ctx: Context, product: Product) -> None:
    """Brief §3.7-3.11. The VAT is chosen before the gross price: Fakturama keeps the net price
    and shows gross from the VAT, so a later VAT change would move the gross price."""
    ctx.ui.press(ctx.wb.toolbar_button("Create a new product"))
    ctx.wb.wait_for_editor_tab(lambda title: title.lstrip("*").casefold() == NEW_PRODUCT.casefold(), NEW_PRODUCT)
    fields = ctx.wb.scan_editor(lambda found: right_of_label(found, "Item Number"), "the New Product editor")
    choose_option(ctx.ui, right_of_label(fields, "VAT", role=Role.POPUP), vat_name(product.vat_percent), label="product_vat")
    set_text(ctx.ui, right_of_label(fields, "Item Number"), product.sku, label="item_number")
    set_text(ctx.ui, right_of_label(fields, "Name"), product.description, label="product_name")
    set_text(ctx.ui, find.product_description(fields), product.description, label="product_description", commit=None)
    set_amount(ctx.ui, right_of_label(fields, "Price (gross)"), product.gross_price, label="gross_price")
    set_amount(ctx.ui, right_of_label(fields, "cost price (net)"), Decimal(0), label="cost_price")
    set_text(ctx.ui, right_of_label(fields, "Stock"), "0.00", label="stock")
    if shown(ctx.ui, right_of_label(fields, "VAT", role=Role.POPUP)) != vat_name(product.vat_percent):
        raise NeedsReview("field_wont_hold", {"field": "product_vat"})
    ctx.wb.shot(f"product-{product.sku}")
    ctx.wb.save("Product")
    ctx.wb.wait_for_editor_tab(lambda title: title == product.description, "saved Product", timeout=15)
    ctx.record("product", Outcome.CREATED, sku=product.sku)
