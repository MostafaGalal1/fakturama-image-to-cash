"""VAT rates and payment methods: search the Data list, reuse one exact row, else create one."""

from __future__ import annotations

from decimal import Decimal

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.elements import Element, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import parse_payment_rows, parse_vat_rows
from image_to_cash.drive.fakturama.fields import percent_holds, shown
from image_to_cash.drive.fakturama.lists import search_until, search_view, view_button
from image_to_cash.drive.fakturama.rules import PAYMENT_CODES, STANDARD_RATE_CODE, decide_payment, decide_vat, vat_name
from image_to_cash.drive.locate import right_of_label
from image_to_cash.drive.report import Outcome
from image_to_cash.errors import NeedsReview
from image_to_cash.model import PaymentMethod

VATS_MENU = ("Data", "VATs")
PAYMENTS_MENU = ("Data", "terms of payment")


def ensure_vat(ctx: Context, percent: Decimal) -> None:
    """Brief §3.4-3.6."""
    name = vat_name(percent)
    if not decide_vat(search_view(ctx, VATS_MENU, name, parse_vat_rows), percent).creates:
        ctx.record("vat", Outcome.FOUND, name=name)
        return
    ctx.ui.press(view_button(ctx, "Create a new tax rate"))
    fields = ctx.wb.scan_editor(lambda found: right_of_label(found, "Description"), "the new VAT editor")
    set_text(ctx.ui, right_of_label(fields, "Name"), name, label="vat_name")
    set_text(ctx.ui, right_of_label(fields, "Description"), name, label="vat_description")
    code = right_of_label(fields, "VAT code (E-Invoice)", role=Role.POPUP)
    if shown(ctx.ui, code) != STANDARD_RATE_CODE:  # the brief keeps the proposed code; anything else is a surprise
        raise NeedsReview("vat_code_unexpected", {"code": shown(ctx.ui, code)})
    set_text(ctx.ui, right_of_label(fields, "Value"), f"{percent.normalize():f}", label="vat_value", holds=percent_holds(percent))
    ctx.wb.shot("vat-filled")
    ctx.wb.save("VAT")
    saved = search_until(ctx, VATS_MENU, name, parse_vat_rows, lambda rows: not decide_vat(rows, percent).creates)
    if decide_vat(saved, percent).creates:
        raise NeedsReview("vat_not_saved", {"name": name})
    ctx.record("vat", Outcome.CREATED, name=name)


def ensure_payment_method(ctx: Context, method: PaymentMethod) -> None:
    """Brief §2.10.1-2.10.6. The caller returns to the Debtor editor afterwards."""
    rows = search_view(ctx, PAYMENTS_MENU, method.value, parse_payment_rows)
    if not decide_payment(rows, method).creates:
        ctx.record("payment_method", Outcome.FOUND, name=method.value)
        return
    ctx.ui.press(view_button(ctx, "Create a new term of payment"))
    fields = ctx.wb.scan_editor(lambda found: right_of_label(found, "Net Days"), "the new payment editor")
    set_text(ctx.ui, right_of_label(fields, "Name"), method.value, label="payment_name")
    set_text(ctx.ui, right_of_label(fields, "Description"), method.value, label="payment_description")
    if shown(ctx.ui, right_of_label(fields, "Account")):
        raise NeedsReview("payment_account_not_blank")
    ctx.ui.choose(_payment_code_popup(fields), PAYMENT_CODES[method])
    set_text(ctx.ui, right_of_label(fields, "Cash discount"), "0", label="cash_discount", holds=percent_holds(Decimal(0)))
    set_text(ctx.ui, right_of_label(fields, "Discount Days"), "0", label="discount_days")
    set_text(ctx.ui, right_of_label(fields, "Net Days"), "0", label="net_days")
    if any(shown(ctx.ui, text) for text in fields if text.role is Role.TEXT_AREA):
        raise NeedsReview("payment_texts_not_blank")
    ctx.wb.shot("payment-method-filled")
    ctx.wb.save("payment method")
    saved = search_until(ctx, PAYMENTS_MENU, method.value, parse_payment_rows, lambda rows: not decide_payment(rows, method).creates)
    if decide_payment(saved, method).creates:
        raise NeedsReview("payment_method_not_saved", {"name": method.value})
    ctx.record("payment_method", Outcome.CREATED, name=method.value, code=PAYMENT_CODES[method])


def _payment_code_popup(fields: tuple[Element, ...]) -> Element:
    """Fakturama 2.2 leaves this label untranslated ("!editorPaymentPaymentcode!"); it is the
    editor's only pop-up."""
    popups = [e for e in fields if e.role is Role.POPUP]
    if len(popups) != 1:
        raise NeedsReview("control_not_found", {"control": "payment code"})
    return popups[0]
