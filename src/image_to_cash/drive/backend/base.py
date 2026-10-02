"""The UI backend contract every OS adapter implements (design §3, §5).

Two kinds of operation:
- Accessibility only (`windows`, `press_menu`, `tree`, `scan`, `element_at`, `focused`, `refresh`, `press`): no mouse or
  keyboard events, so they cannot reach another app.
- Input (`click`, `type_text`, `key`, `copy_selection`, `paste_text`, `focus`, and `choose` and
  `options`, whose menu opens over the screen): only while Fakturama holds the keyboard focus and the front window, checked before
  every event; a click only when the target itself is under the pointer; otherwise UnsafeToAct.
- `bring_to_front` is called once, at the start of a run.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from image_to_cash.drive.elements import Element, Rect, Window


class BackendError(RuntimeError):
    """The OS accessibility API refused or failed an operation."""


class UnsafeToAct(BackendError):
    """Sending input now could reach another app (Fakturama is not frontmost)."""


class FocusNotTaken(UnsafeToAct):
    """The clicked control never took the keyboard focus, so nothing was typed. A freshly opened
    editor can spend its first click on activating itself; clicking again is safe."""


class UiBackend(Protocol):
    def bring_to_front(self) -> None:
        """Activate Fakturama; afterwards losing the front stops the run instead of re-activating."""
        ...

    def windows(self) -> tuple[Window, ...]:
        """Fakturama's top-level windows, dialogs included."""
        ...

    def press_menu(self, path: Sequence[str]) -> None:
        """Press a menu-bar item, e.g. ("Data", "Documents")."""
        ...

    def tree(self, window: Window) -> tuple[Element, ...]:
        """Every element in the window's accessibility tree. Dialogs expose all their controls;
        editors inside tab folders do not, so use `scan` for those."""
        ...

    def scan(self, area: Rect) -> tuple[Element, ...]:
        """Every control inside `area` (on screen, in points), found by hit-testing."""
        ...

    def refresh(self, element: Element) -> Element:
        """The same control with its current value, enabled state and frame."""
        ...

    def press(self, element: Element) -> None:
        """The control's default accessibility action (a button press, a checkbox toggle)."""
        ...

    def focused(self) -> Element | None:
        """The control in Fakturama that holds its keyboard focus."""
        ...

    def element_at(self, x: float, y: float) -> Element | None:
        """The innermost control at a screen point, e.g. a grid that exposes no children."""
        ...

    def choose(self, popup: Element, option: str) -> None:
        """Pick the pop-up option titled `option` (surrounding spaces ignored)."""
        ...

    def options(self, popup: Element) -> tuple[str, ...]:
        """The pop-up's option titles, read by opening its menu and cancelling it."""
        ...

    def focus(self, element: Element) -> None:
        """Give a control the keyboard focus without clicking it (for one something covers)."""
        ...

    def paste_text(self, text: str, into: Element) -> None:
        """Enter `text` in one edit through the clipboard, then restore the clipboard. A search
        box filters on every edit, and one that auto-accepts a single hit must see the whole text."""
        ...

    def click(self, element: Element, *, at: tuple[float, float] | None = None, count: int = 1) -> None:
        """A mouse click (`count` 2 for a double click) at the control's centre, or at the point
        `at` inside it, e.g. one row of a grid."""
        ...

    def type_text(self, text: str) -> None:
        """Type into whatever has keyboard focus."""
        ...

    def key(self, chord: str) -> None:
        """Press a key chord such as "tab" or "primary+c" (Cmd on macOS, Ctrl elsewhere)."""
        ...

    def copy_selection(self) -> str:
        """Copy the selection and return it, leaving the user's clipboard as it was."""
        ...

    def capture(self, area: Rect, path: Path) -> Path:
        """Save a screenshot of `area` to `path`."""
        ...
