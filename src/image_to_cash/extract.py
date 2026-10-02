"""Stage 1: order image -> validated, normalised order (design §3-4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from image_to_cash.errors import NeedsReview
from image_to_cash.field_retry import FieldReader, Retry, retry_single_field
from image_to_cash.imaging import for_ocr, load_image, upscale
from image_to_cash.invariants import Issue, check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import NormalizedOrder, normalize
from image_to_cash.ocr.base import OcrEngine
from image_to_cash.readers.base import ImageReader
from image_to_cash.reconcile import Mismatch, reconcile


@dataclass(frozen=True)
class ExtractionResult:
    source_image: Path
    order: Order
    normalized: NormalizedOrder | None
    mismatches: tuple[Mismatch, ...]
    issues: tuple[Issue, ...]
    retry: Retry | None = None

    @property
    def needs_review(self) -> bool:
        return self.normalized is None or bool(self.mismatches) or bool(self.issues)


def extract(image_path: Path, reader: ImageReader, ocr: OcrEngine) -> ExtractionResult:
    """Read, cross-check, validate and normalise one order image.

    Raises ReaderError, OcrError, OSError (unreadable image) or ValueError (oversized image).
    """
    prepared = upscale(load_image(image_path))
    order = reader.read(prepared.copy())  # a reader must not change what OCR sees
    text_boxes = ocr.recognize(for_ocr(prepared))
    mismatches = reconcile(order, text_boxes)
    retried = retry_single_field(prepared, order, text_boxes, reader, ocr) if isinstance(reader, FieldReader) else None
    retry = None
    if retried is not None:
        order, mismatches, retry = retried.order, retried.mismatches, retried.retry
    issues = check_invariants(order)
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        review_issue = Issue(review.reason, str(review))
        return ExtractionResult(image_path, order, None, mismatches, (*issues, review_issue), retry)
    return ExtractionResult(image_path, order, normalized, mismatches, issues, retry)
