"""OCR engine interface: any engine returns text boxes in top-left pixel coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


class OcrError(RuntimeError):
    """The OCR engine failed to process an image."""


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


@dataclass(frozen=True)
class TextBox:
    text: str
    box: Box
    confidence: float | None = None


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]: ...
