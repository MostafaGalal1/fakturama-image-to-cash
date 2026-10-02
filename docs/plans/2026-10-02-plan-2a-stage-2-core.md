# Plan 2a: Stage 2 Core (offline-testable)

> **For agentic workers:** this plan is already implemented, test-first, one commit per task on
> `feat/stage-2-core`. The code and its tests in the repo are the source of truth; this file records
> the tasks and the decisions behind them. Plan 2b (screens, flow, `drive` command) follows it.

**Goal:** Everything Stage 2 needs that can be built and tested without driving Fakturama. That covers:
- the OS-neutral UI backend contract and the macOS adapter;
- locators that find controls by label, help text or title;
- number and date formats;
- grid parsing and record matching;
- pre-flight checks;
- the run report.

**Architecture:** design §3 and §5, refined by `docs/spike-macos-ax.md`.
- The flow sees only neutral `Element`s (role, frame, title, value, help).
- The macOS adapter finds controls inside SWT tab folders by hit-testing a grid of points, because
  `AXChildren` hides them. Recorded snapshots of the real editors (`tests/fixtures/ax/`) let the
  locators be tested offline.
- Safety:
  - Input events are posted only while Fakturama is frontmost. The bot activates Fakturama once,
    at the start. After that, losing the front stops the run instead of fighting a person for the
    keyboard.
  - A click is posted only when Fakturama's own element is under the pointer.
  - Screenshots capture Fakturama's window, then crop, so another app can't appear in them.

**Tech stack:** as Plan 1, plus `pyobjc-framework-ApplicationServices`, `-Quartz` and `-Cocoa`
(macOS only).

**Conventions:** as Plan 1. Repo-local git identity, no remote, conventional commits **with no
attribution trailer**.

---

| # | Task | Files (under `src/image_to_cash/drive/`) | Tests | Commit |
|---|---|---|---|---|
| 1 | Neutral elements and macOS role mapping; editor snapshots as fixtures | `elements.py`, `backend/ax_roles.py` | `test_elements.py`, `conftest.py` (`ax_snapshot`) | `9c3dae1` |
| 2 | Locators: by label (same row, before the next label, `nth` for shared labels), by help text, by title | `locate.py` | `test_locate.py` | `9a4a302` |
| 3 | Amounts, percentages and dates in each field's own style (`250,00`, `1.234,57 €`, `0.00`, `Oct 2, 2026`) | `formats.py` | `test_formats.py` | `72d8d14` |
| 4 | Grid rows from the clipboard; match classification (exact, none, ambiguous, near-miss) | `grid.py`, `matching.py` | `test_grid_and_matching.py` | `b0f89ac` |
| 5 | Pre-flight: re-validate `order.json`; require a euro currency locale in Fakturama's preferences | `preflight.py` | `test_preflight.py` | `d0e56af` |
| 6 | Run log (JSONL, one line per step) and annotated screenshots | `report.py` | `test_report.py` | `c694144` |
| 7 | Backend contract, key chords, frontmost rule | `backend/base.py`, `backend/keys.py`, `backend/safety.py` | `test_backend_safety.py` | `b1b591e` |
| 8 | macOS adapter; window-only capture; opt-in live contract test | `backend/macos_ax.py`, `backend/window_capture.py` | `test_window_capture.py`, `test_macos_ax_contract.py` (`FAKTURAMA_LIVE=1`) | `8f4c750` |
| 9 | Field writes (click, select all, type, Tab, read back; one retry, then stop naming the field only); condition waits | `actions.py`, `waits.py` | `test_actions_and_waits.py`, `fake_backend.py` | `673fd64` |

## Decisions made while building

- **Matching:**
  - Fields are compared after NFKC normalisation, case folding and collapsing spaces, so
    `Beusselstraße` equals `BEUSSELSTRASSE`.
  - A row within 2 edited characters in total is a near-miss, and the run stops: it could be a
    misread, and creating a record then would duplicate one.
  - Rows further off mean "create".
- **Dates:** only unambiguous display formats are parsed. `07/04/2026` could be April or July, so
  it is rejected.
- **Currency:** `order.json` carries no currency, because Stage 1 rejects anything but EUR. So
  pre-flight reads `PREFERENCE_CURRENCY_LOCALE` and requires a euro-area country (now `de/DE`).
- **Accessibility error -25205 on press:** tolerated only when the element advertises the action.
  SWT table checkboxes toggle and still report it. Callers always read back.
- **Scan cost:** about 6–7 s per editor. Scan once per screen, then `refresh` the elements in use.
- **Checked live, accessibility-only operations:**
  - The operations: `attach`, `windows`, `tree`, `press_menu` (including the error for a missing
    item), `scan`, `refresh`, `capture`, and discarding an editor through "Save Parts".
  - Fakturama's database log was unchanged afterwards.
- **Input-event operations** (`click`, `type_text`, `key`, `choose`, `copy_selection`) wait for
  the live contract test, which needs the Mac to itself.

## Plan 2b: done (2026-10-02)

Built in the live session rather than as a separate plan file: the screen objects under
`src/image_to_cash/drive/fakturama/`, the flow (`drive/flow.py`) and `image-to-cash drive`. The
end-to-end run on an empty database saved PO000001 (open) and INV000001 (paid) in 4 minutes; its
log and annotated screenshots are in the README. What the runs taught is in
`docs/spike-macos-ax.md` ("Settled in the live walkthrough", "Found by the end-to-end runs").
