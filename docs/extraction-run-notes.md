# Extraction run on the supplied image

Stage 1 run on the order image from the brief (`samples/sales-order-input.png`, 385×530 px),
using the recorded reader response (`--reader fixture`) and macOS Vision OCR. Run on 2026-10-02.
This is the demo flow: the run stops at review, a person checks the draft, then approves it.

## Step 1: extract

```bash
uv run image-to-cash extract samples/sales-order-input.png \
  --fixture tests/fixtures/sample_order.json --out out/sample
```

Exit code **3** (needs review):

```text
needs review: 18 unconfirmed field(s), 0 issue(s); see out/sample/review.json
  check every field of draft_order against samples/sales-order-input.png, correct it, then run:
  image-to-cash approve out/sample/review.json --out out/sample
```

`0 issue(s)`: every arithmetic and business check passed. Line totals, the net, VAT and gross
totals, and "PAID with a payment date" are all consistent.

## What OCR confirmed, and what it didn't

OCR confirmed 4 of the 22 critical fields: the payment status (`PAID`) and the three order
totals (net `570.00`, VAT `108.30`, gross `678.30`). It could not confirm the other 18:

| Field | Reader value | Can a person read it on the image? |
|---|---|---|
| `external_reference` | WEB-2026-0714-A17 | Yes (OCR read "IER-…") |
| `order_date` | 2026-07-14 | Yes |
| `customer.phone` | +49 30 3550 1420 | **No**: best reading |
| `billing_address.street` | Friedrichstrasse 88 | **No**: best reading |
| `billing_address.zip` | 10117 | Yes |
| `delivery_address.street` | Huttenstrasse 41 | **No**: best reading |
| `delivery_address.zip` | 10553 | Yes |
| `payment.payment_date` | 2026-07-18 | Yes |
| `items[0].sku` | CHR-ERGO-01 | **No**: best reading |
| `items[0].unit_net_price` | 250.00 | Yes |
| `items[0].discount_percent` | 10% | Yes |
| `items[0].vat_percent` | 19% | Yes |
| `items[0].line_net_total` | 450.00 | Yes |
| `items[1].sku` | MAT-DESK-02 | Yes |
| `items[1].unit_net_price` | 40.00 | Yes |
| `items[1].discount_percent` | 0% | Yes |
| `items[1].vat_percent` | 19% | Yes |
| `items[1].line_net_total` | 120.00 | Yes |

**All 18 are blurry-image fields, not pipeline problems.** At this size the text is a few pixels
high, and Vision misreads most of it. On a sharp render of the same page, it confirms all 22.

The unconfirmed line amounts are still tied to the confirmed totals by the arithmetic checks:
2 × 250.00 − 10% = 450.00, and 3 × 40.00 = 120.00. These sum to 570.00 (confirmed), and 19% VAT
on that is 108.30 (confirmed).

## Step 2: a person checks the draft, then approves it

The person compares **every** field of `draft_order` in `out/sample/review.json` with the image,
not only the 18 flagged ones. OCR never checks names, the email, descriptions, quantities,
cities or the payment method.

On this image:

- The 14 legible flagged fields, and all unflagged fields, match what the image shows.
- Four fields cannot be read at this size: the item 1 SKU, both street names, and the phone
  number. The draft keeps the best readings from `tests/fixtures/sample_order.NOTES.md`.
  **Approving vouches for them.** With the original image, they would be checked properly.
- Item 1's description ("Ergonomic Desk Chair") is also faint. It is not a cross-checked field.

```bash
uv run image-to-cash approve out/sample/review.json --out out/sample
```

Exit code **0**:

```text
approved WEB-2026-0714-A17: Northstar Office GmbH, 2 line(s), gross 678.30 EUR, PAID
order written to out/sample/order.json
```

`approve` re-runs every arithmetic and business check before it writes `order.json`, which is
Stage 2's input. `review.json` stays beside it as the record that a person approved the draft.

## Regression test

`tests/test_sample_run.py` (macOS only) re-runs this extraction and checks two things: that it
still goes to review, and that the four illegible fields are flagged.
