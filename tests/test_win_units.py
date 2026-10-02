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


def test_a_windowless_child_reported_in_points_is_scaled_into_its_parent():
    # SWT's tab items at 200%: the "Documents" tab says (306,497)-(440,517) inside a folder at
    # (612,994)-(3024,1572) pixels; it means points.
    scale = Scale.from_dpi(192)
    assert scale.child_frame((306, 497, 440, 517), (612, 994, 3024, 1572)) == (612, 994, 880, 1034)


def test_a_child_already_in_pixels_is_left_alone():
    scale = Scale.from_dpi(192)
    assert scale.child_frame((2856, 996, 2895, 1034), (612, 994, 3024, 1572)) == (2856, 996, 2895, 1034)


def test_a_child_that_fits_neither_way_is_left_alone():
    scale = Scale.from_dpi(192)
    assert scale.child_frame((10, 10, 20, 20), (612, 994, 3024, 1572)) == (10, 10, 20, 20)
