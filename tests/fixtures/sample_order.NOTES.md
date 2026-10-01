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
