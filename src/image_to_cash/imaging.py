"""Image preparation before reading (design §4, step 1)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

UPSCALE_FACTOR = 3
# Upscaling helps small screenshots; past this long edge it only costs memory and upload size.
MAX_LONG_EDGE = 4000
PAPER_WHITE = (255, 255, 255, 255)


def load_image(path: Path) -> Image.Image:
    """An upright RGB copy: EXIF rotation applied, transparency flattened onto white paper.

    Raises OSError for a missing or unreadable file and ValueError for an oversized one.
    """
    try:
        with Image.open(path) as source:
            return _flatten_to_rgb(ImageOps.exif_transpose(source))
    except Image.DecompressionBombError as error:
        raise ValueError(f"image too large to process safely: {path}") from error


def upscale(image: Image.Image, factor: int = UPSCALE_FACTOR) -> Image.Image:
    """Enlarge by `factor`, lowered so the long edge stays within MAX_LONG_EDGE; never shrinks."""
    if factor < 1:
        raise ValueError(f"upscale factor must be at least 1, got {factor}")
    capped = max(1, min(factor, MAX_LONG_EDGE // max(image.size)))
    return image.resize((image.width * capped, image.height * capped), Image.Resampling.LANCZOS)


def for_ocr(image: Image.Image) -> Image.Image:
    return ImageOps.grayscale(image).filter(ImageFilter.SHARPEN)


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if "A" not in image.getbands() and "transparency" not in image.info:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    return Image.alpha_composite(Image.new("RGBA", rgba.size, PAPER_WHITE), rgba).convert("RGB")
