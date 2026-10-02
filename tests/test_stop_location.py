"""An unexpected stop names the code that failed, in this package only."""

import pytest

from image_to_cash.drive.backend.win_units import Scale
from image_to_cash.drive.flow import where


def test_where_names_the_package_frame_that_failed():
    with pytest.raises(ValueError) as caught:
        Scale.from_dpi(0)
    assert where(caught.value).startswith("win_units.py:")
    assert "test_stop_location" not in where(caught.value)
