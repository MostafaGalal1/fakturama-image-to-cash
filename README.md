# Fakturama Image-to-Cash

Turns a single order image into a saved, verified Order and linked Invoice in Fakturama.
Design: [docs/DESIGN.md](docs/DESIGN.md).

## Status

- **Stage 1 (extract): done.**
  - The output is `order.json`, or `review.json` when anything can't be confirmed.
  - A vision model reads the image through OpenRouter. macOS Vision OCR then confirms every
    critical field, and exact decimal arithmetic checks the totals.
  - Run log: [docs/extraction-run-notes.md](docs/extraction-run-notes.md).
- **Stage 2 (drive Fakturama): next.** It uses the macOS Accessibility API and is planned after an
  accessibility spike. See `docs/plans/`.
- **Windows:** the UI Automation and OCR adapters are designed for but not yet built.

## Setup (macOS)

```bash
uv sync
uv run pytest -q
```

The live reader needs an [OpenRouter](https://openrouter.ai) API key in a git-ignored `.env`. This
command prompts for the key without echoing it:

```bash
(umask 077; read -rs "k?OpenRouter key: " && print -r -- "OPENROUTER_API_KEY=$k" > .env && echo)
```

## Usage

Read the original sample image with the live reader:

```bash
uv run --env-file .env image-to-cash extract samples/sales-order-input-clean.png \
  --reader openrouter --out out/clean
```

- `--model` picks another OpenRouter model. The default is `anthropic/claude-sonnet-5.5`, which
  costs about 1–2 cents per order.
- Requests ask OpenRouter to use only providers that don't collect prompt data.
- `--reader fixture --fixture tests/fixtures/sample_order.json` replays a recorded response
  instead, with no key and no network.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | `order.json` written |
| `1` | error |
| `2` | bad command-line usage |
| `3` | needs review (see `review.json`) |

`extract` clears `order.json` and `review.json` from the `--out` folder first, so a failed run
never leaves an old order behind for Stage 2.

### When a run needs review

The pixelated copy embedded in the brief always needs review, because OCR can confirm only 4 of
its 22 critical fields:

```bash
uv run image-to-cash extract samples/sales-order-input.png \
  --fixture tests/fixtures/sample_order.json --out out/review-demo
```

1. Check **every** field of `draft_order` in `out/review-demo/review.json` against the image. OCR
   never checks names, the email, descriptions, quantities, cities or the payment method.
2. Correct the draft where needed. Write a contact with a multi-word first name as
   `Last, First Names` (for example `Klein, Anna Maria`); otherwise it goes back to review.
3. Approve it:

```bash
uv run image-to-cash approve out/review-demo/review.json --out out/review-demo
```

`approve` re-runs every arithmetic and business check before it writes `order.json`. It skips the
OCR cross-check, because a person has vouched for the values. An `order.json` next to a
`review.json` therefore means a person approved it. Only approve values you can actually read: a
best guess goes into Fakturama as if it were checked (see the run notes, section 2).

## Known limitations

- Names, email, descriptions, quantities, cities and the payment method are not cross-checked by
  OCR. Quantities are covered indirectly by the line-total arithmetic.
- The zoomed-crop retry for a single unconfirmed field (design §4) is not built. A mismatch goes
  straight to review.
- Free OpenRouter vision models misread about half the fields of the pixelated copy. The checks
  stopped them, but they are not usable as readers.
