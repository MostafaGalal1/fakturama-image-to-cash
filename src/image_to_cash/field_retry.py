"""One more look at the single field OCR did not confirm (design §4, step 4).

The reader gets a zoomed crop around the place the field is printed (the OCR box most like its
value) and reads that one field again; OCR reads the same crop. The field counts as confirmed
only when the second reading is found, as whole tokens, in the zoomed OCR. Anything else keeps
the mismatch, and a person reviews the order: the bot never guesses.

Only a value that OCR found nowhere on the page is retried. A value printed fewer times than
fields claim it (billing and delivery ZIP both read from one print) is a question for a person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol, runtime_checkable

from PIL import Image
from pydantic import ValidationError

from image_to_cash.imaging import for_ocr
from image_to_cash.model import Order
from image_to_cash.ocr.base import OcrEngine, TextBox
from image_to_cash.readers.base import ReaderError
from image_to_cash.reconcile import Mismatch, critical_fields, fold, reconcile, value_pattern

ZOOM_FACTOR = 3
MIN_LIKENESS = 0.7  # below this an OCR box is not a misreading of the value (0.5 matches unrelated words)
MARGIN_HEIGHTS = 1.5  # around the box, in box heights, so a cut-off character is inside the crop
PATH_PART = re.compile(r"([a-z_]+)(?:\[(\d+)\])?")


@runtime_checkable
class FieldReader(Protocol):
    def read_field(self, crop: Image.Image, field: str) -> str:
        """The value of `field` (an Order path such as "items[1].sku") as printed in `crop`,
        in the Order schema's format. Raises ReaderError."""
        ...


@dataclass(frozen=True)
class Retry:
    field: str
    first_reading: str
    second_reading: str
    confirmed: bool


@dataclass(frozen=True)
class Retried:
    order: Order
    mismatches: tuple[Mismatch, ...]
    retry: Retry


def retry_single_field(
    image: Image.Image, order: Order, boxes: tuple[TextBox, ...], reader: FieldReader, ocr: OcrEngine
) -> Retried | None:
    """None when there is nothing to retry: not exactly one mismatch, the value is printed
    somewhere, or no OCR box looks like it."""
    mismatches = reconcile(order, boxes)
    if len(mismatches) != 1 or _printed(mismatches[0].expected, boxes):
        return None
    field, first = mismatches[0].field, mismatches[0].expected
    place = locate(first, boxes)
    if place is None:
        return None
    crop = zoom(image, place)
    try:
        second = reader.read_field(crop, field)
    except ReaderError:  # the first reading stands, unconfirmed
        return Retried(order, mismatches, Retry(field, first, "", confirmed=False))
    corrected = with_value(order, field, second)
    if corrected is None:
        return Retried(order, mismatches, Retry(field, first, second, confirmed=False))
    expected = dict(critical_fields(corrected))[field]
    zoomed = tuple(fold(box.text) for box in ocr.recognize(for_ocr(crop)))
    confirmed = any(value_pattern(expected).search(line) for line in zoomed)
    page = reconcile(corrected, boxes)
    # Printed on the page yet still a mismatch: another field already claims that print (the crop
    # found a neighbour, say the billing street for a misread delivery street).
    claimed_elsewhere = _printed(expected, boxes) and any(m.field == field for m in page)
    others = tuple(m for m in page if m.field != field)
    if not confirmed or claimed_elsewhere or others:
        return Retried(order, mismatches, Retry(field, first, second, confirmed=False))
    return Retried(corrected, (), Retry(field, first, expected, confirmed=True))


def locate(expected: str, boxes: tuple[TextBox, ...]) -> TextBox | None:
    """The OCR box most like the value, compared with each run of as many words in the box."""
    target = fold(expected)
    likeness = [(max(_likeness(target, window) for window in _windows(fold(box.text), target)), box) for box in boxes]
    best = max(likeness, key=lambda pair: pair[0], default=(0.0, None))
    return best[1] if best[0] >= MIN_LIKENESS else None


def zoom(image: Image.Image, box: TextBox) -> Image.Image:
    margin = round(box.box.height * MARGIN_HEIGHTS)
    left, top = max(0, box.box.x - margin), max(0, box.box.y - margin)
    right = min(image.width, box.box.x + box.box.width + margin)
    bottom = min(image.height, box.box.y + box.box.height + margin)
    crop = image.crop((left, top, right, bottom))
    return crop.resize((crop.width * ZOOM_FACTOR, crop.height * ZOOM_FACTOR), Image.Resampling.LANCZOS)


def with_value(order: Order, field: str, value: str) -> Order | None:
    """A copy of the order with `field` set to `value`, or None when the schema rejects it."""
    data = order.model_dump(mode="json")
    *parents, last = [_part(piece) for piece in field.split(".")]
    node = data
    for name, index in parents:
        node = node[name] if index is None else node[name][index]
    name, index = last
    if index is None:
        node[name] = value
    else:
        node[name][index] = value
    try:
        return Order.model_validate(data)
    except ValidationError:
        return None


def _printed(expected: str, boxes: tuple[TextBox, ...]) -> bool:
    pattern = value_pattern(expected)
    return any(pattern.search(fold(box.text)) for box in boxes)


def _windows(text: str, target: str) -> list[str]:
    words, size = text.split(), max(1, len(target.split()))
    return [" ".join(words[start : start + size]) for start in range(max(1, len(words) - size + 1))] or [text]


def _likeness(target: str, candidate: str) -> float:
    return SequenceMatcher(None, target, candidate).ratio()


def _part(piece: str) -> tuple[str, int | None]:
    match = PATH_PART.fullmatch(piece)
    if match is None:
        raise ValueError(f"not an Order field path: {piece!r}")
    name, index = match.groups()
    return name, None if index is None else int(index)
