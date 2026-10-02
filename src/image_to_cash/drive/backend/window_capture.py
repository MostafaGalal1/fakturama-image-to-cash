"""Screenshots of Fakturama only: capture its window, then crop, so nothing on top can leak in.

A plain screen-region capture records whatever covers that region, such as another app's window
or a notification. Capturing the window itself records Fakturama's pixels even when it is covered.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from image_to_cash.drive.elements import Rect

NORMAL_WINDOW_LAYER = 0  # tooltips, menus and overlays sit on higher layers


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    pid: int
    layer: int
    bounds: Rect


def window_for(area: Rect, windows: Iterable[WindowInfo], pid: int) -> WindowInfo:
    """The smallest normal window of `pid` that fully contains `area`."""
    candidates = [w for w in windows if w.pid == pid and w.layer == NORMAL_WINDOW_LAYER and w.bounds.contains(area)]
    if not candidates:
        raise ValueError(f"no Fakturama window contains {area}")
    return min(candidates, key=lambda w: w.bounds.width * w.bounds.height)


def crop_box(window: Rect, area: Rect, image_width: int) -> tuple[int, int, int, int]:
    """`area` in the pixels of a capture of `window` that is `image_width` pixels wide."""
    scale = image_width / window.width
    return (
        round((area.x - window.x) * scale),
        round((area.y - window.y) * scale),
        round((area.right - window.x) * scale),
        round((area.bottom - window.y) * scale),
    )
