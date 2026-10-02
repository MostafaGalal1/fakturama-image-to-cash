"""Image readers behind one interface; `build_reader` picks one by name."""

from __future__ import annotations

from pathlib import Path

from image_to_cash.readers.base import ImageReader, ReaderError
from image_to_cash.readers.fixture import FixtureReader
from image_to_cash.readers.openrouter import DEFAULT_MODEL, OpenRouterReader

READERS = ("fixture", "openrouter")


def build_reader(name: str, *, fixture: Path | None = None, model: str | None = None) -> ImageReader:
    if name == "fixture":
        if fixture is None:
            raise ValueError("the fixture reader needs --fixture PATH")
        if model is not None:
            raise ValueError("--model only applies to --reader openrouter")
        return FixtureReader(fixture)
    if name == "openrouter":
        if fixture is not None:
            raise ValueError("--fixture only applies to --reader fixture")
        return OpenRouterReader.from_env(DEFAULT_MODEL if model is None else model)
    raise ValueError(f"unknown image reader: {name!r} (available: {', '.join(READERS)})")


__all__ = ["READERS", "FixtureReader", "ImageReader", "OpenRouterReader", "ReaderError", "build_reader"]
