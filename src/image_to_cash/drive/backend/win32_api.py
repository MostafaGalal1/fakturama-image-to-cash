"""The Win32 calls the Windows adapter needs, through ctypes: windows, input, clipboard, menus,
window capture. Windows only; imported by windows_uia.py alone.
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass

from PIL import Image

from image_to_cash.drive.backend.base import BackendError
from image_to_cash.drive.backend.keys import WIN_EXTENDED_KEYS, WIN_MODIFIER_VK, WIN_VK_CODES, Chord
from image_to_cash.drive.backend.win_units import BASE_DPI, DoubleClick, menu_label

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SW_RESTORE = 9
GWL_STYLE = -16
ES_MULTILINE = 0x0004
BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
WM_INITMENUPOPUP = 0x0117
MF_BYPOSITION = 0x0400
MF_GRAYED, MF_DISABLED = 0x0001, 0x0002
NO_COMMAND = 0xFFFFFFFF  # GetMenuItemID's answer for an item that opens a submenu
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_MOVE = 0x0001
GA_ROOTOWNER, SW_MINIMIZE = 3, 6
SM_CXDOUBLECLK, SM_CYDOUBLECLK = 36, 37
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
CF_UNICODETEXT = 13
NOT_MEMORY_FORMATS = frozenset({2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E})  # GDI handles, not memory blocks
GMEM_MOVEABLE = 0x0002
HWND_MESSAGE = -3
PW_RENDERFULLCONTENT = 0x00000002
CLIPBOARD_OPEN_SECONDS = 1.0
CLICK_PAUSE_SECONDS = 0.03


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3))


def _signatures() -> None:
    """Pointer-sized handles must not be truncated to 32 bits on 64-bit Windows."""
    H, P = wintypes.HANDLE, ctypes.c_void_p
    for name, args, result in (
        ("EnumWindows", (WNDENUMPROC, wintypes.LPARAM), wintypes.BOOL),
        ("IsWindowVisible", (wintypes.HWND,), wintypes.BOOL),
        ("IsIconic", (wintypes.HWND,), wintypes.BOOL),
        ("GetWindowThreadProcessId", (wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD),
        ("GetWindowTextLengthW", (wintypes.HWND,), ctypes.c_int),
        ("GetWindowTextW", (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
        ("GetClassNameW", (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
        ("GetWindowRect", (wintypes.HWND, ctypes.POINTER(wintypes.RECT)), wintypes.BOOL),
        ("GetWindowLongW", (wintypes.HWND, ctypes.c_int), wintypes.LONG),
        ("GetForegroundWindow", (), wintypes.HWND),
        ("SetForegroundWindow", (wintypes.HWND,), wintypes.BOOL),
        ("BringWindowToTop", (wintypes.HWND,), wintypes.BOOL),
        ("ShowWindow", (wintypes.HWND, ctypes.c_int), wintypes.BOOL),
        ("AttachThreadInput", (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL), wintypes.BOOL),
        ("GetDpiForWindow", (wintypes.HWND,), wintypes.UINT),
        ("SendInput", (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int), wintypes.UINT),
        ("SetCursorPos", (ctypes.c_int, ctypes.c_int), wintypes.BOOL),
        ("PostMessageW", (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), wintypes.BOOL),
        ("SendMessageW", (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), wintypes.LPARAM),
        ("GetMenu", (wintypes.HWND,), wintypes.HMENU),
        ("GetSubMenu", (wintypes.HMENU, ctypes.c_int), wintypes.HMENU),
        ("GetMenuItemCount", (wintypes.HMENU,), ctypes.c_int),
        ("GetMenuItemID", (wintypes.HMENU, ctypes.c_int), wintypes.UINT),
        ("GetMenuState", (wintypes.HMENU, wintypes.UINT, wintypes.UINT), wintypes.UINT),
        ("GetMenuStringW", (wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT), ctypes.c_int),
        ("OpenClipboard", (wintypes.HWND,), wintypes.BOOL),
        ("CloseClipboard", (), wintypes.BOOL),
        ("EmptyClipboard", (), wintypes.BOOL),
        ("EnumClipboardFormats", (wintypes.UINT,), wintypes.UINT),
        ("GetClipboardData", (wintypes.UINT,), H),
        ("SetClipboardData", (wintypes.UINT, H), H),
        ("GetClipboardSequenceNumber", (), wintypes.DWORD),
        ("GetMessageW", (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT), wintypes.BOOL),
        ("TranslateMessage", (ctypes.POINTER(wintypes.MSG),), wintypes.BOOL),
        ("DispatchMessageW", (ctypes.POINTER(wintypes.MSG),), ctypes.c_ssize_t),
        ("GetAncestor", (wintypes.HWND, wintypes.UINT), wintypes.HWND),
        ("GetDoubleClickTime", (), wintypes.UINT),
        ("GetSystemMetrics", (ctypes.c_int,), ctypes.c_int),
        ("CreateWindowExW", (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID), wintypes.HWND),
        ("GetWindowDC", (wintypes.HWND,), wintypes.HDC),
        ("ReleaseDC", (wintypes.HWND, wintypes.HDC), ctypes.c_int),
        ("PrintWindow", (wintypes.HWND, wintypes.HDC, wintypes.UINT), wintypes.BOOL),
    ):  # fmt: skip
        function = getattr(user32, name)
        function.argtypes, function.restype = args, result
    for name, args, result in (
        ("GlobalAlloc", (wintypes.UINT, ctypes.c_size_t), H),
        ("GlobalLock", (H,), P),
        ("GlobalUnlock", (H,), wintypes.BOOL),
        ("GlobalSize", (H,), ctypes.c_size_t),
        ("GlobalFree", (H,), H),
        ("GetCurrentThreadId", (), wintypes.DWORD),
    ):
        function = getattr(kernel32, name)
        function.argtypes, function.restype = args, result
    for name, args, result in (
        ("CreateCompatibleDC", (wintypes.HDC,), wintypes.HDC),
        ("CreateCompatibleBitmap", (wintypes.HDC, ctypes.c_int, ctypes.c_int), wintypes.HBITMAP),
        ("SelectObject", (wintypes.HDC, wintypes.HGDIOBJ), wintypes.HGDIOBJ),
        ("DeleteObject", (wintypes.HGDIOBJ,), wintypes.BOOL),
        ("DeleteDC", (wintypes.HDC,), wintypes.BOOL),
        ("GetDIBits", (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                       ctypes.POINTER(BITMAPINFO), wintypes.UINT), ctypes.c_int),
    ):  # fmt: skip
        function = getattr(gdi32, name)
        function.argtypes, function.restype = args, result


_signatures()


# DPI.


def keep_display_on() -> None:
    """Asks Windows to keep the display on and the PC awake while this process runs, as a video
    player does; it changes no setting. Input does not reach a switched-off or locked screen."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
    request = kernel32.SetThreadExecutionState
    request.argtypes, request.restype = (wintypes.DWORD,), wintypes.DWORD
    if not request(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED):
        raise BackendError("Windows refused to keep the display on")


def make_dpi_aware() -> None:
    """Per-monitor DPI awareness, so frames and mouse positions are physical pixels. Called before
    anything reads a frame; an earlier caller (a library) may have set it already, which is fine."""
    try:
        context = user32.SetProcessDpiAwarenessContext
        context.argtypes, context.restype = (ctypes.c_void_p,), wintypes.BOOL
        if context(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except AttributeError:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def window_dpi(hwnd: int) -> int:
    return int(user32.GetDpiForWindow(hwnd)) or BASE_DPI


# Windows.


@dataclass(frozen=True)
class TopWindow:
    hwnd: int
    pid: int
    title: str
    left: int
    top: int
    right: int
    bottom: int


def top_windows() -> tuple[TopWindow, ...]:
    """Every visible top-level window, front to back."""
    handles: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        if hwnd and user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(visit), 0)
    return tuple(_describe(hwnd) for hwnd in handles)


def _describe(hwnd: int) -> TopWindow:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    return TopWindow(int(hwnd), pid_of(hwnd), title.value, rect.left, rect.top, rect.right, rect.bottom)


def pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def foreground_pid() -> int | None:
    hwnd = user32.GetForegroundWindow()
    return pid_of(hwnd) if hwnd else None


def bring_to_front(hwnd: int) -> None:
    """Windows lets a background process raise a window only while its input is attached to the
    foreground window's thread."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    front = user32.GetForegroundWindow()
    front_thread = user32.GetWindowThreadProcessId(front, None) if front else 0
    own_thread = kernel32.GetCurrentThreadId()
    attached = bool(front_thread) and front_thread != own_thread and bool(user32.AttachThreadInput(own_thread, front_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(own_thread, front_thread, False)


def class_name(hwnd: int) -> str:
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, 256)
    return name.value


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_multiline(hwnd: int) -> bool:
    return bool(user32.GetWindowLongW(hwnd, GWL_STYLE) & ES_MULTILINE)


def post_click(hwnd: int) -> None:
    """A native button's own click, posted so a dialog it opens cannot block the caller."""
    if not user32.PostMessageW(hwnd, BM_CLICK, 0, 0):
        raise BackendError(f"posting a click to the button failed (error {ctypes.get_last_error()})")


# Menus: found by their text in the window's menu bar and run by command id, without opening them.


def menu_command(hwnd: int, path: Sequence[str]) -> int:
    """The command id of a menu-bar item such as ("Data", "Documents"). Each submenu is announced
    first (WM_INITMENUPOPUP): SWT fills Eclipse's menus only when they are about to open."""
    menu = user32.GetMenu(hwnd)
    if not menu:
        raise BackendError("Fakturama's window has no menu bar")
    where = " > ".join(path)
    for depth, title in enumerate(path):
        index = _menu_index(menu, title, where)
        if user32.GetMenuState(menu, index, MF_BYPOSITION) & (MF_GRAYED | MF_DISABLED):
            raise BackendError(f"menu {where}: {title!r} is disabled")
        if depth == len(path) - 1:
            command = user32.GetMenuItemID(menu, index)
            if command == NO_COMMAND:
                raise BackendError(f"menu {where}: {title!r} opens a submenu")
            return int(command)
        submenu = user32.GetSubMenu(menu, index)
        if not submenu:
            raise BackendError(f"menu {where}: {title!r} has no submenu")
        user32.SendMessageW(hwnd, WM_INITMENUPOPUP, submenu, index)
        menu = submenu
    raise BackendError("empty menu path")


def run_command(hwnd: int, command: int) -> None:
    """Posted, not sent: a dialog the command opens must not block the caller."""
    if not user32.PostMessageW(hwnd, WM_COMMAND, command & 0xFFFF, 0):
        raise BackendError(f"posting the menu command failed (error {ctypes.get_last_error()})")


def _menu_index(menu: int, title: str, where: str) -> int:
    matches = [index for index in range(user32.GetMenuItemCount(menu)) if menu_label(_menu_text(menu, index)) == title]
    if len(matches) != 1:
        raise BackendError(f"menu {where}: {len(matches)} items titled {title!r}")
    return matches[0]


def _menu_text(menu: int, index: int) -> str:
    length = user32.GetMenuStringW(menu, index, None, 0, MF_BYPOSITION)
    text = ctypes.create_unicode_buffer(length + 1)
    user32.GetMenuStringW(menu, index, text, length + 1, MF_BYPOSITION)
    return text.value


# Input: SendInput reaches whichever window has the focus, so the adapter guards every call.


def press_chord(chord: Chord) -> None:
    modifiers = sorted({WIN_MODIFIER_VK[modifier] for modifier in chord.modifiers})
    key = WIN_VK_CODES[chord.key]
    extended = KEYEVENTF_EXTENDEDKEY if chord.key in WIN_EXTENDED_KEYS else 0
    _send(
        *(_key(modifier) for modifier in modifiers),
        _key(key, flags=extended),
        _key(key, flags=extended | KEYEVENTF_KEYUP),
        *(_key(modifier, flags=KEYEVENTF_KEYUP) for modifier in reversed(modifiers)),
    )


def type_character(char: str) -> None:
    """One character as Unicode input, independent of the keyboard layout."""
    raw = char.encode("utf-16-le")
    units = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]
    _send(
        *(_key(scan=unit, flags=KEYEVENTF_UNICODE) for unit in units),
        *(_key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP) for unit in units),
    )


def double_click_limits() -> DoubleClick:
    """How close in time and place two clicks must be for Windows to make them a double click."""
    reach = max(user32.GetSystemMetrics(SM_CXDOUBLECLK), user32.GetSystemMetrics(SM_CYDOUBLECLK)) // 2
    return DoubleClick(seconds=user32.GetDoubleClickTime() / 1000, reach=reach)


def click_at(x: int, y: int, count: int) -> None:
    """`count` left clicks at a physical pixel; two in a row make a double click."""
    if not user32.SetCursorPos(x, y):
        raise BackendError(f"moving the pointer failed (error {ctypes.get_last_error()})")
    for _ in range(count):
        _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
        time.sleep(CLICK_PAUSE_SECONDS)


def minimize_own_console() -> None:
    """Minimizes the terminal this bot runs in, so it cannot cover Fakturama. Windows Terminal
    owns the console's pseudo window: its root owner is the window a person sees."""
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    console = kernel32.GetConsoleWindow()
    if not console:
        return
    for hwnd in {console, user32.GetAncestor(console, GA_ROOTOWNER)} - {None, 0}:
        user32.ShowWindow(hwnd, SW_MINIMIZE)


def wake_display() -> None:
    """Turns a switched-off display back on with a pointer move of zero: nothing moves, nothing
    is clicked. Keeping it on is not enough once it is off."""
    _send(_mouse(MOUSEEVENTF_MOVE))


def _key(vk: int = 0, *, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))


def _mouse(flags: int) -> INPUT:
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(dwFlags=flags)))


def _send(*events: INPUT) -> None:
    batch = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), batch, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise BackendError(f"SendInput delivered {sent} of {len(events)} events (error {ctypes.get_last_error()})")


# Clipboard: saved before the bot uses it and restored after, so a person's copy survives.

_clipboard_owner: int | None = None


def clipboard_sequence() -> int:
    return int(user32.GetClipboardSequenceNumber())


def save_clipboard() -> tuple[tuple[int, bytes], ...]:
    with _clipboard():
        formats, current = [], user32.EnumClipboardFormats(0)
        while current:
            formats.append(current)
            current = user32.EnumClipboardFormats(current)
        saved = []
        for kind in formats:
            if kind in NOT_MEMORY_FORMATS:
                continue  # Windows derives the bitmap formats again from the saved DIB
            handle = user32.GetClipboardData(kind)
            data = _read_global(handle) if handle else None
            if data is not None:
                saved.append((kind, data))
        return tuple(saved)


def restore_clipboard(saved: tuple[tuple[int, bytes], ...]) -> bool:
    with _clipboard():
        if not user32.EmptyClipboard():
            return False
        return all([_write_global(kind, data) for kind, data in saved])  # noqa: C419  every format is written, even after a failure


def set_clipboard_text(text: str) -> None:
    with _clipboard():
        user32.EmptyClipboard()
        if not _write_global(CF_UNICODETEXT, (text + "\0").encode("utf-16-le")):
            raise BackendError("could not put the text on the clipboard")


def clipboard_text() -> str | None:
    with _clipboard():
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        data = _read_global(handle) if handle else None
    return None if data is None else data.decode("utf-16-le", errors="replace").split("\0", 1)[0]


@contextmanager
def _clipboard() -> Iterator[None]:
    deadline = time.monotonic() + CLIPBOARD_OPEN_SECONDS
    while not user32.OpenClipboard(_owner()):
        if time.monotonic() > deadline:
            raise BackendError("the clipboard stayed busy: another app holds it open")
        time.sleep(0.02)
    try:
        yield
    finally:
        user32.CloseClipboard()


def _owner() -> int:
    """A hidden message-only window to own the clipboard: with no owner, SetClipboardData can fail.
    It lives on its own thread, which answers its messages at once: whoever empties the clipboard
    next (Fakturama copying, Parallels syncing) waits for the owner's reply while holding the
    clipboard open, so an owner that never answered would leave the clipboard locked."""
    global _clipboard_owner
    if _clipboard_owner is None:
        ready: list[int] = []
        created = threading.Event()
        threading.Thread(target=_run_owner, args=(ready, created), name="clipboard-owner", daemon=True).start()
        if not created.wait(5) or not ready[0]:
            raise BackendError(f"could not create the clipboard window (error {ready[1] if len(ready) > 1 else 'timeout'})")
        _clipboard_owner = ready[0]
    return _clipboard_owner


def _run_owner(ready: list[int], created: threading.Event) -> None:
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
    ready.extend((int(hwnd or 0), ctypes.get_last_error()))
    created.set()
    if not hwnd:
        return
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))


def _read_global(handle: int) -> bytes | None:
    size = kernel32.GlobalSize(handle)
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        kernel32.GlobalUnlock(handle)


def _write_global(kind: int, data: bytes) -> bool:
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(kind, handle):
        kernel32.GlobalFree(handle)
        return False
    return True  # the clipboard owns the memory now


# Capture: the window's own pixels, even where another window covers it.


def capture_window(hwnd: int) -> Image.Image:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise BackendError("the window to capture is gone")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    try:
        previous = gdi32.SelectObject(memory_dc, bitmap)
        printed = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        gdi32.SelectObject(memory_dc, previous)  # GetDIBits needs the bitmap out of the DC
        if not printed:
            raise BackendError("PrintWindow failed")
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height  # top-down rows
        info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(info), 0) != height:
            raise BackendError("reading the captured pixels failed")
        return Image.frombuffer("RGB", (width, height), pixels.raw, "raw", "BGRX", 0, 1).copy()
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
