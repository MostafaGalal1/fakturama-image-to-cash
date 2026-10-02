"""Condition waits, never fixed sleeps (design §5): poll until the UI shows what the next step needs."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
DEFAULT_POLL_SECONDS = 0.2


class WaitTimeout(TimeoutError):
    """The UI never reached the expected state; the run stops."""


def wait_until(
    probe: Callable[[], T | None],
    *,
    what: str,
    timeout: float,
    poll: float = DEFAULT_POLL_SECONDS,
    ignoring: tuple[type[Exception], ...] = (),
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Return the first truthy result of `probe`. Errors in `ignoring` mean "not ready yet"."""
    deadline = clock() + timeout
    while True:
        try:
            result = probe()
        except ignoring:
            result = None
        if result:
            return result
        if clock() >= deadline:
            raise WaitTimeout(f"timed out after {timeout:g}s waiting for {what}")
        sleep(poll)
