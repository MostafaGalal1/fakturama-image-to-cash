"""Persist Stage-1 results: order.json when clean, review.json when a person must check."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from image_to_cash.extract import ExtractionResult

ORDER_FILE = "order.json"
REVIEW_FILE = "review.json"


def write_result(result: ExtractionResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not result.needs_review and result.normalized is not None:
        target = out_dir / ORDER_FILE
        target.write_text(result.normalized.model_dump_json(indent=2), encoding="utf-8")
        return target
    target = out_dir / REVIEW_FILE
    payload = {
        "reason": "extraction needs review",
        "mismatches": [asdict(mismatch) for mismatch in result.mismatches],
        "issues": [asdict(issue) for issue in result.issues],
        "draft_order": result.order.model_dump(mode="json"),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
