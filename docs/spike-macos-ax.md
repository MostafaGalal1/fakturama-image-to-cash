# Spike: driving Fakturama through the macOS Accessibility API

Run on 2026-10-02 against Fakturama 2.2 (`/Applications/Fakturama/Fakturama2.app`, an SWT/Eclipse
RCP app). The database is HSQLDB in `~/Desktop/Database`, backed up first to
`~/Desktop/Database.backup-2026-10-02-before-stage2`.

It started empty: no contacts, products or documents. The only VAT was `Tax-free` (0%), and the
only payment method was `Pay Cash`. Every editor opened during the spike was closed without
saving. The database log shows only Fakturama's own bookkeeping: its version, and the
`last_setnextnr_date_*` dates it writes when an editor is opened.

## Results

| Question | Answer |
|---|---|
| Can we reach the app? | Yes. The process is trusted; windows and dialogs are found by title. |
| Menu bar | **Fully exposed, and `AXPress` works on items.** File (Close, Close All, Save), Edit (`mark as "paid"`…), Data (every list), New (New Order, New Debtor, New product, New VAT, New Term of Payment…). This is the most robust way to navigate. |
| Toolbar | Real `AXButton`s with title and help text; `AXPress` works. |
| Dialogs ("Select the address", "Save Parts") | Separate windows, fully exposed. "Save Parts" is a native `AXTable` with one checkbox per unsaved editor. |
| Fields inside editors and views | **Missing from the tree.** SWT's `CTabFolder` reports only its tab buttons as children. **Hit-testing works:** `AXUIElementCopyElementAtPosition` returns the real widgets with correct parent chains. A crawl (hit-test every 20×8 pt) recovers a panel's fields and labels: 32 elements in 1.5 s. |
| Locating a field | By help text when it has one: Cust.Ref., the document date, Name, the paid checkbox… Otherwise by the `AXStaticText` label on the same row, with its right edge about 5 pt left of the field. |
| Entering text | **Click the field, then type `CGEvent` keystrokes, then read `AXValue` back.** This marks the editor dirty, so Fakturama will save the value. |
| Setting `AXValue` directly | Changes the display only. The editor stays clean, so Fakturama would not save it. **Don't use it.** |
| `AXFocused = true` | Does not move SWT's keyboard focus, so the keystrokes go nowhere. Always click. |
| Switching editor tabs | `AXPress` on a tab returns success but doesn't switch. Click the tab. |
| Dates (`CDateTime`) | Typing a whole date does nothing. Click the month segment, type `07`, Right, `14`, Right, `2026`, then Tab, which reads `Jul 14, 2026`. The segment order follows the locale's format, so verify by reading back. |
| Icon buttons | `AXImage`s with help text but **no actions**. Click the centre of the frame. Examples: "Pick an address from the list of all contacts", "Open the contact editor to enter a new address", "Pick an item from the list of all products", "Add a new item…". |
| Checkboxes and pop-ups | `AXPress` works and marks the editor dirty, as with the invoice's `paid`. A pop-up's options are its menu's children after `AXPress`. `AXPress` on an option picks it, and `AXCancel` on the menu closes it. Neither needs a keystroke or focus. |
| Outlines (Preferences page list) | Setting the outline's `AXSelectedRows` to one row switches the page. No mouse event is needed. |
| Grids (NatTable) | `AXScrollArea` with no children. **But Cmd+C copies the selected rows to the clipboard, tab-separated.** List views give clean values, e.g. `true	Tax-free	Free of Tax	0.0`. The order's items grid gives some cells as Java `toString()` dumps, e.g. VAT. Cmd+A then Cmd+C selects and copies all. So grids are read through the clipboard (saved and restored around the copy), with OCR on the grid frame as the fallback. |
| Closing editors | Cmd+W did nothing (focus). **File → Close All** asks with one "Save Parts" dialog per dirty editor. Untick, verify, then OK discards it. **OK with the box ticked saves.** |
| "Save Parts" checkbox | `AXPress` toggles it but returns `kAXErrorActionUnsupported` (-25205), although the box lists `AXPress` among its actions. The adapter accepts that code only when the element advertises the action, and the caller confirms by reading the value back. The table lists each cell under its row and again under its column, so the tree is de-duplicated by role and frame. |
| Hit-test scan cost | About 6–7 s for one editor (1197×416 pt at a 20×8 pt step). Scan once per screen, then refresh only the elements in use. |
| Screenshots | A **screen-region** capture records whatever covers the region: one test capture recorded another app's window. Capture **Fakturama's own window** (`screencapture -l <window id>`), then crop. That records Fakturama's pixels even while it is covered. |

## Editors seen

- **Order:**
  - Fields: No. (`PO000001`), Date, Gross/Net, Cust.Ref., the invoice address (shown as text), Consultant and VAT mode.
  - Items grid: Qty, Item No., Name, Description, VAT, U.Price, Discount, Price.
  - Totals, shipping and remarks.
  - The follow-up buttons (Confirmation, Invoice, Delivery, Proforma) are disabled until the order is saved.
  - Opening the contact editor from an order marks the order dirty.
- **Debtor (contact):**
  - Fields: Customer ID (auto `CUST000001`), Category, Company, Salutation, and First Name / Last Name (two unlabeled fields after one label).
  - Address tab: additional name, Street, ZIP and City (two fields after one label), Country (pop-up) and address type.
  - Contact fields: E-Mail, Telephone, Mobile.
  - `+` adds another address, for the delivery address.
- **Product:**
  - Fields: Item Number, Name, Category, GTIN, Description and **Price (gross)**, which matches the `gross_price` Stage 1 already computes.
  - VAT pop-up (default `Free of Tax`), and Stock.
- **Invoice:** a `paid` checkbox. Ticking it reveals "at" (the payment date) and "Value" (the paid amount). Next to it is the payment-method pop-up (only `Pay Cash`), Due Days and Pay Until.
- **VAT (New → New VAT):** Name, Category, Description, VAT code (E-Invoice) pop-up (default `S (Standard rate)`), and Value (`0%`). The editor opens already marked dirty (`*New TAX Rate`).
- **Term of payment (New → New Term of Payment):**
  - Fields: Name, Account, Description, a payment-code pop-up (default "Mutually defined"), Cash discount, Discount Days and Net Days.
  - Text areas for the unpaid, deposit and paid texts.
- **Snapshots:** blank VAT, payment, product, debtor and order editors are recorded in
  `tests/fixtures/ax/`. The locator tests run against them.

## Consequences for Plan 2

1. **The backend works in layers.** Read structure with read-only accessibility calls. Act through menu items and `AXPress` where they work. Otherwise click the frame centre, then type, then read back.
2. **Use a hit-test crawl to find widgets inside tab folders.** Scope it to the content frame of the tab group in question.
3. **Read grids through the clipboard.** Select, copy, parse the tab-separated text, and save and restore the user's clipboard around it. Use OCR only as a fallback.
4. **The flow must select or create** the VAT (19% doesn't exist), the payment method (`Bank Transfer` doesn't exist), the debtor and the products.
5. **Guards before every click or keystroke:**
   - Fakturama is frontmost. If not, activate it with `AXFrontmost` (`open -a` proved unreliable), then re-check, and stop if it still isn't.
   - No unexpected window is open (the modal guard).
6. **Never press OK on "Save Parts"** unless the run means to save exactly those parts.
7. **The locale leaks into defaults.** Fakturama starts with `NL=en_EG`, taken from the Mac's region.
   - **Currency:** this is a preference. General → Currency locale is now `Germany`, stored as
     `PREFERENCE_CURRENCY_LOCALE=de/DE` in
     `~/.fakturama2/.metadata/.plugins/org.eclipse.core.runtime/.settings/com.sebulli.fakturama.rcp.prefs`.
     The example now reads `-1.234,57 €`, so amounts may need to be typed with a decimal comma.
     Read every amount back.
   - **Country:** there is no preference for it. A new contact's country is
     `getDefaultLocale().getCountry()`, i.e. `EG`. Your Company → Country is only free text for
     printed documents. So the flow sets the country on every address from `order.json`, which
     always carries one.
   - Launching with `-nl en_DE` would change the default country, but also the date and number
     formats the spike measured. It is not used.
8. **A run needs the Mac to itself.** During the spike, one keystroke test ran while another app was in front, and its text went there.

## Still open

- Cmd+A copy across several rows. Only one-row grids were available: the database was empty.
- The "Select the address" and product pickers with real rows: search, select, OK.
- Saving: the first real save of a VAT, payment method, debtor, product, order and invoice belongs to the end-to-end run, against a restorable database copy.
- Number entry under the `de/DE` currency locale: whether price fields expect `199,00` or accept `199.00`.
  (Display is confirmed: price fields show `0,00 €` without a restart.)
- The order editor's total values (Total Gross, VAT, Total): their labels were found, but no value
  element appeared in the scan.
- The payment-code pop-up's options, for "Bank Transfer".
