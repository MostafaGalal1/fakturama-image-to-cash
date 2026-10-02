"""Unattended batch: every image ends in done/, review/ or stopped/, and a drive stop ends the batch."""

import json

import pytest

from image_to_cash.batch import run_batch
from image_to_cash.errors import NeedsReview


@pytest.fixture
def inbox(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    for name in ("a.png", "b.jpg", "c.png", "notes.txt"):
        (folder / name).write_bytes(b"x")
    return folder


def extract_all(image, folder):
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "order.json"


def test_each_image_is_driven_and_moved_to_done(inbox, tmp_path):
    out = tmp_path / "out"
    outcomes = run_batch(inbox, out, extract_all, lambda order, folder: "order PO1, invoice INV1")
    assert [(o.image, o.status) for o in outcomes] == [("a.png", "done"), ("b.jpg", "done"), ("c.png", "done")]
    assert sorted(p.name for p in (inbox / "done").iterdir()) == ["a.png", "b.jpg", "c.png"]
    assert (inbox / "notes.txt").exists()  # not an image: left alone
    assert len((out / "batch.jsonl").read_text().splitlines()) == 3


def test_an_image_needing_review_moves_on_without_touching_fakturama(inbox, tmp_path):
    driven = []
    outcomes = run_batch(
        inbox, tmp_path / "out", lambda image, folder: None if image.name == "a.png" else extract_all(image, folder),
        lambda order, folder: driven.append(order) or "ok",
    )
    assert [o.status for o in outcomes] == ["review", "done", "done"] and len(driven) == 2
    assert (inbox / "review" / "a.png").exists()


def test_a_drive_stop_ends_the_batch_and_leaves_the_rest_waiting(inbox, tmp_path):
    def drive(order, folder):
        raise NeedsReview("totals_mismatch", {"field": "Total"})

    outcomes = run_batch(inbox, tmp_path / "out", extract_all, drive)
    assert [(o.image, o.status) for o in outcomes] == [("a.png", "stopped")]
    assert (inbox / "stopped" / "a.png").exists() and (inbox / "b.jpg").exists()
    logged = json.loads((tmp_path / "out" / "batch.jsonl").read_text())
    assert logged["status"] == "stopped" and "totals_mismatch" in logged["detail"]


def test_an_unreadable_image_goes_to_review(inbox, tmp_path):
    def extract(image, folder):
        raise OSError("cannot identify image file")

    outcomes = run_batch(inbox, tmp_path / "out", extract, lambda order, folder: "ok")
    assert {o.status for o in outcomes} == {"review"}


def test_a_name_processed_before_does_not_overwrite(inbox, tmp_path):
    (inbox / "done").mkdir()
    (inbox / "done" / "a.png").write_bytes(b"old")
    run_batch(inbox, tmp_path / "out", extract_all, lambda order, folder: "ok")
    assert (inbox / "done" / "a.png").read_bytes() == b"old" and (inbox / "done" / "a-1.png").exists()
