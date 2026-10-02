"""A re-run never enters an order twice: what an earlier run saved for this reference decides
where this one starts (README "Known limitations").

Data > Documents is searched for the order's reference (Cust.Ref.) before anything is created:
- nothing: a fresh run;
- one open Order with the image's total: it was saved, the Invoice was not; resume there;
- that Order and one Invoice in the expected state with the same total: already entered;
- anything else (two Orders, an Invoice without its Order, another total or state): a person
  decides, because a guess here would duplicate or overwrite a booking.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import DocumentRow, DocumentState, parse_document_rows
from image_to_cash.drive.fakturama.invoice import INVOICES, ORDERS
from image_to_cash.drive.fakturama.lists import open_row, search_view
from image_to_cash.drive.fakturama.order import OrderEditor
from image_to_cash.errors import NeedsReview
from image_to_cash.model import PaidStatus
from image_to_cash.normalized import NormalizedOrder

DOCUMENTS_MENU = ("Data", "Documents")


@dataclass(frozen=True)
class Earlier:
    """What earlier runs saved for this order: nothing, its Order, or its Order and Invoice."""

    order: DocumentRow | None = None
    invoice: DocumentRow | None = None
    order_row: int = -1  # the Order's row in the Documents search, to open it


def find_earlier(ctx: Context, order: NormalizedOrder) -> Earlier:
    """Invoices first: the Orders search stays on screen for reopen_order."""
    reference = order.external_reference
    invoices = search_view(ctx, DOCUMENTS_MENU, reference, parse_document_rows, category=INVOICES)
    orders = search_view(ctx, DOCUMENTS_MENU, reference, parse_document_rows, category=ORDERS)
    return decide_earlier(orders, invoices, order)


def decide_earlier(order_rows: Sequence[DocumentRow], invoice_rows: Sequence[DocumentRow], order: NormalizedOrder) -> Earlier:
    reference = order.external_reference
    orders = [(index, row) for index, row in enumerate(order_rows) if row.reference == reference]
    invoices = [row for row in invoice_rows if row.reference == reference]
    if not orders and not invoices:
        return Earlier()
    if len(orders) != 1 or len(invoices) > 1 or any(row.kind != "ORDER" for _, row in orders) or any(row.kind != "INVOICE" for row in invoices):
        raise NeedsReview("already_entered", {"reference": reference, "documents": str(len(orders) + len(invoices))})
    index, saved = orders[0]
    _require(saved, DocumentState.OPEN, order)
    if not invoices:
        return Earlier(order=saved, order_row=index)
    paid = DocumentState.PAID if order.payment.status is PaidStatus.PAID else DocumentState.UNPAID
    _require(invoices[0], paid, order)
    return Earlier(order=saved, invoice=invoices[0], order_row=index)


def reopen_order(ctx: Context, earlier: Earlier) -> OrderEditor:
    """Opens the saved Order from the Documents search find_earlier left on screen."""
    if earlier.order is None:
        raise ValueError("no saved Order to reopen")
    number = earlier.order.number
    open_row(ctx, earlier.order_row, "Documents")
    ctx.wb.wait_for_editor_tab(lambda title: title == number, f"Order {number}")
    return OrderEditor(ctx, number)


def _require(row: DocumentRow, state: DocumentState, order: NormalizedOrder) -> None:
    if row.state != state or row.total != order.totals.gross:
        raise NeedsReview("already_entered_differently", {"number": row.number, "state": str(row.state), "total": str(row.total)})
