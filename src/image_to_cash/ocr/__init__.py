"""OCR engines behind one interface; `build_ocr` picks one by name."""

import sys

from image_to_cash.ocr.base import Box, OcrEngine, OcrError, TextBox

ENGINES = ("macos-vision", "windows-ocr")
DEFAULT_ENGINE = "windows-ocr" if sys.platform == "win32" else "macos-vision"


def build_ocr(name: str) -> OcrEngine:
    if name == "macos-vision":
        try:
            from image_to_cash.ocr.macos_vision import MacVisionOcr
        except ImportError as error:
            raise OcrError("macos-vision OCR needs macOS with pyobjc-framework-Vision installed") from error
        return MacVisionOcr()
    if name == "windows-ocr":
        from image_to_cash.ocr.windows_ocr import WindowsOcr  # loads winrt only when it reads

        return WindowsOcr()
    raise ValueError(f"unknown OCR engine: {name!r} (available: {', '.join(ENGINES)})")


__all__ = ["DEFAULT_ENGINE", "ENGINES", "Box", "OcrEngine", "OcrError", "TextBox", "build_ocr"]
