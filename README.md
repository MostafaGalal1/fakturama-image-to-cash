# Fakturama Image-to-Cash

Turns a single order image into a saved, verified Order and linked Invoice in Fakturama.
Design: [docs/DESIGN.md](docs/DESIGN.md).

## Status

- **Stage 1 (extract): done.**
  - The output is `order.json`, or `review.json` when anything can't be confirmed.
  - A vision model reads the image through OpenRouter. macOS Vision OCR then confirms every
    critical field, and exact decimal arithmetic checks the totals.
  - Run log: [docs/extraction-run-notes.md](docs/extraction-run-notes.md).
- **Stage 2 (drive Fakturama): done on macOS.** `image-to-cash drive order.json` runs the brief's
  Order-first flow through the macOS Accessibility API: Order, Debtor (select or create, with its
  payment method), Products (select or create, with their VAT), save, the linked Invoice, the paid
  status, and verification in Data > Documents. Findings: [docs/spike-macos-ax.md](docs/spike-macos-ax.md).
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

## Stage 2: enter the order into Fakturama

### One-time setup

1. Install Fakturama 2.2 and create its workspace (the bot was developed against
   `~/Desktop/Database`, the default when the workspace is the Desktop).
2. In Fakturama: *Settings… > General > Currency locale* = **Germany** (EUR). The bot checks this
   preference and stops if the currency is not the euro.
3. Give the terminal (or IDE) that runs the bot two permissions in *System Settings > Privacy &
   Security*: **Accessibility** (to read and drive Fakturama) and **Screen Recording** (for the
   screenshots and the OCR check that a grid has rows).
4. Back up the database folder before a run you may want to undo, for example
   `cp -R ~/Desktop/Database ~/Desktop/Database.backup` with Fakturama closed. Fakturama keeps its
   preferences in the database too, so restoring an older copy also restores its currency locale:
   set it to Germany again if the bot stops with `fakturama_currency_not_eur`.

### Run

Start Fakturama, leave it on its start page, then leave the Mac alone while the bot runs (about
10 minutes; it refuses to send any click or keystroke unless Fakturama has the keyboard focus and
the front window, so using the Mac makes it stop, never type elsewhere):

```bash
uv run image-to-cash drive out/clean/order.json --out out/drive
```

| Code | Meaning |
|---|---|
| `0` | Order and linked Invoice saved and verified |
| `1` | error (the accessibility API failed; see `run.jsonl`) |
| `3` | stopped for review: the reason is printed and logged, nothing was guessed |

The run writes `out/drive/run.jsonl` (one line per step: what was found, created, checked) and
`out/drive/screens/` (numbered screenshots of Fakturama's own window at each milestone). After a
stop, unsaved editors are left open for a person to finish or discard.

### A complete run

`out/drive/run.jsonl` from the run on an empty database (2026-10-02, 4 minutes):

```text
order_opened     done     PO000001
payment_method   created  Bank Transfer (code Credit transfer)
debtor           created  Northstar Office GmbH (separate delivery address)
debtor_selected  checked
vat              created  VAT 19%
product          created  CHR-ERG-01      line 1 checked
vat              found    VAT 19%
product          created  MAT-DESK-02     line 2 checked
order_saved      done     PO000001        listed as open
invoice_saved    done     INV000001       listed as paid
```

Annotated screenshots of that run, in order:
[order header](docs/screenshots/01-order-header.png),
[payment method](docs/screenshots/02-payment-method-filled.png),
[debtor addresses](docs/screenshots/03-debtor-addresses.png),
[debtor miscellaneous](docs/screenshots/04-debtor-miscellaneous.png),
[debtor reselected](docs/screenshots/05-debtor-selector.png),
[VAT 19%](docs/screenshots/07-vat-filled.png),
[product](docs/screenshots/08-product-CHR-ERG-01.png),
[order lines and totals](docs/screenshots/10-order-complete.png),
[order in Documents](docs/screenshots/11-documents-order.png),
[paid invoice and Documents](docs/screenshots/13-documents-final.png).

![Paid invoice and both documents](docs/screenshots/13-documents-final.png)

### How it decides

- **Reuse or create.** The Debtor is reused only when one row matches Company, First Name, Name,
  ZIP and City exactly; a product only by exact SKU with the same name, gross price and VAT; a VAT
  rate only when `VAT <p>%` has value p; a payment method only with zero discount and days. None
  means create; two, a near miss (≤ 2 characters off) or a conflicting definition stop the run.
- **Every write is read back**: text fields, pop-ups, dates, amounts (typed with a decimal comma,
  as the German currency locale expects), each order line, the totals, and both rows in
  Data > Documents.
- **Grids are read through the clipboard** (saved and restored around each copy), never by OCR;
  OCR only confirms a grid has a first row, because copying an empty grid crashes Fakturama.

## Known limitations

- Names, email, descriptions, quantities, cities and the payment method are not cross-checked by
  OCR. Quantities are covered indirectly by the line-total arithmetic.
- The zoomed-crop retry for a single unconfirmed field (design §4) is not built. A mismatch goes
  straight to review.
- Free OpenRouter vision models misread about half the fields of the pixelated copy. The checks
  stopped them, but they are not usable as readers.
- Stage 2 runs on macOS only. The flow talks to a `UiBackend` protocol; a Windows UI Automation
  backend is designed (DESIGN.md) but not built.
- A stop is not resumable. Master data saved before the stop (VAT, payment method, Debtor,
  Products) is found and reused on the next run, but an Order saved before a stop would be entered
  again, so restore the database backup after a stop past the Order's save.
- Grid rows are assumed 15 pt high. Every row selection is copied back and compared, so a wrong
  assumption stops the run instead of picking the wrong row.

## If I had 3 more hours

In priority order, each item is about trust in an unattended run:

1. **Make the run resumable instead of only stoppable.** Today a stop leaves unsaved editors open
   and a person finishes or discards them. I would checkpoint each save (Debtor, Products, Order,
   Invoice numbers) in `run.jsonl` so a re-run skips what is already saved and verified, and add a
   `--discard-open-editors` clean-up that closes unsaved tabs without saving.
2. **Run every reuse branch live against a seeded database.** The green run created everything;
   Debtor and VAT reuse have also run live, product and payment-method reuse only in unit tests on
   copied grid text. I would seed a database with all of them plus near-duplicates
   (`CHR-ERG-010`, `Northstar Office GmbH & Co`) and confirm each selector reuses the exact row
   and stops on the near miss. The VAT reuse branch should also open the existing rate and check
   its code is S (brief §3.5); today only the creation branch checks it.
3. **Measure grid geometry instead of assuming it**: the row pitch by OCR once per grid.
4. **The Windows UI Automation backend**, against the same contract tests, since the brief's
   reference platform is Windows and SWT exposes more of its tree there.
5. **A recording instead of stills**, and the run report as one HTML page (steps, read-back
   values, annotated screenshots) for whoever reviews a stopped run.
