"""Unattended runs: every order image in an inbox folder, one after another (README "Batch").

Each image ends in one subfolder of the inbox, so nothing is processed twice:
- done/    the Order and Invoice were saved and verified;
- review/  extraction needs a person (review.json says why); Fakturama was not touched;
- stopped/ the drive stopped. A stop for review leaves the bot's own editors open: with `discard`
           they are closed unsaved (drive/fakturama/discard.py) and the batch goes on. Any other
           failure, or a discard that cannot finish, ends the batch: the next order must not start
           on top of what is open.

Results go to OUT/<image name>/ (order.json or review.json, drive/run.jsonl and screens), and one
line per image to OUT/batch.jsonl.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from image_to_cash.errors import NeedsReview

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
DONE, REVIEW, STOPPED = "done", "review", "stopped"
LOG_FILE = "batch.jsonl"


@dataclass(frozen=True)
class Outcome:
    image: str
    status: str
    detail: str
    cleared: bool = False  # a stop whose editors were discarded, so the batch went on


Extract = Callable[[Path, Path], Path | None]  # image, result folder -> order.json, or None for review
Drive = Callable[[Path, Path], str]  # order.json, drive folder -> "PO… / INV…"; raises to stop
Discard = Callable[[], tuple[str, ...]]  # closes what a stop left open -> editors closed; raises if it cannot


def run_batch(
    inbox: Path, out: Path, extract: Extract, drive: Drive, *, discard: Discard | None = None, watch: float | None = None
) -> list[Outcome]:
    """Processes the inbox until it is empty (or, with `watch` seconds, until a stop ends it)."""
    outcomes: list[Outcome] = []
    while True:
        for image in _waiting(inbox):
            outcome = _one(image, out / image.stem, extract, drive, discard)
            _move(image, inbox / outcome.status)
            _log(out, outcome)
            outcomes.append(outcome)
            if outcome.status == STOPPED and not outcome.cleared:
                return outcomes
        if watch is None:
            return outcomes
        time.sleep(watch)


def _one(image: Path, folder: Path, extract: Extract, drive: Drive, discard: Discard | None) -> Outcome:
    try:
        order = extract(image, folder)
    except (OSError, ValueError, RuntimeError) as error:  # unreadable image, reader or OCR failure
        return Outcome(image.name, REVIEW, f"not read: {error}")
    if order is None:
        return Outcome(image.name, REVIEW, f"see {folder / 'review.json'}")
    try:
        return Outcome(image.name, DONE, drive(order, folder / "drive"))
    except NeedsReview as review:
        return _stopped(image.name, f"stopped for review: {review}", discard)
    except Exception as error:  # a refusal, timeout or failure, already in run.jsonl: never discarded
        return Outcome(image.name, STOPPED, f"error: {error}")


def _stopped(image: str, detail: str, discard: Discard | None) -> Outcome:
    if discard is None:
        return Outcome(image, STOPPED, detail)
    try:
        closed = discard()
    except Exception as error:  # what is open stays for a person, and the batch ends
        return Outcome(image, STOPPED, f"{detail}; not discarded: {error}")
    return Outcome(image, STOPPED, f"{detail}; discarded: {', '.join(closed) or 'nothing open'}", cleared=True)


def _waiting(inbox: Path) -> Iterator[Path]:
    return iter(sorted(p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES))


def _move(image: Path, folder: Path) -> None:
    folder.mkdir(exist_ok=True)
    target = folder / image.name
    stamp = 1
    while target.exists():  # an image of the same name processed before keeps its place
        target = folder / f"{image.stem}-{stamp}{image.suffix}"
        stamp += 1
    shutil.move(image, target)


def _log(out: Path, outcome: Outcome) -> None:
    out.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now(UTC).isoformat(), **asdict(outcome)}
    with (out / LOG_FILE).open("a", encoding="utf-8") as log:
        log.write(json.dumps(line, ensure_ascii=False) + "\n")
