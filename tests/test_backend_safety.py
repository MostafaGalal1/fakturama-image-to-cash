import pytest

from image_to_cash.drive.backend.base import BackendError, UnsafeToAct
from image_to_cash.drive.backend.keys import MAC_KEY_CODES, MODIFIERS, WIN_MODIFIER_VK, WIN_VK_CODES, Chord, parse_chord
from image_to_cash.drive.backend.safety import (
    is_within,
    require_copied_text,
    require_frontmost,
    require_keyboard,
    wait_until_frontmost,
)

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
    for key in ("a", "c", "v", "s", "w", "tab", "return", "escape", "up", "down", "left", "right", "delete", "space", "home", "end", "f2", "0", "9"):
        assert key in MAC_KEY_CODES
        assert parse_chord(key).key == key



def test_windows_has_a_key_code_for_every_mac_key():
    assert set(WIN_VK_CODES) == set(MAC_KEY_CODES)
    assert set(WIN_MODIFIER_VK) == MODIFIERS


def test_windows_key_codes_match_the_keys_they_name():
    assert WIN_VK_CODES["a"] == 0x41 and WIN_VK_CODES["z"] == 0x5A and WIN_VK_CODES["7"] == 0x37
    assert WIN_VK_CODES["delete"] == 0x08  # the Mac's delete key is Backspace
    assert WIN_MODIFIER_VK["primary"] == WIN_MODIFIER_VK["ctrl"] == 0x11

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


def test_keyboard_input_needs_fakturama_active_and_owning_the_front_window():
    require_keyboard(FAKTURAMA, app_is_active=True, front_window_pid=FAKTURAMA, focused_app_pid=FAKTURAMA)
    with pytest.raises(UnsafeToAct, match="Fakturama is not the active app"):
        require_keyboard(FAKTURAMA, app_is_active=False, front_window_pid=FAKTURAMA, focused_app_pid=None)
    with pytest.raises(UnsafeToAct, match="front window is held by nothing"):
        require_keyboard(FAKTURAMA, app_is_active=True, front_window_pid=None, focused_app_pid=None)


def test_an_answered_focus_query_naming_another_app_stops_input():
    with pytest.raises(UnsafeToAct, match="keyboard focus is held by pid 77"):
        require_keyboard(FAKTURAMA, app_is_active=True, front_window_pid=FAKTURAMA, focused_app_pid=77)  # e.g. Spotlight


def test_an_unanswered_focus_query_leaves_the_decision_to_the_other_signals():
    require_keyboard(FAKTURAMA, app_is_active=True, front_window_pid=FAKTURAMA, focused_app_pid=None)


PARENTS = {"button": "toolbar", "toolbar": "window", "field": "editor", "editor": "window"}


@pytest.mark.parametrize(
    ("hit", "target", "inside"),
    [("field", "field", True), ("field", "editor", True), ("button", "field", False), (None, "field", False)],
)
def test_click_lands_only_on_the_target_or_its_children(hit, target, inside):
    assert is_within(hit, target, PARENTS.get) is inside


def test_copied_text_must_be_present():
    assert require_copied_text("true\tTax-free\n") == "true\tTax-free\n"
    for empty in (None, "", "  \n"):
        with pytest.raises(BackendError, match="no text was copied"):
            require_copied_text(empty)
