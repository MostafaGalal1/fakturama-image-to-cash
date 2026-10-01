"""Image-reader interface: any provider turns an order image into a schema-valid Order."""

from __future__ import annotations

from typing import Protocol

from PIL import Image

from image_to_cash.model import Order


class ReaderError(RuntimeError):
    """The image reader could not produce a schema-valid Order."""


class ImageReader(Protocol):
    def read(self, image: Image.Image) -> Order:
        """Read an image already prepared by `imaging`: upright, RGB and upscaled."""
        ...
