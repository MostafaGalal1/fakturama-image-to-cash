# Plan 1: Core and Extraction (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an order image into a validated, normalised `order.json`, or a `review.json` when anything can't be confirmed. This is Stage 1 of [DESIGN.md](../DESIGN.md).

**Architecture:**
- A pluggable *image reader* (replaying a recorded fixture until a personal LLM key exists) produces an immutable Pydantic `Order`.
- A pluggable *OCR engine* (macOS Vision) reads the same image independently.
- The pipeline cross-checks critical fields between the two, checks arithmetic invariants with `Decimal`, and normalises the result into the shape Fakturama needs.
- A small CLI exposes `extract` (image → order.json or review.json) and `approve` (a human-corrected draft → order.json).

**Tech Stack:** Python 3.13 (via `uv`), Pydantic 2, Pillow, pyobjc-framework-Vision (macOS), pytest and pytest-cov.

**Plan 2 (Stage 2, driving Fakturama)** gets written after the macOS accessibility spike, because its code depends on what AX exposes.

**Conventions:**
- Repo root: `/Users/mougalal/Desktop/fakturama-image-to-cash`. Every command runs from there.
- Git identity is repo-local: `mostafam.galal82 <mostafam.galal82@gmail.com>`. There is no remote.
- Commit messages use conventional commits **with no attribution trailer**.
- All models are frozen. Update them with `model_copy(update=...)` and never mutate.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.python-version`, `.gitignore` | Project and tooling config |
| `src/image_to_cash/__init__.py` | Package marker and version |
| `src/image_to_cash/model.py` | Stage-1 data contract: `Order` and its parts (frozen Pydantic) |
| `src/image_to_cash/errors.py` | `NeedsReview` exception (stop and hand over, never guess) |
| `src/image_to_cash/invariants.py` | Arithmetic and business checks: `Issue`, `check_invariants` |
| `src/image_to_cash/normalized.py` | Fakturama-shaped contract `NormalizedOrder` and `normalize()` |
| `src/image_to_cash/imaging.py` | Load, upscale and prepare images for OCR |
| `src/image_to_cash/ocr/base.py` | `Box`, `TextBox`, `OcrEngine` protocol, `OcrError` |
| `src/image_to_cash/ocr/macos_vision.py` | macOS Vision OCR adapter |
| `src/image_to_cash/ocr/__init__.py` | `build_ocr(name)` registry and re-exports |
| `src/image_to_cash/reconcile.py` | Cross-check critical fields against OCR text |
| `src/image_to_cash/readers/base.py` | `ImageReader` protocol, `ReaderError` |
| `src/image_to_cash/readers/fixture.py` | `FixtureReader`, which replays a recorded response |
| `src/image_to_cash/readers/__init__.py` | `build_reader(name)` registry |
| `src/image_to_cash/extract.py` | Stage-1 pipeline: `ExtractionResult`, `extract()` |
| `src/image_to_cash/outputs.py` | Write `order.json` or `review.json` |
| `src/image_to_cash/cli.py` | `image-to-cash extract / approve` |
| `tests/…` | One test module per source module; `tests/conftest.py` holds the shared fixtures |
| `tests/fixtures/sample_order.json` (+ `.NOTES.md`) | Recorded reader response for the sample image |
| `samples/sales-order-input.png` | The supplied order image (from the brief) |
| `README.md` | Setup and usage |

---

### Task 1: Project scaffold and git

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `src/image_to_cash/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`

- [ ] **Step 1: Initialise git with the repo-local personal identity**

```bash
cd /Users/mougalal/Desktop/fakturama-image-to-cash
git init
git config user.name "mostafam.galal82"
git config user.email "mostafam.galal82@gmail.com"
git config --get user.email
```
Expected: `mostafam.galal82@gmail.com`

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "image-to-cash"
version = "0.1.0"
description = "Turn a single order image into a verified Order and linked Invoice in Fakturama."
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.8",
    "pillow>=10.4",
    "pyobjc-framework-Vision>=10.3; sys_platform == 'darwin'",
]

[project.scripts]
image-to-cash = "image_to_cash.cli:main"

[dependency-groups]
dev = ["pytest>=8.3", "pytest-cov>=5.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/image_to_cash"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = ["macos: needs macOS system frameworks (Vision, Accessibility)"]
```

- [ ] **Step 3: Write `.python-version`, `.gitignore` and the package marker**

`.python-version`:
```
3.13
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
htmlcov/
out/
```

`src/image_to_cash/__init__.py`:
```python
"""Fakturama image-to-cash automation."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write the failing smoke test and the conftest that skips macOS-only tests elsewhere**

`tests/conftest.py`:
```python
import sys

import pytest


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)
```

`tests/test_smoke.py`:
```python
import image_to_cash


def test_package_exposes_version():
    assert image_to_cash.__version__ == "0.1.0"
```

- [ ] **Step 5: Install and run the tests**

Run: `uv sync && uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 6: Commit (includes the design doc and this plan)**

```bash
git add .
git commit -m "chore: scaffold image-to-cash project with design doc and plan 1"
```

---

### Task 2: Data contract (`Order`) and the sample fixture

**Files:**
- Create: `src/image_to_cash/model.py`, `tests/fixtures/sample_order.json`, `tests/fixtures/sample_order.NOTES.md`, `tests/test_model.py`
- Modify: `tests/conftest.py` (full replacement below)

- [ ] **Step 1: Write the recorded fixture for the sample image**

`tests/fixtures/sample_order.json`:
```json
{
  "external_reference": "WEB-2026-0714-A17",
  "order_date": "2026-07-14",
  "currency": "EUR",
  "customer": {
    "customer_id": "CUST-1007",
    "company": "Northstar Office GmbH",
    "alias": "NORTHSTAR-BERLIN",
    "contact_name": "Marta Klein",
    "email": "marta.klein@example.test",
    "phone": "+49 30 3550 1420"
  },
  "billing_address": {
    "name": "Northstar Office GmbH",
    "street": "Friedrichstrasse 88",
    "zip": "10117",
    "city": "Berlin",
    "country": "Germany"
  },
  "delivery_address": {
    "name": "Northstar Office Warehouse",
    "street": "Huttenstrasse 41",
    "zip": "10553",
    "city": "Berlin",
    "country": "Germany"
  },
  "payment": {
    "method": "Bank Transfer",
    "status": "PAID",
    "payment_date": "2026-07-18"
  },
  "items": [
    {
      "sku": "CHR-ERGO-01",
      "description": "Ergonomic Desk Chair",
      "quantity": "2",
      "unit": "PCS",
      "unit_net_price": "250.00",
      "discount_percent": "10",
      "vat_percent": "19",
      "line_net_total": "450.00"
    },
    {
      "sku": "MAT-DESK-02",
      "description": "Anti-Fatigue Desk Mat",
      "quantity": "3",
      "unit": "PCS",
      "unit_net_price": "40.00",
      "discount_percent": "0",
      "vat_percent": "19",
      "line_net_total": "120.00"
    }
  ],
  "totals": {
    "net": "570.00",
    "vat": "108.30",
    "gross": "678.30"
  }
}
```

`tests/fixtures/sample_order.NOTES.md`:
```markdown
# Sample fixture: provenance

Transcribed by hand from the order image embedded in the take-home brief (385×530 px).
These fields are **not legible** at that resolution. The values below are best readings and
**unverified** (re-record once the original image is available):

- `items[0].sku` (CHR-ERGO-01)
- `billing_address.street` (Friedrichstrasse 88): street name and house number
- `delivery_address.street` (Huttenstrasse 41): street name
- `customer.phone` (+49 30 3550 1420)
- `items[*].unit` (PCS)

Everything else, including all amounts, percentages, dates, the reference and the totals, reads clearly.
The real pipeline's OCR cross-check covers the SKU, both streets and the phone, and is expected
to flag them for review. `unit` is not cross-checked, because it is never entered into Fakturama.
```

- [ ] **Step 2: Replace `tests/conftest.py` with the shared fixtures**

```python
import sys
from pathlib import Path

import pytest

from image_to_cash.model import Order

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ORDER_JSON = FIXTURES / "sample_order.json"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)


@pytest.fixture
def sample_order_path() -> Path:
    return SAMPLE_ORDER_JSON


@pytest.fixture
def sample_order() -> Order:
    return Order.model_validate_json(SAMPLE_ORDER_JSON.read_text(encoding="utf-8"))
```

- [ ] **Step 3: Write the failing tests**

`tests/test_model.py`:
```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from image_to_cash.model import Order, PaidStatus, PaymentMethod


def test_sample_fixture_parses(sample_order):
    assert sample_order.external_reference == "WEB-2026-0714-A17"
    assert sample_order.payment.method is PaymentMethod.BANK_TRANSFER
    assert sample_order.payment.status is PaidStatus.PAID
    assert sample_order.items[0].unit_net_price == Decimal("250.00")
    assert sample_order.totals.gross == Decimal("678.30")


def test_order_is_immutable(sample_order):
    with pytest.raises(ValidationError):
        sample_order.external_reference = "CHANGED"


def test_unknown_fields_are_rejected(sample_order):
    data = sample_order.model_dump(mode="json") | {"surprise": 1}
    with pytest.raises(ValidationError):
        Order.model_validate(data)


def test_order_needs_at_least_one_item(sample_order):
    data = sample_order.model_dump(mode="json") | {"items": []}
    with pytest.raises(ValidationError):
        Order.model_validate(data)


def test_unknown_payment_method_is_rejected(sample_order):
    data = sample_order.model_dump(mode="json")
    data = data | {"payment": data["payment"] | {"method": "Cash"}}
    with pytest.raises(ValidationError):
        Order.model_validate(data)


def test_json_round_trip_is_lossless(sample_order):
    assert Order.model_validate_json(sample_order.model_dump_json()) == sample_order


def test_padded_text_is_stripped(sample_order):
    data = with_value(sample_order.model_dump(mode="json"), ("items", 0, "sku"), "  CHR-ERGO-01 ")
    assert Order.model_validate(data).items[0].sku == "CHR-ERGO-01"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("items", 0, "quantity"), "0"),
        (("items", 0, "unit_net_price"), "-1.00"),
        (("items", 0, "discount_percent"), "101"),
        (("items", 0, "vat_percent"), "19.555"),
        (("items", 0, "line_net_total"), "1E+30"),
        (("items", 0, "sku"), "   "),
        (("items", 0, "unit"), ""),
        (("totals", "net"), "-570.00"),
        (("totals", "gross"), "NaN"),
        (("currency",), "eur"),
        (("billing_address", "zip"), " "),
        (("customer", "surprise"), "x"),
    ],
)
def test_invalid_values_are_rejected_at_their_field(sample_order, path, value):
    data = with_value(sample_order.model_dump(mode="json"), path, value)
    with pytest.raises(ValidationError) as excinfo:
        Order.model_validate(data)
    assert excinfo.value.errors()[0]["loc"] == path


def with_value(data, path, value):
    """Return a copy of nested JSON-like `data` with `value` placed at `path`."""
    head, *rest = path
    new_child = value if not rest else with_value(data[head], rest, value)
    if isinstance(data, list):
        return [new_child if index == head else item for index, item in enumerate(data)]
    return data | {head: new_child}
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_model.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'image_to_cash.model'`

- [ ] **Step 5: Implement `src/image_to_cash/model.py`**

```python
"""Stage-1 data contract: what was printed on the order image (frozen, validated)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Bounded types: a garbled reading (e.g. "1E+30") must fail validation, not crash the money maths.
NonEmptyStr = Annotated[str, Field(min_length=1)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=4)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "Bank Transfer"
    CREDIT_CARD = "Credit Card"
    SEPA_DIRECT_DEBIT = "SEPA Direct Debit"


class PaidStatus(StrEnum):
    PAID = "PAID"
    UNPAID = "UNPAID"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Address(Frozen):
    name: NonEmptyStr
    street: NonEmptyStr
    zip: NonEmptyStr
    city: NonEmptyStr
    country: NonEmptyStr


class Customer(Frozen):
    customer_id: str | None = None
    company: NonEmptyStr
    alias: NonEmptyStr
    contact_name: NonEmptyStr
    email: str = Field(min_length=3)
    phone: NonEmptyStr


class LineItem(Frozen):
    sku: NonEmptyStr
    description: NonEmptyStr
    quantity: Quantity
    unit: NonEmptyStr
    unit_net_price: Amount
    discount_percent: Percent
    vat_percent: Percent
    line_net_total: Amount


class Payment(Frozen):
    method: PaymentMethod
    status: PaidStatus
    payment_date: date | None = None


class Totals(Frozen):
    net: Amount
    vat: Amount
    gross: Amount


class Order(Frozen):
    external_reference: NonEmptyStr
    order_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: Customer
    billing_address: Address
    delivery_address: Address
    payment: Payment
    items: tuple[LineItem, ...] = Field(min_length=1)
    totals: Totals
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: `20 passed`

- [ ] **Step 7: Commit**

```bash
git add src/image_to_cash/model.py tests/conftest.py tests/test_model.py tests/fixtures
git commit -m "feat: add immutable order data contract and sample fixture"
```

---

### Task 3: Arithmetic and business invariants

**Files:**
- Create: `src/image_to_cash/invariants.py`, `tests/test_invariants.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_invariants.py`:
```python
from decimal import Decimal

from image_to_cash.invariants import check_invariants, expected_line_net
from image_to_cash.model import PaidStatus


def codes(order):
    return {issue.code for issue in check_invariants(order)}


def test_sample_order_passes(sample_order):
    assert check_invariants(sample_order) == ()


def test_expected_line_net_applies_discount():
    assert expected_line_net(Decimal("2"), Decimal("250.00"), Decimal("10")) == Decimal("450.00")


def test_expected_line_net_rounds_half_up():
    assert expected_line_net(Decimal("1"), Decimal("0.125"), Decimal("0")) == Decimal("0.13")


def test_line_net_mismatch_is_reported(sample_order):
    first, *rest = sample_order.items
    broken_first = first.model_copy(update={"line_net_total": Decimal("500.00")})
    order = sample_order.model_copy(update={"items": (broken_first, *rest)})
    assert "line_net_mismatch" in codes(order)


def test_net_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"net": Decimal("571.00")})
    assert "net_total_mismatch" in codes(sample_order.model_copy(update={"totals": totals}))


def test_vat_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"vat": Decimal("100.00")})
    assert "vat_total_mismatch" in codes(sample_order.model_copy(update={"totals": totals}))


def test_gross_total_mismatch_is_reported(sample_order):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("678.31")})
    assert codes(sample_order.model_copy(update={"totals": totals})) == {"gross_total_mismatch"}


def test_paid_without_date_is_reported(sample_order):
    payment = sample_order.payment.model_copy(update={"payment_date": None})
    assert codes(sample_order.model_copy(update={"payment": payment})) == {"paid_without_date"}


def test_unpaid_without_date_is_fine(sample_order):
    payment = sample_order.payment.model_copy(
        update={"status": PaidStatus.UNPAID, "payment_date": None}
    )
    assert codes(sample_order.model_copy(update={"payment": payment})) == set()


def test_unpaid_with_date_is_reported(sample_order):
    payment = sample_order.payment.model_copy(update={"status": PaidStatus.UNPAID})
    assert codes(sample_order.model_copy(update={"payment": payment})) == {"unpaid_with_date"}


def test_unsupported_currency_is_reported(sample_order):
    assert codes(sample_order.model_copy(update={"currency": "USD"})) == {"unsupported_currency"}


def test_invalid_email_is_reported(sample_order):
    customer = sample_order.customer.model_copy(update={"email": "marta.klein"})
    assert codes(sample_order.model_copy(update={"customer": customer})) == {"invalid_email"}


def test_mixed_vat_rates_are_applied_per_line(sample_order):
    first, second = sample_order.items
    items = (first, second.model_copy(update={"vat_percent": Decimal("7")}))
    totals = sample_order.totals.model_copy(
        update={"vat": Decimal("93.90"), "gross": Decimal("663.90")}
    )
    order = sample_order.model_copy(update={"items": items, "totals": totals})
    assert check_invariants(order) == ()


def test_vat_is_rounded_once_on_the_sum(sample_order):
    # 2 lines of 0.50 at 19%: rounding per line gives 0.10 + 0.10 = 0.20; the convention gives 0.19.
    line = sample_order.items[1].model_copy(
        update={"quantity": Decimal("1"), "unit_net_price": Decimal("0.50"), "line_net_total": Decimal("0.50")}
    )
    totals = sample_order.totals.model_copy(
        update={"net": Decimal("1.00"), "vat": Decimal("0.19"), "gross": Decimal("1.19")}
    )
    clean = sample_order.model_copy(update={"items": (line, line), "totals": totals})
    assert check_invariants(clean) == ()
    per_line = totals.model_copy(update={"vat": Decimal("0.20"), "gross": Decimal("1.20")})
    assert codes(clean.model_copy(update={"totals": per_line})) == {"vat_total_mismatch"}


def test_one_cent_line_difference_names_line_and_sku(sample_order):
    first, *rest = sample_order.items
    off_by_cent = first.model_copy(update={"line_net_total": Decimal("450.01")})
    order = sample_order.model_copy(update={"items": (off_by_cent, *rest)})
    line_issues = [i for i in check_invariants(order) if i.code == "line_net_mismatch"]
    assert len(line_issues) == 1
    assert line_issues[0].message.startswith("line 1 (CHR-ERGO-01):")


def test_total_messages_name_what_they_compare(sample_order):
    totals = sample_order.totals.model_copy(update={"net": Decimal("571")})
    order = sample_order.model_copy(update={"totals": totals})
    messages = {issue.code: issue.message for issue in check_invariants(order)}
    assert messages["net_total_mismatch"] == (
        "net total: printed line nets sum to 570.00, printed total is 571.00"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_invariants.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.invariants'`

- [ ] **Step 3: Implement `src/image_to_cash/invariants.py`**

```python
"""Arithmetic and business invariants on an extracted Order (design §4, step 5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from image_to_cash.model import LineItem, Order, PaidStatus

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
SUPPORTED_CURRENCY = "EUR"
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def money(value: Decimal) -> Decimal:
    """Round a Decimal to cents, half-up (never the context's default banker's rounding)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def expected_line_net(
    quantity: Decimal, unit_net_price: Decimal, discount_percent: Decimal
) -> Decimal:
    """qty × unit × (1 − discount/100), rounded once at the end (no rounding of the unit price)."""
    return money(quantity * unit_net_price * (1 - discount_percent / HUNDRED))


def check_invariants(order: Order) -> tuple[Issue, ...]:
    return (
        *_line_issues(order),
        *_total_issues(order),
        *_payment_issues(order),
        *_currency_issues(order),
        *_contact_issues(order),
    )


def _line_issues(order: Order) -> tuple[Issue, ...]:
    checked = (_check_line(index, item) for index, item in enumerate(order.items, start=1))
    return tuple(issue for issue in checked if issue is not None)


def _check_line(index: int, item: LineItem) -> Issue | None:
    expected = expected_line_net(item.quantity, item.unit_net_price, item.discount_percent)
    if expected == money(item.line_net_total):
        return None
    return Issue(
        "line_net_mismatch",
        f"line {index} ({item.sku}): {item.quantity} × {item.unit_net_price:.2f} "
        f"− {item.discount_percent}% is {expected:.2f}, printed {money(item.line_net_total):.2f}",
    )


def _sum_line_nets(order: Order) -> Decimal:
    return money(sum((item.line_net_total for item in order.items), Decimal(0)))


def _expected_vat(order: Order) -> Decimal:
    """Convention: Σ(printed line net × VAT%) over all lines, rounded once at the end.

    A document that rounds VAT per line can differ by a cent; it goes to review, never silently through.
    """
    raw = sum((item.line_net_total * item.vat_percent / HUNDRED for item in order.items), Decimal(0))
    return money(raw)


def _total_issues(order: Order) -> tuple[Issue, ...]:
    checks = (
        ("net_total_mismatch", "net total: printed line nets sum to", _sum_line_nets(order), order.totals.net),
        ("vat_total_mismatch", "VAT total: Σ(line net × VAT%) is", _expected_vat(order), order.totals.vat),
        (
            "gross_total_mismatch",
            "gross total: printed net + VAT is",
            money(order.totals.net + order.totals.vat),
            order.totals.gross,
        ),
    )
    return tuple(
        Issue(code, f"{label} {expected:.2f}, printed total is {money(printed):.2f}")
        for code, label, expected, printed in checks
        if expected != money(printed)
    )


def _payment_issues(order: Order) -> tuple[Issue, ...]:
    paid = order.payment.status is PaidStatus.PAID
    has_date = order.payment.payment_date is not None
    if paid and not has_date:
        return (Issue("paid_without_date", "status is PAID but no payment date was printed"),)
    if not paid and has_date:
        return (Issue("unpaid_with_date", "status is not PAID but a payment date was printed"),)
    return ()


def _currency_issues(order: Order) -> tuple[Issue, ...]:
    if order.currency == SUPPORTED_CURRENCY:
        return ()
    return (
        Issue("unsupported_currency", f"only {SUPPORTED_CURRENCY} is supported, got {order.currency}"),
    )


def _contact_issues(order: Order) -> tuple[Issue, ...]:
    if EMAIL_PATTERN.fullmatch(order.customer.email):
        return ()
    return (Issue("invalid_email", f"not an email address: {order.customer.email}"),)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_invariants.py -q`
Expected: `16 passed`

- [ ] **Step 5: Commit**

```bash
git add src/image_to_cash/invariants.py tests/test_invariants.py
git commit -m "feat: check order arithmetic and business invariants"
```

---

### Task 4: Normalise to Fakturama's shape

**Files:**
- Create: `src/image_to_cash/errors.py`, `src/image_to_cash/normalized.py`, `tests/test_normalized.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_normalized.py`:
```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.model import PaymentMethod
from image_to_cash.normalized import NormalizedOrder, gross_price, normalize, split_contact_name


def test_split_contact_name():
    assert split_contact_name("Marta Klein") == ("Marta", "Klein")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Klein, Anna Maria", ("Anna Maria", "Klein")), ("von Klein, Marta", ("Marta", "von Klein"))],
)
def test_split_contact_name_accepts_last_comma_first(name, expected):
    assert split_contact_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Anna Maria Klein",
        "Dr. Klein",
        "Marta K.",
        "Klein,",
        "Marta",
        "Marta Klein, Jr.",
        "Dr. Klein, Marta",
        "Klein, Dr. Marta",
    ],
)
def test_split_contact_name_refuses_to_guess(name):
    with pytest.raises(NeedsReview) as excinfo:
        split_contact_name(name)
    assert excinfo.value.reason == "contact_name_ambiguous"
    assert excinfo.value.details == {"contact_name": name}


def test_needs_review_message_includes_details():
    assert str(NeedsReview("conflicting_sku_lines", {"sku": "X-1"})) == "conflicting_sku_lines: sku=X-1"


def test_gross_price_for_sample_products():
    assert gross_price(Decimal("250.00"), Decimal("19")) == Decimal("297.50")
    assert gross_price(Decimal("40.00"), Decimal("19")) == Decimal("47.60")


def test_gross_price_rounds_half_up_on_ties():
    # 1.50 × 1.19 = 1.785: half-up gives 1.79, banker's rounding would give 1.78.
    assert gross_price(Decimal("1.50"), Decimal("19")) == Decimal("1.79")


def test_normalize_sample(sample_order):
    normalized = normalize(sample_order)
    debtor = normalized.debtor
    assert (debtor.first_name, debtor.last_name) == ("Marta", "Klein")
    assert debtor.delivery_differs is True
    assert normalized.source_customer_id == "CUST-1007"
    assert normalized.payment.method is PaymentMethod.BANK_TRANSFER
    assert normalized.totals == sample_order.totals
    assert [(p.sku, p.gross_price, p.vat_percent) for p in normalized.products] == [
        ("CHR-ERGO-01", Decimal("297.50"), Decimal("19")),
        ("MAT-DESK-02", Decimal("47.60"), Decimal("19")),
    ]
    assert [
        (line.sku, line.quantity, line.discount_percent, line.line_net_total)
        for line in normalized.lines
    ] == [
        ("CHR-ERGO-01", Decimal("2"), Decimal("10"), Decimal("450.00")),
        ("MAT-DESK-02", Decimal("3"), Decimal("0"), Decimal("120.00")),
    ]


def test_normalize_accepts_largest_model_valid_price(sample_order):
    item = sample_order.items[0].model_copy(
        update={
            "quantity": Decimal("1"),
            "unit_net_price": Decimal("9999999999.99"),
            "discount_percent": Decimal("0"),
            "vat_percent": Decimal("100"),
            "line_net_total": Decimal("9999999999.99"),
        }
    )
    normalized = normalize(sample_order.model_copy(update={"items": (item,)}))
    assert normalized.products[0].gross_price == Decimal("19999999999.98")


def test_normalized_order_json_round_trip(sample_order):
    normalized = normalize(sample_order)
    assert NormalizedOrder.model_validate_json(normalized.model_dump_json()) == normalized


def test_same_billing_and_delivery_is_not_flagged(sample_order):
    order = sample_order.model_copy(update={"delivery_address": sample_order.billing_address})
    assert normalize(order).debtor.delivery_differs is False


def test_name_line_difference_alone_counts_as_different(sample_order):
    delivery = sample_order.billing_address.model_copy(update={"name": "Northstar Office Warehouse"})
    order = sample_order.model_copy(update={"delivery_address": delivery})
    assert normalize(order).debtor.delivery_differs is True


def test_same_sku_lines_with_different_quantity_share_one_product(sample_order):
    first = sample_order.items[0]
    second = first.model_copy(
        update={"quantity": Decimal("1"), "discount_percent": Decimal("0"), "line_net_total": Decimal("250.00")}
    )
    normalized = normalize(sample_order.model_copy(update={"items": (first, second)}))
    assert len(normalized.products) == 1
    assert [line.discount_percent for line in normalized.lines] == [Decimal("10"), Decimal("0")]


@pytest.mark.parametrize(
    "change",
    [{"unit_net_price": Decimal("260.00")}, {"description": "Other Chair"}, {"vat_percent": Decimal("7")}],
    ids=["price", "description", "vat"],
)
def test_conflicting_sku_lines_need_review(sample_order, change):
    first = sample_order.items[0]
    items = (first, first.model_copy(update=change))
    with pytest.raises(NeedsReview) as excinfo:
        normalize(sample_order.model_copy(update={"items": items}))
    assert excinfo.value.reason == "conflicting_sku_lines"
    assert excinfo.value.details == {"sku": "CHR-ERGO-01"}


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d | {"lines": [d["lines"][0] | {"sku": "UNKNOWN"}, d["lines"][1]]},
        lambda d: d | {"products": [d["products"][0], d["products"][0]]},
        lambda d: d | {"lines": [d["lines"][0] | {"vat_percent": "7"}, d["lines"][1]]},
        lambda d: d | {"debtor": d["debtor"] | {"first_name": " "}},
        lambda d: d | {"products": [d["products"][0] | {"gross_price": "-1.00"}, d["products"][1]]},
        lambda d: d | {"lines": [d["lines"][0]]},
    ],
    ids=[
        "line-sku-without-product",
        "duplicate-product",
        "line-vat-differs",
        "blank-name",
        "negative-gross",
        "product-without-line",
    ],
)
def test_edited_order_json_is_validated(sample_order, edit):
    data = edit(normalize(sample_order).model_dump(mode="json"))
    with pytest.raises(ValidationError):
        NormalizedOrder.model_validate(data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_normalized.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.errors'`

- [ ] **Step 3: Implement `src/image_to_cash/errors.py`**

```python
"""Exceptions shared across stages."""


class NeedsReview(Exception):
    """The bot must stop and hand over to a person instead of guessing."""

    def __init__(self, reason: str, details: dict[str, str] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = dict(details or {})

    def __str__(self) -> str:
        if not self.details:
            return self.reason
        listed = ", ".join(f"{key}={value}" for key, value in self.details.items())
        return f"{self.reason}: {listed}"
```

- [ ] **Step 4: Implement `src/image_to_cash/normalized.py`**

```python
"""Stage-2 contract: the extracted order mapped onto what Fakturama needs (design §4, step 6).

Precondition: callers run `check_invariants` first; `normalize` does no arithmetic checking.
The contract is re-validated whenever order.json is loaded, because a person may have edited it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from image_to_cash.errors import NeedsReview
from image_to_cash.invariants import HUNDRED, money
from image_to_cash.model import (
    Address,
    Amount,
    Frozen,
    LineItem,
    NonEmptyStr,
    Order,
    Payment,
    Percent,
    Quantity,
    Totals,
)

# A gross price can exceed a net Amount's 12 digits (net × up to 2), so it gets one more digit.
GrossPrice = Annotated[Decimal, Field(ge=0, max_digits=13, decimal_places=2)]


class Debtor(Frozen):
    company: NonEmptyStr
    first_name: NonEmptyStr
    last_name: NonEmptyStr
    alias: NonEmptyStr
    email: NonEmptyStr
    phone: NonEmptyStr
    billing_address: Address
    delivery_address: Address

    @property
    def delivery_differs(self) -> bool:
        """Exact comparison of all fields, name line included: a false 'same' would misship."""
        return self.billing_address != self.delivery_address


class Product(Frozen):
    """Master data. Fakturama's Name and Description both get `description`.

    `gross_price` is net × (1 + VAT) and never includes a line discount.
    """

    sku: NonEmptyStr
    description: NonEmptyStr
    gross_price: GrossPrice
    vat_percent: Percent


class OrderLine(Frozen):
    """One Order line as typed into Fakturama: U.Price is the net unit price."""

    sku: NonEmptyStr
    quantity: Quantity
    unit_net_price: Amount
    discount_percent: Percent
    vat_percent: Percent
    line_net_total: Amount


class NormalizedOrder(Frozen):
    external_reference: NonEmptyStr
    order_date: date
    source_customer_id: str | None  # recorded only; Fakturama proposes its own Customer ID
    debtor: Debtor
    products: tuple[Product, ...] = Field(min_length=1)
    lines: tuple[OrderLine, ...] = Field(min_length=1)
    payment: Payment
    totals: Totals

    @model_validator(mode="after")
    def _lines_match_products(self) -> NormalizedOrder:
        vat_by_sku = {product.sku: product.vat_percent for product in self.products}
        if len(vat_by_sku) != len(self.products):
            raise ValueError("product SKUs must be unique")
        unused = vat_by_sku.keys() - {line.sku for line in self.lines}
        if unused:
            raise ValueError(f"products without a line: {', '.join(sorted(unused))}")
        for line in self.lines:
            if line.sku not in vat_by_sku:
                raise ValueError(f"line SKU {line.sku} has no product")
            if line.vat_percent != vat_by_sku[line.sku]:
                raise ValueError(f"line SKU {line.sku} has a different VAT than its product")
        return self


def split_contact_name(full_name: str) -> tuple[str, str]:
    """Accept 'First Last', or 'Last, First Names' (how a reviewer writes multi-word names).

    Titles and initials (any token ending in '.') go to review in both forms. An undotted
    suffix such as 'Marta Klein, MBA' cannot be told apart from a first name; that is the
    accepted cost of the comma form.
    """
    if "," in full_name:
        last, _, first = full_name.partition(",")
        last, first = last.strip(), first.strip()
        if last and first and "," not in first and not _has_dotted_token(full_name):
            return first, last
        raise _ambiguous_name(full_name)
    parts = full_name.split()
    if len(parts) == 2 and not _has_dotted_token(full_name):
        return parts[0], parts[1]
    raise _ambiguous_name(full_name)


def gross_price(net: Decimal, vat_percent: Decimal) -> Decimal:
    return money(net * (1 + vat_percent / HUNDRED))


def normalize(order: Order) -> NormalizedOrder:
    customer = order.customer
    first_name, last_name = split_contact_name(customer.contact_name)
    return NormalizedOrder(
        external_reference=order.external_reference,
        order_date=order.order_date,
        source_customer_id=customer.customer_id,
        debtor=Debtor(
            company=customer.company,
            first_name=first_name,
            last_name=last_name,
            alias=customer.alias,
            email=customer.email,
            phone=customer.phone,
            billing_address=order.billing_address,
            delivery_address=order.delivery_address,
        ),
        products=_products(order.items),
        lines=tuple(_line(item) for item in order.items),
        payment=order.payment,
        totals=order.totals,
    )


def _has_dotted_token(name: str) -> bool:
    return any(token.endswith(".") for token in name.replace(",", " ").split())


def _ambiguous_name(full_name: str) -> NeedsReview:
    return NeedsReview("contact_name_ambiguous", {"contact_name": full_name})


def _products(items: tuple[LineItem, ...]) -> tuple[Product, ...]:
    by_sku: dict[str, Product] = {}
    for item in items:
        product = _product(item)
        if by_sku.setdefault(item.sku, product) != product:
            raise NeedsReview("conflicting_sku_lines", {"sku": item.sku})
    return tuple(by_sku.values())


def _product(item: LineItem) -> Product:
    return Product(
        sku=item.sku,
        description=item.description,
        gross_price=gross_price(item.unit_net_price, item.vat_percent),
        vat_percent=item.vat_percent,
    )


def _line(item: LineItem) -> OrderLine:
    return OrderLine(
        sku=item.sku,
        quantity=item.quantity,
        unit_net_price=item.unit_net_price,
        discount_percent=item.discount_percent,
        vat_percent=item.vat_percent,
        line_net_total=item.line_net_total,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_normalized.py -q`
Expected: `29 passed`

- [ ] **Step 6: Commit**

```bash
git add src/image_to_cash/errors.py src/image_to_cash/normalized.py tests/test_normalized.py
git commit -m "feat: normalise extracted order into Fakturama-shaped contract"
```

---

### Task 5: Image preprocessing

**Files:**
- Create: `src/image_to_cash/imaging.py`, `tests/test_imaging.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_imaging.py`:
```python
import pytest
from PIL import Image

from image_to_cash.imaging import UPSCALE_FACTOR, for_ocr, load_image, upscale


def test_load_image_returns_rgb(tmp_path):
    path = tmp_path / "order.png"
    Image.new("RGBA", (10, 20), "white").save(path)
    image = load_image(path)
    assert image.mode == "RGB"
    assert image.size == (10, 20)


def test_load_image_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "missing.png")


def test_upscale_multiplies_size():
    image = Image.new("RGB", (10, 20), "white")
    assert upscale(image).size == (10 * UPSCALE_FACTOR, 20 * UPSCALE_FACTOR)


def test_for_ocr_returns_new_grayscale_image():
    image = Image.new("RGB", (10, 20), "white")
    prepared = for_ocr(image)
    assert prepared.mode == "L"
    assert image.mode == "RGB"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_imaging.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.imaging'`

- [ ] **Step 3: Implement `src/image_to_cash/imaging.py`**

```python
"""Image preparation before reading (design §4, step 1)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

UPSCALE_FACTOR = 3


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def upscale(image: Image.Image, factor: int = UPSCALE_FACTOR) -> Image.Image:
    return image.resize((image.width * factor, image.height * factor), Image.Resampling.LANCZOS)


def for_ocr(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image).filter(ImageFilter.SHARPEN)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_imaging.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/image_to_cash/imaging.py tests/test_imaging.py
git commit -m "feat: add image loading, upscaling and OCR preparation"
```

---

### Task 6: OCR interface and macOS Vision adapter

**Files:**
- Create: `src/image_to_cash/ocr/__init__.py`, `src/image_to_cash/ocr/base.py`, `src/image_to_cash/ocr/macos_vision.py`, `tests/test_ocr.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_ocr.py`:
```python
import pytest
from PIL import Image, ImageDraw, ImageFont

from image_to_cash.ocr import Box, build_ocr


def test_box_center():
    assert Box(x=10, y=20, width=30, height=40).center == (25, 40)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="unknown OCR engine"):
        build_ocr("nope")


def render(text: str) -> Image.Image:
    image = Image.new("RGB", (1000, 200), "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black", font=ImageFont.load_default(size=48))
    return image


@pytest.mark.macos
def test_macos_vision_reads_rendered_text_with_top_left_boxes():
    boxes = build_ocr("macos-vision").recognize(render("WEB-2026-0714-A17"))
    joined = "".join(box.text for box in boxes).replace(" ", "")
    assert "WEB-2026-0714-A17" in joined
    first = boxes[0].box
    assert 0 <= first.x < 1000
    assert first.y < 80, "box must use a top-left origin (text was drawn near the top)"
    assert first.width > 0 and first.height > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ocr.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.ocr'`

- [ ] **Step 3: Implement `src/image_to_cash/ocr/base.py`**

```python
"""OCR engine interface: any engine returns text boxes in top-left pixel coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class OcrError(RuntimeError):
    """The OCR engine failed to process an image."""


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


@dataclass(frozen=True)
class TextBox:
    text: str
    box: Box
    confidence: float | None = None


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]: ...
```

- [ ] **Step 4: Implement `src/image_to_cash/ocr/macos_vision.py`**

```python
"""macOS Vision framework OCR adapter (local, no setup)."""

from __future__ import annotations

import io

import Vision
from Foundation import NSData
from PIL import Image

from image_to_cash.ocr.base import Box, OcrError, TextBox


class MacVisionOcr:
    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]:
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(_png_data(image), None)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OcrError(f"Vision text recognition failed: {error}")
        observations = request.results() or []
        boxes = (_to_text_box(observation, image.width, image.height) for observation in observations)
        return tuple(box for box in boxes if box is not None)


def _png_data(image: Image.Image) -> NSData:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    return NSData.dataWithBytes_length_(raw, len(raw))


def _to_text_box(observation, width: int, height: int) -> TextBox | None:
    candidates = observation.topCandidates_(1)
    if not candidates:
        return None
    candidate = candidates[0]
    rect = observation.boundingBox()  # normalised, origin bottom-left
    box = Box(
        x=round(rect.origin.x * width),
        y=round((1 - rect.origin.y - rect.size.height) * height),
        width=round(rect.size.width * width),
        height=round(rect.size.height * height),
    )
    return TextBox(text=str(candidate.string()), box=box, confidence=float(candidate.confidence()))
```

- [ ] **Step 5: Implement `src/image_to_cash/ocr/__init__.py`**

```python
"""OCR engines behind one interface; `build_ocr` picks one by name."""

from image_to_cash.ocr.base import Box, OcrEngine, OcrError, TextBox

ENGINES = ("macos-vision",)


def build_ocr(name: str) -> OcrEngine:
    if name == "macos-vision":
        from image_to_cash.ocr.macos_vision import MacVisionOcr

        return MacVisionOcr()
    raise ValueError(f"unknown OCR engine: {name!r} (available: {', '.join(ENGINES)})")


__all__ = ["ENGINES", "Box", "OcrEngine", "OcrError", "TextBox", "build_ocr"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ocr.py -q`
Expected: `3 passed` on macOS.

- [ ] **Step 7: Commit**

```bash
git add src/image_to_cash/ocr tests/test_ocr.py
git commit -m "feat: add OCR interface with macOS Vision adapter"
```

---

### Task 7: Cross-check critical fields against OCR

**Files:**
- Create: `src/image_to_cash/reconcile.py`, `tests/test_reconcile.py`
- Modify: `tests/conftest.py` (full replacement below; adds `FakeOcr`)

- [ ] **Step 1: Write the failing tests**

`tests/test_reconcile.py`:
```python
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import Mismatch, critical_fields, reconcile


def text_boxes(texts):
    return tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def test_critical_fields_use_printed_formats(sample_order):
    fields = dict(critical_fields(sample_order))
    assert fields["items[0].discount_percent"] == "10%"
    assert fields["items[1].discount_percent"] == "0%"
    assert fields["items[0].unit_net_price"] == "250.00"
    assert fields["totals.gross"] == "678.30"
    assert fields["payment.payment_date"] == "2026-07-18"
    assert fields["delivery_address.street"] == "Huttenstrasse 41"
    assert fields["customer.phone"] == "+49 30 3550 1420"


def test_no_mismatch_when_ocr_sees_everything(sample_order):
    assert reconcile(sample_order, text_boxes(expected_texts(sample_order))) == ()


def test_missing_sku_is_reported(sample_order):
    texts = tuple(t for t in expected_texts(sample_order) if t != "MAT-DESK-02")
    assert reconcile(sample_order, text_boxes(texts)) == (Mismatch("items[1].sku", "MAT-DESK-02"),)


def test_lookalike_characters_are_tolerated(sample_order):
    texts = tuple(t.replace("0", "O") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_spacing_and_decimal_commas_are_tolerated(sample_order):
    texts = tuple(t.replace(".", ",").replace("-", " - ") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reconcile.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.reconcile'`

- [ ] **Step 3: Implement `src/image_to_cash/reconcile.py`**

```python
"""Cross-check critical reader fields against an independent OCR read (design §4, step 4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from image_to_cash.model import Order
from image_to_cash.ocr.base import TextBox

LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1", ",": "."})


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: str


def normalize_token(text: str) -> str:
    return "".join(text.upper().split()).translate(LOOKALIKES)


def critical_fields(order: Order) -> tuple[tuple[str, str], ...]:
    header = (
        ("external_reference", order.external_reference),
        ("order_date", order.order_date.isoformat()),
        ("payment.status", order.payment.status.value),
        ("customer.phone", order.customer.phone),
        ("billing_address.street", order.billing_address.street),
        ("billing_address.zip", order.billing_address.zip),
        ("delivery_address.street", order.delivery_address.street),
        ("delivery_address.zip", order.delivery_address.zip),
        ("totals.net", _amount(order.totals.net)),
        ("totals.vat", _amount(order.totals.vat)),
        ("totals.gross", _amount(order.totals.gross)),
    )
    payment_date = order.payment.payment_date
    payment = (("payment.payment_date", payment_date.isoformat()),) if payment_date else ()
    items = tuple(
        pair
        for index, item in enumerate(order.items)
        for pair in (
            (f"items[{index}].sku", item.sku),
            (f"items[{index}].unit_net_price", _amount(item.unit_net_price)),
            (f"items[{index}].discount_percent", _percent(item.discount_percent)),
            (f"items[{index}].vat_percent", _percent(item.vat_percent)),
            (f"items[{index}].line_net_total", _amount(item.line_net_total)),
        )
    )
    return header + payment + items


def reconcile(order: Order, text_boxes: tuple[TextBox, ...]) -> tuple[Mismatch, ...]:
    haystack = normalize_token("".join(box.text for box in text_boxes))
    return tuple(
        Mismatch(field, expected)
        for field, expected in critical_fields(order)
        if normalize_token(expected) not in haystack
    )


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"
```

- [ ] **Step 4: Replace `tests/conftest.py` (adds `FakeOcr` for later tasks)**

```python
import sys
from pathlib import Path

import pytest
from PIL import Image

from image_to_cash.model import Order
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import critical_fields

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ORDER_JSON = FIXTURES / "sample_order.json"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)


class FakeOcr:
    """OCR stand-in that 'sees' exactly the given texts."""

    def __init__(self, texts: tuple[str, ...]) -> None:
        self._boxes = tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)

    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]:
        return self._boxes


@pytest.fixture
def sample_order_path() -> Path:
    return SAMPLE_ORDER_JSON


@pytest.fixture
def sample_order() -> Order:
    return Order.model_validate_json(SAMPLE_ORDER_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def ocr_seeing_everything(sample_order) -> FakeOcr:
    return FakeOcr(tuple(expected for _, expected in critical_fields(sample_order)))


@pytest.fixture
def ocr_missing_first_sku(sample_order) -> FakeOcr:
    first_sku = sample_order.items[0].sku
    return FakeOcr(tuple(e for _, e in critical_fields(sample_order) if e != first_sku))


@pytest.fixture
def order_image(tmp_path) -> Path:
    path = tmp_path / "order.png"
    Image.new("RGB", (40, 60), "white").save(path)
    return path
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: all passed (`77 passed` on macOS)

- [ ] **Step 6: Commit**

```bash
git add src/image_to_cash/reconcile.py tests/test_reconcile.py tests/conftest.py
git commit -m "feat: cross-check critical order fields against OCR text"
```

---

### Task 8: Image-reader interface and fixture reader

**Files:**
- Create: `src/image_to_cash/readers/__init__.py`, `src/image_to_cash/readers/base.py`, `src/image_to_cash/readers/fixture.py`, `tests/test_readers.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_readers.py`:
```python
import pytest

from image_to_cash.readers import ReaderError, build_reader


def test_fixture_reader_replays_recorded_order(sample_order_path, order_image, sample_order):
    reader = build_reader("fixture", fixture=sample_order_path)
    assert reader.read(order_image) == sample_order


def test_fixture_reader_requires_a_path():
    with pytest.raises(ValueError, match="--fixture"):
        build_reader("fixture")


def test_unknown_reader_is_rejected():
    with pytest.raises(ValueError, match="unknown image reader"):
        build_reader("nope")


def test_missing_fixture_raises_reader_error(tmp_path, order_image):
    reader = build_reader("fixture", fixture=tmp_path / "missing.json")
    with pytest.raises(ReaderError):
        reader.read(order_image)


def test_invalid_fixture_raises_reader_error(tmp_path, order_image):
    bad = tmp_path / "bad.json"
    bad.write_text('{"external_reference": "X"}', encoding="utf-8")
    with pytest.raises(ReaderError):
        build_reader("fixture", fixture=bad).read(order_image)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_readers.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.readers'`

- [ ] **Step 3: Implement `src/image_to_cash/readers/base.py`**

```python
"""Image-reader interface: any provider turns an order image into a schema-valid Order."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from image_to_cash.model import Order


class ReaderError(RuntimeError):
    """The image reader could not produce a schema-valid Order."""


class ImageReader(Protocol):
    def read(self, image_path: Path) -> Order: ...
```

- [ ] **Step 4: Implement `src/image_to_cash/readers/fixture.py`**

```python
"""Replays a recorded reader response. Used until a live provider key is configured."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers.base import ReaderError


class FixtureReader:
    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = fixture_path

    def read(self, image_path: Path) -> Order:
        try:
            return Order.model_validate_json(self._fixture_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ReaderError(f"fixture {self._fixture_path} is unusable: {error}") from error
```

- [ ] **Step 5: Implement `src/image_to_cash/readers/__init__.py`**

```python
"""Image readers behind one interface; `build_reader` picks one by name."""

from __future__ import annotations

from pathlib import Path

from image_to_cash.readers.base import ImageReader, ReaderError
from image_to_cash.readers.fixture import FixtureReader

READERS = ("fixture",)


def build_reader(name: str, *, fixture: Path | None = None) -> ImageReader:
    if name == "fixture":
        if fixture is None:
            raise ValueError("the fixture reader needs --fixture PATH")
        return FixtureReader(fixture)
    raise ValueError(f"unknown image reader: {name!r} (available: {', '.join(READERS)})")


__all__ = ["READERS", "FixtureReader", "ImageReader", "ReaderError", "build_reader"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_readers.py -q`
Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
git add src/image_to_cash/readers tests/test_readers.py
git commit -m "feat: add image-reader interface with fixture reader"
```

---

### Task 9: Stage-1 pipeline and outputs

**Files:**
- Create: `src/image_to_cash/extract.py`, `src/image_to_cash/outputs.py`, `tests/test_extract.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_extract.py`:
```python
import json

from image_to_cash.extract import extract
from image_to_cash.outputs import write_result
from image_to_cash.readers import FixtureReader


def test_clean_extraction(sample_order_path, order_image, ocr_seeing_everything):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything)
    assert result.needs_review is False
    assert result.normalized is not None
    assert result.normalized.external_reference == "WEB-2026-0714-A17"


def test_unconfirmed_field_needs_review(sample_order_path, order_image, ocr_missing_first_sku):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku)
    assert result.needs_review is True
    assert [m.field for m in result.mismatches] == ["items[0].sku"]


def test_normalisation_failure_needs_review(tmp_path, sample_order, order_image, ocr_seeing_everything):
    customer = sample_order.customer.model_copy(update={"contact_name": "Anna Maria Klein"})
    fixture = tmp_path / "order.json"
    fixture.write_text(sample_order.model_copy(update={"customer": customer}).model_dump_json())
    result = extract(order_image, FixtureReader(fixture), ocr_seeing_everything)
    assert result.normalized is None
    assert "contact_name_ambiguous" in {issue.code for issue in result.issues}


def test_write_result_writes_order_json(tmp_path, sample_order_path, order_image, ocr_seeing_everything):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything)
    target = write_result(result, tmp_path / "out")
    assert target.name == "order.json"
    assert json.loads(target.read_text())["debtor"]["first_name"] == "Marta"


def test_write_result_writes_review_json(tmp_path, sample_order_path, order_image, ocr_missing_first_sku):
    result = extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku)
    target = write_result(result, tmp_path / "out")
    payload = json.loads(target.read_text())
    assert target.name == "review.json"
    assert payload["mismatches"] == [{"field": "items[0].sku", "expected": "CHR-ERGO-01"}]
    assert payload["draft_order"]["external_reference"] == "WEB-2026-0714-A17"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_extract.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.extract'`

- [ ] **Step 3: Implement `src/image_to_cash/extract.py`**

```python
"""Stage 1: order image -> validated, normalised order (design §3-4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from image_to_cash.errors import NeedsReview
from image_to_cash.imaging import for_ocr, load_image, upscale
from image_to_cash.invariants import Issue, check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import NormalizedOrder, normalize
from image_to_cash.ocr.base import OcrEngine
from image_to_cash.readers.base import ImageReader
from image_to_cash.reconcile import Mismatch, reconcile


@dataclass(frozen=True)
class ExtractionResult:
    order: Order
    normalized: NormalizedOrder | None
    mismatches: tuple[Mismatch, ...]
    issues: tuple[Issue, ...]

    @property
    def needs_review(self) -> bool:
        return self.normalized is None or bool(self.mismatches) or bool(self.issues)


def extract(image_path: Path, reader: ImageReader, ocr: OcrEngine) -> ExtractionResult:
    order = reader.read(image_path)
    text_boxes = ocr.recognize(for_ocr(upscale(load_image(image_path))))
    mismatches = reconcile(order, text_boxes)
    issues = check_invariants(order)
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        review_issue = Issue(review.reason, str(review))
        return ExtractionResult(order, None, mismatches, (*issues, review_issue))
    return ExtractionResult(order, normalized, mismatches, issues)
```

- [ ] **Step 4: Implement `src/image_to_cash/outputs.py`**

```python
"""Persist Stage-1 results: order.json when clean, review.json when a person must check."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from image_to_cash.extract import ExtractionResult

ORDER_FILE = "order.json"
REVIEW_FILE = "review.json"


def write_result(result: ExtractionResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not result.needs_review and result.normalized is not None:
        target = out_dir / ORDER_FILE
        target.write_text(result.normalized.model_dump_json(indent=2), encoding="utf-8")
        return target
    target = out_dir / REVIEW_FILE
    payload = {
        "reason": "extraction needs review",
        "mismatches": [asdict(mismatch) for mismatch in result.mismatches],
        "issues": [asdict(issue) for issue in result.issues],
        "draft_order": result.order.model_dump(mode="json"),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_extract.py -q`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add src/image_to_cash/extract.py src/image_to_cash/outputs.py tests/test_extract.py
git commit -m "feat: add stage-1 extraction pipeline with review output"
```

---

### Task 10: CLI (`extract` and `approve`)

**Files:**
- Create: `src/image_to_cash/cli.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
import json
from decimal import Decimal

import pytest

from image_to_cash import cli


@pytest.fixture
def use_ocr(monkeypatch):
    def install(fake):
        monkeypatch.setattr(cli, "build_ocr", lambda name: fake)

    return install


def run_extract(order_image, sample_order_path, out_dir):
    return cli.main(
        ["extract", str(order_image), "--fixture", str(sample_order_path), "--out", str(out_dir)]
    )


def test_extract_clean_writes_order(tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything):
    use_ocr(ocr_seeing_everything)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_unconfirmed_writes_review(tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku):
    use_ocr(ocr_missing_first_sku)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_REVIEW
    assert (tmp_path / "review.json").is_file()


def test_approve_turns_review_draft_into_order(tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path / "x")
    code = cli.main(["approve", str(tmp_path / "x" / "review.json"), "--out", str(tmp_path / "ok")])
    assert code == cli.EXIT_OK
    order = json.loads((tmp_path / "ok" / "order.json").read_text())
    assert order["external_reference"] == "WEB-2026-0714-A17"


def test_approve_refuses_draft_that_breaks_invariants(tmp_path, sample_order):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "ok" / "order.json").exists()


def test_missing_image_is_a_clear_error(tmp_path, sample_order_path, capsys):
    code = run_extract(tmp_path / "missing.png", sample_order_path, tmp_path)
    assert code == cli.EXIT_ERROR
    assert "image not found" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Implement `src/image_to_cash/cli.py`**

```python
"""Command line: `image-to-cash extract IMAGE` and `image-to-cash approve DRAFT`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import UnidentifiedImageError

from image_to_cash.errors import NeedsReview
from image_to_cash.extract import extract
from image_to_cash.invariants import check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import normalize
from image_to_cash.ocr import ENGINES, OcrError, build_ocr
from image_to_cash.outputs import ORDER_FILE, write_result
from image_to_cash.readers import READERS, ReaderError, build_reader

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REVIEW = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="image-to-cash", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    extract_cmd = commands.add_parser("extract", help="read an order image into order.json")
    extract_cmd.add_argument("image", type=Path)
    extract_cmd.add_argument("--reader", default="fixture", choices=READERS)
    extract_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    extract_cmd.add_argument("--ocr", default="macos-vision", choices=ENGINES)
    extract_cmd.add_argument("--out", type=Path, default=Path("out"))

    approve_cmd = commands.add_parser(
        "approve", help="turn a human-corrected draft (review.json or order JSON) into order.json"
    )
    approve_cmd.add_argument("draft", type=Path)
    approve_cmd.add_argument("--out", type=Path, default=Path("out"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _extract(args)
        return _approve(args)
    except (ReaderError, OcrError, OSError, UnidentifiedImageError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _extract(args: argparse.Namespace) -> int:
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found: {args.image}")
    reader = build_reader(args.reader, fixture=args.fixture)
    result = extract(args.image, reader, build_ocr(args.ocr))
    target = write_result(result, args.out)
    if result.needs_review:
        print(
            f"needs review: {len(result.mismatches)} unconfirmed field(s), "
            f"{len(result.issues)} issue(s); see {target}"
        )
        return EXIT_REVIEW
    print(f"order written to {target}")
    return EXIT_OK


def _approve(args: argparse.Namespace) -> int:
    payload = json.loads(args.draft.read_text(encoding="utf-8"))
    order = Order.model_validate(payload.get("draft_order", payload))
    issues = check_invariants(order)
    if issues:
        for issue in issues:
            print(f"not approved: {issue.code}: {issue.message}", file=sys.stderr)
        return EXIT_REVIEW
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        print(f"not approved: {review}", file=sys.stderr)
        return EXIT_REVIEW
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / ORDER_FILE
    target.write_text(normalized.model_dump_json(indent=2), encoding="utf-8")
    print(f"order written to {target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the whole suite with coverage**

Run: `uv run pytest -q --cov=image_to_cash --cov-report=term-missing`
Expected: all passed, total coverage ≥ 80%

- [ ] **Step 5: Commit**

```bash
git add src/image_to_cash/cli.py tests/test_cli.py
git commit -m "feat: add extract and approve command-line commands"
```

---

### Task 11: Run the real pipeline on the supplied image

**Files:**
- Create: `samples/sales-order-input.png`, `docs/extraction-run-notes.md`

- [ ] **Step 1: Copy the supplied image out of the brief**

```bash
mkdir -p samples
uv run python - <<'EOF'
import base64, re
from pathlib import Path
brief = Path.home() / "Downloads" / "[EXTERNAL] Take home project 2026.md"
match = re.search(r"\[image1\]:\s*<data:image/png;base64,([A-Za-z0-9+/=]+)>", brief.read_text())
Path("samples/sales-order-input.png").write_bytes(base64.b64decode(match.group(1)))
print("saved")
EOF
```
Expected: `saved`

- [ ] **Step 2: Run extraction with real macOS OCR**

Run: `uv run image-to-cash extract samples/sales-order-input.png --fixture tests/fixtures/sample_order.json --out out/sample`
Expected:
- Exit code 2 (`needs review`), with mismatches at least for the blurry fields listed in `sample_order.NOTES.md`.
- If it exits 0 instead, OCR confirmed everything. Record that as well.

- [ ] **Step 3: Record what OCR confirmed and what it didn't**

Write `docs/extraction-run-notes.md` containing:
- the exact command;
- the exit code;
- the `mismatches` list copied from `out/sample/review.json`;
- one line per mismatch saying whether it's a blurry-image field (expected) or a real problem to fix.

- [ ] **Step 4: Commit**

```bash
git add samples/sales-order-input.png docs/extraction-run-notes.md
git commit -m "docs: record first real extraction run on the supplied image"
```

---

### Task 12: README (setup and Stage-1 usage)

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# Fakturama Image-to-Cash

Turns a single order image into a saved, verified Order and linked Invoice in Fakturama.
Design: [docs/DESIGN.md](docs/DESIGN.md).

## Status

- **Stage 1 (extract): done.** Image → `order.json`, or `review.json` when anything can't be confirmed.
- **Stage 2 (drive Fakturama): in progress.** See `docs/plans/`.
- Image reader: `fixture` (a recorded response) until a personal LLM key is configured.
- OCR: macOS Vision. Windows OCR and the UIA backend are designed for; the Windows adapter is not yet tested.

## Setup (macOS)

```bash
uv sync
uv run pytest -q
```

## Usage

```bash
uv run image-to-cash extract samples/sales-order-input.png \
  --fixture tests/fixtures/sample_order.json --out out/sample
```

Exit codes: `0` order.json written · `2` needs review (see review.json) · `1` error.

When review is needed, correct `draft_order` inside `review.json`, then:

```bash
uv run image-to-cash approve out/sample/review.json --out out/sample
```

`approve` re-checks every invariant and only writes `order.json` if they pass.
It skips the OCR cross-check, because a person has confirmed the values.

## Known limitations

- The supplied image is 385×530 px. Some fields (item 1 SKU, street names, phone) are not legible
  and are expected to go to review. See `tests/fixtures/sample_order.NOTES.md`.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and stage-1 usage"
```

---

## Out of scope for Plan 1 (covered later)

- Live LLM adapters (Claude / Gemini) and the zoomed-crop retry (design §4 step 4). These come once a personal key exists.
- UI backend, macOS AX adapter, grid reader, screen objects, flow, run report: **Plan 2**, after the spike.
- Windows OCR / UIA adapters: Plan 2+, untested until a Windows machine is available.
