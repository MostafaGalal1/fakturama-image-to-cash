import sys
from pathlib import Path

import pytest
from PIL import Image

from image_to_cash.model import Order
from image_to_cash.ocr import Box, TextBox
from image_to_cash.reconcile import critical_fields

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ORDER_JSON = FIXTURES / "sample_order.json"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)


class FakeOcr:
    """OCR stand-in that 'sees' exactly the given texts."""

    def __init__(self, texts: tuple[str, ...]) -> None:
        self._boxes = tuple(TextBox(text=text, box=Box(0, 0, 1, 1)) for text in texts)

    def recognize(self, image: Image.Image) -> tuple[TextBox, ...]:
        return self._boxes


@pytest.fixture
def sample_order_path() -> Path:
    return SAMPLE_ORDER_JSON


@pytest.fixture
def sample_order() -> Order:
    return Order.model_validate_json(SAMPLE_ORDER_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def ocr_seeing_everything(sample_order) -> FakeOcr:
    return FakeOcr(tuple(expected for _, expected in critical_fields(sample_order)))


@pytest.fixture
def ocr_missing_first_sku(sample_order) -> FakeOcr:
    first_sku = sample_order.items[0].sku
    return FakeOcr(tuple(e for _, e in critical_fields(sample_order) if e != first_sku))


@pytest.fixture
def order_image(tmp_path) -> Path:
    path = tmp_path / "order.png"
    Image.new("RGB", (40, 60), "white").save(path)
    return path
