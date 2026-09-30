import pytest

from app.theory import (
    Pitch,
    interval_name,
    key_base_alters,
    parse_note_name,
    spell_note_name,
    transpose_key,
    transpose_pitch,
    validate_interval,
)
from app.theory import MusicTheoryError


def t(step, alter, octave, L, S):
    return transpose_pitch(Pitch(step, alter, octave), L, S)


def test_basic_pitch_transposition_up_major_second():
    # C4 up M2 -> D4 (1 letter step, 2 semitones)
    p = t("C", 0, 4, 1, 2)
    assert (p.step, p.alter, p.octave) == ("D", 0, 4)


def test_bb_trumpet_written_to_concert():
    # written C4, Bb instrument (-1, -2) -> sounding Bb3
    p = t("C", 0, 4, -1, -2)
    assert p == Pitch("B", -1, 3)


def test_concert_to_bb_written():
    # concert Bb3 written as C4 on Bb trumpet: interval (+1,+2)
    p = t("B", -1, 3, 1, 2)
    assert p == Pitch("C", 0, 4)


def test_eb_alto():
    # written C4 -> sounding Eb3 (down M6 = -5,-9)
    p = t("C", 0, 4, -5, -9)
    assert p == Pitch("E", -1, 3)


def test_f_horn():
    # written C5 -> sounding F4 (down P5 = -4,-7)
    p = t("C", 0, 5, -4, -7)
    assert p == Pitch("F", 0, 4)


def test_preserves_accidental_spelling():
    # F#4 down m2 (-1,-1) -> E#4 (enharmonic, diatonic spelling kept)
    p = t("F", 1, 4, -1, -1)
    assert p == Pitch("E", 1, 4)


def test_octave_direction():
    # C4 up P8 (+7,+12) -> C5
    p = t("C", 0, 4, 7, 12)
    assert p == Pitch("C", 0, 5)
    # C4 down P8
    p = t("C", 0, 4, -7, -12)
    assert p == Pitch("C", 0, 3)


def test_invalid_intervals():
    with pytest.raises(MusicTheoryError):
        validate_interval(1, 6)   # augmented second on every letter -> triple
    with pytest.raises(MusicTheoryError):
        validate_interval(1, -1)  # sign mismatch
    with pytest.raises(MusicTheoryError):
        validate_interval(0, 5)
    with pytest.raises(MusicTheoryError):
        validate_interval(-3, -1)  # incompatible letter/semitone magnitude
    # augmented second (1,3) is a real interval and stays valid
    validate_interval(1, 3)


def test_note_name_parsing():
    assert parse_note_name("C4") == Pitch("C", 0, 4)
    assert parse_note_name("Bb3") == Pitch("B", -1, 3)
    assert parse_note_name("F#5") == Pitch("F", 1, 5)
    assert parse_note_name("Ebb4") == Pitch("E", -2, 4)
    assert parse_note_name("D𝄪6") == Pitch("D", 2, 6)
    with pytest.raises(MusicTheoryError):
        parse_note_name("H4")


def test_key_transposition_major():
    # Bb trumpet written->sounding (-1,-2); written key = concert key
    # transposed by the *opposite* interval (+1,+2)
    # concert C major -> written D major; concert F -> written G
    assert transpose_key(0, "major", 1, 2) == 2
    assert transpose_key(-1, "major", 1, 2) == 1


def test_key_transposition_eb_alto():
    # Eb alto written->sounding is down M6 (-5,-9); written key is concert
    # transposed up M6 (+5,+9): concert C -> written A major (3#)
    assert transpose_key(0, "major", 5, 9) == 3
    # concert Eb major (-3) -> written C major (0)
    assert transpose_key(-3, "major", 5, 9) == 0


def test_key_transposition_horn():
    # F horn written C5 sounds F4, i.e. written->sounding (+4,+7) in
    # register-neutral terms. A concert F-major part transposed to the horn
    # written part therefore moves notes/keys by -4,-7 at the same register:
    # concert F (1#) -> written C (0)
    assert transpose_key(1, "major", -4, -7) == 0
    # the reverse direction: written C -> sounding F-major key
    assert transpose_key(0, "major", 4, 7) == 1


def test_key_transposition_minor():
    # A minor (f=0 minor tonic A) transposed up M2 -> B minor (f=2)
    assert transpose_key(0, "minor", 1, 2) == 2


def test_key_base_alters():
    g = key_base_alters(1)
    assert g["F"] == 1 and g["C"] == 0
    df = key_base_alters(-3)
    assert df["B"] == -1 and df["E"] == -1 and df["A"] == -1


def test_interval_name():
    assert "纯一度" in interval_name(0, 0)
    name = interval_name(1, 2)
    assert "大" in name and "二度" in name
    name = interval_name(-4, -7)
    assert "纯" in name and "五度" in name


def test_spell_note_name():
    assert spell_note_name("B", -1, 3) == "Bb3"
    assert spell_note_name("E", 1, 4) == "E#4"
