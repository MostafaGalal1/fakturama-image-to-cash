"""Field writes as find → act → read back → confirm (design §5), with one retry before stopping."""

from __future__ import annotations

from collections.abc import Callable

from image_to_cash.drive.backend.base import FocusNotTaken, UiBackend
from image_to_cash.drive.elements import Element
from image_to_cash.errors import NeedsReview

ATTEMPTS = 2


def set_text(
    backend: UiBackend,
    field: Element,
    text: str,
    *,
    label: str,
    holds: Callable[[str], bool] | None = None,
    commit: str | None = "tab",
) -> Element:
    """Replace the field's text, commit it with Tab, and return the field as read back.

    `holds` decides whether the shown value means what was typed (an amount typed as '297,50'
    shows as '297,50 €'); by default it must equal the text exactly. The stop reason names the
    field, never the value, which may be personal data. `commit` is the key that leaves the
    field: None for a multi-line text area, where Tab would type a tab character.
    """
    accepts = holds or (lambda shown: shown == text)
    for _ in range(ATTEMPTS):
        try:
            backend.click(field)
        except FocusNotTaken:
            continue  # the click only activated the editor; nothing was typed, so click again
        backend.key("primary+a")
        backend.type_text(text)
        if commit:
            backend.key(commit)
        current = backend.refresh(field)
        if accepts(current.value or ""):
            return current
    raise NeedsReview("field_wont_hold", {"field": label})
