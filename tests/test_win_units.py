import pytest

from image_to_cash.drive.backend.win_units import Scale, menu_label
from image_to_cash.drive.elements import Rect


def test_frames_at_150_percent_become_points():
    scale = Scale.from_dpi(144)
    assert scale.to_points(300, 150, 450, 180) == Rect(200, 100, 100, 20)
    assert scale.to_pixels(200, 100) == (300, 150)


def test_at_100_percent_pixels_are_points():
    assert Scale.from_dpi(96).to_points(10, 20, 110, 41) == Rect(10, 20, 100, 21)


def test_a_broken_dpi_is_refused():
    with pytest.raises(ValueError):
        Scale.from_dpi(0)


@pytest.mark.parametrize(
    ("raw", "shown"),
    [("&File", "File"), ("Close &All\tCtrl+Shift+W", "Close All"), ("terms of payment", "terms of payment"), ("Save && Close", "Save & Close")],
)
def test_menu_labels_lose_their_mnemonics_and_shortcuts(raw, shown):
    assert menu_label(raw) == shown
