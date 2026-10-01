"""Replays a recorded reader response. Used until a live provider key is configured."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers.base import ReaderError, describe_validation_error


class FixtureReader:
    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = fixture_path

    def read(self, image: Image.Image) -> Order:
        try:
            recorded = self._fixture_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ReaderError(f"fixture {self._fixture_path} cannot be read: {error}") from error
        try:
            return Order.model_validate_json(recorded)
        except ValidationError as error:
            problems = describe_validation_error(error)
            raise ReaderError(f"fixture {self._fixture_path} is not a valid order: {problems}") from error
