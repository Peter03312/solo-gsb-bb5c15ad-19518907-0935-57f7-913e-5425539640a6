"""End-to-end tests for the transposition engine."""

from __future__ import annotations

import pytest
from lxml import etree

from app.musicxml import analyze_parts, parse_score
from app.theory import MusicTheoryError
from app.transposer import (
    OutOfRangeError,
    TransposeParams,
    build_transposed_score,
    serialize,
    transpose_hint,
)

from .helpers import make_xml


def run(measures, *, src=(0, 0), dst=(-1, -2), rng=("C3", "C6"), fifths=0, **kw):
    data = make_xml(measures, fifths=fifths, **kw)
    root = parse_score(data)
    parts = analyze_parts(root)
    params = TransposeParams(
        src[0], src[1], dst[0], dst[1], rng[0], rng[1]
    )
    out_tree, meta = build_transposed_score(root, parts[0].part_id, params)
    return out_tree, meta


def collect_pitches(part):
    rows = []
    for m in part.findall("measure"):
        for note in m.findall("note"):
            p = note.find("pitch")
            if p is None:
                rows.append(("rest", None))
                continue
            alter = p.find("alter")
            rows.append(
                (
                    p.find("step").text,
                    int(alter.text) if alter is not None else 0,
                    int(p.find("octave").text),
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Sounding-pitch preservation
# ---------------------------------------------------------------------------

def test_sounding_pitches_preserved_bb_trumpet():
    # concert score C4 D4 E4 -> trumpet written D4 E4 F#4 (sounding identical)
    src = (0, 0)   # concert instrument
    dst = (-1, -2)  # Bb trumpet written->sounding
    out, meta = run(
        [[
            {"step": "C", "octave": 4},
            {"step": "D", "octave": 4},
            {"step": "E", "octave": 4},
        ]],
        src=src, dst=dst,
    )
    part = out.find("part")
    written = collect_pitches(part)
    # written notes
    assert written[:3] == [("D", 0, 4), ("E", 0, 4), ("F", 1, 4)]
    # applying the instrument interval must recover the original pitches
    from app.theory import Pitch, transpose_pitch
    sounding = [transpose_pitch(Pitch(*w), dst[0], dst[1]) for w in written[:3]]
    assert [p.name() for p in sounding] == ["C4", "D4", "E4"]
    assert meta["measures"] == 1
    assert meta["notes"] == 3


def test_sounding_pitches_preserved_eb_alto():
    # written C5 for alto sounds Eb4 (down M6 -5,-9); converting a concert
    # part to alto uses +5,+9
    out, meta = run(
        [[{"step": "C", "octave": 4}, {"step": "E", "alter": -1, "octave": 4}]],
        src=(0, 0), dst=(-5, -9),
    )
    written = collect_pitches(out.find("part"))
    from app.theory import Pitch, transpose_pitch
    sounding = [transpose_pitch(Pitch(*w), -5, -9) for w in written]
    assert [p.name() for p in sounding] == ["C4", "Eb4"]
    # concert C -> alto written A ; concert Eb -> alto written C
    assert written == [("A", 0, 4), ("C", 0, 5)]


def test_key_signature_transposed():
    out, _ = run([[
        {"step": "F", "octave": 4},
    ]], src=(0, 0), dst=(-1, -2), fifths=-1)  # F major concert
    key = out.find(".//part/measure/attributes/key/fifths")
    assert int(key.text) == 1  # G major for trumpet
    # no accidental needed on the F# note because the key supplies it
    note = out.find(".//note")
    assert note.find("accidental") is None
    p = note.find("pitch")
    assert p.find("step").text == "G"


def test_chord_notes_all_transposed():
    out, _ = run([[
        {"step": "C", "octave": 4},
        {"step": "E", "octave": 4, "chord": True},
        {"step": "G", "octave": 4, "chord": True},
    ]])
    pitches = collect_pitches(out.find("part"))
    assert pitches == [("D", 0, 4), ("F", 1, 4), ("A", 0, 4)]


def test_measure_rest_and_repeat_preserved():
    data = make_xml([
        [{"step": "C", "octave": 4}, {"rest": True}],
        [{"rest": True}],
    ])
    # insert a repeat barline on measure 1
    root = etree.fromstring(data)
    m1 = root.find("part/measure")
    barline = etree.SubElement(m1, "barline", location="right")
    etree.SubElement(barline, "repeat", direction="forward")
    out, meta = build_transposed_score(
        root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
    )
    assert len(out.findall(".//measure")) == 2
    assert out.find(".//repeat") is not None
    # the rest survives
    rests = out.findall(".//note/rest")
    assert len(rests) == 2


def test_ties_pair_keeps_same_written_pitch():
    out, _ = run([
        [{"step": "C", "octave": 4, "ties": ["start"]}],
        [{"step": "C", "octave": 4, "ties": ["stop"]}],
    ], dst=(-1, -2))
    notes = out.findall(".//note")
    written = collect_pitches(out.find("part"))
    assert written[0] == written[1]
    assert written[0] == ("D", 0, 4)
    # continuation note carries no new accidental
    assert notes[1].find("accidental") is None


def test_broken_tie_rejected():
    data = make_xml([[
        {"step": "C", "octave": 4, "ties": ["start"]},
    ]])
    root = parse_score(data)
    with pytest.raises(MusicTheoryError):
        build_transposed_score(
            root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
        )


def test_tie_pitch_mismatch_rejected():
    data = make_xml([
        [{"step": "C", "octave": 4, "ties": ["start"]}],
        [{"step": "D", "octave": 4, "ties": ["stop"]}],
    ])
    root = parse_score(data)
    with pytest.raises(MusicTheoryError):
        build_transposed_score(
            root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
        )


def test_unpitched_rejected():
    data = make_xml([[
        {"step": "C", "octave": 4},
        {"unpitched": True},
    ]])
    root = parse_score(data)
    parts = analyze_parts(root)
    assert parts[0].has_unpitched
    with pytest.raises(MusicTheoryError):
        build_transposed_score(
            root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
        )


def test_out_of_range_lists_measures_and_pitches():
    data = make_xml([
        [{"step": "C", "octave": 4}],
        [{"step": "B", "octave": 3}],
    ])
    root = parse_score(data)
    with pytest.raises(OutOfRangeError) as exc:
        build_transposed_score(
            root, "P1", TransposeParams(0, 0, -1, -2, "E4", "C6"),
        )
    violations = exc.value.violations
    measures = {v["measure"] for v in violations}
    assert measures == {"1", "2"}
    # C4 -> D4 and B3 -> C#4; both are below the E4 written floor
    names = {v["pitch"] for v in violations}
    assert names == {"D4", "C#4"}
    assert all(v["direction"] == "低于下限" for v in violations)


def test_invalid_range_rejected():
    data = make_xml([[{"step": "C", "octave": 4}]])
    root = parse_score(data)
    with pytest.raises(MusicTheoryError):
        build_transposed_score(
            root, "P1", TransposeParams(0, 0, -1, -2, "C6", "C3"),
        )


def test_corrupt_xml_rejected():
    with pytest.raises(MusicTheoryError):
        parse_score(b"<score-partwise><part")


def test_timewise_rejected():
    data = b"""<score-timewise version="3.1"/>"""
    with pytest.raises(MusicTheoryError):
        parse_score(data)


def test_transpose_hint_values():
    # written->written note interval for converting to a Bb part is +1,+2
    assert transpose_hint(1, 2) == (1, 2, 0)
    # to Eb alto: +5,+9 folds into up m3 + one octave
    assert transpose_hint(5, 9) == (-2, -3, 1)
    # to F horn: -4,-7 already compact
    assert transpose_hint(-4, -7) == (-4, -7, 0)
    # to piccolo written (part is an octave above concert): +7,+12 -> oc +1
    assert transpose_hint(7, 12) == (0, 0, 1)
    # to double-bass written (part is an octave below concert): -7,-12
    assert transpose_hint(-7, -12) == (0, 0, -1)


def test_output_is_single_part_with_transpose_element():
    data = make_xml([[{"step": "C", "octave": 4}]])
    root = parse_score(data)
    out, _ = build_transposed_score(
        root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
    )
    assert len(out.findall("part")) == 1
    tr = out.find(".//transpose")
    assert tr is not None
    assert int(tr.findtext("diatonic")) == 1
    assert int(tr.findtext("chromatic")) == 2
    # serialized output is valid XML
    payload = serialize(out)
    etree.fromstring(payload)


def test_accidentals_reset_per_measure():
    # Source is C major (0#). To Bb trumpet, key becomes D major (F#, C#).
    # A#4 in m.1 -> B#5, not in the D-major key -> sharp accidental shown.
    # B4 in m.2 -> C#5, IS in the D-major key -> no accidental.
    data = make_xml([
        [{"step": "A", "alter": 1, "octave": 4}],
        [{"step": "B", "octave": 4}],
    ], fifths=0)
    root = parse_score(data)
    out, _ = build_transposed_score(
        root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
    )
    notes = out.findall(".//note")
    first_pitch = notes[0].find("pitch")
    assert (
        first_pitch.find("step").text,
        int(first_pitch.find("alter").text),
        int(first_pitch.find("octave").text),
    ) == ("B", 1, 4)
    assert notes[0].find("accidental") is not None
    # C#5 in m.2 is supplied by the D-major key signature
    second_pitch = notes[1].find("pitch")
    assert second_pitch.find("step").text == "C"
    assert int(second_pitch.find("alter").text) == 1
    assert int(second_pitch.find("octave").text) == 5
    assert notes[1].find("accidental") is None


def test_identity_interval_preserves_everything():
    # C instrument to C instrument: same written notes, key and accidentals
    data = make_xml([[
        {"step": "B", "alter": -1, "octave": 4},
        {"step": "F", "octave": 4, "chord": True},
    ]], fifths=-1)
    root = parse_score(data)
    out, meta = build_transposed_score(
        root, "P1", TransposeParams(0, 0, 0, 0, "C3", "C6"),
    )
    written = collect_pitches(out.find("part"))
    assert written == [("B", -1, 4), ("F", 0, 4)]
    assert int(out.findtext(".//key/fifths")) == -1


def test_midmeasure_key_change_transposes():
    # key change in measure 2: F major -> C major; to Bb trumpet -> G -> D
    data = make_xml([
        [{"step": "F", "octave": 4}],
        [{"step": "C", "octave": 5}],
    ], fifths=-1)
    root = parse_score(data)
    m2 = root.findall(".//measure")[1]
    attrs = etree.Element("attributes")
    key = etree.SubElement(attrs, "key")
    etree.SubElement(key, "fifths").text = "0"
    etree.SubElement(key, "mode").text = "major"
    m2.insert(0, attrs)
    out, _ = build_transposed_score(
        root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
    )
    keys = [int(k.text) for k in out.findall(".//key/fifths")]
    assert keys == [1, 2]   # F->G, C->D


def test_cross_measure_tie_no_repeated_accidental():
    # source note outside the target key signature so a sharp would be needed
    # on a fresh note, but the tie continuation must not carry one
    data = make_xml([
        [{"step": "A", "alter": 1, "octave": 4, "ties": ["start"]}],
        [{"step": "A", "alter": 1, "octave": 4, "ties": ["stop"]}],
    ], fifths=0)
    root = parse_score(data)
    out, _ = build_transposed_score(
        root, "P1", TransposeParams(0, 0, -1, -2, "C3", "C6"),
    )
    notes = out.findall(".//note")
    written = collect_pitches(out.find("part"))
    assert written[0] == written[1]
    assert notes[0].find("accidental") is not None
    assert notes[1].find("accidental") is None
