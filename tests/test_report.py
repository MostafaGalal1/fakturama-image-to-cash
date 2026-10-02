import json
from datetime import UTC, datetime

import pytest
from PIL import Image

from image_to_cash.drive.elements import Rect
from image_to_cash.drive.report import MARK_COLOUR, Outcome, RunLog, annotate


def fixed_clock() -> datetime:
    return datetime(2026, 10, 2, 9, 30, tzinfo=UTC)


def test_each_step_is_appended_as_one_json_line(tmp_path):
    log = RunLog(tmp_path / "run" / "steps.jsonl", clock=fixed_clock)
    first = log.record("vat", Outcome.FOUND, name="VAT 19%")
    log.record("order", Outcome.STOPPED, reason="total_mismatch")
    lines = (tmp_path / "run" / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"at": "2026-10-02T09:30:00+00:00", "step": "vat", "outcome": "found", "details": {"name": "VAT 19%"}},
        {"at": "2026-10-02T09:30:00+00:00", "step": "order", "outcome": "stopped", "details": {"reason": "total_mismatch"}},
    ]
    assert first.details == {"name": "VAT 19%"}


def test_recorded_details_cannot_be_changed_afterwards(tmp_path):
    step = RunLog(tmp_path / "steps.jsonl", clock=fixed_clock).record("vat", Outcome.CREATED, name="VAT 19%")
    with pytest.raises(TypeError):
        step.details["name"] = "other"


def test_annotation_marks_the_target_on_a_copy(tmp_path):
    shot = tmp_path / "shot.png"
    Image.new("RGB", (200, 100), "white").save(shot)  # a Retina capture: 2 pixels per point
    out = annotate(shot, area=Rect(100, 50, 100, 50), target=Rect(110, 60, 20, 10), label="Cust.Ref.", out=tmp_path / "marked.png")
    marked = Image.open(out).convert("RGB")
    assert marked.getpixel((20, 30)) == MARK_COLOUR  # left edge of the box, at 2x
    assert marked.getpixel((150, 90)) == (255, 255, 255)
    assert Image.open(shot).convert("RGB").getpixel((20, 30)) == (255, 255, 255)


def test_annotation_target_must_lie_inside_the_capture(tmp_path):
    shot = tmp_path / "shot.png"
    Image.new("RGB", (100, 100), "white").save(shot)
    with pytest.raises(ValueError, match="outside"):
        annotate(shot, area=Rect(0, 0, 100, 100), target=Rect(90, 90, 20, 20), label="x", out=tmp_path / "m.png")
