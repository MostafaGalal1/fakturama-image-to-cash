# Extraction runs on the sample order

There are two images of the same order:

- **Original:** `samples/sales-order-input-clean.png`, 992×1382 px, supplied separately.
- **Pixelated copy:** `samples/sales-order-input.png`, 385×530 px, the image embedded in the brief.
  Its text is a few pixels high.

All runs used macOS Vision OCR on 2026-10-02.

## 1. Original image, live reader: straight to `order.json`

```bash
uv run --env-file .env image-to-cash extract samples/sales-order-input-clean.png \
  --reader openrouter --out out/clean-live
```

Exit code **0**:

```text
order written to out/clean-live/order.json
```

- **Reader:** `anthropic/claude-sonnet-5.5` through OpenRouter, the default model.
- **OCR:** confirmed all 22 critical fields. Every arithmetic and business check passed, so there
  was no review.
- **Result:** every value in `order.json` matches the image. It is byte-for-byte identical to the
  `order.json` from the recorded response (`--fixture tests/fixtures/sample_order.json`).
- **First attempt:** refused with HTTP 402, because the account had no credit for the 8,192-token
  reply cap. OpenRouter reserves credit for the whole cap, and an order reply needs about 400
  tokens plus 65 per line, so the cap is now 3,000.

## 2. Original image catches wrong values

The recorded response was first transcribed by hand from the pixelated copy. It held best readings
for four fields that copy hides. Run against the original, OCR flagged exactly the three that were
wrong (exit **3**, 19 of 22 confirmed):

| Field | Best reading from the copy | Printed on the original |
|---|---|---|
| `customer.phone` | +49 30 3550 1420 | +49 30 5550 1420 |
| `delivery_address.street` | Huttenstrasse 41 | Beusselstrasse 44 |
| `items[0].sku` | CHR-ERGO-01 | CHR-ERG-01 |

The fourth best reading, `Friedrichstrasse 88`, was right. The fixture now holds the printed values
(see `tests/fixtures/sample_order.NOTES.md`).

## 3. Pixelated copy: review, then approve

```bash
uv run image-to-cash extract samples/sales-order-input.png \
  --fixture tests/fixtures/sample_order.json --out out/fixture-blurry
```

Exit code **3** (needs review):

```text
needs review: 18 unconfirmed field(s), 0 issue(s); see out/fixture-blurry/review.json
  check every field of draft_order against samples/sales-order-input.png, correct it, then run:
  image-to-cash approve out/fixture-blurry/review.json --out out/fixture-blurry
```

OCR confirmed only 4 of the 22 critical fields: the payment status (`PAID`) and the three order
totals (net `570.00`, VAT `108.30`, gross `678.30`). It flagged the other 18:

| Field | Value | Can a person read it on the copy? |
|---|---|---|
| `external_reference` | WEB-2026-0714-A17 | Yes (OCR read "IER-…") |
| `order_date` | 2026-07-14 | Yes |
| `customer.phone` | +49 30 5550 1420 | **No** |
| `billing_address.street` | Friedrichstrasse 88 | **No** |
| `billing_address.zip` | 10117 | Yes |
| `delivery_address.street` | Beusselstrasse 44 | **No** |
| `delivery_address.zip` | 10553 | Yes |
| `payment.payment_date` | 2026-07-18 | Yes |
| `items[0].sku` | CHR-ERG-01 | **No** |
| `items[0].unit_net_price` | 250.00 | Yes |
| `items[0].discount_percent` | 10% | Yes |
| `items[0].vat_percent` | 19% | Yes |
| `items[0].line_net_total` | 450.00 | Yes |
| `items[1].sku` | MAT-DESK-02 | Yes |
| `items[1].unit_net_price` | 40.00 | Yes |
| `items[1].discount_percent` | 0% | Yes |
| `items[1].vat_percent` | 19% | Yes |
| `items[1].line_net_total` | 120.00 | Yes |

`0 issue(s)` means every arithmetic and business check passed. That ties the unconfirmed line
amounts to the confirmed totals: 2 × 250.00 − 10% = 450.00, and 3 × 40.00 = 120.00. These sum to
570.00, and 19% VAT on that is 108.30.

A person then compares **every** field of `draft_order` with the image, not only the flagged ones,
because OCR never checks names, the email, descriptions, quantities, cities or the payment method.
Then they approve the draft:

```bash
uv run image-to-cash approve out/fixture-blurry/review.json --out out/fixture-blurry
```

Exit code **0**:

```text
approved WEB-2026-0714-A17: Northstar Office GmbH, 2 line(s), gross 678.30 EUR, PAID
order written to out/fixture-blurry/order.json
```

`approve` re-runs every arithmetic and business check before it writes `order.json`. `review.json`
stays beside it as the record that a person approved the draft.

**Lesson from section 2:** approving vouches for every value in the draft. When this copy was the
only image, the draft held best readings for the four illegible fields, and three of them were
wrong. When a field can't be read, the right fix is a better image, not an approved guess.

## Regression tests

`tests/test_sample_run.py` (macOS only) re-runs the OCR side of each section with the recorded
response:

- The original confirms every critical field.
- The original flags exactly the three misreadings from the copy.
- The copy goes to review, with its four illegible fields flagged.
