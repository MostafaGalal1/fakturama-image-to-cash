import sys

import pytest


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip_macos = pytest.mark.skip(reason="macOS only")
    for item in items:
        if "macos" in item.keywords:
            item.add_marker(skip_macos)
