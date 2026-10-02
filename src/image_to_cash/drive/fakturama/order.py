"""The Order editor (brief §1.3-1.8, §3.13-3.17, §4) and the shared parts of the Invoice editor."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import LineRow, parse_line_rows
from image_to_cash.drive.fakturama.fields import set_date, shown
from image_to_cash.drive.fakturama.grids import column_centres, copy_all, copy_line, edit_cell, grid_at, measure_rows
from image_to_cash.drive.fakturama.rules import check_line
from image_to_cash.drive.formats import GERMAN, format_amount, parse_amount
from image_to_cash.drive.fakturama import controls as find
from image_to_cash.drive.locate import LocatorError, by_title, label, right_of_label
from image_to_cash.drive.report import Outcome
from image_to_cash.errors import NeedsReview
from image_to_cash.model import Totals
from image_to_cash.normalized import NormalizedOrder, OrderLine

NEW_ORDER = "New Order"
QTY, UNIT_PRICE, DISCOUNT = "Qty.", "U.Price", "Discount"
GRID_DX = 250  # from the "Items" label into the grid


FOLLOW_UP_INVOICE_HELP = frozenset({"Create: New Invoice", "Invoice"})  # Windows: a toolbar button's help is its name


class DocumentEditor:
    """An Order or Invoice editor tab, found again by its title (it changes when saved)."""

    def __init__(self, ctx: Context, title: str) -> None:
        self.ctx = ctx
        self.title = title
        self._columns: Mapping[str, float] | None = None

    def activate(self) -> None:
        self.ctx.wb.activate_editor(lambda title: title.lstrip("*") == self.title, self.title)

    def scan(self) -> tuple[Element, ...]:
        return self.ctx.ui.scan(self.ctx.wb.editor_area())

    def number(self) -> str:
        return shown(self.ctx.ui, find.document_number(self.scan()))

    def address_texts(self) -> tuple[str, str]:
        """The Invoice address and Delivery address blocks, each on its own tab."""
        texts = []
        for tab in ("Delivery address", "Invoice address"):  # end on the Invoice tab, as opened
            controls = self.scan()
            radio = by_title(controls, Role.RADIO, tab)
            if self.ctx.ui.refresh(radio).value != "True":
                self.ctx.ui.click(radio)
                self.ctx.sleep(0.5)
            texts.append(shown(self.ctx.ui, self._address_block(self.scan())))
        delivery, invoice = texts
        return invoice, delivery

    def _address_block(self, controls: tuple[Element, ...]) -> Element:
        picker = find.address_picker(controls)
        blocks = [e for e in controls if e.role is Role.TEXT_AREA and abs(e.rect.y - picker.rect.y) <= 4]
        if len(blocks) != 1:
            raise NeedsReview("control_not_found", {"control": "address block"})
        return blocks[0]

    # Items grid.

    def grid(self) -> Element:
        items = label(self.scan(), "Items")
        return grid_at(self.ctx.ui, items.rect.right + GRID_DX, items.rect.y + 12, "items")

    def lines(self) -> tuple[LineRow, ...]:
        grid = self.grid()
        return parse_line_rows(copy_all(self.ctx.ui, grid, x_offset=12))

    def line(self, index: int) -> LineRow:
        grid = self.grid()
        rows = parse_line_rows(copy_line(self.ctx.ui, grid, index, measure_rows(self.ctx.ui, self.ctx.ocr, grid)))
        if len(rows) != 1:
            raise NeedsReview("line_not_read", {"position": str(index + 1)})
        return rows[0]

    def complete_line(self, index: int, line: OrderLine) -> LineRow:
        """Brief §3.13-3.16: quantity, unit price and discount, then the line is read back."""
        grid = self.grid()
        if self._columns is None:
            self._columns = column_centres(self.ctx.ui, self.ctx.ocr, grid, (QTY, UNIT_PRICE, DISCOUNT))
        current = self.line(index)
        measured = measure_rows(self.ctx.ui, self.ctx.ocr, grid)
        if current.sku != line.sku:
            raise NeedsReview("line_mismatch", {"position": str(index + 1), "field": "sku"})
        wanted = (
            (QTY, current.quantity, line.quantity, f"{line.quantity.normalize():f}"),
            (UNIT_PRICE, current.unit_net_price, line.unit_net_price, format_amount(line.unit_net_price, GERMAN)),
            (DISCOUNT, current.discount_percent, line.discount_percent, f"{line.discount_percent.normalize():f}"),
        )
        for column, have, want, typed in wanted:
            if have != want:
                edit_cell(self.ctx.ui, grid, x=self._columns[column], index=index, text=typed, rows=measured)
                self.ctx.wb.check_errors()
        row = self.line(index)
        check_line(row, line, position=index + 1)
        return row

    # Totals.

    def totals(self) -> dict[str, Decimal]:
        controls = self.scan()
        area = self.ctx.wb.editor_area()
        items = label(controls, "Items")
        corner = [e for e in controls if e.rect.x > area.center[0] and e.rect.y > items.rect.y]
        read = {name: right_of_label(corner, name) for name in ("Total Net", "Discount", "VAT", "Total")}
        return {name: parse_amount(shown(self.ctx.ui, field), GERMAN) for name, field in read.items() if name != "Discount"} | {
            "Discount": Decimal(shown(self.ctx.ui, read["Discount"]).removesuffix("%").strip().replace(",", ".") or "0")
        }

    def check_totals(self, totals: Totals) -> None:
        """Brief §4.2-4.3: no order discount, free shipping, and the source totals."""
        shown_totals = self.totals()
        expected = {"Total Net": totals.net, "VAT": totals.vat, "Total": totals.gross, "Discount": Decimal(0)}
        for name, want in expected.items():
            if shown_totals[name] != want:
                raise NeedsReview("totals_mismatch", {"field": name})
        try:
            shipping = find.shipping(self.scan())
        except LocatorError:
            raise NeedsReview("shipping_not_free") from None
        if shown(self.ctx.ui, shipping) != "Free of shipping costs":
            raise NeedsReview("shipping_not_free")


class OrderEditor(DocumentEditor):
    @classmethod
    def open(cls, ctx: Context, order: NormalizedOrder) -> OrderEditor:
        """Brief §1.3-1.7."""
        ctx.ui.press(ctx.wb.toolbar_button("Create: New Order"))
        ctx.wb.wait_for_editor_tab(lambda title: title.lstrip("*") == NEW_ORDER, NEW_ORDER)
        editor = cls(ctx, NEW_ORDER)
        controls = ctx.wb.scan_editor(lambda found: right_of_label(found, "Cust.Ref."), "the New Order editor")
        number = shown(ctx.ui, find.document_number(controls))
        if not number:
            raise NeedsReview("order_number_missing")
        set_date(ctx.ui, right_of_label(controls, "Date"), order.order_date, label="order_date")
        set_text(ctx.ui, right_of_label(controls, "Cust.Ref."), order.external_reference, label="cust_ref")
        ctx.ui.choose(find.price_mode(controls), "Net")
        if shown(ctx.ui, find.vat_mode(controls)) != "With VAT":
            raise NeedsReview("vat_mode_not_with_vat")
        ctx.record("order_opened", Outcome.DONE, number=number)
        ctx.wb.shot("order-header")
        return editor

    def save(self) -> str:
        """Brief §4.4: saved once; the tab then carries the order number."""
        number = self.number()
        self.ctx.wb.save("Order")
        self.ctx.wb.wait_for_editor_tab(lambda title: title == number, "saved Order", timeout=15)
        self.title = number
        return number

    def follow_up_invoice(self) -> InvoiceEditor:
        """Brief §4.6: the Invoice button in the Order's own follow-up area, not the toolbar's."""
        self.activate()
        area = self.ctx.wb.editor_area()
        buttons = [
            e for e in self.scan() if e.role is Role.BUTTON and e.title == "Invoice" and e.help in FOLLOW_UP_INVOICE_HELP and area.contains(e.rect)
        ]
        if len(buttons) != 1:
            raise NeedsReview("control_not_found", {"control": "follow-up Invoice"})
        self.ctx.ui.press(buttons[0])
        self.ctx.wb.wait_for_editor_tab(lambda title: title.lstrip("*") == "New Invoice", "New Invoice")
        return InvoiceEditor(self.ctx, "New Invoice")


class InvoiceEditor(DocumentEditor):
    def payment_row(self) -> tuple[tuple[Element, ...], Element]:
        """The controls on the 'paid' row (payment method, date, value) and the checkbox."""
        controls = self.scan()
        paid = find.paid_box(controls)
        row = Rect(self.ctx.wb.editor_area().x, paid.rect.y - 8, 700, paid.rect.height + 16)
        return tuple(e for e in controls if row.contains(e.rect)), paid

    def save(self) -> str:
        number = self.number()
        self.ctx.wb.save("Invoice")
        self.ctx.wb.wait_for_editor_tab(lambda title: title == number, "saved Invoice", timeout=15)
        self.title = number
        return number

