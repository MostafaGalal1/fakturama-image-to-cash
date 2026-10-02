"""Windows adapter: drives Fakturama through UI Automation (the `uiautomation` package) and Win32.

The same contract and safety rules as the macOS adapter (base.py, safety.py):
- Reading, pressing native buttons and running menu commands send no input, so they cannot reach
  another app. Menus run by command id (win32_api.menu_command) without opening.
- Clicks and keystrokes go through SendInput, which reaches whichever window has the focus, so
  each one is sent only while Fakturama owns the foreground window and the keyboard focus; a
  click only when the target itself is under the pointer; typing only while the clicked field
  still has the focus. Text is typed, never set through the Value pattern: like macOS's AXValue,
  that changes what the field shows without telling Fakturama.
- Screenshots capture Fakturama's window (PrintWindow), so nothing on top of it can leak in.

Frames are read in physical pixels (the process is per-monitor DPI aware) and handed to the flow
in 96-dpi points, as macOS does. One monitor scale per run: the main window's.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

from image_to_cash.drive.backend import win32_api as win32

win32.make_dpi_aware()  # before uiautomation reads any frame

import uiautomation as auto  # noqa: E402  (needs the DPI awareness set above)

from image_to_cash.drive.backend.base import BackendError, FocusNotTaken, UnsafeToAct  # noqa: E402
from image_to_cash.drive.backend.keys import parse_chord  # noqa: E402
from image_to_cash.drive.backend.safety import require_copied_text, require_keyboard, wait_until_frontmost  # noqa: E402
from image_to_cash.drive.backend.uia_roles import UiaRecord, element_from_uia  # noqa: E402
from image_to_cash.drive.backend.win_units import Scale  # noqa: E402
from image_to_cash.drive.backend.window_capture import NORMAL_WINDOW_LAYER, WindowInfo, crop_box, window_for  # noqa: E402
from image_to_cash.drive.elements import Element, Rect, Role, Window, distinct  # noqa: E402
from image_to_cash.drive.layout import WINDOWS_LAYOUT  # noqa: E402
from image_to_cash.drive.waits import WaitTimeout, wait_until  # noqa: E402

MAIN_TITLE_PREFIX = "Fakturama - "
TREE_DEPTH = 40  # SWT nests composites deeply
MAX_PARENT_DEPTH = 40
TYPE_PAUSE_SECONDS = 0.01
CLIPBOARD_TIMEOUT_SECONDS = 2.0
CLIPBOARD_POLL_SECONDS = 0.05
CLICK_SETTLE_SECONDS = 1.5
FOCUS_SETTLE_SECONDS = 1.0
LIST_OPEN_SECONDS = 2.0
TEXT_TYPES = frozenset({"Edit", "Document", "ComboBox"})
FOCUS_MOVING_KEYS = frozenset({"tab", "return", "escape"})
NOT_IN_SCANS = frozenset({Role.OTHER, Role.TAB_GROUP, Role.WINDOW})  # containers, as on macOS
STATE_SELECTED, STATE_CHECKED = 0x2, 0x10  # MSAA states


class WindowsUiaBackend:
    layout = WINDOWS_LAYOUT

    def __init__(self, pid: int, main_hwnd: int) -> None:
        win32.keep_display_on()
        self._pid = pid
        self._main_hwnd = main_hwnd
        self._scale = Scale.from_dpi(win32.window_dpi(main_hwnd))
        self._clicked: object | None = None  # the field that should hold keyboard focus for typing

    @classmethod
    def attach(cls) -> WindowsUiaBackend:
        mains = [w for w in win32.top_windows() if w.title.startswith(MAIN_TITLE_PREFIX)]
        if len(mains) != 1:
            raise BackendError(f"expected one running Fakturama main window, found {len(mains)}")
        return cls(mains[0].pid, mains[0].hwnd)

    def bring_to_front(self) -> None:
        """Called once, at the start of a run; afterwards losing the front stops the run."""
        win32.wake_display()
        win32.minimize_own_console()
        win32.bring_to_front(self._main_hwnd)
        wait_until_frontmost(self._pid, win32.foreground_pid, sleep=time.sleep)
        self._guard()

    # Reading, and actions that send no input: safe while someone else uses the PC.

    def windows(self) -> tuple[Window, ...]:
        return tuple(
            Window(w.title, self._points(w.left, w.top, w.right, w.bottom), w.hwnd)
            for w in win32.top_windows()
            if w.pid == self._pid and w.right > w.left and w.bottom > w.top
        )

    def press_menu(self, path: Sequence[str]) -> None:
        win32.run_command(self._main_hwnd, win32.menu_command(self._main_hwnd, path))

    def tree(self, window: Window) -> tuple[Element, ...]:
        found: list[Element] = []
        self._walk(auto.ControlFromHandle(window.handle), 0, found, None)
        return distinct(found)

    def scan(self, area: Rect) -> tuple[Element, ...]:
        """UI Automation lists every control, so a scan walks the window holding `area` and keeps
        the controls centred in it. Subtrees outside the area are skipped unread."""
        found: list[Element] = []
        self._walk(auto.ControlFromHandle(self._window_holding(area)), 0, found, area)
        kept = (e for e in distinct(found) if e.role not in NOT_IN_SCANS and area.holds(*e.rect.center))
        return tuple(sorted(kept, key=lambda e: (e.rect.y, e.rect.x)))

    def refresh(self, element: Element) -> Element:
        return self._element(_handle(element))

    def press(self, element: Element) -> None:
        """A native button (checkboxes too) gets a posted click, so a dialog it opens cannot block
        the bot; anything else its UI Automation action. Callers read every effect back."""
        handle = _handle(element)
        hwnd = _safe(lambda: handle.NativeWindowHandle) or 0
        if hwnd and win32.class_name(hwnd) == "Button":
            win32.post_click(hwnd)
            return
        for pattern, act in (
            (auto.PatternId.InvokePattern, lambda p: p.Invoke()),
            (auto.PatternId.TogglePattern, lambda p: p.Toggle()),
            (auto.PatternId.SelectionItemPattern, lambda p: p.Select()),
            (auto.PatternId.LegacyIAccessiblePattern, lambda p: p.DoDefaultAction()),
        ):
            found = _safe(lambda pattern=pattern: handle.GetPattern(pattern))
            if found is None:
                continue
            try:
                act(found)
            except Exception as error:  # comtypes' COMError: the element refused or closed
                raise BackendError(f"pressing the {element.native_role} failed: {error}") from error
            return
        raise BackendError(f"{element.native_role} offers no action to press")

    def focused(self) -> Element | None:
        handle = self._focused_control()
        return None if handle is None or not self._alive(handle) else self._element(handle)

    def element_at(self, x: float, y: float) -> Element | None:
        handle = self._hit(x, y)
        if handle is None or _safe(lambda: handle.ProcessId) != self._pid or not self._alive(handle):
            return None
        return self._element(handle)

    def capture(self, area: Rect, path: Path) -> Path:
        """Fakturama's own pixels only: the window holding `area` is captured, then cropped."""
        try:
            window = window_for(area, self._window_infos(), self._pid)
        except ValueError as error:
            raise BackendError(str(error)) from None
        path.parent.mkdir(parents=True, exist_ok=True)
        image = win32.capture_window(window.window_id)
        image.crop(crop_box(window.bounds, area, image.width)).save(path)
        return path

    # Input: only while Fakturama owns the foreground window and the keyboard focus.

    def focus(self, element: Element) -> None:
        handle = _handle(element)
        self._guard()
        _safe(handle.SetFocus)  # its return value is not trusted: the wait below reads the focus back
        self._clicked = handle
        try:
            wait_until(self._clicked_has_focus, what="the control to take the focus", timeout=FOCUS_SETTLE_SECONDS, poll=0.05)
        except WaitTimeout:
            raise UnsafeToAct("the control did not take the keyboard focus") from None

    def choose(self, popup: Element, option: str) -> None:
        """Opens the drop-down and clicks the option, as a person would: selecting it through UI
        Automation would change the display without telling Fakturama."""
        if _same_option(self.refresh(popup).value, option):
            return
        handle = _handle(popup)
        items = self._open_list(handle)
        try:
            matches = [item for item in items if _same_option(_safe(lambda item=item: item.Name), option)]
            if len(matches) != 1:
                raise BackendError(f"pop-up has {len(matches)} options titled {option!r}")
            scroll = _safe(lambda: matches[0].GetPattern(auto.PatternId.ScrollItemPattern))
            if scroll is not None:
                _safe(scroll.ScrollIntoView)  # a long list (countries) shows only some; the click checks it is on top
            self.click(self._element(matches[0]))
        except BaseException:
            self._close_list(handle)
            raise
        try:
            wait_until(lambda: _same_option(self.refresh(popup).value, option), what=f"the pop-up to show {option!r}", timeout=2)
        except WaitTimeout:
            raise BackendError(f"pop-up shows {self.refresh(popup).value!r} after choosing {option!r}") from None

    def options(self, popup: Element) -> tuple[str, ...]:
        handle = _handle(popup)
        items = self._open_list(handle)
        try:
            names = (_safe(lambda item=item: item.Name) for item in items)
            return tuple(name.strip() for name in names if name and name.strip())
        finally:
            self._close_list(handle)

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
        self._guard()
        win32.click_at(*self._scale.to_pixels(x, y), count)
        self._clicked = handle
        if _native(handle) in TEXT_TYPES:
            try:
                wait_until(self._clicked_has_focus, what="the field to take the focus", timeout=FOCUS_SETTLE_SECONDS, poll=0.05)
            except WaitTimeout:
                raise FocusNotTaken("the clicked field did not take the keyboard focus") from None

    def type_text(self, text: str) -> None:
        if self._clicked is not None:
            try:
                wait_until(self._clicked_has_focus, what="the field to take the focus", timeout=FOCUS_SETTLE_SECONDS, poll=0.05)
            except WaitTimeout:
                raise FocusNotTaken("the clicked field never took the keyboard focus; nothing was typed") from None
        for char in text:
            self._guard_typing()
            win32.type_character(char)
            time.sleep(TYPE_PAUSE_SECONDS)

    def key(self, chord: str) -> None:
        parsed = parse_chord(chord)
        self._guard()
        win32.press_chord(parsed)
        if parsed.key in FOCUS_MOVING_KEYS:
            self._clicked = None

    def paste_text(self, text: str, into: Element) -> None:
        saved = win32.save_clipboard()
        try:
            win32.set_clipboard_text(text)
            self.key("primary+v")
            # Restore only once the field shows the text, or once it is gone: a selector that
            # auto-accepts a single hit closes at once.
            handle = _handle(into)
            wait_until(
                lambda: not self._alive(handle) or self.refresh(into).value == text,
                what="the pasted text",
                timeout=CLIPBOARD_TIMEOUT_SECONDS,
            )
        finally:
            if not win32.restore_clipboard(saved):
                raise BackendError("pasted the text, but could not restore the clipboard")

    def copy_selection(self) -> str:
        saved = win32.save_clipboard()
        try:
            before = win32.clipboard_sequence()
            self.key("primary+c")
            wait_until(
                lambda: win32.clipboard_sequence() != before,
                what="the copy to reach the clipboard",
                timeout=CLIPBOARD_TIMEOUT_SECONDS,
                poll=CLIPBOARD_POLL_SECONDS,
            )
            self._guard()  # still Fakturama's copy, not something a person copied meanwhile
            copied = require_copied_text(win32.clipboard_text())
        except BaseException:
            win32.restore_clipboard(saved)  # best effort: the copy's own error matters more
            raise
        if not win32.restore_clipboard(saved):
            raise BackendError("copied the grid, but could not restore the clipboard")
        return copied

    # Helpers.

    def _guard(self) -> None:
        front = win32.foreground_pid()
        require_keyboard(self._pid, app_is_active=front == self._pid, front_window_pid=front, focused_app_pid=self._focused_pid())

    def _guard_typing(self) -> None:
        """Typing also needs the clicked field to still hold the keyboard focus."""
        self._guard()
        if self._clicked is not None and not self._clicked_has_focus():
            raise UnsafeToAct("keyboard focus moved away from the field that was clicked; refusing to type")

    def _focused_control(self) -> object | None:
        return _safe(auto.GetFocusedControl)

    def _focused_pid(self) -> int | None:
        handle = self._focused_control()
        return None if handle is None else _safe(lambda: handle.ProcessId)

    def _clicked_has_focus(self) -> bool:
        return self._clicked is not None and _is_within(self._focused_control(), self._clicked)

    def _on_top(self, handle: object, x: float, y: float) -> bool:
        hit = self._hit(x, y)
        return _is_within(hit, handle) or _draws(hit, handle)

    def _hit(self, x: float, y: float) -> object | None:
        return _safe(lambda: auto.ControlFromPoint(*self._scale.to_pixels(x, y)))

    def _open_list(self, handle: object) -> list[object]:
        self._guard()
        expand = _safe(lambda: handle.GetPattern(auto.PatternId.ExpandCollapsePattern))
        if expand is None:
            raise BackendError("the pop-up cannot be opened")
        try:
            expand.Expand()
        except Exception as error:  # comtypes' COMError
            raise BackendError(f"the pop-up did not open: {error}") from error
        try:
            return wait_until(lambda: self._list_items(handle), what="the pop-up list", timeout=LIST_OPEN_SECONDS, poll=0.1)
        except WaitTimeout:
            self._close_list(handle)
            raise BackendError("the pop-up list did not open") from None

    def _close_list(self, handle: object) -> None:
        expand = _safe(lambda: handle.GetPattern(auto.PatternId.ExpandCollapsePattern))
        if expand is not None:
            _safe(expand.Collapse)  # never leave a drop-down holding the keyboard

    def _list_items(self, handle: object) -> list[object]:
        items: list[object] = []
        stack = list(_safe(handle.GetChildren) or ())
        while stack:
            child = stack.pop()
            if _native(child) == "ListItem":
                items.append(child)
            else:
                stack.extend(_safe(child.GetChildren) or ())
        return items

    def _walk(self, handle: object, depth: int, found: list[Element], area: Rect | None) -> None:
        if handle is None or _hidden(handle):
            return
        try:
            rect = self._rect(handle)
        except BackendError:
            rect = None
        if rect is not None:
            if area is not None and not _overlaps(rect, area):
                return
            found.append(self._element(handle, rect))
        if depth < TREE_DEPTH:
            for child in _safe(handle.GetChildren) or ():
                self._walk(child, depth + 1, found, area)

    def _element(self, handle: object, rect: Rect | None = None) -> Element:
        native = _native(handle)
        record = UiaRecord(
            control_type=native,
            rect=rect or self._rect(handle),
            name=_safe(lambda: handle.Name),
            value=self._value(handle, native),
            help=_help(handle) or (_safe(lambda: handle.Name) if _in_toolbar(handle) else None),
            enabled=bool(_safe(lambda: handle.IsEnabled)),
            multiline=native == "Edit" and _multiline(handle),
            editable=native == "ComboBox" and any(_native(c) == "Edit" for c in _safe(handle.GetChildren) or ()),
            toggled=_toggled(handle) if native == "CheckBox" else None,
            selected=_selected(handle) if native in ("RadioButton", "TabItem") else None,
        )
        return element_from_uia(record, handle)

    def _value(self, handle: object, native: str) -> str | None:
        if native not in TEXT_TYPES:
            return None
        value = _safe(lambda: handle.GetPattern(auto.PatternId.ValuePattern).Value)
        if value is None and native == "ComboBox":
            chosen = _safe(lambda: handle.GetPattern(auto.PatternId.SelectionPattern).GetSelection())
            value = _safe(lambda: chosen[0].Name) if chosen else None
        if value is None:
            value = _safe(lambda: handle.GetPattern(auto.PatternId.LegacyIAccessiblePattern).Value)
        return value

    def _rect(self, handle: object) -> Rect:
        frame = _frame(handle)
        if frame is None:
            raise BackendError("element has no frame (it may have closed)")
        if not _safe(lambda: handle.NativeWindowHandle):  # windowless: SWT may report it in points
            parent = _frame(_safe(handle.GetParentControl))
            frame = frame if parent is None else self._scale.child_frame(frame, parent)
        return self._points(*frame)

    def _points(self, left: float, top: float, right: float, bottom: float) -> Rect:
        return self._scale.to_points(left, top, right, bottom)

    def _alive(self, handle: object) -> bool:
        try:
            self._rect(handle)
        except BackendError:
            return False
        return True

    def _window_infos(self) -> tuple[WindowInfo, ...]:
        return tuple(
            WindowInfo(w.hwnd, w.pid, NORMAL_WINDOW_LAYER, self._points(w.left, w.top, w.right, w.bottom))
            for w in win32.top_windows()
            if w.right > w.left and w.bottom > w.top
        )

    def _window_holding(self, area: Rect) -> int:
        try:
            return window_for(area, self._window_infos(), self._pid).window_id
        except ValueError:
            return self._main_hwnd


def _handle(element: Element) -> object:
    if element.handle is None:
        raise BackendError("element was not read from the live app (no handle)")
    return element.handle


def _safe(read: Callable[[], object]) -> object | None:
    """A UI Automation read, or None when the element is gone or does not support it."""
    try:
        return read()
    except Exception:  # comtypes' COMError and friends: the answer is "not available"
        return None


def _frame(handle: object | None) -> tuple[float, float, float, float] | None:
    frame = None if handle is None else _safe(lambda: handle.BoundingRectangle)
    if frame is None or frame.right <= frame.left or frame.bottom <= frame.top:
        return None
    return frame.left, frame.top, frame.right, frame.bottom


def _hidden(handle: object) -> bool:
    """A control in a hidden window (an unselected tab's page). Not IsOffscreen: SWT's tab folders
    claim to be offscreen while shown."""
    hwnd = _safe(lambda: handle.NativeWindowHandle)
    return bool(hwnd) and not win32.is_visible(hwnd)


def _in_toolbar(handle: object) -> bool:
    """A toolbar button, whose UI Automation name is its tooltip."""
    if _native(handle) not in ("Button", "SplitButton") or _safe(lambda: handle.NativeWindowHandle):
        return False
    parent = _safe(handle.GetParentControl)
    return parent is not None and _safe(lambda: parent.ClassName) == "ToolbarWindow32"


def _native(handle: object) -> str:
    return str(_safe(lambda: handle.ControlTypeName) or "").removesuffix("Control")


def _help(handle: object) -> str | None:
    """SWT's tooltip, wherever this Windows version exposes it."""
    legacy = _safe(lambda: handle.GetPattern(auto.PatternId.LegacyIAccessiblePattern))
    for read in (lambda: handle.HelpText, lambda: legacy.Description, lambda: legacy.Help):
        text = _safe(read)
        if text:
            return str(text)
    return None


def _multiline(handle: object) -> bool:
    hwnd = _safe(lambda: handle.NativeWindowHandle)
    return bool(hwnd) and win32.is_multiline(hwnd)


def _toggled(handle: object) -> int | None:
    state = _safe(lambda: handle.GetPattern(auto.PatternId.TogglePattern).ToggleState)
    if state is not None:
        return int(state)
    legacy = _safe(lambda: handle.GetPattern(auto.PatternId.LegacyIAccessiblePattern).State)
    return None if legacy is None else int(bool(legacy & STATE_CHECKED))


def _selected(handle: object) -> bool | None:
    selected = _safe(lambda: handle.GetPattern(auto.PatternId.SelectionItemPattern).IsSelected)
    if selected is not None:
        return bool(selected)
    legacy = _safe(lambda: handle.GetPattern(auto.PatternId.LegacyIAccessiblePattern).State)
    return None if legacy is None else bool(legacy & (STATE_SELECTED | STATE_CHECKED))


def _is_within(hit: object | None, target: object) -> bool:
    """True when the element under the pointer (or holding the focus) is the target or inside it."""
    for _ in range(MAX_PARENT_DEPTH):
        if hit is None:
            return False
        if _safe(lambda hit=hit: auto.ControlsAreSame(hit, target)):
            return True
        hit = _safe(hit.GetParentControl)
    return False


def _draws(hit: object | None, target: object) -> bool:
    """True when the hit is the window that draws a windowless target. UI Automation reports the
    tab folder under the pointer, not the tab it points at."""
    if hit is None or _safe(lambda: target.NativeWindowHandle):
        return False
    parent = _safe(target.GetParentControl)
    return parent is not None and bool(_safe(lambda: auto.ControlsAreSame(hit, parent)))


def _overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def _same_option(shown: object, option: str) -> bool:
    return isinstance(shown, str) and shown.strip() == option.strip()
