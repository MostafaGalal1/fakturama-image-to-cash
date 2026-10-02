"""Pure helpers for the Windows adapter, kept apart so they are tested on any OS."""

from __future__ import annotations

from dataclasses import dataclass

from image_to_cash.drive.elements import Rect

BASE_DPI = 96  # Windows' 100 % scale


@dataclass(frozen=True)
class Scale:
    """Physical pixels per point. The adapter is per-monitor DPI aware, so UI Automation frames and
    mouse positions are physical pixels; the flow works in 96-dpi points, as on macOS."""

    factor: float

    @classmethod
    def from_dpi(cls, dpi: int) -> Scale:
        if dpi <= 0:
            raise ValueError(f"impossible DPI {dpi}")
        return cls(dpi / BASE_DPI)

    def to_points(self, left: float, top: float, right: float, bottom: float) -> Rect:
        f = self.factor
        return Rect(left / f, top / f, (right - left) / f, (bottom - top) / f)

    def to_pixels(self, x: float, y: float) -> tuple[int, int]:
        return round(x * self.factor), round(y * self.factor)

    def child_frame(self, child: Frame, parent: Frame) -> Frame:
        """A windowless child's frame in pixels. SWT reports some (a tab folder's tabs) in points
        when the screen is scaled: such a frame fits its parent only once scaled."""
        if _inside(child, parent):
            return child
        scaled = tuple(round(value * self.factor) for value in child)
        return scaled if _inside(scaled, parent) else child


Frame = tuple[float, float, float, float]  # left, top, right, bottom


def _inside(child: Frame, parent: Frame) -> bool:
    return parent[0] <= child[0] and parent[1] <= child[1] and child[2] <= parent[2] and child[3] <= parent[3]


@dataclass(frozen=True)
class DoubleClick:
    """Two clicks closer than this, in seconds and in pixels either way, make a double click."""

    seconds: float
    reach: int

    def wait_before(self, last: tuple[float, int, int] | None, now: float, x: int, y: int) -> float:
        """Seconds to wait so a single click at (x, y) is not read as the second half of a double
        click with the `last` one (time, x, y): the selector's row would then be accepted."""
        if last is None:
            return 0.0
        then, last_x, last_y = last
        if abs(x - last_x) > self.reach or abs(y - last_y) > self.reach:
            return 0.0
        return max(0.0, then + self.seconds - now)


def focus_owner(pid: int | None) -> int | None:
    """The process holding the keyboard focus. UI Automation answers pid 0 (the desktop) while no
    window holds it, as right after a dialog closes itself: that is no answer, not another app."""
    return pid or None


def menu_label(raw: str) -> str:
    """A Win32 menu item's text as a person reads it: "&Close All\\tCtrl+Shift+W" -> "Close All"."""
    text = raw.split("\t", 1)[0]
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()
