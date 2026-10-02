"""Key chords written once, OS-neutrally ("primary+c"), and the macOS key codes they map to."""

from __future__ import annotations

from dataclasses import dataclass

MODIFIERS = frozenset({"primary", "shift", "alt", "ctrl"})  # primary is Cmd on macOS, Ctrl elsewhere

# macOS virtual key codes (ANSI layout) for the keys the bot presses.
MAC_KEY_CODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "o": 31, "u": 32,
    "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "return": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
    "home": 115, "end": 119, "left": 123, "right": 124, "down": 125, "up": 126, "f2": 120,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
}  # fmt: skip


@dataclass(frozen=True)
class Chord:
    key: str
    modifiers: frozenset[str]


def parse_chord(text: str) -> Chord:
    *mods, key = text.strip().lower().split("+")
    if not key:
        raise ValueError(f"no key in chord {text!r}")
    unknown = [mod for mod in mods if mod not in MODIFIERS]
    if unknown:
        raise ValueError(f"unknown modifier {unknown[0]!r} in chord {text!r}")
    if key not in MAC_KEY_CODES:
        raise ValueError(f"unsupported key {key!r} in chord {text!r}")
    return Chord(key, frozenset(mods))
