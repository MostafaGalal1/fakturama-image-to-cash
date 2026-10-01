"""Image preparation before reading (design §4, step 1)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

UPSCALE_FACTOR = 3


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def upscale(image: Image.Image, factor: int = UPSCALE_FACTOR) -> Image.Image:
    return image.resize((image.width * factor, image.height * factor), Image.Resampling.LANCZOS)


def for_ocr(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image).filter(ImageFilter.SHARPEN)
