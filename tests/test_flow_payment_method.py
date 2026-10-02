"""The Invoice's payment method exists before the Invoice is made, whichever way the run got there:
a created Debtor makes sure of it; a found Debtor and a resumed Order make sure of it too."""

import pytest

from image_to_cash.drive import flow
from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.product import Picked
from image_to_cash.drive.fakturama.resume import Earlier
from image_to_cash.normalized import normalize


class Log:
    def record(self, step, outcome, **details):
        pass


class Screen:
    def __init__(self, calls):
        self.calls = calls
        self.ui = self

    def bring_to_front(self):
        pass

    def check_errors(self):
        pass

    def shot(self, name):
        self.calls.append(f"shot {name}")


class Editor:
    def __init__(self, calls):
        self.calls = calls

    def complete_line(self, index, line):
        pass

    def activate(self):
        pass

    def check_totals(self, totals):
        pass

    def save(self):
        self.calls.append("order saved")
        return "PO1"


@pytest.fixture
def run(sample_order, monkeypatch):
    order = normalize(sample_order)
    calls = []
    editor = Editor(calls)
    monkeypatch.setattr(flow, "find_earlier", lambda ctx, order: Earlier())
    monkeypatch.setattr(flow.OrderEditor, "open", lambda ctx, order: editor)
    monkeypatch.setattr(flow, "create_debtor", lambda ctx, debtor, method: calls.append(f"debtor created with {method}"))
    monkeypatch.setattr(flow, "ensure_payment_method", lambda ctx, method: calls.append(f"made sure of {method}"))
    monkeypatch.setattr(flow, "select_product", lambda *args, **kwargs: Picked.SELECTED)
    monkeypatch.setattr(flow, "_debtor_still_selected", lambda editor, order: True)
    monkeypatch.setattr(flow, "check_order_listed", lambda ctx, order, number: None)
    monkeypatch.setattr(flow, "_invoice", lambda ctx, editor, order, number: calls.append("invoice") or flow.DriveResult(number, "INV1"))

    def go(selected_at_once):
        answers = iter([selected_at_once, True])
        monkeypatch.setattr(flow, "select_debtor", lambda ctx, editor, debtor: next(answers))
        flow._run(Context(Screen(calls), None, Log()), order)
        return calls

    return go


def test_a_found_debtor_makes_sure_of_the_method_before_the_order_is_saved(run):
    calls = run(selected_at_once=True)
    assert calls.index("made sure of Bank Transfer") < calls.index("order saved") < calls.index("invoice")


def test_a_created_debtor_already_made_sure_of_it(run):
    calls = run(selected_at_once=False)
    assert "debtor created with Bank Transfer" in calls
    assert not any(call.startswith("made sure of") for call in calls)


def test_a_resumed_order_makes_sure_of_the_method_before_its_invoice(sample_order, monkeypatch):
    order = normalize(sample_order)
    calls = []
    monkeypatch.setattr(flow, "reopen_order", lambda ctx, earlier: calls.append("reopened") or Editor(calls))
    monkeypatch.setattr(flow, "ensure_payment_method", lambda ctx, method: calls.append(f"made sure of {method}"))
    monkeypatch.setattr(flow, "_invoice", lambda ctx, editor, order, number: calls.append("invoice"))

    class Saved:
        number = "PO1"

    monkeypatch.setattr(flow, "find_earlier", lambda ctx, order: Earlier(order=Saved(), order_row=0))
    flow._run(Context(Screen(calls), None, Log()), order)
    assert calls == ["reopened", "made sure of Bank Transfer", "invoice"]
