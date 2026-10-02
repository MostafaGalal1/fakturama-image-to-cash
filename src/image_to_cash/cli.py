"""Command line: `image-to-cash extract IMAGE` and `image-to-cash approve DRAFT`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import UnidentifiedImageError
from pydantic import ValidationError

from image_to_cash.errors import NeedsReview
from image_to_cash.extract import extract
from image_to_cash.invariants import check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import normalize
from image_to_cash.ocr import ENGINES, OcrError, build_ocr
from image_to_cash.outputs import ORDER_FILE, clear_results, discard_order, write_order, write_result
from image_to_cash.readers import READERS, ReaderError, build_reader
from image_to_cash.readers.base import describe_validation_error

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REVIEW = 3  # 2 is argparse's code for bad command-line usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="image-to-cash", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    extract_cmd = commands.add_parser("extract", help="read an order image into order.json")
    extract_cmd.add_argument("image", type=Path)
    extract_cmd.add_argument("--reader", default="fixture", choices=READERS)
    extract_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    extract_cmd.add_argument("--ocr", default="macos-vision", choices=ENGINES)
    extract_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="result folder; cleared of order.json and review.json first"
    )

    approve_cmd = commands.add_parser(
        "approve", help="turn a human-corrected draft (review.json or order JSON) into order.json"
    )
    approve_cmd.add_argument("draft", type=Path)
    approve_cmd.add_argument(
        "--out", type=Path, default=Path("out"), help="folder for order.json; an earlier one is removed first"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _extract(args)
        return _approve(args)
    except (ReaderError, OcrError, OSError, UnidentifiedImageError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _extract(args: argparse.Namespace) -> int:
    clear_results(args.out)  # a failed run must not leave an earlier order for Stage 2
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found: {args.image}")
    reader = build_reader(args.reader, fixture=args.fixture)
    result = extract(args.image, reader, build_ocr(args.ocr))
    target = write_result(result, args.out)
    if result.needs_review:
        print(
            f"needs review: {len(result.mismatches)} unconfirmed field(s), "
            f"{len(result.issues)} issue(s); see {target}"
        )
        return EXIT_REVIEW
    print(f"order written to {target}")
    return EXIT_OK


def _approve(args: argparse.Namespace) -> int:
    if args.draft.resolve() == (args.out / ORDER_FILE).resolve():
        raise ValueError(f"{args.draft} is Stage 2's input, not a draft; approve review.json instead")
    draft = args.draft.read_text(encoding="utf-8")
    discard_order(args.out)  # a refused draft must not leave an earlier order for Stage 2
    payload = json.loads(draft)
    candidate = payload.get("draft_order", payload) if isinstance(payload, dict) else payload
    try:
        order = Order.model_validate(candidate)
    except ValidationError as error:
        print(f"not approved: draft is not a valid order: {describe_validation_error(error)}", file=sys.stderr)
        return EXIT_REVIEW
    issues = check_invariants(order)
    if issues:
        for issue in issues:
            print(f"not approved: {issue.code}: {issue.message}", file=sys.stderr)
        return EXIT_REVIEW
    try:
        normalized = normalize(order)
    except NeedsReview as review:
        print(f"not approved: {review}", file=sys.stderr)
        return EXIT_REVIEW
    target = write_order(normalized, args.out)
    print(f"order written to {target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
