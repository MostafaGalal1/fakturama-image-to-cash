import sys
from pathlib import Path

import pytest

from image_to_cash.model import Order

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ORDER_JSON = FIXTURES / "sample_order.json"


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)


@pytest.fixture
def sample_order_path() -> Path:
    return SAMPLE_ORDER_JSON


@pytest.fixture
def sample_order() -> Order:
    return Order.model_validate_json(SAMPLE_ORDER_JSON.read_text(encoding="utf-8"))
