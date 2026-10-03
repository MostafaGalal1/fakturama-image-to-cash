"""The Debtor: selected from the open Order, created in a New Debtor editor when missing (brief §2)."""

from __future__ import annotations

from decimal import Decimal

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.backend.base import BackendError
from image_to_cash.drive.elements import Element, Role
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.copied import parse_address_rows
from image_to_cash.drive.fakturama.fields import button_inside, choose_option, percent_holds, shown
from image_to_cash.drive.fakturama.grids import SETTLE_SECONDS, copy_all, has_rows, measure_rows, select_row
from image_to_cash.drive.fakturama.master_data import ensure_payment_method
from image_to_cash.drive.fakturama.order import OrderEditor
from image_to_cash.drive.fakturama.rules import address_lines_match, decide_debtor
from image_to_cash.drive.fakturama import controls as find
from image_to_cash.drive.locate import by_title, right_of_label
from image_to_cash.drive.report import Outcome
from image_to_cash.drive.waits import WaitTimeout, wait_until
from image_to_cash.errors import NeedsReview
from image_to_cash.model import Address, PaymentMethod
from image_to_cash.normalized import Debtor

SELECTOR = "Select the address"
NEW_DEBTOR = "New Debtor"
NEW_CONTACT_BUTTON = "Create a new contact"  # the main toolbar's Contact button
INVOICE_ROLE, DELIVERY_ROLE = "Invoice address", "Delivery address"
EXTRA_ADDRESS_TAB = "additional address #1"
TOGGLE_CLOSE_SECONDS = 1.5  # macOS closes the role window on the second ▶ press within this


def select_debtor(ctx: Context, order: OrderEditor, debtor: Debtor) -> bool:
    """Brief §2.1-2.4 and §2.12-2.13. True when the Order now holds this Debtor's addresses."""
    order.activate()
    ctx.ui.click(find.address_picker(order.scan()))
    dialog = ctx.wb.wait_dialog(SELECTOR)
    controls = ctx.ui.tree(dialog)
    search = right_of_label(controls, "Search:")
    ctx.ui.focus(search)
    ctx.ui.key("primary+a")
    ctx.ui.paste_text(debtor.company, search)
    ctx.sleep(SETTLE_SECONDS)
    ctx.wb.check_errors()
    if ctx.wb.dialog_open(SELECTOR):
        if not _pick_row(ctx, controls, debtor):
            ctx.ui.press(by_title(controls, Role.BUTTON, "Cancel"))
            wait_until(lambda: not ctx.wb.dialog_open(SELECTOR), what="the selector to close", timeout=5)
            return False
    # else: the selector accepted its single hit by itself; the addresses below decide.
    return _addresses_match(ctx, order, debtor)


def _pick_row(ctx: Context, controls: tuple[Element, ...], debtor: Debtor) -> bool:
    grid = _selector_grid(controls)
    if not has_rows(ctx.ui, ctx.ocr, grid):
        return False
    try:
        measured = measure_rows(ctx.ui, ctx.ocr, grid)
        rows = parse_address_rows(copy_all(ctx.ui, grid, rows=measured))
    except (BackendError, WaitTimeout):  # BackendError covers UnsafeToAct
        if ctx.wb.dialog_open(SELECTOR):
            raise
        return True  # the selector accepted its single hit late, by itself; the addresses decide
    decision = decide_debtor(rows, debtor)
    if decision.creates:
        return False
    picked = parse_address_rows(select_row(ctx.ui, grid, decision.index, len(rows), measured=measured))
    if picked != (rows[decision.index],):
        raise NeedsReview("selector_row_not_selected", {"selector": SELECTOR})
    ctx.wb.shot("debtor-selector")
    ctx.ui.press(by_title(controls, Role.BUTTON, "OK"))
    wait_until(lambda: not ctx.wb.dialog_open(SELECTOR), what="the selector to close", timeout=5)
    return True


def _selector_grid(controls: tuple[Element, ...]) -> Element:
    grids = sorted((e for e in controls if e.role is Role.OTHER and e.rect.height > 200), key=lambda e: (e.rect.width, e.rect.height))  # the innermost: a grid sits below its search row
    if not grids:
        raise NeedsReview("grid_not_found", {"grid": SELECTOR})
    return grids[0]


def _addresses_match(ctx: Context, order: OrderEditor, debtor: Debtor) -> bool:
    invoice, delivery = order.address_texts()
    return address_lines_match(invoice, debtor, debtor.billing_address) and address_lines_match(
        delivery, debtor, debtor.delivery_address
    )


def open_new_debtor(ctx: Context) -> None:
    """Brief §2.5: New Contact in the left panel. In the Windows VM, after Fakturama restarted,
    that link opened a saved Debtor instead; the toolbar's Contact button, which opens the same
    New Debtor editor, is the fallback."""
    try:
        ctx.wb.click_nav("New Contact", opened=lambda: ctx.wb.active_editor_title() == NEW_DEBTOR)
    except NeedsReview as stop:
        if stop.reason != "navigation_failed":
            raise
        ctx.record("new_contact_link", Outcome.DONE, opened="another editor", fallback="toolbar Contact button")
        ctx.ui.press(ctx.wb.toolbar_button(NEW_CONTACT_BUTTON))
        ctx.wb.wait_for_editor_tab(lambda title: title == NEW_DEBTOR, NEW_DEBTOR)


def create_debtor(ctx: Context, debtor: Debtor, method: PaymentMethod) -> None:
    """Brief §2.5-2.11, leaving the Order tab open. The payment method is made sure of first: an
    open Debtor editor lists the methods it found when it opened, never one saved after."""
    ensure_payment_method(ctx, method)
    open_new_debtor(ctx)
    fields = ctx.wb.scan_editor(lambda found: right_of_label(found, "Company", role=Role.TEXT_AREA), "the New Debtor editor")
    set_text(ctx.ui, right_of_label(fields, "Company", role=Role.TEXT_AREA), debtor.company, label="company", commit=None)
    set_text(ctx.ui, right_of_label(fields, "First Name Last Name", nth=0), debtor.first_name, label="first_name")
    set_text(ctx.ui, right_of_label(fields, "First Name Last Name", nth=1), debtor.last_name, label="last_name")
    if shown(ctx.ui, right_of_label(fields, "Salutation", role=Role.POPUP)) != "---":
        raise NeedsReview("salutation_not_blank")
    same = not debtor.delivery_differs
    _fill_address(ctx, debtor, debtor.billing_address, roles=(INVOICE_ROLE, DELIVERY_ROLE) if same else (INVOICE_ROLE,), main=True)
    if not same:
        ctx.ui.press(find.add_address_button(ctx.ui.scan(ctx.wb.editor_area())))
        _open_tab(ctx, EXTRA_ADDRESS_TAB)
        _fill_address(ctx, debtor, debtor.delivery_address, roles=(DELIVERY_ROLE,), main=False)
    ctx.wb.shot("debtor-addresses")
    _fill_miscellaneous(ctx, debtor, method)
    ctx.wb.save("Debtor")
    saved = f"{debtor.company}, {debtor.first_name} {debtor.last_name}"
    ctx.wb.wait_for_editor_tab(lambda title: title == saved, "saved Debtor", timeout=15)
    ctx.record("debtor", Outcome.CREATED, company=debtor.company, delivery_address="separate" if not same else "same")


def _fill_address(ctx: Context, debtor: Debtor, address: Address, *, roles: tuple[str, ...], main: bool) -> None:
    fields = ctx.ui.scan(ctx.wb.editor_area())
    if address.name != debtor.company:  # an extra name line only when the image gives one
        set_text(ctx.ui, right_of_label(fields, "additional name"), address.name, label="additional_name")
    set_text(ctx.ui, right_of_label(fields, "Street"), address.street, label="street")
    ctx.wb.check_errors()  # Fakturama warns here when a contact of this name has this street
    set_text(ctx.ui, right_of_label(fields, "ZIP - City", nth=0), address.zip, label="zip")
    set_text(ctx.ui, right_of_label(fields, "ZIP - City", nth=1), address.city, label="city")
    choose_option(ctx.ui, right_of_label(fields, "Country", role=Role.POPUP), address.country, label="country")
    if main:
        set_text(ctx.ui, right_of_label(fields, "E-Mail"), debtor.email, label="email")
        set_text(ctx.ui, right_of_label(fields, "Telephone"), debtor.phone, label="telephone")
    _set_address_roles(ctx, fields, roles)


def _set_address_roles(ctx: Context, fields: tuple[Element, ...], roles: tuple[str, ...]) -> None:
    """The ▶ at the end of "address type" opens a small window of role checkboxes."""
    kind = right_of_label(fields, "address type")
    toggle = button_inside(fields, kind)
    ctx.ui.press(toggle)
    boxes = wait_until(lambda: _role_boxes(ctx), what="the address type choices", timeout=5, poll=0.2)
    for title, box in boxes.items():
        if (ctx.ui.refresh(box).value == "1") != (title in roles):
            ctx.ui.press(box)
            wait_until(lambda b=box, t=title: (ctx.ui.refresh(b).value == "1") == (t in roles), what=f"{title} to toggle", timeout=3)
    _close_role_boxes(ctx, toggle)
    if shown(ctx.ui, kind) != ", ".join(roles) and set(shown(ctx.ui, kind).split(", ")) != set(roles):
        raise NeedsReview("address_type_wont_hold", {"wanted": ", ".join(roles)})


def _close_role_boxes(ctx: Context, toggle: Element) -> None:
    """The ▶ closes the window on macOS. On Windows the window closes as it loses focus and the
    same press opens it again, so Escape closes it there."""
    ctx.ui.press(toggle)
    try:
        wait_until(lambda: not _role_boxes(ctx), what="the address type choices to close", timeout=TOGGLE_CLOSE_SECONDS, poll=0.2)
    except WaitTimeout:
        ctx.ui.key("escape")
        wait_until(lambda: not _role_boxes(ctx), what="the address type choices to close", timeout=5, poll=0.2)


def _role_boxes(ctx: Context) -> dict[str, Element]:
    for window in ctx.ui.windows():
        if window.title:
            continue
        boxes = {e.title: e for e in ctx.ui.tree(window) if e.role is Role.CHECKBOX and e.title in (INVOICE_ROLE, DELIVERY_ROLE)}
        if len(boxes) == 2:
            return boxes
    return {}


def _open_tab(ctx: Context, title: str) -> None:
    tab = wait_until(
        lambda: by_title(ctx.ui.scan(ctx.wb.editor_area()), Role.RADIO, title), what=f"the '{title}' tab", timeout=10, poll=0.5, ignoring=(LookupError,)
    )
    if ctx.ui.refresh(tab).value != "True":
        ctx.ui.click(tab)
        wait_until(lambda: ctx.ui.refresh(tab).value == "True", what=f"the '{title}' tab", timeout=5, poll=0.2)


def _fill_miscellaneous(ctx: Context, debtor: Debtor, method: PaymentMethod) -> None:
    """Brief §2.9-2.10: alias, 0 % discount, Net, and the payment method (made sure of already)."""
    _open_tab(ctx, "Miscellaneous")
    fields = ctx.ui.scan(ctx.wb.editor_area())
    set_text(ctx.ui, right_of_label(fields, "Alias name"), debtor.alias, label="alias")
    set_text(ctx.ui, right_of_label(fields, "Discount"), "0", label="debtor_discount", holds=percent_holds(Decimal(0)))
    choose_option(ctx.ui, right_of_label(fields, "Net or Gross", role=Role.POPUP), "Net", label="net_or_gross")
    choose_option(ctx.ui, right_of_label(fields, "Payment", role=Role.POPUP), method.value, label="payment_method")
    ctx.wb.shot("debtor-miscellaneous")
