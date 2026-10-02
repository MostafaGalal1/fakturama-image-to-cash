"""Never send input to the wrong app.

Mouse and keyboard events go to whichever app is frontmost. The bot brings Fakturama to the front
once, at the start of a run. After that it never re-activates it: if another app comes to the
front, someone else is using the Mac, and the run stops instead of fighting them for the keyboard.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from image_to_cash.drive.backend.base import BackendError, UnsafeToAct

H = TypeVar("H")  # an OS element reference

ACTIVATE_TIMEOUT_SECONDS = 2.0
ACTIVATE_POLL_SECONDS = 0.1
MAX_PARENT_DEPTH = 30


def require_frontmost(target_pid: int, frontmost_pid: int | None) -> None:
    if frontmost_pid == target_pid:
        return
    holder = "no app is frontmost" if frontmost_pid is None else f"pid {frontmost_pid} is frontmost"
    raise UnsafeToAct(f"{holder}, not Fakturama (pid {target_pid}); refusing to send input")


def wait_until_frontmost(
    target_pid: int,
    frontmost_pid: Callable[[], int | None],
    *,
    sleep: Callable[[float], None],
    timeout: float = ACTIVATE_TIMEOUT_SECONDS,
    poll: float = ACTIVATE_POLL_SECONDS,
) -> None:
    """After asking for activation: return once Fakturama is in front, or raise UnsafeToAct."""
    waited = 0.0
    while True:
        current = frontmost_pid()
        if current == target_pid:
            return
        if waited >= timeout:
            require_frontmost(target_pid, current)
        sleep(poll)
        waited += poll


def require_keyboard(
    target_pid: int, *, app_is_active: bool, front_window_pid: int | None, focused_app_pid: int | None
) -> None:
    """Fakturama must be the active app and own the front window, both read live.

    `focused_app_pid` is the system's answer to "who holds the keyboard focus", which catches a
    panel such as Spotlight that takes the keyboard without becoming active. That query often
    cannot complete right after a burst of accessibility calls; None means "no answer", and then
    the other two signals decide. An answer naming another app always stops input.
    """
    refusal = "refusing to send input"
    if focused_app_pid is not None and focused_app_pid != target_pid:
        raise UnsafeToAct(f"keyboard focus is held by pid {focused_app_pid}, not Fakturama (pid {target_pid}); {refusal}")
    if not app_is_active:
        raise UnsafeToAct(f"Fakturama is not the active app; {refusal}")
    if front_window_pid != target_pid:
        holder = "nothing" if front_window_pid is None else f"pid {front_window_pid}"
        raise UnsafeToAct(f"front window is held by {holder}, not Fakturama (pid {target_pid}); {refusal}")


def is_within(hit: H | None, target: H, parent_of: Callable[[H], H | None], max_depth: int = MAX_PARENT_DEPTH) -> bool:
    """True when the element under the pointer is the target or one of its descendants."""
    for _ in range(max_depth):
        if hit is None:
            return False
        if hit == target:
            return True
        hit = parent_of(hit)
    return False


def require_copied_text(copied: str | None) -> str:
    """An empty copy must never read as "the grid has no rows": that would create a duplicate."""
    if copied is None or not copied.strip():
        raise BackendError("no text was copied: is a row selected?")
    return copied
