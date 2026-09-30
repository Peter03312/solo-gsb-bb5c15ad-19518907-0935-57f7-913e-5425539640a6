"""端到端测试：转换正确性 + 各类拒绝条件。

语义约定（与界面文案一致）：
  src / dst = 该乐器“记谱音 -> 实际发声音”的【完整】有向音程 (字母步数, 半音数)，
  含真实八度差。
  例：中音萨克斯记谱 A4 实际发 C4（大六度下行）-> (-5, -9)；
      Bb 小号记谱 D4 实际发 C4（小二度下行）-> (-1, -2)；
      低音提琴记谱比实高高八度 -> (-7, -12)。
  新记谱音 = 旧记谱音 + (src - dst)。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app import service
from app.mx import (
    ScoreError, ValidationError, RangeExceeded,
    localname, find_child, find_children, child_text,
)
from app.intervals import pitch_midi
from tests.make_fixtures import main as build_fixtures

FX = Path(__file__).parent / "fixtures"


def setup_module(_):
    build_fixtures()


def read(name):
    return (FX / name).read_bytes()


def pitches_of(xml_bytes):
    tree = etree.fromstring(xml_bytes)
    part = next(p for p in tree if localname(p) == "part")
    out = []
    for measure in find_children(part, "measure"):
        mnum = measure.get("number")
        for note in find_children(measure, "note"):
            pitch = find_child(note, "pitch")
            if pitch is None:
                out.append((mnum, "rest", None))
            else:
                out.append((mnum, "note", (
                    child_text(pitch, "step"),
                    int(child_text(pitch, "alter") or 0),
                    int(child_text(pitch, "octave")),
                )))
    return out


def transpose_out(name, part="P1", src=(0, 0), dst=(-5, -9), lo="C3", hi="C7"):
    return service.transpose(read(name), name, part,
                             src[0], src[1], dst[0], dst[1], lo, hi)


# ----------------------------------------------------------- 成功转换

def test_inspect_lists_parts():
    info = service.inspect(read("band.xml"), "band.xml")
    ids = {p["id"] for p in info["parts"]}
    assert ids == {"T1", "D1"}
    drum = next(p for p in info["parts"] if p["id"] == "D1")
    assert drum["has_unpitched"] is True
    tpt = next(p for p in info["parts"] if p["id"] == "T1")
    assert tpt["has_pitched"] is True


def test_basic_transposition_c_to_eb_alto():
    """C 调长笛实际音高谱移到 Eb 中音萨克斯（dst=(-5,-9)，记谱比实音高大六度）：
    记谱整体上行大六度；输出带 -9 标记，发声音高不变。"""
    xml, fname, meta = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    ps = pitches_of(xml)
    # C4 -> A4；E4 -> C#5；G#4 -> E#5；C5(tie start) -> A5
    assert ps[:4] == [
        ("1", "note", ("A", 0, 4)),
        ("1", "note", ("C", 1, 5)),
        ("1", "note", ("E", 1, 5)),
        ("1", "note", ("A", 0, 5)),
    ]
    # C major 记谱 M6 上行 -> A major（3 升号）；m4 由 G major 记谱 M6 上行 -> E major（4 升号）
    tree = etree.fromstring(xml)
    keys = tree.findall(".//{*}fifths")
    assert [int(k.text) for k in keys] == [3, 4]
    assert meta["measures"] == 4
    assert fname.endswith(".musicxml")


def test_sounding_pitch_preserved():
    """核心：旧记谱+src 与 新记谱+dst 的发声 MIDI 必须逐音相等。"""
    cases = [
        (0, 0, -5, -9),   # -> Eb 中音（记谱 M6 上行）
        (0, 0, -1, -2),   # -> Bb 调（记谱 M2 上行）
        (0, 0, -7, -12),  # -> 低八度发声乐器（记谱八度上行）
        (0, 0, 0, 0),     # 恒等
        (0, 0, 7, 12),    # -> 短笛类（发声高八度，记谱八度下行）
    ]
    orig = pitches_of(read("flute_c.xml"))
    for sd, sc, dd, dc in cases:
        xml, _, _ = transpose_out("flute_c.xml", src=(sd, sc), dst=(dd, dc),
                                  lo="A0", hi="C9")
        for (_, tk1, p1), (_, tk2, p2) in zip(orig, pitches_of(xml)):
            if tk1 == "rest":
                assert tk2 == "rest"
                continue
            assert pitch_midi(*p1) + sc == pitch_midi(*p2) + dc, ((sd, sc, dd, dc), p1, p2)


def test_tied_notes_same_written_pitch():
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    tree = etree.fromstring(xml)
    part = next(p for p in tree if localname(p) == "part")
    tied_pitches = []
    for measure in find_children(part, "measure"):
        for note in find_children(measure, "note"):
            if find_children(note, "tie"):
                p = find_child(note, "pitch")
                tied_pitches.append((
                    child_text(p, "step"),
                    int(child_text(p, "alter") or 0),
                    int(child_text(p, "octave")),
                ))
    # C5 tie 链 -> A5，三个端点必须完全一致
    assert tied_pitches == [("A", 0, 5)] * 3
    types = sorted(t.get("type") for t in tree.findall(".//{*}tie"))
    assert types == ["start", "start", "stop", "stop"]


def test_chords_transpose_together():
    """和弦两音按相同音程移动且仍为同时发声（保留 <chord/>）。"""
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    tree = etree.fromstring(xml)
    part = next(p for p in tree if localname(p) == "part")
    m3 = find_children(find_children(part, "measure")[2], "note")
    # m3 源：C5(stop), E4, G4(chord), B4 dotted, C5
    # M6 上行：A5(stop), C#5, E#5(chord), G#5, A5
    assert find_child(m3[2], "chord") is not None
    p1 = (child_text(find_child(m3[1], "pitch"), "step"),
          child_text(find_child(m3[1], "pitch"), "octave"))
    p2 = (child_text(find_child(m3[2], "pitch"), "step"),
          child_text(find_child(m3[2], "pitch"), "octave"))
    assert p1 == ("C", "5")
    assert p2 == ("E", "5")


def test_rests_durations_dots_preserved():
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    tree = etree.fromstring(xml)
    part = next(p for p in tree if localname(p) == "part")
    m2 = find_children(part, "measure")[1]
    notes = find_children(m2, "note")
    assert child_text(notes[0], "duration") == "4"
    assert child_text(notes[0], "type") == "half"
    assert find_child(notes[1], "rest") is not None
    assert child_text(notes[1], "duration") == "2"
    m3 = find_children(part, "measure")[2]
    dotted = find_children(m3, "note")[3]
    assert len(find_children(dotted, "dot")) == 1


def test_repeat_barlines_preserved():
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    tree = etree.fromstring(xml)
    repeats = tree.findall(".//{*}repeat")
    endings = tree.findall(".//{*}ending")
    assert len(repeats) == 1 and repeats[0].get("direction") == "backward"
    assert len(endings) == 1 and endings[0].get("type") == "stop"


def test_measure_count_and_numbers_preserved():
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -8), lo="A3", hi="A7")
    om = etree.fromstring(read("flute_c.xml")).findall(".//{*}measure")
    nm = etree.fromstring(xml).findall(".//{*}measure")
    assert len(om) == len(nm) == 4
    assert [m.get("number") for m in om] == [m.get("number") for m in nm]


def test_accidentals_rewritten():
    """临时变音记号随音符重算。m1 G#4 上行 M6 -> E#5（sharp）。"""
    xml, _, _ = transpose_out("flute_c.xml", dst=(-5, -9), lo="A3", hi="A6")
    accs = sorted(a.text for a in etree.fromstring(xml).findall(".//{*}accidental"))
    assert "sharp" in accs
    ps = pitches_of(xml)
    assert ("1", "note", ("E", 1, 5)) in ps


def test_minor_key_transposition():
    """a 小调（K=0）记谱 M6 上行 -> f# 小调（A 大调调号 K=3），mode 保留。"""
    xml, _, _ = service.transpose(read("a_minor.xml"), "a_minor.xml", "V1",
                                  0, 0, -5, -9, "A3", "A6")
    tree = etree.fromstring(xml)
    assert int(tree.findall(".//{*}fifths")[0].text) == 3
    assert tree.findall(".//{*}mode")[0].text == "minor"
    ps = pitches_of(xml)
    # A4 上行 M6 -> F#5
    assert ps[0][2] == ("F", 1, 5)


def test_bb_trumpet_to_eb_alto():
    """Bb 小号(src=(-1,-2))转 Eb 中音(dst=(-5,-9))：
    新记谱 = 旧 + (4,7)，即纯五度上行。D4 -> A4。
    发声：D4-2=C4(60)；A4-9=60。"""
    xml, _, _ = service.transpose(read("band.xml"), "band.xml", "T1",
                                  -1, -2, -5, -9, "E3", "A6")
    ps = pitches_of(xml)
    assert ps[0][2] == ("A", 0, 4)
    tree = etree.fromstring(xml)
    tr = tree.findall(".//{*}transpose")[0]
    assert int(child_text(tr, "chromatic")) == -9
    assert int(child_text(tr, "diatonic")) == -5
    # 原写谱 D major(K=2) 记谱 P5 上行 -> A major(K=3)
    assert int(tree.findall(".//{*}fifths")[0].text) == 3
    for (_, _, p_old), (_, _, p_new) in zip(pitches_of(read("band.xml")), ps):
        if p_old is None:
            continue
        assert pitch_midi(*p_old) - 2 == pitch_midi(*p_new) - 9


def test_bb_to_concert_pitch():
    """Bb 小号分谱(src=(-1,-2))转实音 C 调(dst=0)：记谱 M2 下行，D4->C4。"""
    xml, _, _ = service.transpose(read("band.xml"), "band.xml", "T1",
                                  -1, -2, 0, 0, "A3", "A6")
    ps = pitches_of(xml)
    assert ps[0][2] == ("C", 0, 4)
    assert pitch_midi(*ps[0][2]) == 60  # D4-2=C4=60


def test_source_transpose_octave_equivalent_accepted():
    """文件 <transpose> 用“压缩八度音程 + octave-change”记录时的等价判定。

    MusicXML 语义：diatonic 不随 octave-change 变；chromatic 含 octave-change。
    """
    from app.service import _equivalent_interval
    # 中音标准写法：读出 (diatonic=2, chromatic=3-12=-9)，用户完整填 (-5,-9)
    assert _equivalent_interval((2, -9), (-5, -9))
    # 完整写法直接相等
    assert _equivalent_interval((-5, -9), (-5, -9))
    # 半音数不同则必不等价
    assert not _equivalent_interval((2, 3), (-5, -9))
    assert not _equivalent_interval((-1, -2), (-5, -9))
    # 字母差不是整 7：如 (4,-7) 与 (-4,-7) 不等价
    assert not _equivalent_interval((4, -7), (-4, -7))
    # F 圆号标准写法读出 (diatonic=4, chromatic=5-12=-7)，用户完整填 (-3?,-7)
    # 用户若填 (-3,-7) 则 4-(-3)=7 等价
    assert _equivalent_interval((4, -7), (-3, -7))


def test_existing_transpose_mismatch_rejected():
    # 谱里标记 (-1,-2)，却填成 C 乐器 (0,0)
    with pytest.raises(ValidationError, match="不一致"):
        service.transpose(read("band.xml"), "band.xml", "T1",
                          0, 0, -5, -9, "E3", "A6")


def test_alto_file_with_standard_notation_transpose():
    """文件 <transpose>=(2,3,octave-change=-1)（标准压缩写法），
    用户按界面填完整原乐器音程 (-5,-9)，应通过等价校验；转到 C 调(dst=0)。
    记谱 A4（发声 C4）-> 实音 C4。"""
    xml, _, _ = service.transpose(read("alto_std.xml"), "alto_std.xml", "AS1",
                                  -5, -9, 0, 0, "A3", "A6")
    ps = pitches_of(xml)
    assert ps[0][2] == ("C", 0, 4)
    # 输出为 C 调乐器，transpose=(0,0)
    tree = etree.fromstring(xml)
    tr = tree.findall(".//{*}transpose")[0]
    assert int(child_text(tr, "chromatic")) == 0
    assert int(child_text(tr, "diatonic")) == 0


def test_mxl_compressed_loads():
    xml, fname, _ = service.transpose(read("clarinet.mxl"), "clarinet.mxl", "M1",
                                      0, 0, -5, -9, "A3", "A6")
    assert b"score-partwise" in xml
    assert fname.startswith("clarinet.")


def test_output_valid_xml_single_part():
    xml, _, _ = service.transpose(read("band.xml"), "band.xml", "T1",
                                  -1, -2, -5, -9, "E3", "A6")
    tree = etree.fromstring(xml)
    assert len([p for p in tree if localname(p) == "part"]) == 1
    sp = tree.findall(".//{*}score-part")
    assert len(sp) == 1
    assert "移调分谱" in (sp[0].find("{*}part-name").text or "")


def test_octave_transposing_instrument():
    """低音提琴记谱高八度（src=(-7,-12)）转实音 C 调(dst=0)：新记谱下移八度。"""
    xml, _, _ = service.transpose(read("a_minor.xml"), "a_minor.xml", "V1",
                                  -7, -12, 0, 0, "A2", "A6")
    tree = etree.fromstring(xml)
    tr = tree.findall(".//{*}transpose")[0]
    assert int(child_text(tr, "chromatic")) == 0
    ps = pitches_of(xml)
    assert ps[0][2] == ("A", 0, 3)  # A4 -> A3；发声 A3+0 = A4-12 ✓


# ----------------------------------------------------------- 音域检查

def test_out_of_range_lists_measures_and_pitches():
    # 中音写法整体上行 M6 后落到 A4/A5…；把下限抬到 C6 必然越界
    with pytest.raises(RangeExceeded) as ei:
        transpose_out("flute_c.xml", dst=(-5, -9), lo="C6", hi="C8")
    items = ei.value.items
    assert items
    assert "1" in {i["measure"] for i in items}
    assert "A4" in {i["pitch"] for i in items}


def test_range_error_reports_written_pitch_no_octave_fudging():
    """越界时报告真实记谱音高，引擎从不自动挪八度。"""
    with pytest.raises(RangeExceeded) as ei:
        transpose_out("flute_c.xml", dst=(0, 0), lo="E4", hi="G5")
    reported = {i["pitch"] for i in ei.value.items}
    assert "C4" in reported
    assert "C5" not in reported and "C3" not in reported


def test_range_lo_above_hi_rejected():
    with pytest.raises(ValidationError):
        transpose_out("flute_c.xml", dst=(-5, -9), lo="C6", hi="C4")


# ----------------------------------------------------------- 拒绝类

def test_corrupt_file_rejected():
    with pytest.raises(ScoreError, match="解析失败|损坏"):
        service.inspect(read("broken.xml"), "broken.xml")


def test_timewise_rejected():
    with pytest.raises(ScoreError, match="timewise"):
        service.inspect(read("timewise.xml"), "timewise.xml")


def test_unpitched_part_rejected():
    with pytest.raises(ValidationError, match="无调打击乐|unpitched"):
        service.transpose(read("band.xml"), "band.xml", "D1",
                          0, 0, -5, -9, "C3", "C7")


def test_microtone_rejected():
    with pytest.raises(ScoreError, match="微音分"):
        service.transpose(read("microtone.xml"), "microtone.xml", "Q1",
                          0, 0, -5, -9, "C3", "C7")


def test_mid_piece_transpose_change_rejected():
    with pytest.raises(ScoreError, match="中途更换移调乐器"):
        service.transpose(read("mid_transpose.xml"), "mid_transpose.xml", "X1",
                          0, 0, -5, -9, "C3", "C7")


@pytest.mark.parametrize("d,c", [(2, 5), (-2, 1), (0, 3), (8, 0)])
def test_invalid_intervals_rejected(d, c):
    with pytest.raises(ValidationError):
        service.transpose(read("flute_c.xml"), "flute_c.xml", "P1",
                          d, c, -5, -9, "C3", "C7")


@pytest.mark.parametrize("bad", ["H4", "C", "C#", "4C", "C99"])
def test_invalid_range_pitch_rejected(bad):
    with pytest.raises(ValidationError):
        service.transpose(read("flute_c.xml"), "flute_c.xml", "P1",
                          0, 0, -5, -9, bad, "C7")


def test_empty_file_rejected():
    with pytest.raises(ScoreError):
        service.inspect(b"", "empty.xml")


def test_missing_part_rejected():
    with pytest.raises(ValidationError):
        service.transpose(read("flute_c.xml"), "flute_c.xml", "NOPE",
                          0, 0, -5, -9, "C3", "C7")


def test_no_partial_output_on_range_error():
    with pytest.raises(RangeExceeded):
        service.transpose(read("flute_c.xml"), "flute_c.xml", "P1",
                          0, 0, -5, -9, "C9", "C10")
