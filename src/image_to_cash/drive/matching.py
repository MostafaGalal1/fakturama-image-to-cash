"""Decide whether a master record already exists (design §6, stage 2-3).

One exact row is reused. No plausible row means "create". Several exact rows, or a row that is
only a few characters off, stop the run: either could be a misread, and creating a record then
would make a duplicate.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

NEAR_MISS_LIMIT = 2  # total edited characters across all fields that still look like the same record


class MatchKind(StrEnum):
    EXACT = "exact"
    NONE = "none"
    AMBIGUOUS = "ambiguous"
    NEAR_MISS = "near_miss"


@dataclass(frozen=True)
class MatchResult:
    kind: MatchKind
    index: int | None = None


def canonical(text: str) -> str:
    """Compatibility-normalised, case-folded, single-spaced: 'Straße ' equals 'STRASSE'."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insertions, deletions, substitutions)."""
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def classify(expected: Sequence[str], rows: Sequence[Sequence[str]]) -> MatchResult:
    for row in rows:
        if len(row) != len(expected):
            raise ValueError(f"every row must have {len(expected)} fields to compare, got {len(row)}")
    distances = [_distance(expected, row) for row in rows]
    exact = [index for index, distance in enumerate(distances) if distance == 0]
    if len(exact) == 1:
        return MatchResult(MatchKind.EXACT, exact[0])
    if exact:
        return MatchResult(MatchKind.AMBIGUOUS)
    near = [index for index, distance in enumerate(distances) if distance <= NEAR_MISS_LIMIT]
    if near:
        return MatchResult(MatchKind.NEAR_MISS, near[0])
    return MatchResult(MatchKind.NONE)


def _distance(expected: Sequence[str], row: Sequence[str]) -> int:
    return sum(edit_distance(canonical(want), canonical(have)) for want, have in zip(expected, row, strict=True))
