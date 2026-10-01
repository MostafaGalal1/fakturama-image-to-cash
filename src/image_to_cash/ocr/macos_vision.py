"""macOS Vision framework OCR adapter (local, no setup)."""

from __future__ import annotations

import io

import Vision
from Foundation import NSData
from PIL import Image

from image_to_cash.ocr.base import Box, OcrError, TextBox


class MacVisionOcr:
    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]:
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(False)
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(_png_data(image), None)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OcrError(f"Vision text recognition failed: {error}")
        observations = request.results() or []
        boxes = (_to_text_box(observation, image.width, image.height) for observation in observations)
        return tuple(box for box in boxes if box is not None)


def vision_rect_to_box(x: float, y: float, w: float, h: float, width: int, height: int) -> Box:
    """Vision's normalised rect (origin bottom-left) as a top-left pixel box inside the image."""
    left = _clamp(round(x * width), width)
    right = _clamp(round((x + w) * width), width)
    top = _clamp(round((1 - y - h) * height), height)
    bottom = _clamp(round((1 - y) * height), height)
    return Box(x=left, y=top, width=right - left, height=bottom - top)


def _png_data(image: Image.Image) -> NSData:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    return NSData.dataWithBytes_length_(raw, len(raw))


def _to_text_box(observation, width: int, height: int) -> TextBox | None:
    candidates = observation.topCandidates_(1)
    if not candidates:
        return None
    candidate = candidates[0]
    rect = observation.boundingBox()
    box = vision_rect_to_box(rect.origin.x, rect.origin.y, rect.size.width, rect.size.height, width, height)
    return TextBox(text=str(candidate.string()), box=box, confidence=float(candidate.confidence()))


def _clamp(value: int, limit: int) -> int:
    return min(max(value, 0), limit)
