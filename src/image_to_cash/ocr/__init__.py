"""OCR engines behind one interface; `build_ocr` picks one by name."""

from image_to_cash.ocr.base import Box, OcrEngine, OcrError, TextBox

ENGINES = ("macos-vision",)


def build_ocr(name: str) -> OcrEngine:
    if name == "macos-vision":
        try:
            from image_to_cash.ocr.macos_vision import MacVisionOcr
        except ImportError as error:
            raise OcrError("macos-vision OCR needs macOS with pyobjc-framework-Vision installed") from error
        return MacVisionOcr()
    raise ValueError(f"unknown OCR engine: {name!r} (available: {', '.join(ENGINES)})")


__all__ = ["ENGINES", "Box", "OcrEngine", "OcrError", "TextBox", "build_ocr"]
