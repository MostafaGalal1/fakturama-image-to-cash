import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Read-only spike (README "What I would do differently"): loaded into Fakturama's own JVM, it
 * reads the open windows, editor tabs, text fields and NatTable cells directly, on SWT's UI
 * thread, and writes what it saw to a text file. It clicks, types and changes nothing.
 *
 * SWT and NatTable live in OSGi bundles this agent's class loader cannot see, so every call goes
 * through reflection on the classes Fakturama has already loaded.
 */
public final class Probe {
    private static final int MAX_ROWS = 12;
    private static final int MAX_DEPTH = 60;

    public static void agentmain(String args, Instrumentation inst) throws Exception {
        Path out = Path.of(args);
        long started = System.nanoTime();
        Class<?> displayClass = loaded(inst, "org.eclipse.swt.widgets.Display");
        Object display = displayClass.getMethod("getDefault").invoke(null);
        List<String> lines = new ArrayList<>();
        long[] uiMillis = new long[1];
        Runnable read = () -> {
            long t = System.nanoTime();
            try {
                for (Object shell : (Object[]) call(display, "getShells")) {
                    if ((Boolean) call(shell, "isVisible")) {
                        walk(shell, 0, lines);
                    }
                }
            } catch (Exception error) {
                lines.add("ERROR " + error);
            }
            uiMillis[0] = (System.nanoTime() - t) / 1_000_000;
        };
        displayClass.getMethod("syncExec", Runnable.class).invoke(display, read);
        long total = (System.nanoTime() - started) / 1_000_000;
        lines.add(0, "# read on the UI thread in " + uiMillis[0] + " ms; " + total + " ms with attaching the probe");
        Files.write(out, lines, StandardCharsets.UTF_8);
    }

    private static void walk(Object widget, int depth, List<String> lines) throws Exception {
        if (depth > MAX_DEPTH || !(Boolean) call(widget, "isVisible")) {
            return;
        }
        String kind = widget.getClass().getSimpleName();
        String indent = "  ".repeat(depth);
        switch (kind) {
            case "Shell" -> lines.add(indent + "Shell '" + call(widget, "getText") + "'");
            case "CTabFolder" -> lines.add(indent + "Tabs " + tabs(widget));
            case "Text", "StyledText", "Combo", "CCombo", "Button", "Label", "CLabel", "Link" -> {
                Object text = callOrNull(widget, "getText");
                if (text != null && !text.toString().isBlank()) {
                    lines.add(indent + kind + " '" + text.toString().replace("\n", " | ") + "'" + checked(widget));
                }
            }
            case "NatTable" -> lines.addAll(cells(widget, indent));
            default -> { }
        }
        Object children = callOrNull(widget, "getChildren");
        if (children instanceof Object[] list) {
            for (Object child : list) {
                walk(child, depth + 1, lines);
            }
        }
    }

    private static String tabs(Object folder) throws Exception {
        Object selected = call(folder, "getSelection");
        StringBuilder found = new StringBuilder();
        for (Object item : (Object[]) call(folder, "getItems")) {
            found.append(item == selected ? "[" : "").append(call(item, "getText")).append(item == selected ? "] " : " ");
        }
        return found.toString().trim();
    }

    private static String checked(Object widget) {
        Object selection = callOrNull(widget, "getSelection");
        return selection instanceof Boolean ticked ? (ticked ? " (ticked)" : " (not ticked)") : "";
    }

    /** Every cell's stored value, header rows included, as NatTable's own layers report them. */
    private static List<String> cells(Object table, String indent) throws Exception {
        List<String> rows = new ArrayList<>();
        int columns = (Integer) call(table, "getColumnCount");
        int count = (Integer) call(table, "getRowCount");
        rows.add(indent + "NatTable " + count + " rows x " + columns + " columns");
        Method value = table.getClass().getMethod("getDataValueByPosition", int.class, int.class);
        for (int row = 0; row < Math.min(count, MAX_ROWS); row++) {
            List<String> shown = new ArrayList<>();
            for (int column = 0; column < columns; column++) {
                Object cell = value.invoke(table, column, row);
                shown.add(cell == null ? "" : cell.toString());
            }
            rows.add(indent + "  " + String.join(" | ", shown));
        }
        return rows;
    }

    private static Class<?> loaded(Instrumentation inst, String name) {
        for (Class<?> type : inst.getAllLoadedClasses()) {
            if (type.getName().equals(name)) {
                return type;
            }
        }
        throw new IllegalStateException(name + " is not loaded: is this Fakturama?");
    }

    private static Object call(Object target, String method) throws Exception {
        return target.getClass().getMethod(method).invoke(target);
    }

    private static Object callOrNull(Object target, String method) {
        try {
            return call(target, method);
        } catch (Exception missing) {
            return null;
        }
    }
}
