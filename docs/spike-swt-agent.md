# Spike: reading Fakturama from inside its JVM

**Question:** would a driver inside Fakturama's own Java process be faster and more robust than
UI Automation (Windows) and the Accessibility API (macOS), as the README suggests?

**What was built** ([spikes/swt-agent](../spikes/swt-agent)): a read-only Java agent
(`Probe.java`) and an attacher (`Attach.java`), compiled for Java 17 by `build.sh`. The attacher
loads the agent into the running Fakturama with the JDK's Attach API, so Fakturama needs no
restart and no change to its launch settings. The agent finds SWT's `Display` among the classes
Fakturama has loaded and walks every visible window on SWT's UI thread (`Display.syncExec`). It
writes what it saw to a text file. It clicks, types and changes nothing.

```bash
spikes/swt-agent/build.sh
java -cp spikes/swt-agent/build/attach.jar Attach <fakturama pid> \
  "$PWD/spikes/swt-agent/build/probe.jar" "$PWD/out/swt-probe.txt"
```

## Result (macOS, Fakturama 2.2 on its x64 Java 17, attached from an arm64 JDK 17)

| | In-process probe | Today's adapters |
|---|---|---|
| Whole window: editor tabs, every field's text, checkboxes, two grids | **45 ms** on the UI thread (539 ms on the first read, while reflection warms up) | one accessibility scan per area plus a copy per grid: seconds, not milliseconds (not timed side by side) |
| Grid rows | NatTable's stored values, header row included: `EUR 250`, `-0.1`, `678.3`, the VAT record, the state `COMMAND_ORDER_PENDING` | select a row, copy, read the clipboard, parse the display text; OCR to find rows |
| Needs the foreground, mouse or clipboard | no | yes, for every click, keystroke and copy |
| Tooltips, hidden tabs, DPI, double-click timing | not involved: widgets are read as objects | each was a live bug on Windows |

What it read in one pass (`out/swt-probe-mac.txt`):
- the editor tabs with the selected one marked (`[INV000002]`);
- the Invoice's fields: number, dates, Cust.Ref., price and VAT modes, the address block, the
  totals, and `paid (ticked)` with its method, date and value;
- the Invoice's line grid, cell by cell;
- the Documents list with its search text and the matching row.

## What it would take to drive, not only read

- **Writing values:** set a widget's value and send the SWT events Fakturama's data binding
  listens to (Modify, Selection, FocusOut), or post key events through `Display.post`. SWTBot
  does this and is the reference.
- **Selecting grid rows:** NatTable's `SelectRowsCommand` selects exact rows by index, with no
  pixel geometry.
- **Saving:** the Save command through Eclipse's command service, then the same read-back as
  today.
- **Windows:** Fakturama's bundled runtime has no `jdk.attach` module. Either attach from a JDK
  installed beside it, or start the agent with Fakturama through `-javaagent:` in
  `Fakturama.ini` (one line in its launch settings).

## Costs and risks

- It ties the bot to Fakturama's widget classes (SWT, NatTable, Fakturama's editors), which
  change with Fakturama releases. Today's adapters rely only on what any user sees.
- Every call goes through reflection, because SWT and NatTable live in OSGi bundles the agent's
  class loader cannot see. A small compiled bridge loaded as an OSGi fragment would be cleaner.
- Code running on SWT's UI thread must be quick and must never block, or Fakturama freezes.
- The brief asks for Fakturama's UI. Setting values through the same widgets and events a user
  triggers stays inside that rule, but it is a closer reading of it than mouse and keyboard.

## Verdict

For reading and verifying, it is clearly better: one pass in well under a second, exact stored
values, and none of the foreground, clipboard, OCR or DPI work. Next step: move the read-backs
(field values, grid rows, the Documents search) to the agent first, and keep today's input path.
That removes the copy/OCR code where most live bugs were, without yet relying on synthetic SWT
events for input.
