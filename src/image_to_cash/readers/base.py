"""Image-reader interface: any provider turns an order image into a schema-valid Order."""

from __future__ import annotations

from typing import Protocol

from PIL import Image
from pydantic import ValidationError

from image_to_cash.model import Order

MAX_ISSUES_SHOWN = 5


class ReaderError(RuntimeError):
    """The image reader could not produce a schema-valid Order."""


class ImageReader(Protocol):
    def read(self, image: Image.Image) -> Order:
        """Read an image already prepared by `imaging`: upright, RGB and upscaled.

        Must not modify `image` (copy it before resizing). Raises ReaderError when it cannot
        produce a schema-valid Order.
        """
        ...


def describe_validation_error(error: ValidationError) -> str:
    """A one-line summary of the first few problems, without the offending values.

    The values are left out because a reader's output can hold personal data.
    """
    issues = error.errors(include_url=False, include_context=False, include_input=False)
    shown = "; ".join(f"{_location(issue['loc'])}: {issue['msg']}" for issue in issues[:MAX_ISSUES_SHOWN])
    hidden = len(issues) - MAX_ISSUES_SHOWN
    return f"{shown} (+{hidden} more)" if hidden > 0 else shown


def _location(loc: tuple[str | int, ...]) -> str:
    return ".".join(str(part) for part in loc) or "<document>"
