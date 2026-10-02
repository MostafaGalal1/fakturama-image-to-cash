"""Read NatTable grids through the clipboard: Fakturama copies selected rows as tab-separated text."""

from __future__ import annotations


def parse_rows(copied: str) -> tuple[tuple[str, ...], ...]:
    """One tuple per copied row, cells in column order; blank lines are dropped."""
    lines = copied.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return tuple(tuple(cell.strip() for cell in line.split("\t")) for line in lines if line.strip())
