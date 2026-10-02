import pytest

from image_to_cash.drive.backend.window_capture import WindowInfo, crop_box, window_for
from image_to_cash.drive.elements import Rect

FAKTURAMA = 2386
MAIN = WindowInfo(window_id=10, pid=FAKTURAMA, layer=0, bounds=Rect(12, 33, 1500, 872))
DIALOG = WindowInfo(window_id=11, pid=FAKTURAMA, layer=0, bounds=Rect(592, 211, 341, 387))
SPOTIFY = WindowInfo(window_id=12, pid=999, layer=0, bounds=Rect(0, 0, 1600, 1000))
TOOLTIP = WindowInfo(window_id=13, pid=FAKTURAMA, layer=101, bounds=Rect(0, 0, 1600, 1000))


def test_rect_containment():
    assert Rect(0, 0, 10, 10).contains(Rect(2, 2, 8, 8))
    assert not Rect(0, 0, 10, 10).contains(Rect(2, 2, 9, 8))


def test_area_is_captured_from_fakturamas_own_window_never_from_a_window_on_top():
    area = Rect(315, 125, 1197, 443)
    assert window_for(area, (SPOTIFY, TOOLTIP, MAIN), FAKTURAMA) is MAIN


def test_the_smallest_containing_window_wins():
    area = Rect(600, 250, 300, 300)
    assert window_for(area, (MAIN, DIALOG), FAKTURAMA) is DIALOG


def test_area_outside_every_fakturama_window_is_refused():
    with pytest.raises(ValueError, match="no Fakturama window contains"):
        window_for(Rect(1400, 800, 200, 200), (MAIN, SPOTIFY), FAKTURAMA)


def test_crop_box_scales_points_to_pixels():
    # A Retina capture of the main window is 3000 pixels wide: 2 pixels per point.
    assert crop_box(MAIN.bounds, Rect(315, 125, 1197, 443), image_width=3000) == (606, 184, 3000, 1070)
