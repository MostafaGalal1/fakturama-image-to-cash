# Sample fixture: provenance

The recorded reader response for the sample order. It has been checked field by field against
the original image, `samples/sales-order-input-clean.png` (992×1382 px), and every value matches.

The take-home brief embeds a pixelated 385×530 copy of that image
(`samples/sales-order-input.png`). This fixture was first transcribed from that copy, with best
readings for the fields the copy hides. The original showed that three of those readings were
wrong. OCR on the original flagged exactly those three:

- `customer.phone`: read as +49 30 3550 1420, printed +49 30 5550 1420
- `delivery_address.street`: read as Huttenstrasse 41, printed Beusselstrasse 44
- `items[0].sku`: read as CHR-ERGO-01, printed CHR-ERG-01

`items[*].unit` was corrected too, from PCS to pcs as printed. It is not cross-checked, because
it is never entered into Fakturama.

On the original, macOS Vision OCR confirms all 22 critical fields. On the pixelated copy it
confirms only the payment status and the three order totals (measured 2026-10-02), so a run on
that copy always goes to review.
