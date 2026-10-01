# Fakturama Image-to-Cash Automation: Design Doc

**Date:** 2026-10-01 · **Status:** Draft for review · **Scope:** Part 1 (design, no code)

## 1. Goal and constraints

Turn one order image into a saved, verified **Order** and linked **Invoice** in Fakturama. The bot extracts the data, resolves or creates the Debtor, Products, VAT rate and payment method, and applies the payment status. It verifies each step before moving on.

- **Platform: OS-agnostic core, two backends built.** The flow drives Fakturama through a neutral *UI backend* interface. v1 builds two backends. **macOS (Accessibility API)** is where development happens. **Windows (Microsoft UI Automation)** is the reference the brief requires. Linux (AT-SPI) is designed for but not built. OCR covers only what the accessibility API can't see. An LLM is used **only to read the source image**.
- **No hardcoded coordinates or fixed layout.** Every click position is computed at run time from accessibility-API element rectangles or OCR word boxes.
- **Out of scope (v1):** Delivery, Correction and Dunning documents; currencies other than EUR; batch runs. If the image has an order-level discount or shipping cost other than zero, the run stops for manual review instead of applying it.

## 2. Findings that shape the design

I inspected the Fakturama 2.2.0 install (its plugin jars and local database) before designing:

| Finding | Consequence |
|---|---|
| Java desktop app (Eclipse RCP/SWT). Fully local; data lives in an embedded **HSQLDB** file that is **locked while the app runs**. | Only the extraction step needs network. The database can't be the live source of truth, and the spec requires UI-based checks anyway (see §9). |
| Form fields, combos, buttons, the toolbar, menus and message boxes are **native SWT controls**. SWT uses each OS's own widgets (Win32, Cocoa, GTK). | Each OS's accessibility API (UIA, macOS AX, AT-SPI) can find, set and read them. That is what makes an OS-agnostic driver practical. |
| Price and percent fields use Nebula `FormattedText`, which wraps a native text box. | They behave as ordinary text fields to the accessibility API. A value is committed on Tab, then read back. |
| Dates use Nebula `CDateTime`; editor sub-tabs use `CTabFolder`. | Probably usable through the accessibility API. **To confirm in a first spike.** |
| The **item table, every Data list and both "Select…" dialogs are NatTable**, which is custom-drawn on a canvas. | Every OS's accessibility API sees one opaque pane with no rows. NatTable draws the same way everywhere, so the bot reads these grids with **OCR inside the pane's rectangle** on every OS. |
| The "Select…" dialogs' **search box is a native text box**. | The bot types the search through the backend, so the grid only shows 1–2 rows for OCR to read. |
| The sample image is small (385×530 px), and its billing and delivery addresses differ. It also shows `CUST-1007`, while the spec says to keep Fakturama's own Customer ID. | Upscale before reading. Create a separate Delivery address. Extract the customer ID for the record but never enter it. |

## 3. Architecture

```
order.png
  │
  ▼  Stage 1: EXTRACT (network)
  Vision LLM (pluggable) → schema JSON ─┐
  OCR engine (pluggable) → word tokens ─┴─► reconcile + validate ─► order.json (immutable)
                                                        │ fails ─► manual-review bundle
  ▼  Stage 2: DRIVE (local only)
  Flow state machine ─► screen objects ─► UI backend (UIA | AX | AT-SPI) + grid OCR ─► Fakturama
  ▼
  Run report: decisions, checks, annotated screenshots
```

- **`order.json` is the only contract between the stages.** Stage 2 never sees the image. That lets us re-run Stage 2 without calling the LLM again, and during manual review a person can correct the JSON and resume.
- **Components:** *extractor* (preprocess, LLM, OCR) · *validator* (reconcile, invariants, normalise) · *UI driver* (locators, actions, waits, modal guard, grid reader) · *screen objects*, one per Fakturama screen (Order, Debtor, Product, VAT, Payment and Invoice editors, the two Select dialogs, Documents) · *flow* (stages and decision rules) · *reporter*.
- **Stack:** Python 3.12 (runs on all three OSes) · Pydantic for the data contract · `Decimal` for all money maths · `mss` for screenshots. Everything OS- or vendor-specific sits behind one of three **swappable interfaces**. Config picks the implementation; the flow doesn't change.
  - *UI backend*: find an element (by neutral role, name or label, and container), read and set its value, click it, press keys, list top-level windows, and get its rectangle. Adapters: **macOS AX via `pyobjc`** (development platform, built in v1), **Windows UIA via `pywinauto`** (the reference, built in v1) and Linux AT-SPI via `pyatspi` (designed for, not built). Each adapter owns four things. First, role mapping: a *text field* is `Edit` in UIA, `AXTextField` in AX and `text` in AT-SPI. Second, the shortcut modifier, Ctrl or Cmd. Third, scaling DPI and Retina coordinates to physical pixels. Fourth, OS permissions, such as macOS Accessibility and Screen Recording.
  - *Image reader*: takes an image and returns order fields matching the Pydantic schema. Adapters: Claude (Anthropic API or Vertex AI), Gemini (Vertex AI) and Document AI Custom Extractor, each using its provider's structured-output feature. Every result is re-validated against the same schema.
  - *OCR engine*: takes an image or a region of one and returns words with boxes (and confidence where the engine provides it). Adapters: Windows built-in OCR and the macOS Vision framework (both local, no setup, each the default on its OS), Google Cloud Vision (for poor-quality scans), and Tesseract (offline, any OS).
  - Every adapter must pass the same contract and golden tests (§8), so a new OS or vendor is a new adapter, not a redesign.

## 4. Image-extraction strategy

1. **Preprocess.** Upscale 3× (Lanczos). The LLM gets the colour image; OCR gets a grayscale, sharpened copy.
2. **LLM read.** One call at temperature 0, using the configured provider's structured-output feature (tool calling for Claude, response schema for Gemini) with the `Order` model as the schema. The prompt says to **transcribe exactly what is printed**, never compute or correct, and to return `null` for anything absent. Each critical field carries both its raw string and its parsed value.
3. **Independent OCR read** of the whole image produces word tokens with boxes.
4. **Reconcile critical fields**, each of which must also appear in the OCR tokens after normalising look-alikes (O/0, I/1, spacing): external reference, dates, SKUs, unit prices, discounts, VAT %, line and order totals, streets, ZIP codes, phone and paid status. Quantities are checked indirectly, because a wrong quantity breaks the line-total invariant. On a mismatch, the LLM gets one retry on a zoomed crop around that field's OCR location. If it still disagrees, the run goes to manual review. **The bot never guesses.**
5. **Invariants** (exact decimal arithmetic, ROUND_HALF_UP). Each line net = qty × unit × (1 − disc/100); for the sample, 2 × 250.00 × 0.90 = 450.00 and 3 × 40.00 = 120.00. The lines must sum to the net total (570.00), Σ(line net × VAT%) must equal the VAT total (108.30), and net + VAT must equal gross (678.30). VAT is summed across lines and rounded once. Stage 2 checks empirically whether Fakturama rounds the same way; a 1-cent difference goes to review. The payment method must be one of the three supported ones, PAID requires a payment date, and all dates must be valid.
6. **Normalise to Fakturama's shape.** Split the contact name into first and last (more than two words goes to review). Split each address into street, ZIP, city and country. Flag billing ≠ delivery. Precompute the Product gross price = round(net × (1 + VAT/100), 2), e.g. 297.50 and 47.60.

**Why an LLM plus OCR, rather than one or the other.** A vision LLM handles layout and labels robustly but can misread or "fix" digits. OCR is literal but fragile on layout. Using the LLM for structure, OCR for literal confirmation and arithmetic for consistency means a wrong digit would have to fool all three checks.

## 5. Control-discovery and grounding strategy

**Decision: deterministic, code-driven grounding. No LLM while driving the UI.** Writes to accounting data must be predictable and auditable. When the bot is unsure, it stops rather than improvises.

- **Semantic locators, not positions.** Each control is described in OS-neutral terms: *role + name or label + container*. For example: "the text field next to the label `Cust.Ref.` inside the `New Order` tab", "the toolbar button `Save`", "the menu `Data → Documents`". The order of preference is:
  1. the accessible name or ID (AutomationId on Windows);
  2. the nearest label, by reading order;
  3. position within a uniquely named container.

  Native menus are used in preference to the custom-drawn left navigation panel; the backend knows that macOS puts them in the global menu bar. Shortcuts are written as `primary+C`, which the backend maps to Ctrl or Cmd. All label strings are kept in one table per screen, with Fakturama pinned to the English UI.
- **Every action follows find → act → read back → confirm.** For example: type into Date, press Tab, read the value back, parse it with a locale-aware parser (`14.07.2026` and `07/14/2026` both handled), and compare. A mismatch gets one retry, then a stop.
- **Condition waits, never fixed sleeps.** The bot waits for a dialog to appear, an editor tab to lose its `*` (meaning saved), or a grid to be stable (two identical OCR reads about 300 ms apart). Every wait has a timeout.
- **Modal guard.** After each action, the bot checks for new top-level windows and reads their text through the backend. Known prompts are handled by explicit rules. Anything unknown means a screenshot and a stop.
- **Grid reading (NatTable):**
  1. Narrow the grid with the native search box.
  2. Get the grid's rectangle from the backend and capture only that rectangle.
  3. Run OCR on it.
  4. Find the column headers by text ("Company", "ZIP", "Item No.", …) to map columns.
  5. Cluster words into rows by their y-coordinate.
  6. Match rows against the expected values.
  7. Click the centre of the matched row, then confirm the selection took effect, e.g. the addresses fill in after OK.

  The spike will also test **copy (`primary+C`) on a selected row**. If NatTable copies the row text to the clipboard, that becomes the primary reader and OCR becomes the fallback.
- **Item-line editing.** Locate the cell by its row (found by SKU) and its column (found by header), then double-click it. This opens a native editor that the accessibility API can see. Type the value, press Enter, and then confirm through the **Order totals**, which are native read-only fields and the most reliable check the bot has.

## 6. Flow and decision rules

| Stage | Main actions | Stops for manual review if… |
|---|---|---|
| 0. Pre-flight | Find the main window. Check *Documents* for an existing Order with this Cust.Ref. (the idempotency key). | An Order with this Cust.Ref. already exists |
| 1. New Order | Toolbar **Order**. Keep the proposed No. Set Date and Cust.Ref. Set **Net** and **With VAT**. The tab stays open throughout. | A field won't hold its value |
| 2. Debtor | Open the address selector (the upper icon). Search by Company. An **exact** match means Company, First Name, Name, ZIP and City all match. **1 exact row** → select it. **No plausible row** → create the Debtor (§2.5–2.11 of the brief), creating the Payment Method under *Data → terms of payment* first if needed. Then go back to the Order and reselect. | More than one exact row; a **near-miss** (one field differs by 1–2 characters, which could be an OCR error or a real conflict); or a conflicting payment-method definition |
| 3. Each Product (source order) | Open the product selector and search by exact SKU. If missing: check *Data → VATs* for `VAT 19%` with value 19 and code S, and create it if absent. Then create the Product (gross price, VAT, stock 0) and reselect it. Set Qty, U.Price and Discount, then check the line price. | Conflicting SKU or VAT rows; the new product not found after saving |
| 4. Save Order | Compare Total Net, VAT and Total with the source totals. **Save**. Check the *Documents* row: number, date, Cust.Ref., open state and total. | Any total differs |
| 5. Linked Invoice | Use the **follow-up** Invoice action (not the toolbar). Check the copied fields. Set the payment method. If PAID: tick paid, payment date, value = invoice total. **Save**. Check *Documents*. Reopen the invoice only if needed. | Payment method unavailable; saved values differ |

- **Interpretation:** the brief only details the case where billing and delivery are the same. When they differ, as in the sample, the main address gets the **Invoice** role and a second address gets the **Delivery** role. The delivery name line ("Northstar Office Warehouse") goes into that address's name field.
- **Safe to re-run.** Every master record is checked before it's created, so a crashed run can be restarted: it reuses what already exists. Only the Order needs the pre-flight duplicate check.

## 7. Verification, errors and observability

- **Layered verification:** (1) every field write is read back; (2) each stage has a postcondition, e.g. a Debtor counts as saved only once selecting it from the Order fills in the addresses; (3) Order and Invoice totals must equal the source totals; (4) the saved records are checked in *Data → Documents*; (5) *optional:* a post-run audit reads a **copy** of the HSQLDB file.
- **Error classes:** *transient* (control not ready yet) gets a bounded retry. *Data ambiguity* (multiple or near-miss matches, conflicting settings) and *unexpected UI* (unknown dialog, locator not found) both stop the run. On a stop, the bot **saves nothing further**. It leaves the Order tab open for a person, writes a review bundle (reason, step, `order.json`, screenshots) and exits with a distinct code.
- **Run report:** a JSONL step log, each decision (found, created or stopped), and **annotated screenshots** showing the target rectangle and the value read back at each step. The screenshots double as the demo deliverable.

## 8. Testing strategy

- **Unit (test-first):** invariants and rounding; name and address splitting; locale parsing; match classification (exact, none, ambiguous or near-miss); grid row clustering on saved NatTable screenshots.
- **Extraction:** a golden test on the sample image that every adapter must pass, producing the same expected `order.json`. It runs against recorded responses, plus an opt-in live test per provider.
- **Backend contract tests:** one checklist (find, set, read back, click, detect a modal, capture a rectangle) run against Fakturama's Order editor. Every UI backend must pass it before the flow runs on that OS.
- **End-to-end on both built backends**: macOS locally and Windows 11 in a VM. A known **database snapshot** is restored before each run. Scenarios: everything new; everything exists; Debtor exists but a Product is missing; duplicate Debtor (must stop); unpaid order; conflicting VAT row (must stop). The same suite runs unchanged on each backend.

## 9. Tradeoffs and risks

| Choice | Benefit | Cost and mitigation |
|---|---|---|
| Deterministic accessibility-API grounding, no LLM at run time | Predictable, fast, auditable, testable | A renamed label breaks a locator. Labels are centralised, and a failure stops with diagnostics. **Future:** an LLM that may only *choose among the backend's candidates* to repair a locator. |
| OS-agnostic core with per-OS backends | The same flow, screen objects and tests on Windows, macOS and Linux; development can happen on a Mac | The interface is limited to what all three APIs support. Per-OS quirks (focus, DPI scaling, menu bar, permissions) stay inside the adapters. v1 builds macOS and Windows. The second backend is only a thin adapter, because the flow and tests are shared. |
| OCR for NatTable grids | Works with no app changes and no fixed coordinates | An OCR misread could look like "no match" and cause a **duplicate Debtor or Product**. Mitigations: narrow with search first; a near-miss stops instead of creating; check for clipboard copy in the spike. |
| UI reads instead of database reads | Meets the brief; the UI is the product's stable contract; avoids the DB lock and stale reads | Slower and less precise. The DB is used only for test snapshots and the optional post-run audit. (Fakturama's MySQL/MariaDB mode would allow live reads, but changes the reviewers' setup.) |
| Vision LLM + OCR + arithmetic for extraction | Robust to layout; digits are triple-checked | API dependency and cost per image. Providers sit behind one interface, so swapping vendor is a config change. If the configured provider is unavailable, the run stops before touching Fakturama. |
| UI automation in general | Works where there's no API | A run takes minutes, not seconds. That's acceptable for one document per run. |

**Spike first (about 30 min, on macOS with Accessibility Inspector, then on Windows with Accessibility Insights):** typing into `CDateTime`; whether `CTabFolder` items are named; copy on NatTable rows; how the follow-up-document buttons are exposed; OCR accuracy on NatTable fonts at 100% and 125%/Retina scaling. On macOS, the terminal running the bot needs the **Accessibility** and **Screen Recording** permissions, which the user grants once.

**Build order for the 5-hour Part 2:** spike → extraction and validation → macOS backend and Order header → Debtor and Product *selection* paths (against a seeded snapshot) → line editing, Order save and verification → linked Invoice and payment → Windows UIA adapter, running the same tests in a VM → creation branches (Debtor, payment method, VAT, Product) as time allows.
