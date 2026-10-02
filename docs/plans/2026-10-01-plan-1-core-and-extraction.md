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

To a person, everything else (all amounts, percentages, dates, the reference and the totals)
reads clearly. macOS Vision OCR does much worse at this size: on this image the cross-check
confirms only the payment status and the three order totals, and flags the other 18 critical
fields (measured 2026-10-02). A run on this image therefore always goes to review, and
`approve` is the way through. `unit` is not cross-checked, because it is never entered into
Fakturama.
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

from image_to_cash.imaging import MAX_LONG_EDGE, UPSCALE_FACTOR, for_ocr, load_image, upscale

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
EXIF_ORIENTATION = 0x0112
ROTATED_90_CW = 6


def test_load_image_returns_rgb(tmp_path):
    path = tmp_path / "order.png"
    Image.new("RGBA", (10, 20), "white").save(path)
    image = load_image(path)
    assert image.mode == "RGB"
    assert image.size == (10, 20)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_load_image_flattens_transparency_onto_white(tmp_path, mode):
    # A transparent pixel stored as black, next to an opaque black one.
    source = Image.frombytes("RGBA", (2, 1), bytes([0, 0, 0, 0, 0, 0, 0, 255]))
    path = tmp_path / "transparent.png"
    source.convert(mode).save(path)
    image = load_image(path)
    assert [image.getpixel((0, 0)), image.getpixel((1, 0))] == [WHITE, BLACK]


def test_load_image_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = ROTATED_90_CW
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (40, 20), "white").save(path, exif=exif)
    assert load_image(path).size == (20, 40)


def test_load_image_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "missing.png")


def test_load_image_rejects_non_image(tmp_path):
    path = tmp_path / "order.png"
    path.write_text("not an image", encoding="utf-8")
    with pytest.raises(OSError):
        load_image(path)


def test_load_image_rejects_oversized_image(tmp_path, monkeypatch):
    path = tmp_path / "huge.png"
    Image.new("RGB", (10, 20), "white").save(path)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50)
    with pytest.raises(ValueError, match="too large"):
        load_image(path)


def test_upscale_multiplies_size():
    image = Image.new("RGB", (10, 20), "white")
    assert upscale(image).size == (10 * UPSCALE_FACTOR, 20 * UPSCALE_FACTOR)


def test_upscale_interpolates_instead_of_repeating_pixels():
    image = Image.frombytes("L", (2, 1), bytes([0, 255]))
    row = [upscale(image).getpixel((x, 0)) for x in range(2 * UPSCALE_FACTOR)]
    assert any(0 < value < 255 for value in row)


def test_upscale_lowers_factor_to_respect_long_edge_limit():
    image = Image.new("RGB", (MAX_LONG_EDGE // 2, 10), "white")
    assert upscale(image).size == (MAX_LONG_EDGE, 20)


def test_upscale_never_shrinks_large_images():
    image = Image.new("RGB", (MAX_LONG_EDGE + 1, 10), "white")
    assert upscale(image).size == image.size


@pytest.mark.parametrize("factor", [0, -1])
def test_upscale_rejects_factor_below_one(factor):
    with pytest.raises(ValueError, match="factor"):
        upscale(Image.new("RGB", (10, 20), "white"), factor)


def test_for_ocr_returns_new_grayscale_image():
    image = Image.new("RGB", (10, 20), "white")
    prepared = for_ocr(image)
    assert prepared.mode == "L"
    assert prepared is not image
    assert image.mode == "RGB"


def test_for_ocr_sharpens_edges():
    # Five rows of grey 100 above five rows of grey 200: sharpening overshoots both sides.
    image = Image.frombytes("L", (3, 10), bytes([100] * 15 + [200] * 15)).convert("RGB")
    prepared = for_ocr(image)
    assert prepared.getpixel((1, 4)) < 100
    assert prepared.getpixel((1, 5)) > 200
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
# Upscaling helps small screenshots; past this long edge it only costs memory and upload size.
MAX_LONG_EDGE = 4000
PAPER_WHITE = (255, 255, 255, 255)


def load_image(path: Path) -> Image.Image:
    """An upright RGB copy: EXIF rotation applied, transparency flattened onto white paper.

    Raises OSError for a missing or unreadable file and ValueError for an oversized one.
    """
    try:
        with Image.open(path) as source:
            return _flatten_to_rgb(ImageOps.exif_transpose(source))
    except Image.DecompressionBombError as error:
        raise ValueError(f"image too large to process safely: {path}") from error


def upscale(image: Image.Image, factor: int = UPSCALE_FACTOR) -> Image.Image:
    """Enlarge by `factor`, lowered so the long edge stays within MAX_LONG_EDGE; never shrinks."""
    if factor < 1:
        raise ValueError(f"upscale factor must be at least 1, got {factor}")
    capped = max(1, min(factor, MAX_LONG_EDGE // max(image.size)))
    return image.resize((image.width * capped, image.height * capped), Image.Resampling.LANCZOS)


def for_ocr(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image).filter(ImageFilter.SHARPEN)


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if "A" not in image.getbands() and "transparency" not in image.info:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", rgba.size, PAPER_WHITE), rgba).convert("RGB")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_imaging.py -q`
Expected: `16 passed`

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
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from image_to_cash.ocr import Box, OcrError, build_ocr


def test_box_center():
    assert Box(x=10, y=20, width=30, height=40).center == (25, 40)


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="unknown OCR engine"):
        build_ocr("nope")


def test_missing_vision_framework_is_an_ocr_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "Vision", None)
    monkeypatch.delitem(sys.modules, "image_to_cash.ocr.macos_vision", raising=False)
    with pytest.raises(OcrError, match="pyobjc-framework-Vision"):
        build_ocr("macos-vision")


@pytest.mark.macos
@pytest.mark.parametrize(
    ("rect", "expected"),
    [
        ((0.0, 0.0, 1.0, 1.0), Box(0, 0, 200, 100)),
        ((0.1, 0.9, 0.5, 0.1), Box(20, 0, 100, 10)),
        ((0.1, 0.0, 0.5, 0.1), Box(20, 90, 100, 10)),
        ((-0.125, 0.9375, 0.5, 0.125), Box(0, 0, 75, 6)),
        ((0.75, -0.0625, 0.5, 0.125), Box(150, 94, 50, 6)),
    ],
    ids=["whole-image", "top-strip", "bottom-strip", "clamped-top-left", "clamped-bottom-right"],
)
def test_vision_rect_becomes_top_left_pixel_box(rect, expected):
    from image_to_cash.ocr.macos_vision import vision_rect_to_box  # imports Vision: macOS only

    assert vision_rect_to_box(*rect, width=200, height=100) == expected


VISION_PADDING_PX = 10  # Vision's boxes sit a few pixels outside the drawn glyphs


def render(text: str, origin: tuple[int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """A 1000x200 white image with `text` drawn at `origin`, plus the text's true bounding box."""
    image = Image.new("RGB", (1000, 200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text(origin, text, fill="black", font=font)
    return image, draw.textbbox(origin, text, font=font)


@pytest.mark.macos
@pytest.mark.parametrize("origin", [(20, 20), (500, 120)], ids=["top-left", "bottom-right"])
def test_macos_vision_box_matches_drawn_text(origin):
    image, truth = render("WEB-2026-0714-A17", origin)
    boxes = build_ocr("macos-vision").recognize(image)
    assert [box.text for box in boxes] == ["WEB-2026-0714-A17"]
    box = boxes[0].box
    edges = (box.x, box.y, box.x + box.width, box.y + box.height)
    assert all(abs(edge - true) <= VISION_PADDING_PX for edge, true in zip(edges, truth)), (edges, truth)
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
    """Each box holds an engine-defined text run (a line or a word), in engine-defined order.

    Callers search the texts; they must not rely on box order or on neighbouring boxes.
    """

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


def vision_rect_to_box(x: float, y: float, w: float, h: float, width: int, height: int) -> Box:
    """Vision's normalised rect (origin bottom-left) as a top-left pixel box inside the image."""
    left = _clamp(round(x * width), width)
    right = _clamp(round((x + w) * width), width)
    top = _clamp(round((1 - y - h) * height), height)
    bottom = _clamp(round((1 - y) * height), height)
    return Box(x=left, y=top, width=right - left, height=bottom - top)


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
    rect = observation.boundingBox()
    box = vision_rect_to_box(rect.origin.x, rect.origin.y, rect.size.width, rect.size.height, width, height)
    return TextBox(text=str(candidate.string()), box=box, confidence=float(candidate.confidence()))


def _clamp(value: int, limit: int) -> int:
    return min(max(value, 0), limit)
```

- [ ] **Step 5: Implement `src/image_to_cash/ocr/__init__.py`**

```python
"""OCR engines behind one interface; `build_ocr` picks one by name."""

from image_to_cash.ocr.base import Box, OcrEngine, OcrError, TextBox

ENGINES = ("macos-vision",)


def build_ocr(name: str) -> OcrEngine:
    if name == "macos-vision":
        try:
            from image_to_cash.ocr.macos_vision import MacVisionOcr
        except ImportError as error:
            raise OcrError("macos-vision OCR needs macOS with pyobjc-framework-Vision installed") from error
        return MacVisionOcr()
    raise ValueError(f"unknown OCR engine: {name!r} (available: {', '.join(ENGINES)})")


__all__ = ["ENGINES", "Box", "OcrEngine", "OcrError", "TextBox", "build_ocr"]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ocr.py -q`
Expected: `10 passed` on macOS.

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
from decimal import Decimal

import pytest

from image_to_cash.model import PaidStatus
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import Mismatch, critical_fields, fold, reconcile, value_pattern


def text_boxes(texts):
    return tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def flagged(order, texts):
    return tuple(mismatch.field for mismatch in reconcile(order, text_boxes(texts)))


def without_one(texts, value):
    index = texts.index(value)
    return texts[:index] + texts[index + 1 :]


def inserted_after(texts, anchor, *new):
    index = texts.index(anchor) + 1
    return texts[:index] + new + texts[index:]


def replaced(texts, old, new):
    return tuple(new if text == old else text for text in texts)


def with_item(order, index, **changes):
    items = tuple(
        item.model_copy(update=changes) if position == index else item
        for position, item in enumerate(order.items)
    )
    return order.model_copy(update={"items": items})


def with_billing(order, **changes):
    return order.model_copy(update={"billing_address": order.billing_address.model_copy(update=changes)})


def test_critical_fields_use_printed_formats(sample_order):
    fields = dict(critical_fields(sample_order))
    assert fields["items[0].discount_percent"] == "10%"
    assert fields["items[1].discount_percent"] == "0%"
    assert fields["items[0].unit_net_price"] == "250.00"
    assert fields["totals.gross"] == "678.30"
    assert fields["payment.payment_date"] == "2026-07-18"
    assert fields["delivery_address.street"] == "Huttenstrasse 41"
    assert fields["customer.phone"] == "+49 30 3550 1420"


def test_unpaid_order_has_no_payment_date_field(sample_order):
    payment = sample_order.payment.model_copy(update={"status": PaidStatus.UNPAID, "payment_date": None})
    fields = dict(critical_fields(sample_order.model_copy(update={"payment": payment})))
    assert fields["payment.status"] == "UNPAID"
    assert "payment.payment_date" not in fields


def test_no_mismatch_when_ocr_sees_everything(sample_order):
    assert reconcile(sample_order, text_boxes(expected_texts(sample_order))) == ()


def test_empty_ocr_flags_every_field(sample_order):
    assert len(reconcile(sample_order, ())) == len(critical_fields(sample_order))


def test_missing_sku_is_reported(sample_order):
    texts = tuple(t for t in expected_texts(sample_order) if t != "MAT-DESK-02")
    assert reconcile(sample_order, text_boxes(texts)) == (Mismatch("items[1].sku", "MAT-DESK-02"),)


def test_wrong_digit_is_reported(sample_order):
    texts = replaced(expected_texts(sample_order), "450.00", "460.00")
    assert flagged(sample_order, texts) == ("items[0].line_net_total",)


def test_lookalike_characters_are_tolerated(sample_order):
    texts = tuple(t.replace("0", "O").replace("1", "l") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_spacing_and_decimal_commas_are_tolerated(sample_order):
    texts = tuple(t.replace(".", ",").replace("-", " - ") for t in expected_texts(sample_order))
    assert reconcile(sample_order, text_boxes(texts)) == ()


def test_accents_and_dashes_are_tolerated(sample_order):
    texts = replaced(expected_texts(sample_order), "Huttenstrasse 41", "Hüttenstraße 41")
    texts = replaced(texts, "WEB-2026-0714-A17", "WEB–2026–0714–A17")
    assert flagged(sample_order, texts) == ()


def test_values_inside_a_merged_table_row_are_found(sample_order):
    row = "1 CHR-ERGO-01 Ergonomic Desk Chair 2 PCS 250.00 10% 19% 450.00"
    merged = {"CHR-ERGO-01", "250.00", "10%", "450.00"}
    rest = tuple(t for t in expected_texts(sample_order) if t not in merged)
    assert flagged(sample_order, (*rest, row)) == ()


@pytest.mark.parametrize(
    "printed", ["1.250,00", "1,250.00", "1'250.00", "1250.00", "EUR 1.250,00", "1.250,00 €"]
)
def test_thousands_separators_are_tolerated(sample_order, printed):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1250.00")})
    order = sample_order.model_copy(update={"totals": totals})
    assert "totals.gross" not in flagged(order, (printed,))


def test_quantity_beside_a_price_is_not_a_thousands_group(sample_order):
    order = with_item(sample_order, 0, unit_net_price=Decimal("2250.00"))
    assert "items[0].unit_net_price" in flagged(order, ("2 250.00",))


@pytest.mark.parametrize(("expected", "printed"), [("10117", "10117Berlin"), ("570.00", "EUR570.00")])
def test_numbers_may_touch_letters(expected, printed):
    assert value_pattern(expected).search(fold(printed))


@pytest.mark.parametrize("printed", ["FOIL", "OILX"])
def test_lookalike_only_words_keep_letter_boundaries(printed):
    assert not value_pattern("OIL").search(fold(printed))


@pytest.mark.parametrize("printed", ["10%", "1.0%", "100%"])
def test_zero_discount_is_not_vouched_for_by_a_longer_percent(sample_order, printed):
    texts = replaced(expected_texts(sample_order), "0%", printed)
    assert flagged(sample_order, texts) == ("items[1].discount_percent",)


def test_each_field_needs_its_own_occurrence(sample_order):
    texts = without_one(expected_texts(sample_order), "19%")
    assert flagged(sample_order, texts) == ("items[1].vat_percent",)


def test_paid_is_not_vouched_for_by_unpaid(sample_order):
    texts = replaced(expected_texts(sample_order), "PAID", "UNPAID")
    assert flagged(sample_order, texts) == ("payment.status",)


def test_amount_is_not_the_tail_of_a_longer_number(sample_order):
    texts = replaced(expected_texts(sample_order), "120.00", "1120.00")
    assert flagged(sample_order, texts) == ("items[1].line_net_total",)


def test_truncated_values_are_reported(sample_order):
    order = with_item(sample_order, 0, sku="CHR-ERGO-0", unit_net_price=Decimal("50.00"))
    assert flagged(order, expected_texts(sample_order)) == ("items[0].sku", "items[0].unit_net_price")


def test_house_number_must_match_in_full(sample_order):
    order = with_billing(sample_order, street="Friedrichstrasse 8")
    assert flagged(order, expected_texts(sample_order)) == ("billing_address.street",)


def test_zip_is_not_found_inside_the_phone_number(sample_order):
    order = with_billing(sample_order, zip="30355")
    assert flagged(order, expected_texts(sample_order)) == ("billing_address.zip",)


def test_values_are_not_glued_across_boxes(sample_order):
    order = with_item(sample_order, 0, sku="CHR-ERGO-012")
    texts = inserted_after(without_one(expected_texts(sample_order), "250.00"), "CHR-ERGO-01", "2")
    texts = (*texts, "Qty 2", "50.00 EUR")
    assert flagged(order, texts) == ("items[0].sku", "items[0].unit_net_price")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reconcile.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.reconcile'`

- [ ] **Step 3: Implement `src/image_to_cash/reconcile.py`**

```python
"""Cross-check critical reader fields against an independent OCR read (design §4, step 4).

A field counts as confirmed only when its printed form appears inside one OCR box, as whole
tokens, and the page shows it at least as many times as there are fields claiming it. A
match never spans two boxes, so neighbouring boxes cannot be glued into a value.

Limits: the check ignores where a value sits, so two fields that swapped values (say billing
and delivery ZIP) both pass; catching that needs box geometry. A thousands group printed with
a space ("1 250.00") still contains "250.00" as whole tokens. Space is not accepted as a
thousands separator, so "2 250.00" (a quantity beside a price) never confirms 2250.00.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from image_to_cash.model import Order
from image_to_cash.ocr.base import TextBox

# Folded on both sides: OCR confuses these, and "," -> "." also unifies decimal commas.
LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1", ",": "."})
DASHES = str.maketrans(dict.fromkeys("‐‑‒–—−", "-"))
AMOUNT = re.compile(r"\d+\.\d\d")
THOUSANDS_SEPARATOR = r"[.']?"
# Alphanumeric runs stay intact; OCR may add or drop spaces between runs and punctuation.
TOKEN_PIECE = re.compile(r"[^\W_]+|\S")


@dataclass(frozen=True)
class Mismatch:
    field: str
    expected: str


def fold(text: str) -> str:
    """Uppercase, drop accents, unify dashes and lookalikes, collapse whitespace to one space."""
    decomposed = unicodedata.normalize("NFKD", text.upper())
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(bare.translate(DASHES).translate(LOOKALIKES).split())


def value_pattern(expected: str) -> re.Pattern[str]:
    """Matches the printed value as whole tokens inside one folded OCR line."""
    folded = fold(expected)
    body = _amount_body(folded) if AMOUNT.fullmatch(folded) else _text_body(folded)
    # Decided before folding, so a value of lookalike letters only ("OIL") keeps letter edges.
    edge = r"\w" if any(char.isalpha() for char in expected) else "[0-9]"
    head = f"(?<!{edge})" + (r"(?<![0-9][.])" if folded[0].isdigit() else "")
    tail = f"(?!{edge})" if folded[-1].isalnum() else ""
    return re.compile(head + body + tail)


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
    lines = tuple(fold(box.text) for box in text_boxes)
    fields = critical_fields(order)
    patterns = tuple(value_pattern(expected) for _, expected in fields)
    return tuple(
        Mismatch(field, expected)
        for index, (field, expected) in enumerate(fields)
        if _claim_rank(patterns, index) > _occurrences(patterns[index], lines)
    )


def _amount_body(amount: str) -> str:
    """'1250.00' -> 1[.']?250\\.00, because a printed amount may group its thousands."""
    whole, cents = amount.split(".")
    groups = [whole[max(0, end - 3) : end] for end in range(len(whole), 0, -3)][::-1]
    return THOUSANDS_SEPARATOR.join(groups) + r"\." + cents


def _text_body(value: str) -> str:
    return r"\s*".join(re.escape(piece) for piece in TOKEN_PIECE.findall(value))


def _claim_rank(patterns: tuple[re.Pattern[str], ...], index: int) -> int:
    """1 for the first field claiming this value, 2 for the second, and so on."""
    return sum(1 for pattern in patterns[: index + 1] if pattern.pattern == patterns[index].pattern)


def _occurrences(pattern: re.Pattern[str], lines: tuple[str, ...]) -> int:
    return sum(len(pattern.findall(line)) for line in lines)


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
Expected: all passed (`122 passed` on macOS)

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
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers import ReaderError, build_reader
from image_to_cash.readers.base import MAX_ISSUES_SHOWN, describe_validation_error

MAX_MESSAGE_LENGTH = 600


@pytest.fixture
def prepared_image() -> Image.Image:
    return Image.new("RGB", (40, 60), "white")


def test_fixture_reader_replays_recorded_order(sample_order_path, prepared_image, sample_order):
    reader = build_reader("fixture", fixture=sample_order_path)
    assert reader.read(prepared_image) == sample_order


def test_fixture_reader_reads_the_path_it_was_given(tmp_path, prepared_image, sample_order):
    other = tmp_path / "other.json"
    other_order = sample_order.model_copy(update={"external_reference": "OTHER-1"})
    other.write_text(other_order.model_dump_json(), encoding="utf-8")
    assert build_reader("fixture", fixture=other).read(prepared_image).external_reference == "OTHER-1"


def test_fixture_reader_requires_a_path():
    with pytest.raises(ValueError, match="--fixture"):
        build_reader("fixture")


def test_unknown_reader_is_rejected():
    with pytest.raises(ValueError, match="unknown image reader"):
        build_reader("nope")


def test_missing_fixture_raises_reader_error(tmp_path, prepared_image):
    reader = build_reader("fixture", fixture=tmp_path / "missing.json")
    with pytest.raises(ReaderError, match="missing.json"):
        reader.read(prepared_image)


def test_non_utf8_fixture_raises_reader_error(tmp_path, prepared_image):
    latin1 = tmp_path / "latin1.json"
    latin1.write_bytes(b'{"external_reference": "\xe9"}')
    with pytest.raises(ReaderError, match="latin1.json"):
        build_reader("fixture", fixture=latin1).read(prepared_image)


@pytest.mark.parametrize("content", ["", "{not json", "[]", '{"surprise": 1}', '{"external_reference": "X"}'])
def test_invalid_fixture_raises_a_short_reader_error(tmp_path, prepared_image, content):
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(ReaderError, match="bad.json") as caught:
        build_reader("fixture", fixture=bad).read(prepared_image)
    assert len(str(caught.value)) < MAX_MESSAGE_LENGTH


def test_invalid_fixture_message_omits_the_offending_value(tmp_path, prepared_image, sample_order):
    fixture = tmp_path / "order.json"
    recorded = sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}
    fixture.write_text(json.dumps(recorded), encoding="utf-8")
    with pytest.raises(ReaderError, match="order_date") as caught:
        build_reader("fixture", fixture=fixture).read(prepared_image)
    assert "SECRET-VALUE" not in str(caught.value)


def test_validation_summary_lists_a_few_problems_and_counts_the_rest():
    with pytest.raises(ValidationError) as caught:
        Order.model_validate({})
    hidden = len(caught.value.errors()) - MAX_ISSUES_SHOWN
    summary = describe_validation_error(caught.value)
    assert hidden > 0
    assert summary.count(";") == MAX_ISSUES_SHOWN - 1
    assert summary.endswith(f"(+{hidden} more)")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_readers.py -q`
Expected: `ModuleNotFoundError: No module named 'image_to_cash.readers'`

- [ ] **Step 3: Implement `src/image_to_cash/readers/base.py`**

```python
"""Image-reader interface: any provider turns an order image into a schema-valid Order."""

from __future__ import annotations

from typing import Protocol

from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order

MAX_ISSUES_SHOWN = 5


class ReaderError(RuntimeError):
    """The image reader could not produce a schema-valid Order."""


class ImageReader(Protocol):
    def read(self, image: Image.Image) -> Order:
        """Read an image already prepared by `imaging`: upright, RGB and upscaled.

        Must not modify `image` (copy it before resizing). Raises ReaderError when it cannot
        produce a schema-valid Order.
        """
        ...


def describe_validation_error(error: ValidationError) -> str:
    """A one-line summary of the first few problems, without the offending values.

    The values are left out because a reader's output can hold personal data.
    """
    issues = error.errors(include_url=False, include_context=False, include_input=False)
    shown = "; ".join(f"{_location(issue['loc'])}: {issue['msg']}" for issue in issues[:MAX_ISSUES_SHOWN])
    hidden = len(issues) - MAX_ISSUES_SHOWN
    return f"{shown} (+{hidden} more)" if hidden > 0 else shown


def _location(loc: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in loc) or "<document>"
```

- [ ] **Step 4: Implement `src/image_to_cash/readers/fixture.py`**

```python
"""Replays a recorded reader response. Used until a live provider key is configured."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers.base import ReaderError, describe_validation_error


class FixtureReader:
    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = fixture_path

    def read(self, image: Image.Image) -> Order:
        try:
            recorded = self._fixture_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ReaderError(f"fixture {self._fixture_path} cannot be read: {error}") from error
        try:
            return Order.model_validate_json(recorded)
        except ValidationError as error:
            problems = describe_validation_error(error)
            raise ReaderError(f"fixture {self._fixture_path} is not a valid order: {problems}") from error
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
Expected: `13 passed`

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
import os
from decimal import Decimal

import pytest

from image_to_cash.extract import extract
from image_to_cash.imaging import UPSCALE_FACTOR
from image_to_cash.ocr import Box, TextBox
from image_to_cash.outputs import write_result
from image_to_cash.readers import FixtureReader
from image_to_cash.reconcile import critical_fields


class RecordingOcr:
    """Sees exactly the given texts and keeps a copy of the image it was handed."""

    def __init__(self, texts):
        self._boxes = tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)
        self.seen = None

    def recognize(self, image):
        self.seen = image.copy()
        return self._boxes


class PaintingReader:
    """Paints the image it is handed black, then replays the fixture."""

    def __init__(self, fixture_path):
        self._inner = FixtureReader(fixture_path)
        self.seen_size = None

    def read(self, image):
        self.seen_size = image.size
        image.paste((0, 0, 0), (0, 0, *image.size))
        return self._inner.read(image)


def expected_texts(order):
    return tuple(expected for _, expected in critical_fields(order))


def write_fixture(path, order):
    path.write_text(order.model_dump_json(), encoding="utf-8")
    return path


def output_names(out_dir):
    return sorted(path.name for path in out_dir.iterdir())


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
    fixture = write_fixture(tmp_path / "order.json", sample_order.model_copy(update={"customer": customer}))
    result = extract(order_image, FixtureReader(fixture), ocr_seeing_everything)
    assert result.needs_review is True
    assert result.normalized is None
    assert "contact_name_ambiguous" in {issue.code for issue in result.issues}


def test_arithmetic_issue_alone_needs_review(tmp_path, sample_order, order_image):
    totals = sample_order.totals.model_copy(update={"gross": Decimal("679.30")})
    tampered = sample_order.model_copy(update={"totals": totals})
    fixture = write_fixture(tmp_path / "order.json", tampered)
    result = extract(order_image, FixtureReader(fixture), RecordingOcr(expected_texts(tampered)))
    assert result.mismatches == ()
    target = write_result(result, tmp_path / "out")
    assert target.name == "review.json"
    assert [issue["code"] for issue in json.loads(target.read_text())["issues"]] == ["gross_total_mismatch"]


def test_reader_gets_a_copy_and_ocr_gets_the_clean_greyscale_upscale(sample_order_path, sample_order, order_image):
    reader = PaintingReader(sample_order_path)
    ocr = RecordingOcr(expected_texts(sample_order))
    extract(order_image, reader, ocr)
    upscaled = (40 * UPSCALE_FACTOR, 60 * UPSCALE_FACTOR)
    assert reader.seen_size == upscaled
    assert (ocr.seen.mode, ocr.seen.size) == ("L", upscaled)
    assert ocr.seen.getpixel((0, 0)) == 255, "the reader's paint must not reach OCR"


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
    assert payload["reason"] == "1 field(s) not confirmed by OCR, 0 issue(s)"
    assert payload["source_image"] == str(order_image)
    assert payload["mismatches"] == [{"field": "items[0].sku", "expected": "CHR-ERGO-01"}]
    assert payload["draft_order"]["external_reference"] == "WEB-2026-0714-A17"


def test_review_json_keeps_non_ascii_readable(tmp_path, sample_order, order_image):
    customer = sample_order.customer.model_copy(update={"company": "Müller & Söhne GmbH"})
    fixture = write_fixture(tmp_path / "order.json", sample_order.model_copy(update={"customer": customer}))
    target = write_result(extract(order_image, FixtureReader(fixture), RecordingOcr(())), tmp_path / "out")
    assert "Müller & Söhne GmbH" in target.read_text(encoding="utf-8")


def test_review_run_removes_an_earlier_order_json(
    tmp_path, sample_order_path, order_image, ocr_seeing_everything, ocr_missing_first_sku
):
    out = tmp_path / "out"
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything), out)
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku), out)
    assert output_names(out) == ["review.json"]


def test_clean_run_removes_an_earlier_review_json(
    tmp_path, sample_order_path, order_image, ocr_seeing_everything, ocr_missing_first_sku
):
    out = tmp_path / "out"
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_missing_first_sku), out)
    write_result(extract(order_image, FixtureReader(sample_order_path), ocr_seeing_everything), out)
    assert output_names(out) == ["order.json"]


@pytest.mark.parametrize(
    "ocr_fixture", ["ocr_seeing_everything", "ocr_missing_first_sku"], ids=["order", "review"]
)
def test_failed_write_leaves_neither_file(
    tmp_path, monkeypatch, request, sample_order_path, order_image, ocr_fixture
):
    out = tmp_path / "out"
    result = extract(order_image, FixtureReader(sample_order_path), request.getfixturevalue(ocr_fixture))
    write_result(result, out)

    def disk_full(*_):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError):
        write_result(result, out)
    assert output_names(out) == []
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
    source_image: Path
    order: Order
    normalized: NormalizedOrder | None
    mismatches: tuple[Mismatch, ...]
    issues: tuple[Issue, ...]

    @property
    def needs_review(self) -> bool:
        return self.normalized is None or bool(self.mismatches) or bool(self.issues)


def extract(image_path: Path, reader: ImageReader, ocr: OcrEngine) -> ExtractionResult:
    """Read, cross-check, validate and normalise one order image.

    Raises ReaderError, OcrError, OSError (unreadable image) or ValueError (oversized image).
    """
    prepared = upscale(load_image(image_path))
    order = reader.read(prepared.copy())  # a reader must not change what OCR sees
    text_boxes = ocr.recognize(for_ocr(prepared))
    mismatches = reconcile(order, text_boxes)
    issues = check_invariants(order)
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        review_issue = Issue(review.reason, str(review))
        return ExtractionResult(image_path, order, None, mismatches, (*issues, review_issue))
    return ExtractionResult(image_path, order, normalized, mismatches, issues)
```

- [ ] **Step 4: Implement `src/image_to_cash/outputs.py`**

```python
"""Persist Stage-1 results: order.json when clean, review.json when a person must check.

The out dir only ever holds the latest run's complete result. Both files are removed before
a new one is written, and each is written to a temporary file and renamed into place, so
Stage 2 can never pick up an earlier order or a half-written one.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from image_to_cash.extract import ExtractionResult
from image_to_cash.normalized import NormalizedOrder

ORDER_FILE = "order.json"
REVIEW_FILE = "review.json"


def discard_order(out_dir: Path) -> None:
    """Remove order.json so a stopped or failed run cannot leave an earlier order for Stage 2."""
    (out_dir / ORDER_FILE).unlink(missing_ok=True)


def clear_results(out_dir: Path) -> None:
    discard_order(out_dir)
    (out_dir / REVIEW_FILE).unlink(missing_ok=True)


def write_order(normalized: NormalizedOrder, out_dir: Path) -> Path:
    """The only place order.json is created (`approve` uses it too)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return _write_atomic(out_dir / ORDER_FILE, normalized.model_dump_json(indent=2) + "\n")


def write_result(result: ExtractionResult, out_dir: Path) -> Path:
    clear_results(out_dir)
    if result.normalized is not None and not result.needs_review:
        return write_order(result.normalized, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return _write_atomic(out_dir / REVIEW_FILE, _review_json(result))


def _review_json(result: ExtractionResult) -> str:
    payload = {
        "reason": (
            f"{len(result.mismatches)} field(s) not confirmed by OCR, "
            f"{len(result.issues)} issue(s)"
        ),
        "source_image": str(result.source_image.absolute()),
        "mismatches": [asdict(mismatch) for mismatch in result.mismatches],
        "issues": [asdict(issue) for issue in result.issues],
        "draft_order": result.order.model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_atomic(target: Path, text: str) -> Path:
    """Write beside the target, then rename: readers see the old file or the new one, never half."""
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return target
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_extract.py -q`
Expected: `12 passed`

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


def test_extract_clean_writes_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    assert run_extract(order_image, sample_order_path, tmp_path) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()


def test_extract_unconfirmed_writes_review(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
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


def test_failed_extract_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert run_extract(order_image, tmp_path / "missing.json", tmp_path) == cli.EXIT_ERROR
    assert not (tmp_path / "order.json").exists()


def test_refused_approve_removes_an_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, sample_order
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path / "out")
    totals = sample_order.totals.model_copy(update={"gross": Decimal("1.00")})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"totals": totals}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "out")]) == cli.EXIT_REVIEW
    assert not (tmp_path / "out" / "order.json").exists()


def test_invalid_draft_is_refused_briefly_without_echoing_values(tmp_path, sample_order, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(sample_order.model_dump(mode="json") | {"order_date": "SECRET-VALUE"}))
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    error = capsys.readouterr().err
    assert "order_date" in error
    assert "SECRET-VALUE" not in error


def test_approve_refuses_an_ambiguous_contact_name(tmp_path, sample_order, capsys):
    customer = sample_order.customer.model_copy(update={"contact_name": "Anna Maria Klein"})
    draft = tmp_path / "draft.json"
    draft.write_text(sample_order.model_copy(update={"customer": customer}).model_dump_json())
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "contact_name_ambiguous" in capsys.readouterr().err
    assert not (tmp_path / "ok" / "order.json").exists()


def test_approve_refuses_a_draft_that_is_not_an_object(tmp_path, capsys):
    draft = tmp_path / "draft.json"
    draft.write_text("[]")
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert "not approved" in capsys.readouterr().err


def test_approve_in_the_extract_folder_keeps_the_review_as_a_record(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    assert (tmp_path / "order.json").is_file()
    assert (tmp_path / "review.json").is_file()


def test_approve_refuses_order_json_as_a_draft_and_keeps_it(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, capsys
):
    use_ocr(ocr_seeing_everything)
    run_extract(order_image, sample_order_path, tmp_path)
    assert cli.main(["approve", str(tmp_path / "order.json"), "--out", str(tmp_path)]) == cli.EXIT_ERROR
    assert "Stage 2's input" in capsys.readouterr().err
    assert (tmp_path / "order.json").is_file()


def test_help_lists_the_exit_codes(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    help_text = " ".join(capsys.readouterr().out.split())  # argparse wraps to the terminal width
    assert "3 needs review" in help_text


def test_exit_codes_are_the_documented_contract():
    assert (cli.EXIT_OK, cli.EXIT_ERROR, cli.EXIT_REVIEW) == (0, 1, 3)


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as stop:
        cli.main(["extract"])
    assert stop.value.code == 2


def test_review_message_names_the_next_step(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    out = capsys.readouterr().out
    assert "needs review: 1 unconfirmed field(s), 0 issue(s)" in out
    assert f"image-to-cash approve {tmp_path / 'review.json'}" in out


def test_approve_says_what_it_approved(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_missing_first_sku, capsys
):
    use_ocr(ocr_missing_first_sku)
    run_extract(order_image, sample_order_path, tmp_path)
    capsys.readouterr()
    assert cli.main(["approve", str(tmp_path / "review.json"), "--out", str(tmp_path)]) == cli.EXIT_OK
    approved = "approved WEB-2026-0714-A17: Northstar Office GmbH, 2 line(s), gross 678.30 EUR, PAID"
    assert approved in capsys.readouterr().out


@pytest.mark.parametrize("draft_name", ["missing.json", "binary.json", "broken.json"])
def test_unreadable_draft_leaves_no_earlier_order(
    tmp_path, order_image, sample_order_path, use_ocr, ocr_seeing_everything, draft_name
):
    use_ocr(ocr_seeing_everything)
    out = tmp_path / "out"
    run_extract(order_image, sample_order_path, out)
    (tmp_path / "binary.json").write_bytes(b"\x89PNG\xff")
    (tmp_path / "broken.json").write_text("{oops")
    assert cli.main(["approve", str(tmp_path / draft_name), "--out", str(out)]) != cli.EXIT_OK
    assert not (out / "order.json").exists()


def test_broken_json_draft_names_the_file(tmp_path, capsys):
    draft = tmp_path / "review.json"
    draft.write_text('{"draft_order": {},}')
    assert cli.main(["approve", str(draft), "--out", str(tmp_path / "ok")]) == cli.EXIT_REVIEW
    assert f"{draft} is not valid JSON" in capsys.readouterr().err
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
import shlex
import sys
from pathlib import Path

from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.extract import extract
from image_to_cash.invariants import check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import normalize
from image_to_cash.ocr import ENGINES, OcrError, build_ocr
from image_to_cash.outputs import ORDER_FILE, clear_results, discard_order, write_order, write_result
from image_to_cash.readers import READERS, ReaderError, build_reader
from image_to_cash.readers.base import describe_validation_error

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REVIEW = 3  # 2 is argparse's code for bad command-line usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-to-cash",
        description="Read an order image into order.json for Stage 2, or review.json for a person.",
        epilog="exit codes: 0 order.json written, 1 error, 2 bad usage, 3 needs review",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    extract_cmd = commands.add_parser("extract", help="read an order image into order.json")
    extract_cmd.add_argument("image", type=Path)
    extract_cmd.add_argument("--reader", default="fixture", choices=READERS)
    extract_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    extract_cmd.add_argument("--ocr", default="macos-vision", choices=ENGINES)
    extract_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="result folder; cleared of order.json and review.json first"
    )

    approve_cmd = commands.add_parser(
        "approve", help="turn a human-corrected draft (review.json or order JSON) into order.json"
    )
    approve_cmd.add_argument("draft", type=Path)
    approve_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="folder for order.json; an earlier one is removed first"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _extract(args)
        return _approve(args)
    except (ReaderError, OcrError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _extract(args: argparse.Namespace) -> int:
    clear_results(args.out)  # a failed run must not leave an earlier order for Stage 2
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found or not a file: {args.image}")
    reader = build_reader(args.reader, fixture=args.fixture)
    result = extract(args.image, reader, build_ocr(args.ocr))
    target = write_result(result, args.out)
    if result.needs_review:
        print(
            f"needs review: {len(result.mismatches)} unconfirmed field(s), "
            f"{len(result.issues)} issue(s); see {target}"
        )
        print(f"  check every field of draft_order against {result.source_image}, correct it, then run:")
        print(f"  image-to-cash approve {shlex.quote(str(target))} --out {shlex.quote(str(args.out))}")
        return EXIT_REVIEW
    print(f"order written to {target}")
    return EXIT_OK


def _approve(args: argparse.Namespace) -> int:
    if args.draft.resolve() == (args.out / ORDER_FILE).resolve():
        raise ValueError(f"{args.draft} is Stage 2's input, not a draft; approve review.json instead")
    discard_order(args.out)  # any outcome but "approved" must leave no earlier order for Stage 2
    draft = args.draft.read_text(encoding="utf-8")
    try:
        payload = json.loads(draft)
    except json.JSONDecodeError as error:
        print(f"not approved: {args.draft} is not valid JSON: {error}", file=sys.stderr)
        return EXIT_REVIEW
    candidate = payload.get("draft_order", payload) if isinstance(payload, dict) else payload
    try:
        order = Order.model_validate(candidate)
    except ValidationError as error:
        print(f"not approved: draft is not a valid order: {describe_validation_error(error)}", file=sys.stderr)
        return EXIT_REVIEW
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
    target = write_order(normalized, args.out)
    print(
        f"approved {normalized.external_reference}: {normalized.debtor.company}, "
        f"{len(normalized.lines)} line(s), gross {normalized.totals.gross} {order.currency}, "
        f"{normalized.payment.status.value}"
    )
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

The demo uses only the supplied image. The run stops at review, a person checks the draft, then
approves it. There is no synthetic sharp image.

**Files:**
- Create: `samples/sales-order-input.png`, `tests/test_sample_run.py`, `docs/extraction-run-notes.md`

- [ ] **Step 1: Copy the supplied image out of the brief**

```bash
mkdir -p samples
uv run python - <<'PY'
import base64, re
from pathlib import Path
brief = Path.home() / "Downloads" / "[EXTERNAL] Take home project 2026.md"
match = re.search(r"\[image1\]:\s*<data:image/png;base64,([A-Za-z0-9+/=]+)>", brief.read_text())
Path("samples/sales-order-input.png").write_bytes(base64.b64decode(match.group(1)))
print("saved")
PY
```
Expected: `saved`

- [ ] **Step 2: Write the regression test**

`tests/test_sample_run.py`:

```python
import json
from pathlib import Path

import pytest

from image_to_cash import cli

SAMPLE_IMAGE = Path(__file__).parent.parent / "samples" / "sales-order-input.png"
# Not legible at 385x530 even to a person (see tests/fixtures/sample_order.NOTES.md).
ILLEGIBLE_FIELDS = {"items[0].sku", "billing_address.street", "delivery_address.street", "customer.phone"}


@pytest.mark.macos
def test_supplied_image_goes_to_review_with_the_illegible_fields_flagged(tmp_path, sample_order_path):
    argv = ["extract", str(SAMPLE_IMAGE), "--fixture", str(sample_order_path), "--out", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_REVIEW
    assert not (tmp_path / "order.json").exists()
    review = json.loads((tmp_path / "review.json").read_text(encoding="utf-8"))
    assert ILLEGIBLE_FIELDS <= {mismatch["field"] for mismatch in review["mismatches"]}
    assert review["issues"] == []
```

Run: `uv run pytest tests/test_sample_run.py -v`
Expected: 1 passed

- [ ] **Step 3: Run extraction with real macOS OCR**

Run: `uv run image-to-cash extract samples/sales-order-input.png --fixture tests/fixtures/sample_order.json --out out/sample`
Expected: exit code 3 (`needs review`); the four illegible fields are among the mismatches; 0 issues.

- [ ] **Step 4: Check the draft by hand, then approve it**

Compare every field of `draft_order` in `out/sample/review.json` with the image, not only the
flagged ones. Then:

Run: `uv run image-to-cash approve out/sample/review.json --out out/sample`
Expected: exit code 0, `approved WEB-2026-0714-A17: ...`, and `out/sample/order.json` is written.

- [ ] **Step 5: Record the run**

Write `docs/extraction-run-notes.md` containing:
- both commands, their output and exit codes;
- what OCR confirmed;
- one row per mismatch, saying whether a person can read that field on the image;
- how the arithmetic checks tie the unconfirmed line amounts to the confirmed totals;
- what the human check covers, and which fields approving vouches for.

- [ ] **Step 6: Commit**

```bash
git add samples/sales-order-input.png tests/test_sample_run.py docs/extraction-run-notes.md docs/plans/2026-10-01-plan-1-core-and-extraction.md
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

Exit codes: `0` order.json written · `3` needs review (see review.json) · `1` error · `2` bad command-line usage.

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
