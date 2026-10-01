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
    rect = observation.boundingBox()  # normalised, origin bottom-left
    box = Box(
        x=round(rect.origin.x * width),
        y=round((1 - rect.origin.y - rect.size.height) * height),
        width=round(rect.size.width * width),
        height=round(rect.size.height * height),
    )
    return TextBox(text=str(candidate.string()), box=box, confidence=float(candidate.confidence()))
