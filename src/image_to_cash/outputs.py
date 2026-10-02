"""Persist Stage-1 results: order.json when clean, review.json when a person must check.

The out dir only ever holds the latest run's complete result. Both files are removed before
a new one is written, and each is written to a temporary file and renamed into place, so
Stage 2 can never pick up an earlier order or a half-written one.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from image_to_cash.extract import ExtractionResult
from image_to_cash.normalized import NormalizedOrder

ORDER_FILE = "order.json"
REVIEW_FILE = "review.json"


def discard_order(out_dir: Path) -> None:
    """Remove order.json so a stopped or failed run cannot leave an earlier order for Stage 2."""
    (out_dir / ORDER_FILE).unlink(missing_ok=True)


def clear_results(out_dir: Path) -> None:
    discard_order(out_dir)
    (out_dir / REVIEW_FILE).unlink(missing_ok=True)


def write_order(normalized: NormalizedOrder, out_dir: Path) -> Path:
    """The only place order.json is created (`approve` uses it too)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return _write_atomic(out_dir / ORDER_FILE, normalized.model_dump_json(indent=2) + "\n")


def write_result(result: ExtractionResult, out_dir: Path) -> Path:
    clear_results(out_dir)
    if result.normalized is not None and not result.needs_review:
        return write_order(result.normalized, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return _write_atomic(out_dir / REVIEW_FILE, _review_json(result))


def _review_json(result: ExtractionResult) -> str:
    payload = {
        "reason": (
            f"{len(result.mismatches)} field(s) not confirmed by OCR, "
            f"{len(result.issues)} issue(s)"
        ),
        "source_image": str(result.source_image.absolute()),
        "mismatches": [asdict(mismatch) for mismatch in result.mismatches],
        "issues": [asdict(issue) for issue in result.issues],
        "zoomed_retry": None if result.retry is None else asdict(result.retry),
        "confirmed_by_arithmetic": list(result.pinned),
        "draft_order": result.order.model_dump(mode="json"),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _write_atomic(target: Path, text: str) -> Path:
    """Write beside the target, then rename: readers see the old file or the new one, never half."""
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return target
