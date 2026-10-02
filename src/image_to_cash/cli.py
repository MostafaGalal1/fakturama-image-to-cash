"""Command line: `image-to-cash extract IMAGE`, `approve DRAFT`, `drive ORDER_JSON`, `batch INBOX`
and `discard`."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from image_to_cash.drive.backend.base import UiBackend
from image_to_cash.errors import NeedsReview
from image_to_cash.extract import extract
from image_to_cash.invariants import check_invariants
from image_to_cash.model import Order
from image_to_cash.normalized import normalize
from image_to_cash.ocr import DEFAULT_ENGINE, ENGINES, OcrEngine, OcrError, build_ocr
from image_to_cash.outputs import ORDER_FILE, clear_results, discard_order, write_order, write_result
from image_to_cash.readers import READERS, ReaderError, build_reader
from image_to_cash.readers.base import describe_validation_error
from image_to_cash.readers.openrouter import DEFAULT_MODEL

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REVIEW = 3  # 2 is argparse's code for bad command-line usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-to-cash",
        description="Read an order image into order.json for Stage 2, or review.json for a person.",
        epilog="exit codes: 0 order.json written, 1 error, 2 bad usage, 3 needs review",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    extract_cmd = commands.add_parser("extract", help="read an order image into order.json")
    extract_cmd.add_argument("image", type=Path)
    extract_cmd.add_argument("--reader", default="fixture", choices=READERS)
    extract_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    extract_cmd.add_argument(
        "--model", help=f"OpenRouter model for --reader openrouter (default {DEFAULT_MODEL})"
    )
    extract_cmd.add_argument("--ocr", default=DEFAULT_ENGINE, choices=ENGINES)
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
    drive_cmd = commands.add_parser("drive", help="enter an approved order.json into the running Fakturama")
    drive_cmd.add_argument("order", type=Path, help="order.json written by extract or approve")
    drive_cmd.add_argument("--out", type=Path, default=Path("out/drive"), help="folder for run.jsonl and screens/")
    batch_cmd = commands.add_parser("batch", help="extract and drive every order image in a folder, unattended")
    batch_cmd.add_argument("inbox", type=Path, help="folder of order images; each moves to done/, review/ or stopped/")
    batch_cmd.add_argument("--reader", default="openrouter", choices=READERS)
    batch_cmd.add_argument("--fixture", type=Path, help="recorded response for --reader fixture")
    batch_cmd.add_argument("--model", help=f"OpenRouter model (default {DEFAULT_MODEL})")
    batch_cmd.add_argument("--ocr", default=DEFAULT_ENGINE, choices=ENGINES)
    batch_cmd.add_argument("--out", type=Path, default=Path("out/batch"), help="results, one folder per image")
    batch_cmd.add_argument("--watch", type=float, metavar="SECONDS", help="keep watching the inbox at this interval")
    batch_cmd.add_argument(
        "--keep-open", action="store_true", help="end the batch at a stop for review, leaving its editors open"
    )
    commands.add_parser("discard", help="close Fakturama's open editors without saving, after a stop")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _extract(args)
        if args.command == "drive":
            return _drive(args)
        if args.command == "batch":
            return _batch(args)
        if args.command == "discard":
            return _discard()
        return _approve(args)
    except (ReaderError, OcrError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


def _extract(args: argparse.Namespace) -> int:
    clear_results(args.out)  # a failed run must not leave an earlier order for Stage 2
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found or not a file: {args.image}")
    reader = build_reader(args.reader, fixture=args.fixture, model=args.model)
    result = extract(args.image, reader, build_ocr(args.ocr))
    target = write_result(result, args.out)
    if result.needs_review:
        print(
            f"needs review: {len(result.mismatches)} unconfirmed field(s), "
            f"{len(result.issues)} issue(s); see {target}"
        )
        print(f"  check every field of draft_order against {result.source_image}, correct it, then run:")
        print(f"  image-to-cash approve {shell_arg(str(target))} --out {shell_arg(str(args.out))}")
        return EXIT_REVIEW
    print(f"order written to {target}")
    return EXIT_OK


def _approve(args: argparse.Namespace) -> int:
    if args.draft.resolve() == (args.out / ORDER_FILE).resolve():
        raise ValueError(f"{args.draft} is Stage 2's input, not a draft; approve review.json instead")
    discard_order(args.out)  # any outcome but "approved" must leave no earlier order for Stage 2
    draft = args.draft.read_text(encoding="utf-8")
    try:
        payload = json.loads(draft)
    except json.JSONDecodeError as error:
        print(f"not approved: {args.draft} is not valid JSON: {error}", file=sys.stderr)
        return EXIT_REVIEW
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
    print(
        f"approved {normalized.external_reference}: {normalized.debtor.company}, "
        f"{len(normalized.lines)} line(s), gross {normalized.totals.gross} {order.currency}, "
        f"{normalized.payment.status.value}"
    )
    print(f"order written to {target}")
    return EXIT_OK


def _drive(args: argparse.Namespace) -> int:
    from image_to_cash.drive.flow import drive
    from image_to_cash.drive.preflight import check_currency, load_order

    order = load_order(args.order)
    try:
        check_currency()
        backend, ocr = _driver()
        result = drive(order, backend, ocr, args.out)
    except NeedsReview as review:
        print(f"stopped for review: {review}; see {args.out / 'run.jsonl'}", file=sys.stderr)
        return EXIT_REVIEW
    except RuntimeError as error:  # BackendError: the accessibility API refused or failed
        print(f"error: {error}; see {args.out / 'run.jsonl'}", file=sys.stderr)
        return EXIT_ERROR
    print(f"order {result.order_number} and invoice {result.invoice_number} saved and verified; see {args.out}")
    return EXIT_OK


def _batch(args: argparse.Namespace) -> int:
    from image_to_cash.batch import DONE, STOPPED, run_batch
    from image_to_cash.drive.flow import drive
    from image_to_cash.drive.preflight import check_currency, load_order

    if not args.inbox.is_dir():
        raise FileNotFoundError(f"inbox not found or not a folder: {args.inbox}")
    reader = build_reader(args.reader, fixture=args.fixture, model=args.model)
    ocr = build_ocr(args.ocr)
    driver: list[tuple[UiBackend, OcrEngine]] = []  # attached on the first clean order

    def read(image: Path, folder: Path) -> Path | None:
        clear_results(folder)
        result = extract(image, reader, ocr)
        target = write_result(result, folder)
        return None if result.needs_review else target

    def enter(order_path: Path, folder: Path) -> str:
        if not driver:
            check_currency()
            driver.append(_driver())
        result = drive(load_order(order_path), *driver[0], folder)
        return f"order {result.order_number}, invoice {result.invoice_number}"

    def discard() -> tuple[str, ...]:
        if not driver:
            raise RuntimeError("the stop came before Fakturama was attached")
        return _discard_editors(driver[0][0], args.out / "discard")

    outcomes = run_batch(args.inbox, args.out, read, enter, discard=None if args.keep_open else discard, watch=args.watch)
    for outcome in outcomes:
        print(f"{outcome.status:8} {outcome.image}: {outcome.detail}")
    if any(outcome.status == STOPPED and not outcome.cleared for outcome in outcomes):
        print("batch stopped: finish or discard Fakturama's open editors, then run it again", file=sys.stderr)
        return EXIT_REVIEW
    if any(outcome.status != DONE for outcome in outcomes):
        return EXIT_REVIEW  # the batch went on, but an image in review/ or stopped/ needs a person
    return EXIT_OK


def _discard() -> int:
    try:
        backend, _ = _driver()
        closed = _discard_editors(backend, Path("out/discard"))
    except NeedsReview as review:
        print(f"not discarded: {review}", file=sys.stderr)
        return EXIT_REVIEW
    except RuntimeError as error:  # BackendError: the accessibility API refused or failed
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(f"closed without saving: {', '.join(closed) or 'nothing was open'}")
    return EXIT_OK


def _discard_editors(backend: UiBackend, shots: Path) -> tuple[str, ...]:
    from image_to_cash.drive.fakturama.discard import discard_editors
    from image_to_cash.drive.fakturama.workbench import Workbench

    return discard_editors(Workbench(backend, shots))


def _driver() -> tuple[UiBackend, OcrEngine]:
    """This OS's adapter and OCR, imported here: each needs its own packages and permissions, and
    extract needs neither. Grid headers are read word by word, so Windows OCR returns words."""
    try:
        if sys.platform == "darwin":
            from image_to_cash.drive.backend.macos_ax import MacAxBackend

            return MacAxBackend.attach(), build_ocr("macos-vision")
        if sys.platform == "win32":
            from image_to_cash.drive.backend.windows_uia import WindowsUiaBackend
            from image_to_cash.ocr.windows_ocr import WindowsOcr

            return WindowsUiaBackend.attach(), WindowsOcr(words=True)
    except ImportError as error:
        raise RuntimeError(f"the {sys.platform} adapter is not installed ({error}); run uv sync") from error
    raise RuntimeError(f"drive runs on macOS and Windows, not {sys.platform}")


def shell_arg(text: str, platform: str = sys.platform) -> str:
    """`text` as one argument of a command a person pastes: POSIX quoting on macOS, Windows'
    (understood by cmd and PowerShell alike) on Windows."""
    return subprocess.list2cmdline([text]) if platform == "win32" else shlex.quote(text)

if __name__ == "__main__":
    sys.exit(main())
