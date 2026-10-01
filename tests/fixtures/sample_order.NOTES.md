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
