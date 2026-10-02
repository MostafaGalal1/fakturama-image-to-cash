from decimal import Decimal

import pytest
from fake_backend import FakeBackend

from image_to_cash.drive.actions import set_text
from image_to_cash.drive.elements import Element, Rect, Role
from image_to_cash.drive.formats import GERMAN, parse_amount
from image_to_cash.drive.locate import LocatorError
from image_to_cash.drive.waits import WaitTimeout, wait_until
from image_to_cash.errors import NeedsReview

FIELD = Element(Role.TEXT_FIELD, Rect(10, 10, 100, 20), value="")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_text_is_replaced_typed_committed_and_read_back():
    backend = FakeBackend()
    shown = set_text(backend, FIELD, "PO-2026-0714", label="Cust.Ref.")
    assert shown.value == "PO-2026-0714"
    assert backend.calls == [
        ("click", FIELD.rect),
        ("key", "primary+a"),
        ("type", "PO-2026-0714"),
        ("key", "tab"),
    ]


def test_a_formatted_value_is_accepted_when_it_means_the_same():
    backend = FakeBackend(display=lambda typed: f"{typed} €")
    shown = set_text(
        backend, FIELD, "297,50", label="Price (gross)", holds=lambda v: parse_amount(v, GERMAN) == Decimal("297.50")
    )
    assert shown.value == "297,50 €"


def test_a_field_that_will_not_hold_its_value_is_retried_once_then_stops():
    backend = FakeBackend(display=lambda typed: "")
    with pytest.raises(NeedsReview, match="field_wont_hold: field=Cust.Ref."):
        set_text(backend, FIELD, "PO-2026-0714", label="Cust.Ref.")
    assert [call for call in backend.calls if call[0] == "type"] == [("type", "PO-2026-0714")] * 2


def test_the_stop_reason_names_the_field_but_not_the_value():
    backend = FakeBackend(display=lambda typed: "")
    with pytest.raises(NeedsReview) as raised:
        set_text(backend, FIELD, "marta.klein@example.com", label="E-Mail")
    assert "marta.klein" not in str(raised.value)


def test_wait_returns_the_first_truthy_probe_result():
    clock = FakeClock()
    answers = iter([None, None, "ready"])
    assert wait_until(lambda: next(answers), what="editor", timeout=5, poll=0.5, sleep=clock.sleep, clock=clock.monotonic) == "ready"
    assert clock.now == pytest.approx(1.0)


def test_wait_treats_listed_errors_as_not_ready_yet():
    clock = FakeClock()
    attempts = iter([LocatorError("not drawn yet"), "found"])

    def probe():
        answer = next(attempts)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert wait_until(probe, what="field", timeout=5, ignoring=(LocatorError,), sleep=clock.sleep, clock=clock.monotonic) == "found"


def test_wait_times_out_with_what_it_waited_for():
    clock = FakeClock()
    with pytest.raises(WaitTimeout, match="the Save Parts dialog"):
        wait_until(lambda: None, what="the Save Parts dialog", timeout=2, poll=0.5, sleep=clock.sleep, clock=clock.monotonic)
    assert clock.now == pytest.approx(2.0)


def test_unlisted_errors_are_not_swallowed():
    with pytest.raises(ZeroDivisionError):
        wait_until(lambda: 1 / 0, what="anything", timeout=1)
