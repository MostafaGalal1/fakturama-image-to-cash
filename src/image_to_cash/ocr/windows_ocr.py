"""Windows' built-in OCR (Windows.Media.Ocr, through the winrt packages): local, no account.

It reads lines made of words. Extraction wants lines: it counts how often each value appears,
and a value would count twice if its words were returned beside its line. Driving wants words:
it finds single column headers ("Qty.") in one header line. So the caller picks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator

from PIL import Image

from image_to_cash.ocr.base import Box, OcrError, TextBox

MIN_HEIGHT = 60  # pixels: a thin strip (one grid row) is enlarged first, small text reads badly
ENLARGE = 2

RunRect = tuple[float, float, float, float]  # x, y, width, height in the read image's pixels


class WindowsOcr:
    def __init__(self, *, words: bool = False) -> None:
        self._words = words

    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]:
        try:
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine as WinOcrEngine
            from winrt.windows.security.cryptography import CryptographicBuffer
        except ImportError as error:
            raise OcrError("windows-ocr needs Windows 10 or later with the winrt packages installed") from error
        engine = WinOcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrError("Windows has no OCR language for this user: add one in Settings > Time & language")
        factor = fit_factor(image.width, image.height, int(WinOcrEngine.max_image_dimension))
        prepared = image.convert("RGBA")
        if factor != 1:
            prepared = prepared.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.LANCZOS)
        pixels = CryptographicBuffer.create_from_byte_array(prepared.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(pixels, BitmapPixelFormat.RGBA8, prepared.width, prepared.height)
        try:
            result = asyncio.run(_read(engine, bitmap))
        except Exception as error:  # a WinRT failure surfaces as OSError or RuntimeError
            raise OcrError(f"Windows OCR failed: {error}") from error
        return text_boxes(_runs(result, words=self._words), factor, image.width, image.height)


async def _read(engine: object, bitmap: object) -> object:
    return await engine.recognize_async(bitmap)


def _runs(result: object, *, words: bool) -> Iterator[tuple[str, RunRect]]:
    for line in result.lines:
        rects = [(w.bounding_rect.x, w.bounding_rect.y, w.bounding_rect.width, w.bounding_rect.height) for w in line.words]
        if words:
            yield from ((word.text, rect) for word, rect in zip(line.words, rects, strict=True))
        elif rects:
            yield line.text, union(rects)


def fit_factor(width: int, height: int, max_dimension: int) -> float:
    """Enlarge a thin strip, then shrink anything the engine would refuse as too large."""
    factor = float(ENLARGE) if height < MIN_HEIGHT else 1.0
    largest = max(width, height) * factor
    return factor * max_dimension / largest if largest > max_dimension else factor


def union(rects: Iterable[RunRect]) -> RunRect:
    rects = tuple(rects)
    left, top = min(r[0] for r in rects), min(r[1] for r in rects)
    right, bottom = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    return left, top, right - left, bottom - top


def text_boxes(runs: Iterable[tuple[str, RunRect]], factor: float, width: int, height: int) -> tuple[TextBox, ...]:
    """Runs read from an image scaled by `factor`, as boxes in the original image's pixels."""
    boxes = []
    for text, (x, y, w, h) in runs:
        left, top = _clamp(round(x / factor), width), _clamp(round(y / factor), height)
        right, bottom = _clamp(round((x + w) / factor), width), _clamp(round((y + h) / factor), height)
        if text.strip():
            boxes.append(TextBox(text=text, box=Box(left, top, right - left, bottom - top)))
    return tuple(boxes)


def _clamp(value: int, limit: int) -> int:
    return min(max(value, 0), limit)
