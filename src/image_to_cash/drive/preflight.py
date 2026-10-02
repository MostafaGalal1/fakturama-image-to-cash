"""Checks before the bot touches Fakturama (design §6, stage 0).

order.json is re-validated because a person may have edited it. Stage 1 only lets EUR orders
through, and order.json carries no currency, so Fakturama itself must book in euros: its
currency locale has to be a euro-area country.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.normalized import NormalizedOrder
from image_to_cash.readers.base import describe_validation_error

CURRENCY_LOCALE_KEY = "PREFERENCE_CURRENCY_LOCALE"
FAKTURAMA_PREFS = (
    Path.home()
    / ".fakturama2/.metadata/.plugins/org.eclipse.core.runtime/.settings/com.sebulli.fakturama.rcp.prefs"
)
EURO_COUNTRIES = frozenset(
    "AT BE CY DE EE ES FI FR GR HR IE IT LT LU LV MT NL PT SI SK".split()
)


def load_order(path: Path) -> NormalizedOrder:
    """Raises OSError when unreadable, ValueError (without the file's values) when invalid."""
    text = path.read_text(encoding="utf-8")
    try:
        return NormalizedOrder.model_validate_json(text)
    except ValidationError as error:
        raise ValueError(f"{path} is not a valid order.json: {describe_validation_error(error)}") from None


def currency_locale(prefs_text: str) -> str | None:
    """The currency locale from Fakturama's Java-properties preference file, e.g. 'de/DE'."""
    for line in prefs_text.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip() == CURRENCY_LOCALE_KEY:
            return re.sub(r"\\(.)", r"\1", value.strip()) or None
    return None


def check_currency(prefs_path: Path = FAKTURAMA_PREFS) -> str:
    """Return the currency locale when it is a euro country; otherwise stop for review."""
    locale = currency_locale(prefs_path.read_text(encoding="utf-8")) if prefs_path.is_file() else None
    if locale is None or locale.rpartition("/")[2] not in EURO_COUNTRIES:
        raise NeedsReview("fakturama_currency_not_eur", {"currency_locale": locale or "unset"})
    return locale
