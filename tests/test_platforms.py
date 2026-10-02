import sys

import pytest
from PIL import Image

from image_to_cash import cli
from image_to_cash.ocr import ENGINES, OcrError, build_ocr
from image_to_cash.ocr.windows_ocr import WindowsOcr


def test_drive_refuses_an_os_it_has_no_adapter_for(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="macOS and Windows"):
        cli._driver()


def test_windows_ocr_is_offered_and_built_anywhere():
    assert "windows-ocr" in ENGINES
    assert isinstance(build_ocr("windows-ocr"), WindowsOcr)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the message where winrt is missing")
def test_windows_ocr_off_windows_says_what_it_needs():
    with pytest.raises(OcrError, match="Windows 10"):
        WindowsOcr().recognize(Image.new("RGB", (10, 10), "white"))
