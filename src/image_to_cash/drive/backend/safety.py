"""Never send input to the wrong app.

Mouse and keyboard events go to whichever app is frontmost. The bot brings Fakturama to the front
once, at the start of a run. After that it never re-activates it: if another app comes to the
front, someone else is using the Mac, and the run stops instead of fighting them for the keyboard.
"""

from __future__ import annotations

from collections.abc import Callable

from image_to_cash.drive.backend.base import UnsafeToAct

ACTIVATE_TIMEOUT_SECONDS = 2.0
ACTIVATE_POLL_SECONDS = 0.1


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
