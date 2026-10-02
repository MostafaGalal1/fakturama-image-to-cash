import pytest

from image_to_cash.drive.backend.base import UnsafeToAct
from image_to_cash.drive.backend.keys import MAC_KEY_CODES, Chord, parse_chord
from image_to_cash.drive.backend.safety import require_frontmost, wait_until_frontmost

FAKTURAMA = 2386


@pytest.mark.parametrize(
    ("text", "chord"),
    [
        ("tab", Chord("tab", frozenset())),
        ("primary+c", Chord("c", frozenset({"primary"}))),
        ("Shift+Tab", Chord("tab", frozenset({"shift"}))),
        ("primary+shift+s", Chord("s", frozenset({"primary", "shift"}))),
    ],
)
def test_chords_parse(text, chord):
    assert parse_chord(text) == chord


@pytest.mark.parametrize(("text", "problem"), [("", "no key"), ("primary+", "no key"), ("hyper+a", "modifier"), ("f13", "key"), ("a+b", "modifier")])
def test_bad_chords_are_rejected(text, problem):
    with pytest.raises(ValueError, match=problem):
        parse_chord(text)


def test_every_parseable_key_has_a_mac_key_code():
    for key in ("a", "c", "v", "s", "w", "tab", "return", "escape", "up", "down", "left", "right", "delete", "space", "home", "end"):
        assert key in MAC_KEY_CODES
        assert parse_chord(key).key == key


def test_input_is_allowed_only_while_fakturama_is_frontmost():
    require_frontmost(FAKTURAMA, FAKTURAMA)
    with pytest.raises(UnsafeToAct, match="pid 77 is frontmost"):
        require_frontmost(FAKTURAMA, 77)
    with pytest.raises(UnsafeToAct, match="no app is frontmost"):
        require_frontmost(FAKTURAMA, None)


class FakeClock:
    def __init__(self) -> None:
        self.slept = 0.0

    def sleep(self, seconds: float) -> None:
        self.slept += seconds


def test_waits_until_fakturama_comes_to_the_front():
    answers = iter([77, 77, FAKTURAMA])
    clock = FakeClock()
    wait_until_frontmost(FAKTURAMA, lambda: next(answers), sleep=clock.sleep, timeout=2.0, poll=0.1)
    assert clock.slept == pytest.approx(0.2)


def test_gives_up_when_fakturama_never_comes_to_the_front():
    clock = FakeClock()
    with pytest.raises(UnsafeToAct):
        wait_until_frontmost(FAKTURAMA, lambda: 77, sleep=clock.sleep, timeout=1.0, poll=0.25)
    assert clock.slept == pytest.approx(1.0)
