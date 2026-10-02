"""Run report: a JSONL step log and annotated screenshots (design §7)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from PIL import Image, ImageDraw

from image_to_cash.drive.elements import Rect

MARK_COLOUR = (220, 30, 30)
MARK_WIDTH_POINTS = 1.5


class Outcome(StrEnum):
    CHECKED = "checked"  # a value was read back and matched
    FOUND = "found"  # an existing record was reused
    CREATED = "created"  # a record was created
    DONE = "done"  # an action finished
    STOPPED = "stopped"  # the run handed over to a person


@dataclass(frozen=True)
class Step:
    at: str
    step: str
    outcome: Outcome
    details: Mapping[str, str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RunLog:
    """Appends one JSON line per step, so a crash still leaves every earlier step on disk."""

    def __init__(self, path: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self._path = path
        self._clock = clock

    def record(self, step: str, outcome: Outcome, **details: str) -> Step:
        entry = Step(self._clock().isoformat(), step, outcome, MappingProxyType(dict(details)))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = {"at": entry.at, "step": entry.step, "outcome": entry.outcome.value, "details": dict(entry.details)}
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return entry


def annotate(shot: Path, *, area: Rect, target: Rect, label: str, out: Path) -> Path:
    """Copy `shot` (a capture of `area`) to `out` with `target` boxed and labelled."""
    if not area.contains(target):
        raise ValueError(f"target {target} lies outside the captured area {area}")
    with Image.open(shot) as source:
        marked = source.convert("RGB")
    scale = marked.width / area.width
    box = (
        round((target.x - area.x) * scale),
        round((target.y - area.y) * scale),
        round((target.right - area.x) * scale) - 1,
        round((target.bottom - area.y) * scale) - 1,
    )
    draw = ImageDraw.Draw(marked)
    draw.rectangle(box, outline=MARK_COLOUR, width=max(1, round(MARK_WIDTH_POINTS * scale)))
    draw.text((box[0], max(0, box[1] - round(12 * scale))), label, fill=MARK_COLOUR)
    out.parent.mkdir(parents=True, exist_ok=True)
    marked.save(out)
    return out
