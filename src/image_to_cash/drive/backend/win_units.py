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


def menu_label(raw: str) -> str:
    """A Win32 menu item's text as a person reads it: "&Close All\\tCtrl+Shift+W" -> "Close All"."""
    text = raw.split("\t", 1)[0]
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()
