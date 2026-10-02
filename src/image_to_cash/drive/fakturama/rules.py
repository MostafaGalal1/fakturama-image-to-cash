"""The brief's decisions, kept apart from the clicking: reuse or create, and when to stop.

Each decide_* function takes the rows a search showed and the record the order needs. One
exact row is reused; none means create; anything else (several exact rows, a near miss, an
exact key with conflicting settings) raises NeedsReview, because creating a record then could
make a duplicate and reusing it could put wrong data on the invoice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from image_to_cash.drive.fakturama.copied import AddressRow, DocumentRow, DocumentState, LineRow, PaymentRow, ProductRow, VatRow
from image_to_cash.drive.matching import MatchKind, canonical, classify
from image_to_cash.errors import NeedsReview
from image_to_cash.model import Address, PaymentMethod
from image_to_cash.normalized import Debtor, OrderLine, Product

# Brief §2.10.4: the e-invoice payment code for each method.
PAYMENT_CODES = {
    PaymentMethod.BANK_TRANSFER: "Credit transfer",
    PaymentMethod.CREDIT_CARD: "Credit card",
    PaymentMethod.SEPA_DIRECT_DEBIT: "SEPA direct debit",
}
STANDARD_RATE_CODE = "S (Standard rate)"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Decision:
    index: int | None  # the row to reuse; None means create

    @classmethod
    def reuse(cls, index: int) -> Decision:
        return cls(index)

    @classmethod
    def create(cls) -> Decision:
        return cls(None)

    @property
    def creates(self) -> bool:
        return self.index is None


def vat_name(percent: Decimal) -> str:
    return f"VAT {percent.normalize():f}%"


def date_keys(when: date) -> tuple[str, str, str]:
    """What to type into Fakturama's segmented date field, which reads month, day, year."""
    return f"{when.month:02d}", f"{when.day:02d}", f"{when.year:04d}"


def decide_debtor(rows: Sequence[AddressRow], debtor: Debtor) -> Decision:
    """Brief §2.3: Company, First Name, Name, ZIP and City must all match the billing data."""
    billing = debtor.billing_address
    expected = (debtor.company, debtor.first_name, debtor.last_name, billing.zip, billing.city)
    found = classify(expected, [(r.company, r.first_name, r.last_name, r.zip, r.city) for r in rows])
    if found.kind is MatchKind.EXACT:
        return Decision.reuse(found.index)
    if found.kind is MatchKind.NONE:
        return Decision.create()
    raise NeedsReview(f"debtor_{found.kind.value}", {"rows": str(len(rows))})


def address_lines_match(text: str, debtor: Debtor, address: Address) -> bool:
    """The address block Fakturama fills in: company, contact, street, '<CC>-ZIP City', country.

    Fakturama leaves the address's additional name out of this block, so it is not compared.
    """
    lines = [canonical(line) for line in text.splitlines() if line.strip()]
    wanted = [
        canonical(debtor.company),
        canonical(f"{debtor.first_name} {debtor.last_name}"),
        canonical(address.street),
        canonical(address.country),
    ]
    zip_city = canonical(f"{address.zip} {address.city}")
    return all(want in lines for want in wanted) and any(line.endswith(zip_city) for line in lines)


def decide_product(rows: Sequence[ProductRow], product: Product) -> Decision:
    """Brief §3.3: select by exact SKU; an exact SKU whose master data differs is a conflict."""
    matches = [index for index, row in enumerate(rows) if row.sku == product.sku]
    if not matches:
        return Decision.create()
    if len(matches) > 1:
        raise NeedsReview("product_ambiguous", {"sku": product.sku})
    row = rows[matches[0]]
    differs = {
        "name": canonical(row.name) != canonical(product.description),
        "gross_price": row.gross_price != product.gross_price,
        "vat": row.vat_percent != product.vat_percent or row.vat_name != vat_name(product.vat_percent),
    }
    conflicts = [field for field, bad in differs.items() if bad]
    if conflicts:
        raise NeedsReview("product_conflict", {"sku": product.sku, "fields": ",".join(conflicts)})
    return Decision.reuse(matches[0])


def decide_vat(rows: Sequence[VatRow], percent: Decimal) -> Decision:
    """Brief §3.5: reuse 'VAT <p>%' only when its value is p; the code is checked in its editor."""
    name = vat_name(percent)
    matches = [index for index, row in enumerate(rows) if row.name == name]
    if not matches:
        return Decision.create()
    if len(matches) > 1:
        raise NeedsReview("vat_ambiguous", {"name": name})
    if rows[matches[0]].percent != percent:
        raise NeedsReview("vat_conflict", {"name": name, "value": str(rows[matches[0]].percent)})
    return Decision.reuse(matches[0])


def decide_payment(rows: Sequence[PaymentRow], method: PaymentMethod) -> Decision:
    """Brief §2.10.2: one exact row is reused; several, or other terms, stop the run."""
    matches = [index for index, row in enumerate(rows) if row.name == method.value]
    if not matches:
        return Decision.create()
    if len(matches) > 1:
        raise NeedsReview("payment_ambiguous", {"name": method.value})
    row = rows[matches[0]]
    if (row.description, row.discount_percent, row.discount_days, row.net_days) != (method.value, ZERO, 0, 0):
        raise NeedsReview("payment_conflict", {"name": method.value})
    return Decision.reuse(matches[0])


def check_line(row: LineRow, line: OrderLine, *, position: int) -> None:
    """Brief §3.13-3.16, read back from the grid."""
    expected = {
        "sku": line.sku,
        "quantity": line.quantity,
        "unit_net_price": line.unit_net_price,
        "discount_percent": line.discount_percent,
        "vat_percent": line.vat_percent,
        "line_net_total": line.line_net_total,
    }
    for field, want in expected.items():
        if getattr(row, field) != want:
            raise NeedsReview("line_mismatch", {"position": str(position), "field": field})


def check_document(
    rows: Sequence[DocumentRow],
    *,
    number: str,
    kind: str,
    reference: str,
    state: DocumentState,
    total: Decimal,
) -> DocumentRow:
    """Brief §4.5 and §5.5: the saved document's row in Data > Documents."""
    matches = [row for row in rows if row.number == number and row.kind == kind]
    if len(matches) != 1:
        raise NeedsReview("document_missing", {"number": number, "rows": str(len(matches))})
    row = matches[0]
    expected = {"reference": reference, "state": state, "total": total}
    for field, want in expected.items():
        if getattr(row, field) != want:
            raise NeedsReview("document_mismatch", {"number": number, "field": field})
    return row
