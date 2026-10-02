from image_to_cash.ocr.base import Box
from image_to_cash.ocr.windows_ocr import fit_factor, text_boxes, union


def test_a_thin_strip_is_enlarged_and_a_huge_image_shrunk():
    assert fit_factor(1700, 30, 10_000) == 2.0
    assert fit_factor(3000, 1744, 10_000) == 1.0
    assert fit_factor(6000, 1000, 3000) == 0.5


def test_an_enlarged_strip_that_would_be_too_wide_is_held_at_the_limit():
    factor = fit_factor(2000, 30, 3000)
    assert 2000 * factor == 3000


def test_a_line_spans_its_words():
    assert union([(10, 5, 30, 12), (50, 4, 20, 14)]) == (10, 4, 60, 14)


def test_boxes_come_back_in_the_original_pixels():
    boxes = text_boxes([("Qty.", (200, 10, 40, 20)), ("  ", (0, 0, 5, 5))], 2.0, 1700, 30)
    assert len(boxes) == 1
    assert (boxes[0].text, boxes[0].box) == ("Qty.", Box(100, 5, 20, 10))


def test_boxes_never_leave_the_image():
    (box,) = text_boxes([("edge", (-4, -2, 30, 50))], 1.0, 20, 30)
    assert box.box == Box(0, 0, 20, 30)
