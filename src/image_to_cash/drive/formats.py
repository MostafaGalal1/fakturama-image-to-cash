"""Numbers and dates as Fakturama shows them and as the bot types them.

Fakturama formats money with its currency locale (`de/DE` here: `1.234,57 €`), but some fields,
such as Stock, use plain `0.00`. So every call names the style of the field it reads or writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

CURRENCY_MARKS = "€$£   "
# Only formats that cannot be misread: "07/04/2026" could be April or July, so it is rejected.
DISPLAY_DATE_FORMATS = ("%b %d, %Y", "%d.%m.%Y", "%Y-%m-%d")


@dataclass(frozen=True)
class NumberStyle:
    decimal: str
    group: str


GERMAN = NumberStyle(decimal=",", group=".")
ENGLISH = NumberStyle(decimal=".", group=",")


def format_amount(value: Decimal, style: NumberStyle) -> str:
    """Two decimals and no grouping, as a person would type it: '250,00'."""
    return f"{value:.2f}".replace(".", style.decimal)


def parse_amount(text: str, style: NumberStyle) -> Decimal:
    bare = text.strip(CURRENCY_MARKS)
    if not _amount_pattern(style).fullmatch(bare):
        raise ValueError(f"not an amount in {_name(style)} style: {text!r}")
    return Decimal(bare.replace(style.group, "").replace(style.decimal, "."))


def format_percent(value: Decimal, style: NumberStyle) -> str:
    return f"{value.normalize():f}".replace(".", style.decimal)


def parse_percent(text: str, style: NumberStyle) -> Decimal:
    bare = text.strip().removesuffix("%").strip()
    decimal = re.escape(style.decimal)
    if not re.fullmatch(rf"-?\d+(?:{decimal}\d+)?", bare):
        raise ValueError(f"not a percentage in {_name(style)} style: {text!r}")
    return Decimal(bare.replace(style.decimal, "."))


def parse_display_date(text: str) -> date:
    for pattern in DISPLAY_DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f"not a date in a known unambiguous format: {text!r}")


def _amount_pattern(style: NumberStyle) -> re.Pattern[str]:
    group, decimal = re.escape(style.group), re.escape(style.decimal)
    return re.compile(rf"-?(?:\d{{1,3}}(?:{group}\d{{3}})+|\d+)(?:{decimal}\d+)?")


def _name(style: NumberStyle) -> str:
    return f"'{style.group}' grouping, '{style.decimal}' decimal"
