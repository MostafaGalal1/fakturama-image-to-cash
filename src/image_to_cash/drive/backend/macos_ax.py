"""macOS adapter: drives Fakturama through the Accessibility API (pyobjc).

Built on docs/spike-macos-ax.md:
- SWT tab folders hide their contents from AXChildren, so `scan` hit-tests a grid of points.
- Text is entered by clicking, typing CGEvent keystrokes and reading the value back. Setting
  AXValue directly only changes the display: Fakturama would not save it, so it is never used.
- Input events are posted only while Fakturama holds the keyboard focus and the front window
  (see safety.py), a click only when the target itself is under the pointer, and typing only while
  the clicked field still has the focus.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

import ApplicationServices as AX
import Quartz
from AppKit import NSPasteboard, NSPasteboardItem, NSRunningApplication
from PIL import Image

from image_to_cash.drive.backend.ax_roles import AX_ROLES, element_from_record
from image_to_cash.drive.backend.base import BackendError, UnsafeToAct
from image_to_cash.drive.backend.keys import MAC_KEY_CODES, parse_chord
from image_to_cash.drive.backend.safety import is_within, require_copied_text, require_keyboard, wait_until_frontmost
from image_to_cash.drive.backend.window_capture import NORMAL_WINDOW_LAYER, WindowInfo, crop_box, window_for
from image_to_cash.drive.elements import Element, Rect, Window, distinct
from image_to_cash.drive.waits import WaitTimeout, wait_until

BUNDLE_ID = "Fakturama.ID"
AX_SUCCESS = 0
AX_ACTION_UNSUPPORTED = -25205  # kAXErrorActionUnsupported
SCAN_STEP_X, SCAN_STEP_Y = 12.0, 8.0  # finer than the smallest control (14 pt tall, 14 pt wide)
CONTAINER_ROLES = frozenset({"AXGroup", "AXScrollArea", "AXUnknown", "AXTabGroup", "AXSplitGroup"})
LEAF_ROLES = frozenset(AX_ROLES) - {"AXTabGroup", "AXWindow"}  # controls with nothing inside them
TREE_DEPTH = 12
EVENT_PAUSE_SECONDS = 0.02
TYPE_PAUSE_SECONDS = 0.01
MENU_OPEN_SECONDS = 0.5
CLIPBOARD_TIMEOUT_SECONDS = 2.0
CLIPBOARD_POLL_SECONDS = 0.05
CLICK_SETTLE_SECONDS = 1.5  # a window raised a moment ago may still be under another one
CAPTURE_TIMEOUT_SECONDS = 30
FOCUS_MOVING_KEYS = frozenset({"tab", "return", "escape"})
MODIFIER_FLAGS = {
    "primary": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "ctrl": Quartz.kCGEventFlagMaskControl,
}


class MacAxBackend:
    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._app = AX.AXUIElementCreateApplication(pid)
        self._system = AX.AXUIElementCreateSystemWide()
        self._clicked: object | None = None  # the field that should hold keyboard focus for typing

    @classmethod
    def attach(cls) -> MacAxBackend:
        if not AX.AXIsProcessTrusted():
            raise BackendError(
                "this terminal needs Accessibility access: System Settings > Privacy & Security > Accessibility"
            )
        running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
        if len(running) != 1:
            raise BackendError(f"expected one running Fakturama, found {len(running)}")
        return cls(running[0].processIdentifier())

    def bring_to_front(self) -> None:
        """Called once, at the start of a run; afterwards losing the front stops the run."""
        self._set(self._app, "AXFrontmost", True)
        wait_until_frontmost(self._pid, self._active_pid, sleep=time.sleep)
        wait_until_frontmost(self._pid, _front_window_pid, sleep=time.sleep)
        self._guard()

    # Accessibility only: safe while someone else uses the Mac.

    def windows(self) -> tuple[Window, ...]:
        handles = [h for h in self._attr(self._app, "AXWindows") or () if self._has_frame(h)]
        return tuple(Window(str(self._attr(h, "AXTitle") or ""), self._rect(h), h) for h in handles)

    def press_menu(self, path: Sequence[str]) -> None:
        element = self._attr(self._app, "AXMenuBar")
        for title in path:
            element = self._menu_item(element, title, path)
        self._perform(element, "AXPress")

    def tree(self, window: Window) -> tuple[Element, ...]:
        found: list[Element] = []
        self._walk(window.handle, 0, found)
        return distinct(found)  # a table lists each cell under its row and again under its column

    def scan(self, area: Rect) -> tuple[Element, ...]:
        found: dict[tuple[str, tuple[int, int, int, int]], object] = {}
        containers: dict[tuple[int, int, int, int], object] = {}
        y = area.y
        while y < area.bottom:
            x = area.x
            while x < area.right:
                handle = self._hit(self._app, x, y)
                role = self._attr(handle, "AXRole") if handle is not None else None
                step = SCAN_STEP_X
                if role in CONTAINER_ROLES and self._has_frame(handle):
                    containers.setdefault(self._rect(handle).rounded(), handle)
                elif role is not None and self._has_frame(handle):
                    rect = self._rect(handle)
                    found.setdefault((str(role), rect.rounded()), handle)  # read the rest once
                    if role in LEAF_ROLES:  # nothing else to find inside this control
                        step = max(step, rect.right - x)
                x += step
            y += SCAN_STEP_Y
        for container in containers.values():  # disabled fields are listed there, though not hit-testable
            for child in self._attr(container, "AXChildren") or ():
                role = self._attr(child, "AXRole")
                if role in LEAF_ROLES and self._has_frame(child) and area.contains(self._rect(child)):
                    found.setdefault((str(role), self._rect(child).rounded()), child)
        elements = (self._element(handle) for handle in found.values())
        return tuple(sorted(elements, key=lambda e: (e.rect.y, e.rect.x)))

    def refresh(self, element: Element) -> Element:
        return self._element(_handle(element))

    def press(self, element: Element) -> None:
        self._perform(_handle(element), "AXPress")

    def choose(self, popup: Element, option: str) -> None:
        """Opens a menu over the screen, so it needs Fakturama in front like any input."""
        handle = _handle(popup)
        self._guard()
        self._perform(handle, "AXPress")
        menus = wait_until(lambda: self._menus(handle), what="the pop-up menu", timeout=MENU_OPEN_SECONDS * 4)
        try:
            items = [item for menu in menus for item in self._attr(menu, "AXChildren") or ()]
            matches = [item for item in items if self._attr(item, "AXTitle") == option]
            if len(matches) != 1:
                raise BackendError(f"pop-up has {len(matches)} options titled {option!r}")
            self._perform(matches[0], "AXPress")
        except BaseException:
            for menu in menus:
                AX.AXUIElementPerformAction(menu, "AXCancel")  # never leave a menu holding the keyboard
            raise
        try:
            wait_until(lambda: self.refresh(popup).value == option, what=f"the pop-up to show {option!r}", timeout=2)
        except WaitTimeout:
            raise BackendError(f"pop-up shows {self.refresh(popup).value!r} after choosing {option!r}") from None

    def capture(self, area: Rect, path: Path) -> Path:
        """Fakturama's own pixels only: the window holding `area` is captured, then cropped."""
        try:
            window = window_for(area, self._window_infos(), self._pid)
        except ValueError as error:
            raise BackendError(str(error)) from None
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as scratch:
            whole = Path(scratch) / "window.png"
            command = ["screencapture", "-x", "-o", f"-l{window.window_id}", str(whole)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=CAPTURE_TIMEOUT_SECONDS)
            if result.returncode != 0 or not whole.is_file():
                raise BackendError(f"window capture failed (Screen Recording permission?): {result.stderr.strip()}")
            with Image.open(whole) as image:
                image.crop(crop_box(window.bounds, area, image.width)).save(path)
        return path

    # Input: only while Fakturama holds the keyboard and the front window.

    def click(self, element: Element, *, at: tuple[float, float] | None = None, count: int = 1) -> None:
        """Clicks the control's current centre (or `at`), only once the control itself is under the pointer."""
        handle = _handle(element)
        frame = self._rect(handle)
        x, y = frame.center if at is None else at
        if not frame.holds(x, y):
            raise ValueError(f"click point ({x:.0f}, {y:.0f}) lies outside the target {frame}")
        try:
            wait_until(lambda: self._on_top(handle, x, y), what="the target to be on top", timeout=CLICK_SETTLE_SECONDS, poll=0.1)
        except WaitTimeout:
            raise UnsafeToAct(f"something else covers the target at ({x:.0f}, {y:.0f}); refusing to click") from None
        for click_state in range(1, count + 1):
            self._guard()
            for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                event = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
                Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, click_state)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
                time.sleep(EVENT_PAUSE_SECONDS)
        self._clicked = handle

    def type_text(self, text: str) -> None:
        for char in text:
            self._guard_typing()
            units = len(char.encode("utf-16-le")) // 2
            for down in (True, False):
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
                Quartz.CGEventSetFlags(event, 0)  # no modifier still held from an earlier chord
                Quartz.CGEventKeyboardSetUnicodeString(event, units, char)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(TYPE_PAUSE_SECONDS)

    def key(self, chord: str) -> None:
        parsed = parse_chord(chord)
        flags = 0
        for modifier in parsed.modifiers:
            flags |= MODIFIER_FLAGS[modifier]
        self._guard()
        for down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, MAC_KEY_CODES[parsed.key], down)
            Quartz.CGEventSetFlags(event, flags)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(EVENT_PAUSE_SECONDS)
        if parsed.key in FOCUS_MOVING_KEYS:
            self._clicked = None

    def copy_selection(self) -> str:
        board = NSPasteboard.generalPasteboard()
        saved = _save_clipboard(board)
        try:
            before = board.changeCount()
            self.key("primary+c")
            wait_until(
                lambda: board.changeCount() != before,
                what="the copy to reach the clipboard",
                timeout=CLIPBOARD_TIMEOUT_SECONDS,
                poll=CLIPBOARD_POLL_SECONDS,
            )
            self._guard()  # still Fakturama's copy, not something a person copied meanwhile
            copied = require_copied_text(board.stringForType_("public.utf8-plain-text"))
        except BaseException:
            _restore_clipboard(board, saved)  # best effort: the copy's own error matters more
            raise
        if not _restore_clipboard(board, saved):
            raise BackendError("copied the grid, but could not restore the clipboard")
        return str(copied)

    # Helpers.

    def _guard(self) -> None:
        require_keyboard(
            self._pid,
            app_is_active=self._attr(self._app, "AXFrontmost") is True,
            front_window_pid=_front_window_pid(),
            focused_app_pid=self._focused_app_pid(),
        )

    def _guard_typing(self) -> None:
        """Typing also needs the clicked field to still hold the keyboard focus."""
        self._guard()
        if self._clicked is None:
            return
        focused = self._attr(self._app, "AXFocusedUIElement")
        if not is_within(focused, self._clicked, lambda e: self._attr(e, "AXParent")):
            raise UnsafeToAct("keyboard focus moved away from the field that was clicked; refusing to type")

    def _on_top(self, handle: object, x: float, y: float) -> bool:
        return is_within(self._hit(self._system, x, y), handle, lambda e: self._attr(e, "AXParent"))

    def _focused_app_pid(self) -> int | None:
        """The system's answer to "who holds the keyboard focus", or None when it cannot say:
        on this Mac the query often fails ("cannot complete") after a burst of accessibility calls."""
        app = self._attr(self._system, "AXFocusedApplication")
        if app is None:
            return None
        error, pid = AX.AXUIElementGetPid(app, None)
        return int(pid) if error == AX_SUCCESS else None

    def _active_pid(self) -> int | None:
        return self._pid if self._attr(self._app, "AXFrontmost") is True else None

    def _menus(self, handle: object) -> list[object]:
        return [m for m in self._attr(handle, "AXChildren") or () if self._attr(m, "AXRole") == "AXMenu"]

    def _has_frame(self, handle: object) -> bool:
        return self._attr(handle, "AXPosition") is not None and self._attr(handle, "AXSize") is not None

    @staticmethod
    def _window_infos() -> tuple[WindowInfo, ...]:
        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        infos = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or ()
        return tuple(
            WindowInfo(
                window_id=int(info["kCGWindowNumber"]),
                pid=int(info["kCGWindowOwnerPID"]),
                layer=int(info["kCGWindowLayer"]),
                bounds=Rect(*(float(info["kCGWindowBounds"][key]) for key in ("X", "Y", "Width", "Height"))),
            )
            for info in infos
        )

    def _menu_item(self, parent: object, title: str, path: Sequence[str]) -> object:
        candidates: list[object] = []
        for child in self._attr(parent, "AXChildren") or ():
            if self._attr(child, "AXRole") == "AXMenu":
                candidates.extend(self._attr(child, "AXChildren") or ())
            else:
                candidates.append(child)
        matches = [c for c in candidates if self._attr(c, "AXTitle") == title]
        where = " > ".join(path)
        if len(matches) != 1:
            raise BackendError(f"menu {where}: {len(matches)} items titled {title!r}")
        if self._attr(matches[0], "AXEnabled") is False:
            raise BackendError(f"menu {where}: {title!r} is disabled")
        return matches[0]

    def _walk(self, handle: object, depth: int, found: list[Element]) -> None:
        if self._has_frame(handle):
            found.append(self._element(handle))
        if depth < TREE_DEPTH:
            for child in self._attr(handle, "AXChildren") or ():
                self._walk(child, depth + 1, found)

    def _element(self, handle: object) -> Element:
        rect = self._rect(handle)
        record = {
            "role": self._attr(handle, "AXRole"),
            "title": _plain(self._attr(handle, "AXTitle")),
            "value": _plain(self._attr(handle, "AXValue")),
            "help": _plain(self._attr(handle, "AXHelp")),
            "enabled": _plain(self._attr(handle, "AXEnabled")),
            "rect": [rect.x, rect.y, rect.width, rect.height],
        }
        return element_from_record(record, handle)

    def _rect(self, handle: object) -> Rect:
        position, size = self._attr(handle, "AXPosition"), self._attr(handle, "AXSize")
        if position is None or size is None:
            raise BackendError("element has no frame (it may have closed)")
        _, point = AX.AXValueGetValue(position, AX.kAXValueCGPointType, None)
        _, extent = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
        return Rect(float(point.x), float(point.y), float(extent.width), float(extent.height))

    @staticmethod
    def _attr(handle: object, name: str) -> object | None:
        error, value = AX.AXUIElementCopyAttributeValue(handle, name, None)
        return value if error == AX_SUCCESS else None

    @staticmethod
    def _set(handle: object, name: str, value: object) -> None:
        error = AX.AXUIElementSetAttributeValue(handle, name, value)
        if error != AX_SUCCESS:
            raise BackendError(f"setting {name} failed with accessibility error {error}")

    @staticmethod
    def _perform(handle: object, action: str) -> None:
        """Callers confirm every effect by reading back, so a spurious error code is tolerated:
        SWT table checkboxes toggle on AXPress yet report ActionUnsupported."""
        error = AX.AXUIElementPerformAction(handle, action)
        if error == AX_SUCCESS:
            return
        _, actions = AX.AXUIElementCopyActionNames(handle, None)
        if error == AX_ACTION_UNSUPPORTED and action in (actions or ()):
            return
        raise BackendError(f"{action} failed with accessibility error {error}")

    @staticmethod
    def _hit(root: object, x: float, y: float) -> object | None:
        error, handle = AX.AXUIElementCopyElementAtPosition(root, x, y, None)
        return handle if error == AX_SUCCESS else None


def _front_window_pid() -> int | None:
    """Owner of the frontmost normal window, live from the window server (NSWorkspace's answer
    can be stale in a process without a run loop)."""
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for info in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or ():
        if int(info["kCGWindowLayer"]) == NORMAL_WINDOW_LAYER:
            return int(info["kCGWindowOwnerPID"])
    return None


def _handle(element: Element) -> object:
    if element.handle is None:
        raise BackendError("element was not read from the live app (no handle)")
    return element.handle


def _plain(value: object) -> str | None:
    """Text, numbers and booleans as text; references to other elements are dropped."""
    return str(value) if isinstance(value, (str, int, float)) else None


def _save_clipboard(board: NSPasteboard) -> list[dict[str, object]]:
    return [{kind: item.dataForType_(kind) for kind in item.types()} for item in board.pasteboardItems() or ()]


def _restore_clipboard(board: NSPasteboard, saved: list[dict[str, object]]) -> bool:
    board.clearContents()
    items = []
    for kinds in saved:
        item = NSPasteboardItem.alloc().init()
        for kind, data in kinds.items():
            if data is not None:
                item.setData_forType_(data, kind)
        items.append(item)
    return bool(board.writeObjects_(items)) if items else True
