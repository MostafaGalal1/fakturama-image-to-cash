from image_to_cash.drive.fakturama import lists
from image_to_cash.drive.fakturama.context import Context


class Results:
    """search_view stand-in: answers with the queued results, one per search."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.searches = 0

    def __call__(self, ctx, menu, text, parse):
        self.searches += 1
        return self.answers.pop(0)


def context(pauses: list[float]) -> Context:
    return Context(wb=None, ocr=None, log=None, sleep=pauses.append)


def test_a_row_saved_a_moment_ago_is_found_on_a_later_search(monkeypatch):
    search = Results((), ("VAT 19%",))
    monkeypatch.setattr(lists, "search_view", search)
    pauses = []
    rows = lists.search_until(context(pauses), ("Data", "VATs"), "VAT 19%", str, lambda rows: bool(rows))
    assert rows == ("VAT 19%",)
    assert search.searches == 2
    assert pauses == [lists.SETTLE_SECONDS]


def test_a_row_that_never_shows_up_returns_the_last_search(monkeypatch):
    search = Results((), (), ())
    monkeypatch.setattr(lists, "search_view", search)
    rows = lists.search_until(context([]), ("Data", "VATs"), "VAT 19%", str, lambda rows: bool(rows))
    assert rows == ()
    assert search.searches == lists.LIST_ATTEMPTS


def test_a_row_found_at_once_is_not_searched_again(monkeypatch):
    search = Results(("VAT 19%",))
    monkeypatch.setattr(lists, "search_view", search)
    pauses = []
    lists.search_until(context(pauses), ("Data", "VATs"), "VAT 19%", str, lambda rows: bool(rows))
    assert search.searches == 1
    assert pauses == []
