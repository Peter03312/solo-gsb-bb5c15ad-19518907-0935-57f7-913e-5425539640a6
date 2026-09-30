"""Pure music-theory helpers for written-pitch transposition.

Convention used throughout the application
------------------------------------------
For a transposing instrument the user provides the interval from a *written*
note to the *sounding* note as:

* ``L`` -- directed diatonic letter steps (written letter -> sounding letter),
  each step-name (A..G) counting as one, octaves included
  (written C4 -> sounding Bb3 => L = -1);
* ``S`` -- directed chromatic semitone count for that same interval,
  in the same octave direction (C4 -> Bb3 => S = -2).

Transposing a part written for instrument A into the written notation of
instrument B while keeping the sounding pitch identical is therefore

    written_b = written_a + (L_src - L_dst, S_src - S_dst).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LETTER_INDEX = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
INDEX_LETTER = {v: k for k, v in LETTER_INDEX.items()}

# semitone offset of the natural letter inside an octave (C major diatonic scale)
NATURAL_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]  # fifths 1..7
FLAT_ORDER = list(reversed(SHARP_ORDER))            # B,E,A,D,G,C,F


class MusicTheoryError(ValueError):
    """Raised when user-supplied musical parameters cannot be honoured."""


@dataclass(frozen=True)
class Pitch:
    """A concrete spelled pitch, mirroring a MusicXML <pitch>."""

    step: str
    alter: int          # semitones: -2 bb, -1 b, 0 natural, 1 #, 2 x
    octave: int

    @property
    def letter_index(self) -> int:
        return LETTER_INDEX[self.step]

    @property
    def midi(self) -> int:
        return (self.octave + 1) * 12 + NATURAL_SEMI[self.step] + self.alter

    @property
    def diatonic_index(self) -> int:
        """Letter count above C0; C4 -> 28."""
        return self.octave * 7 + LETTER_INDEX[self.step]

    def name(self) -> str:
        return spell_note_name(self.step, self.alter, self.octave)


# ---------------------------------------------------------------------------
# Interval validity
# ---------------------------------------------------------------------------

def _natural_delta_up(start_index: int, steps: int) -> int:
    """Semitone distance from a natural letter up ``steps`` letter steps."""
    end_index = start_index + steps
    return (
        NATURAL_SEMI[INDEX_LETTER[end_index % 7]]
        - NATURAL_SEMI[INDEX_LETTER[start_index % 7]]
        + 12 * (end_index // 7 - start_index // 7)
    )


def validate_interval(L: int, S: int) -> None:
    """Reject (L, S) pairs that cannot be written with ordinary accidentals.

    For every possible starting letter the resulting alteration must lie in
    [-2, 2] (double flat .. double sharp), and the letter/semitone directions
    must agree.
    """
    if not isinstance(L, int) or not isinstance(S, int):
        raise MusicTheoryError("音程的字母步数与半音数必须为整数。")
    if L == 0 and S == 0:
        return
    if L == 0 or S == 0 or (L > 0) != (S > 0):
        raise MusicTheoryError(
            f"无效音程：字母步数 {L:+d} 与半音数 {S:+d} 方向或大小不一致。"
        )
    # A written interval is usable only if *some* diatonic spelling exists
    # without accidentals beyond double sharp/flat. Checking the seven
    # possible starting letters (alter 0) is equivalent to checking all
    # pitches, because a pre-existing alter shifts every result identically.
    for start in range(7):
        end_idx = start + L
        new_natural = NATURAL_SEMI[INDEX_LETTER[end_idx % 7]] + 12 * (
            end_idx // 7
        )
        start_natural = NATURAL_SEMI[INDEX_LETTER[start]]
        alter_needed = start_natural + S - new_natural
        if alter_needed < -2 or alter_needed > 2:
            raise MusicTheoryError(
                f"无效音程：字母步数 {L:+d} 与半音数 {S:+d} 不构成可用常规"
                "升降号（重降/重升以内）书写的音程。"
            )


def transpose_pitch(pitch: Pitch, L: int, S: int) -> Pitch:
    """Return the spelled pitch ``L`` letter-steps / ``S`` semitones away."""
    if L == 0 and S == 0:
        return pitch
    idx = pitch.diatonic_index + L
    new_letter = INDEX_LETTER[idx % 7]
    new_oct = idx // 7
    # The alteration is forced by the requirement that the new MIDI pitch
    # equals the old MIDI pitch plus S.
    new_alter = pitch.midi + S - ((new_oct + 1) * 12 + NATURAL_SEMI[new_letter])
    if new_alter < -2 or new_alter > 2:
        raise MusicTheoryError(
            f"音程（字母 {L:+d} / 半音 {S:+d}）使音符 {pitch.name()} "
            "超出重降到重升的可记写范围，请检查乐器音程方向与大小。"
        )
    return Pitch(new_letter, int(new_alter), new_oct)


# ---------------------------------------------------------------------------
# Interval naming (used for on-screen confirmation only)
# ---------------------------------------------------------------------------

_PERFECT_GROUP = {0, 3, 4}  # unison, fourth, fifth within an octave
_DEGREE_NAMES = {
    1: "一度", 2: "二度", 3: "三度", 4: "四度",
    5: "五度", 6: "六度", 7: "七度", 8: "八度",
}


def interval_name(L: int, S: int) -> str:
    if L == 0 and S == 0:
        return "纯一度（同音高）"
    steps = abs(L)               # letter steps: unison 0, second 1, ...
    degree = steps % 7 + 1
    compound = steps // 7
    # generic natural interval from C over ``steps`` letter steps
    base = _natural_delta_up(0, steps)
    delta = abs(S) - base  # natural perfect/major intervals -> 0
    if (degree - 1) in _PERFECT_GROUP:
        quality = {
            -2: "倍减", -1: "减", 0: "纯", 1: "增", 2: "倍增",
        }.get(delta, "")
    else:
        # natural letter interval is major; -1 is minor, -2 diminished ...
        quality = {
            -3: "倍减", -2: "减", -1: "小", 0: "大", 1: "增", 2: "倍增",
        }.get(delta, "")
    name = f"{quality}{_DEGREE_NAMES[degree]}"
    if compound:
        name = f"隔{compound}个八度的{name}" if compound > 1 else f"{name}（含八度）"
    direction = "上行" if L > 0 else "下行"
    return f"{direction}{name}"


# ---------------------------------------------------------------------------
# Key signatures
# ---------------------------------------------------------------------------

def _major_tonic_letter(f: int) -> str:
    return INDEX_LETTER[(f * 4) % 7]


def _major_tonic_pc(f: int) -> int:
    return f * 7 % 12


def transpose_key(fifths: int, mode: str, L: int, S: int) -> int:
    """Return the new circle-of-fifths value after transposition."""
    minor = mode == "minor"
    if minor:
        # minor tonic letter/pitch class from relative major
        letter_i = (LETTER_INDEX[_major_tonic_letter(fifths)] - 2) % 7
        pc = (_major_tonic_pc(fifths) - 3) % 12
    else:
        letter_i = LETTER_INDEX[_major_tonic_letter(fifths)]
        pc = _major_tonic_pc(fifths)
    # The written key is transposed by the same written->written interval
    # applied to every note, so its tonic letter/pitch class moves by (L, S).
    new_letter_i = (letter_i + L) % 7
    new_pc = (pc + S) % 12
    for f2 in range(-7, 8):
        if minor:
            l2 = (LETTER_INDEX[_major_tonic_letter(f2)] - 2) % 7
            p2 = (_major_tonic_pc(f2) - 3) % 12
        else:
            l2 = LETTER_INDEX[_major_tonic_letter(f2)]
            p2 = _major_tonic_pc(f2)
        if l2 == new_letter_i and p2 == new_pc:
            return f2
    raise MusicTheoryError(
        "按该音程转换后的调号超出七个升降号范围，无法用常规调号书写。"
    )


def key_base_alters(fifths: int) -> dict[str, int]:
    """Default alteration of every letter under a key signature."""
    alters: dict[str, int] = {l: 0 for l in LETTER_INDEX}
    if fifths > 0:
        for letter in SHARP_ORDER[: fifths]:
            alters[letter] = 1
    elif fifths < 0:
        for letter in FLAT_ORDER[: -fifths]:
            alters[letter] = -1
    return alters


# ---------------------------------------------------------------------------
# Note-name parsing (target written range input)
# ---------------------------------------------------------------------------

_NOTE_RE = re.compile(
    r"^\s*([A-Ga-g])\s*"
    r"(x|𝄪|##|♯♯|bb|𝄫|♭♭|#|♯|b|♭|)?"
    r"\s*(-?\d+)\s*$"
)

_ALTER_TEXT = {
    "": 0, "#": 1, "b": -1, "##": 2, "x": 2, "bb": -2,
    "♯": 1, "♭": -1, "♯♯": 2, "𝄪": 2, "♭♭": -2, "𝄫": -2,
}


def parse_note_name(text: str) -> Pitch:
    m = _NOTE_RE.match(text or "")
    if not m:
        raise MusicTheoryError(
            f"无法识别的音名 “{text}”，请使用如 C4、Bb3、F#5 的格式。"
        )
    step = m.group(1).upper()
    alter = _ALTER_TEXT[m.group(2) or ""]
    octave = int(m.group(3))
    return Pitch(step, alter, octave)


def spell_note_name(step: str, alter: int, octave: int) -> str:
    symbol = {2: "x", 1: "#", 0: "", -1: "b", -2: "bb"}.get(alter, f"({alter})")
    return f"{step}{symbol}{octave}"


ACCIDENTAL_TEXT = {
    2: "double-sharp",
    1: "sharp",
    0: "natural",
    -1: "flat",
    -2: "flat-flat",
}
