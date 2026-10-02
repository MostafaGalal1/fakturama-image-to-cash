"""The linked Invoice (brief §5) and the Data > Documents check (brief §4.5, §5.5)."""

from __future__ import annotations

from image_to_cash.drive.elements import Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import DocumentRow, DocumentState, parse_document_rows
from image_to_cash.drive.fakturama.fields import choose_option, set_amount, set_date, shown
from image_to_cash.drive.fakturama.lists import search_until
from image_to_cash.drive.fakturama.order import InvoiceEditor
from image_to_cash.drive.fakturama.rules import address_lines_match, check_document, check_line
from image_to_cash.drive.formats import parse_display_date
from image_to_cash.drive.fakturama import controls as find
from image_to_cash.drive.locate import right_of_label
from image_to_cash.drive.report import Outcome
from image_to_cash.drive.waits import wait_until
from image_to_cash.errors import NeedsReview
from image_to_cash.model import PaidStatus
from image_to_cash.normalized import NormalizedOrder

DOCUMENTS_MENU = ("Data", "Documents")


def check_copied_from_order(invoice: InvoiceEditor, order: NormalizedOrder) -> None:
    """Brief §5.1: number and dates are left as proposed; the rest must equal the Order."""
    ui = invoice.ctx.ui
    controls = invoice.scan()
    checks = {
        "cust_ref": shown(ui, right_of_label(controls, "Cust.Ref.")) == order.external_reference,
        "order_date": parse_display_date(shown(ui, right_of_label(controls, "Order Date"))) == order.order_date,
        "price_mode": shown(ui, find.price_mode(controls)) == "Net",
        "vat_mode": shown(ui, find.vat_mode(controls)) == "With VAT",
    }
    invoice_text, delivery_text = invoice.address_texts()
    checks["invoice_address"] = address_lines_match(invoice_text, order.debtor, order.debtor.billing_address)
    checks["delivery_address"] = address_lines_match(delivery_text, order.debtor, order.debtor.delivery_address)
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise NeedsReview("invoice_not_copied", {"fields": ",".join(failed)})
    lines = invoice.lines()
    if len(lines) != len(order.lines):
        raise NeedsReview("invoice_lines", {"lines": str(len(lines))})
    for position, (row, line) in enumerate(zip(lines, order.lines, strict=True), start=1):
        check_line(row, line, position=position)
    invoice.check_totals(order.totals)


def record_payment(invoice: InvoiceEditor, order: NormalizedOrder) -> None:
    """Brief §5.2-5.3: the payment method, and paid/date/value only for a PAID image."""
    ctx = invoice.ctx
    row, paid = invoice.payment_row()
    methods = [e for e in row if e.role is Role.POPUP]
    if len(methods) != 1:
        raise NeedsReview("control_not_found", {"control": "invoice payment method"})
    choose_option(ctx.ui, methods[0], order.payment.method.value, label="invoice_payment_method")
    is_paid = ctx.ui.refresh(paid).value == "1"
    if order.payment.status is not PaidStatus.PAID:
        if is_paid:
            raise NeedsReview("invoice_marked_paid")
        return
    if not is_paid:
        ctx.ui.press(paid)
        wait_until(lambda: ctx.ui.refresh(paid).value == "1", what="'paid' to tick", timeout=3)
    row, _ = wait_until(
        lambda: _with_value_field(invoice.payment_row()), what="the payment date and value", timeout=5, poll=0.3, ignoring=(LookupError,)
    )
    set_date(ctx.ui, find.payment_date(row), order.payment.payment_date, label="payment_date")
    set_amount(ctx.ui, find.paid_value(row), order.totals.gross, label="paid_value")


def _with_value_field(found):
    row, paid = found
    find.paid_value(row)  # raises LookupError until shown
    return row, paid


ORDERS, INVOICES = "Orders", "Invoices"  # Documents' categories


def documents(ctx: Context, reference: str, number: str, category: str) -> tuple[DocumentRow, ...]:
    """The Documents rows of `category` for `reference`, searched again while `number` is not
    among them yet."""
    return search_until(
        ctx, DOCUMENTS_MENU, reference, parse_document_rows, lambda rows: any(row.number == number for row in rows), category=category
    )


def check_order_listed(ctx: Context, order: NormalizedOrder, number: str) -> None:
    rows = documents(ctx, order.external_reference, number, ORDERS)
    check_document(rows, number=number, kind="ORDER", reference=order.external_reference, state=DocumentState.OPEN, total=order.totals.gross)
    ctx.wb.shot("documents-order")
    ctx.record("order_listed", Outcome.CHECKED, number=number, state="open")


def check_invoice_listed(ctx: Context, order: NormalizedOrder, order_number: str, invoice_number: str) -> None:
    state = DocumentState.PAID if order.payment.status is PaidStatus.PAID else DocumentState.UNPAID
    invoices = documents(ctx, order.external_reference, invoice_number, INVOICES)
    check_document(invoices, number=invoice_number, kind="INVOICE", reference=order.external_reference, state=state, total=order.totals.gross)
    orders = documents(ctx, order.external_reference, order_number, ORDERS)
    check_document(orders, number=order_number, kind="ORDER", reference=order.external_reference, state=DocumentState.OPEN, total=order.totals.gross)
    ctx.wb.shot("documents-final")
    ctx.record("invoice_listed", Outcome.CHECKED, number=invoice_number, state=state.name.lower())
