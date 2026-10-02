"""Stage 2: one continuous Order-first run of the brief, from order.json to a verified Invoice.

Order of work follows the brief exactly: open the Order first, resolve the Debtor and each
Product through the Order's own selectors, create missing master data only then, return to the
same open Order, save it, create the linked Invoice, record the payment, verify both documents.
Any NeedsReview stops the run with a screenshot and a log line; nothing is guessed.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path

from image_to_cash.drive.backend.base import UiBackend
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.debtor import create_debtor, select_debtor
from image_to_cash.drive.fakturama.invoice import check_copied_from_order, check_invoice_listed, check_order_listed, record_payment
from image_to_cash.drive.fakturama.master_data import ensure_vat
from image_to_cash.drive.fakturama.order import OrderEditor
from image_to_cash.drive.fakturama.product import Picked, create_product, select_product
from image_to_cash.drive.fakturama.rules import address_lines_match
from image_to_cash.drive.fakturama.workbench import Workbench
from image_to_cash.drive.report import Outcome, RunLog
from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import NormalizedOrder
from image_to_cash.ocr.base import OcrEngine

WHERE_FRAMES = 4  # enough to name the step and the call that failed


@dataclass(frozen=True)
class DriveResult:
    order_number: str
    invoice_number: str


def drive(order: NormalizedOrder, backend: UiBackend, ocr: OcrEngine, out_dir: Path) -> DriveResult:
    ctx = Context(Workbench(backend, out_dir / "screens"), ocr, RunLog(out_dir / "run.jsonl"))
    try:
        return _run(ctx, order)
    except NeedsReview as stop:
        ctx.record("stopped", Outcome.STOPPED, reason=stop.reason, **stop.details)
        _try_shot(ctx, "stopped")
        raise
    except Exception as error:  # an unexpected failure is still a stop, with the same evidence
        ctx.record("stopped", Outcome.STOPPED, reason="unexpected_error", error=type(error).__name__, message=str(error)[:200], where=where(error))
        _try_shot(ctx, "stopped")
        raise


def where(error: BaseException) -> str:
    """The innermost frames of this package, so an unexpected stop names the code that failed."""
    frames = [f for f in traceback.extract_tb(error.__traceback__) if f"{Path('image_to_cash')}" in f.filename]
    return " < ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames[-WHERE_FRAMES:]))


def _run(ctx: Context, order: NormalizedOrder) -> DriveResult:
    ctx.ui.bring_to_front()
    ctx.wb.check_errors()
    editor = OrderEditor.open(ctx, order)
    _resolve_debtor(ctx, editor, order)
    products = {product.sku: product for product in order.products}
    for index, line in enumerate(order.lines):
        product = products[line.sku]
        if select_product(ctx, editor, product, lines_before=index) is Picked.MISSING:
            ensure_vat(ctx, product.vat_percent)
            create_product(ctx, product)
            if select_product(ctx, editor, product, lines_before=index) is Picked.MISSING:
                raise NeedsReview("product_not_selectable", {"sku": product.sku})
        else:
            ctx.record("product", Outcome.FOUND, sku=product.sku)
        editor.complete_line(index, line)
        ctx.record("line", Outcome.CHECKED, position=str(index + 1), sku=line.sku)
    editor.activate()
    if not _debtor_still_selected(editor, order):
        raise NeedsReview("debtor_addresses_changed")
    editor.check_totals(order.totals)
    ctx.wb.shot("order-complete")
    order_number = editor.save()
    ctx.record("order_saved", Outcome.DONE, number=order_number)
    check_order_listed(ctx, order, order_number)
    invoice = editor.follow_up_invoice()
    check_copied_from_order(invoice, order)
    record_payment(invoice, order)
    ctx.wb.shot("invoice-complete")
    invoice_number = invoice.save()
    ctx.record("invoice_saved", Outcome.DONE, number=invoice_number, paid=order.payment.status.value)
    check_invoice_listed(ctx, order, order_number, invoice_number)
    return DriveResult(order_number, invoice_number)


def _resolve_debtor(ctx: Context, editor: OrderEditor, order: NormalizedOrder) -> None:
    """Brief §2: select from the Order; else create, then select the new Debtor from the Order."""
    if select_debtor(ctx, editor, order.debtor):
        ctx.record("debtor", Outcome.FOUND, company=order.debtor.company)
    else:
        create_debtor(ctx, order.debtor, order.payment.method)
        if not select_debtor(ctx, editor, order.debtor):
            raise NeedsReview("debtor_not_selectable", {"company": order.debtor.company})
    ctx.wb.shot("order-debtor")
    ctx.record("debtor_selected", Outcome.CHECKED, company=order.debtor.company)


def _debtor_still_selected(editor: OrderEditor, order: NormalizedOrder) -> bool:
    invoice, delivery = editor.address_texts()
    return address_lines_match(invoice, order.debtor, order.debtor.billing_address) and address_lines_match(
        delivery, order.debtor, order.debtor.delivery_address
    )


def _try_shot(ctx: Context, name: str) -> None:
    try:
        ctx.wb.shot(name)
    except Exception as error:  # the stop reason matters more than its screenshot
        ctx.record("screenshot_failed", Outcome.STOPPED, shot=name, error=type(error).__name__)
