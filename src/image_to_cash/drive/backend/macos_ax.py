"""macOS adapter: drives Fakturama through the Accessibility API (pyobjc).

Built on docs/spike-macos-ax.md:
- SWT tab folders hide their contents from AXChildren, so `scan` hit-tests a grid of points.
- Text is entered by clicking, typing CGEvent keystrokes and reading the value back. Setting
  AXValue directly only changes the display: Fakturama would not save it, so it is never used.
- Input events are posted only while Fakturama is frontmost (see safety.py), and a click only
  when Fakturama's own element is under the pointer.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

import ApplicationServices as AX
import Quartz
from AppKit import NSPasteboard, NSPasteboardItem, NSRunningApplication, NSWorkspace
from PIL import Image

from image_to_cash.drive.backend.ax_roles import element_from_record
from image_to_cash.drive.backend.base import BackendError, UnsafeToAct
from image_to_cash.drive.backend.keys import MAC_KEY_CODES, parse_chord
from image_to_cash.drive.backend.safety import require_frontmost, wait_until_frontmost
from image_to_cash.drive.backend.window_capture import WindowInfo, crop_box, window_for
from image_to_cash.drive.elements import Element, Rect, Window, distinct

BUNDLE_ID = "Fakturama.ID"
AX_SUCCESS = 0
AX_ACTION_UNSUPPORTED = -25205  # kAXErrorActionUnsupported
SCAN_STEP_X, SCAN_STEP_Y = 20.0, 8.0  # finer than the smallest control (14 pt tall, 16 pt wide)
CONTAINER_ROLES = frozenset({"AXGroup", "AXScrollArea", "AXUnknown", "AXTabGroup", "AXSplitGroup"})
TREE_DEPTH = 12
EVENT_PAUSE_SECONDS = 0.02
TYPE_PAUSE_SECONDS = 0.01
MENU_OPEN_SECONDS = 0.5
CLIPBOARD_TIMEOUT_SECONDS = 2.0
CLIPBOARD_POLL_SECONDS = 0.05
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
        wait_until_frontmost(self._pid, _frontmost_pid, sleep=time.sleep)

    # Accessibility only: safe while someone else uses the Mac.

    def windows(self) -> tuple[Window, ...]:
        handles = self._attr(self._app, "AXWindows") or ()
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
        y = area.y
        while y < area.bottom:
            x = area.x
            while x < area.right:
                handle = self._hit(self._app, x, y)
                role = self._attr(handle, "AXRole") if handle is not None else None
                if role is not None and role not in CONTAINER_ROLES:
                    found.setdefault((str(role), self._rect(handle).rounded()), handle)  # read the rest once
                x += SCAN_STEP_X
            y += SCAN_STEP_Y
        elements = (self._element(handle) for handle in found.values())
        return tuple(sorted(elements, key=lambda e: (e.rect.y, e.rect.x)))

    def refresh(self, element: Element) -> Element:
        return self._element(_handle(element))

    def press(self, element: Element) -> None:
        self._perform(_handle(element), "AXPress")

    def choose(self, popup: Element, option: str) -> None:
        handle = _handle(popup)
        self._perform(handle, "AXPress")
        time.sleep(MENU_OPEN_SECONDS)
        menus = [m for m in self._attr(handle, "AXChildren") or () if self._attr(m, "AXRole") == "AXMenu"]
        items = [item for menu in menus for item in self._attr(menu, "AXChildren") or ()]
        matches = [item for item in items if self._attr(item, "AXTitle") == option]
        if len(matches) != 1:
            for menu in menus:
                AX.AXUIElementPerformAction(menu, "AXCancel")
            raise BackendError(f"pop-up has {len(matches)} options titled {option!r}")
        self._perform(matches[0], "AXPress")
        chosen = self.refresh(popup).value
        if chosen != option:
            raise BackendError(f"pop-up shows {chosen!r} after choosing {option!r}")

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
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0 or not whole.is_file():
                raise BackendError(f"window capture failed (Screen Recording permission?): {result.stderr.strip()}")
            with Image.open(whole) as image:
                image.crop(crop_box(window.bounds, area, image.width)).save(path)
        return path

    # Input events: only while Fakturama is frontmost.

    def click(self, element: Element) -> None:
        x, y = element.rect.center
        self._require_on_top(x, y)
        for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            Quartz.CGEventPost(
                Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
            )
            time.sleep(EVENT_PAUSE_SECONDS)

    def type_text(self, text: str) -> None:
        for char in text:
            self._guard()
            units = len(char.encode("utf-16-le")) // 2
            for down in (True, False):
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
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

    def copy_selection(self) -> str:
        board = NSPasteboard.generalPasteboard()
        saved = _save_clipboard(board)
        try:
            before = board.changeCount()
            self.key("primary+c")
            deadline = time.monotonic() + CLIPBOARD_TIMEOUT_SECONDS
            while board.changeCount() == before:
                if time.monotonic() > deadline:
                    raise BackendError("nothing was copied: is a row selected?")
                time.sleep(CLIPBOARD_POLL_SECONDS)
            return str(board.stringForType_("public.utf8-plain-text") or "")
        finally:
            _restore_clipboard(board, saved)

    # Helpers.

    def _guard(self) -> None:
        require_frontmost(self._pid, _frontmost_pid())

    def _require_on_top(self, x: float, y: float) -> None:
        self._guard()
        top = self._hit(AX.AXUIElementCreateSystemWide(), x, y)
        error, owner = AX.AXUIElementGetPid(top, None) if top is not None else (1, None)
        if error != AX_SUCCESS or owner != self._pid:
            raise UnsafeToAct(f"something else covers the target at ({x:.0f}, {y:.0f}); refusing to click")

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
        if self._attr(handle, "AXPosition") is not None:
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


def _frontmost_pid() -> int | None:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return None if app is None else int(app.processIdentifier())


def _handle(element: Element) -> object:
    if element.handle is None:
        raise BackendError("element was not read from the live app (no handle)")
    return element.handle


def _plain(value: object) -> str | None:
    """Text, numbers and booleans as text; references to other elements are dropped."""
    return str(value) if isinstance(value, (str, int, float)) else None


def _save_clipboard(board: NSPasteboard) -> list[dict[str, object]]:
    return [{kind: item.dataForType_(kind) for kind in item.types()} for item in board.pasteboardItems() or ()]


def _restore_clipboard(board: NSPasteboard, saved: list[dict[str, object]]) -> None:
    board.clearContents()
    items = []
    for kinds in saved:
        item = NSPasteboardItem.alloc().init()
        for kind, data in kinds.items():
            if data is not None:
                item.setData_forType_(data, kind)
        items.append(item)
    if items:
        board.writeObjects_(items)
