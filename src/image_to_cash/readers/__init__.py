"""Image readers behind one interface; `build_reader` picks one by name."""

from __future__ import annotations

from pathlib import Path

from image_to_cash.readers.base import ImageReader, ReaderError
from image_to_cash.readers.fixture import FixtureReader

READERS = ("fixture",)


def build_reader(name: str, *, fixture: Path | None = None) -> ImageReader:
    if name == "fixture":
        if fixture is None:
            raise ValueError("the fixture reader needs --fixture PATH")
        return FixtureReader(fixture)
    raise ValueError(f"unknown image reader: {name!r} (available: {', '.join(READERS)})")


__all__ = ["READERS", "FixtureReader", "ImageReader", "ReaderError", "build_reader"]
