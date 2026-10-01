"""Replays a recorded reader response. Used until a live provider key is configured."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order
from image_to_cash.readers.base import ReaderError


class FixtureReader:
    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = fixture_path

    def read(self, image: Image.Image) -> Order:
        try:
            return Order.model_validate_json(self._fixture_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ReaderError(f"fixture {self._fixture_path} is unusable: {error}") from error
