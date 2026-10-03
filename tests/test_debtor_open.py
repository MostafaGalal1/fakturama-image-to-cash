import pytest

from image_to_cash.drive.fakturama.context import Context
from image_to_cash.drive.fakturama.debtor import NEW_DEBTOR, open_new_debtor
from image_to_cash.errors import NeedsReview


class Ui:
    def __init__(self, calls):
        self.calls = calls

    def press(self, element):
        self.calls.append(("press", element))


class Wb:
    def __init__(self, nav_stop=None):
        self.calls = []
        self.ui = Ui(self.calls)
        self.nav_stop = nav_stop

    def click_nav(self, text, opened):
        self.calls.append(("nav", text))
        if self.nav_stop is not None:
            raise self.nav_stop

    def toolbar_button(self, help_text):
        return f"button:{help_text}"

    def wait_for_editor_tab(self, matches, what):
        self.calls.append(("wait", what, matches(NEW_DEBTOR), matches("Northstar Office GmbH & Co, Jonas Weber")))


class Log:
    def __init__(self):
        self.steps = []

    def record(self, step, outcome, **details):
        self.steps.append((step, outcome, details))


def test_the_left_panel_link_opens_the_new_debtor():
    wb, log = Wb(), Log()
    open_new_debtor(Context(wb, None, log))
    assert wb.calls == [("nav", "New Contact")]
    assert log.steps == []


def test_the_toolbar_contact_button_is_used_when_the_link_opens_something_else():
    """Seen in the Windows VM: the left panel's New Contact opened a saved Debtor."""
    wb, log = Wb(NeedsReview("navigation_failed", {"item": "New Contact"})), Log()
    open_new_debtor(Context(wb, None, log))
    assert wb.calls == [
        ("nav", "New Contact"),
        ("press", "button:Create a new contact"),
        ("wait", NEW_DEBTOR, True, False),
    ]
    assert [step for step, _, _ in log.steps] == ["new_contact_link"]


def test_other_stops_are_not_retried():
    wb = Wb(NeedsReview("dialog_open", {}))
    with pytest.raises(NeedsReview, match="dialog_open"):
        open_new_debtor(Context(wb, None, Log()))
    assert wb.calls == [("nav", "New Contact")]
