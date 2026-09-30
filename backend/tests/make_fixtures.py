"""生成测试用 MusicXML 夹具并运行端到端断言。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from lxml import etree

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DIR.mkdir(exist_ok=True)

# 简化的 partwise MusicXML 生成器：(note 描述)
# note: dict(step, alter?, oct, dur, type, dot?|rest=True|chord=True|tie=start/stop/startstop,
#            accidental?, grace?, voice?)
MEASURES_DEFAULT = 4


def note_el(n, divisions):
    note = etree.Element("note")
    if n.get("grace"):
        etree.SubElement(note, "grace")
    if n.get("chord"):
        etree.SubElement(note, "chord")
    if n.get("rest"):
        etree.SubElement(note, "rest")
    else:
        pitch = etree.SubElement(note, "pitch")
        etree.SubElement(pitch, "step").text = n["step"]
        if "alter" in n:
            etree.SubElement(pitch, "alter").text = str(n["alter"])
        etree.SubElement(pitch, "octave").text = str(n["oct"])
    if "dur" in n:
        etree.SubElement(note, "duration").text = str(n["dur"])
    if n.get("voice"):
        etree.SubElement(note, "voice").text = n["voice"]
    if n.get("type"):
        t = etree.SubElement(note, "type")
        t.text = n["type"]
    for _ in range(n.get("dots", 0)):
        etree.SubElement(note, "dot")
    if n.get("accidental"):
        a = etree.SubElement(note, "accidental")
        a.text = n["accidental"]
        if n.get("accidental_cautionary"):
            a.set("cautionary", "yes")
    for ty in n.get("ties", []):
        t = etree.SubElement(note, "tie")
        t.set("type", ty)
    return note


def make_part(part_id, name, measures_notes, *, fifths=0, mode="major",
              divisions=2, beats=4, beat_type=4, transpose=None,
              mid_key=None, barlines=None, include_abbr=False):
    part = etree.Element("part", id=part_id)
    barlines = barlines or {}
    for mi, notes in enumerate(measures_notes, start=1):
        measure = etree.SubElement(part, "measure", number=str(mi))
        if mi == 1 or mid_key == mi:
            attrs = etree.SubElement(measure, "attributes")
            if mi == 1:
                etree.SubElement(attrs, "divisions").text = str(divisions)
                key = etree.SubElement(attrs, "key")
                etree.SubElement(key, "fifths").text = str(fifths)
                etree.SubElement(key, "mode").text = mode
                time = etree.SubElement(attrs, "time")
                etree.SubElement(time, "beats").text = str(beats)
                etree.SubElement(time, "beat-type").text = str(beat_type)
                clef = etree.SubElement(attrs, "clef")
                etree.SubElement(clef, "sign").text = "G"
                etree.SubElement(clef, "line").text = "2"
                if transpose is not None:
                    tr = etree.SubElement(attrs, "transpose")
                    # transpose: (diatonic, chromatic) 或 (diatonic, chromatic, octave-change)
                    etree.SubElement(tr, "diatonic").text = str(transpose[0])
                    etree.SubElement(tr, "chromatic").text = str(transpose[1])
                    if len(transpose) >= 3:
                        etree.SubElement(tr, "octave-change").text = str(transpose[2])
            elif mid_key == mi:
                key = etree.SubElement(attrs, "key")
                etree.SubElement(key, "fifths").text = str(mid_key[1] if isinstance(mid_key, tuple) else 1)
                etree.SubElement(key, "mode").text = "major"
        for n in notes:
            measure.append(note_el(n, divisions))
        if mi in barlines:
            measure.append(barlines[mi])
    return part


def barline(location, ending_type=None, ending_number=None, repeat_dir=None, bar_style="light-light"):
    bl = etree.Element("barline", location=location)
    if ending_type:
        e = etree.SubElement(bl, "ending")
        e.set("type", ending_type)
        if ending_number:
            e.set("number", ending_number)
    if repeat_dir:
        r = etree.SubElement(bl, "repeat")
        r.set("direction", repeat_dir)
    if bar_style:
        etree.SubElement(bl, "bar-style").text = bar_style
    return bl


def make_score(parts, root_attrs=None, doctype=False):
    """parts: [(id, name, abbr, part_el)] 或 [(id, name, part_el)]。"""
    norm = []
    for t in parts:
        if len(t) == 4:
            norm.append(t)
        else:
            pid, name, part_el = t
            norm.append((pid, name, None, part_el))
    parts = norm
    root = etree.Element("score-partwise", version="3.1", nsmap={None: "http://www.musicxml.org/xsd/MusicXML"})
    pl = etree.SubElement(root, "part-list")
    for pid, name, abbr, part_el in parts:
        sp = etree.SubElement(pl, "score-part", id=pid)
        etree.SubElement(sp, "part-name").text = name
        if abbr:
            etree.SubElement(sp, "part-abbreviation").text = abbr
    for pid, name, abbr, part_el in parts:
        root.append(part_el)
    tree = etree.ElementTree(root)
    buf = io.BytesIO()
    tree.write(buf, xml_declaration=True, encoding="UTF-8")
    return buf.getvalue()


def N(step, oct, dur=2, typ="quarter", **kw):
    return dict(step=step, oct=oct, dur=dur, type=typ, **kw)


def R(dur=2, typ="quarter", **kw):
    return dict(rest=True, dur=dur, type=typ, **kw)


def fixture_main():
    """Flute in C 谱：含临时升降、和弦、休止、附点、延音线跨小节、反复记号、中途转调。"""
    m1 = [
        N("C", 4), N("E", 4), N("G", 4, alter=1, accidental="sharp"),
        dict(step="C", oct=5, dur=2, type="quarter", ties=["start"]),
    ]
    m2 = [
        dict(step="C", oct=5, dur=4, type="half", ties=["stop", "start"]),
        R(2),
    ]
    m3 = [
        dict(step="C", oct=5, dur=2, type="quarter", ties=["stop"]),
        # 和弦：主音 + 三音同时发声
        N("E", 4, dur=2),
        N("G", 4, dur=2, chord=True),
        N("B", 4, dur=1, typ="eighth", dots=1),
        N("C", 5, dur=1, typ="eighth"),
    ]
    m4 = [
        # 第 4 小节转入 G 大调（一个升号）：F 自然音需显式还原号，随后再 F#
        N("F", 5, alter=0, accidental="natural"), N("F", 5, alter=1, accidental="sharp"),
        N("G", 5), N("C", 5),
    ]
    notes = [m1, m2, m3, m4]
    bl = {
        1: barline("right", repeat_dir="backward", bar_style=None),
        4: barline("right", ending_type="stop", ending_number="1", bar_style="light-light"),
    }
    part = make_part("P1", "Flute", notes, fifths=0, mid_key=4, barlines=bl)
    xml = make_score([("P1", "Flute", "Fl.", part)])
    (FIXTURE_DIR / "flute_c.xml").write_bytes(xml)

def fixture_concert_band():
    """双声部：Bb Trumpet（带 transpose 标记）+ 无调打击乐。"""
    m1 = [N("D", 4), N("F", 4, alter=1), N("A", 4), N("D", 5)]
    m2 = [N("C", 4, alter=1, dur=4, typ="half"), R(4, "half")]
    tp = make_part("T1", "Trumpet in Bb", [m1, m2], fifths=2, transpose=(-1, -2))

    # 打击乐
    perc_part = etree.Element("part", id="D1")
    for i in range(1, 3):
        meas = etree.SubElement(perc_part, "measure", number=str(i))
        if i == 1:
            attrs = etree.SubElement(meas, "attributes")
            clef = etree.SubElement(attrs, "clef")
            etree.SubElement(clef, "sign").text = "percussion"
            etree.SubElement(clef, "line").text = "2"
        for _ in range(4):
            note = etree.SubElement(meas, "note")
            etree.SubElement(note, "unpitched")
            etree.SubElement(note, "duration").text = "1"
            etree.SubElement(note, "type").text = "eighth"
    xml = make_score([
        ("T1", "Trumpet in Bb", "Tpt.", tp),
        ("D1", "Drumset", "Drm.", perc_part),
    ])
    (FIXTURE_DIR / "band.xml").write_bytes(xml)


def fixture_minor_tied():
    """a 小调，跨小节延音线，音域检查用。"""
    m1 = [N("A", 4), N("C", 5), N("E", 5, ties=["start"])]
    m2 = [dict(step="E", oct=5, dur=4, typ="half", ties=["stop"]), N("A", 5)]
    part = make_part("V1", "Violin", [m1, m2], fifths=0, mode="minor")
    xml = make_score([("V1", "Violin", "Vln.", part)])
    (FIXTURE_DIR / "a_minor.xml").write_bytes(xml)


def fixture_microtone():
    m1 = [N("C", 4), N("E", 4, alter=1)]
    # 手工塞入 0.5
    part = make_part("Q1", "Quarter", [m1], fifths=0)
    # 替换第二个音的 alter
    alter = part.findall(".//{*}alter")[0]
    alter.text = "0.5"
    xml = make_score([("Q1", "Quarter", None, part)])
    (FIXTURE_DIR / "microtone.xml").write_bytes(xml)


def fixture_mid_transpose_change():
    part = make_part("X1", "X", [[N("C", 4)]], fifths=0, transpose=(0, 0))
    meas2 = etree.SubElement(part, "measure", number="2")
    attrs = etree.SubElement(meas2, "attributes")
    tr = etree.SubElement(attrs, "transpose")
    etree.SubElement(tr, "diatonic").text = "-2"
    etree.SubElement(tr, "chromatic").text = "-3"
    meas2.append(note_el(N("D", 4), 2))
    xml = make_score([("X1", "X", None, part)])
    (FIXTURE_DIR / "mid_transpose.xml").write_bytes(xml)


def fixture_alto_standard_notation():
    """Eb 中音萨克斯分谱：文件用 MusicXML 常见压缩写法
    diatonic=2, chromatic=3, octave-change=-1（等价完整音程 -5,-9）。
    记谱 A4 -> 发声 C4。"""
    m1 = [N("A", 4), N("C", 5, alter=1), N("E", 5), N("A", 5)]
    # A 大调（3 升号）是中音萨克斯 C 大调实际音高的记谱调
    part = make_part("AS1", "Alto Sax", [m1], fifths=3, transpose=(2, 3, -1))
    xml = make_score([("AS1", "Alto Sax", "A.Sax", part)])
    (FIXTURE_DIR / "alto_std.xml").write_bytes(xml)


def fixture_mxl():
    """压缩 .mxl：容器 + container.xml + 根谱。"""
    part = make_part("M1", "Clarinet", [[N("C", 4)]], fifths=0)
    root = etree.Element("score-partwise", version="3.1")
    pl = etree.SubElement(root, "part-list")
    sp = etree.SubElement(pl, "score-part", id="M1")
    etree.SubElement(sp, "part-name").text = "Clarinet"
    root.append(part)
    score_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    container = b"""<?xml version="1.0" encoding="UTF-8"?>
<container><rootfiles><rootfile full-path="score.xml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.recordare.musicxml")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("score.xml", score_xml)
    (FIXTURE_DIR / "clarinet.mxl").write_bytes(buf.getvalue())


def fixture_broken():
    (FIXTURE_DIR / "broken.xml").write_bytes(
        b'<?xml version="1.0"?><score-partwise version="3.1"><part-list><score-part id="P1">'
        b'<part-name>X</part-name></score-part></part-list><part id="P1"><measure number="1">'
        b'<note><pitch><step>C</step><octave>4</pitch></note></measure></part>')


def fixture_timewise():
    xml = b"""<?xml version="1.0"?>
<score-timewise version="3.1"><part-list><score-part id="P1"><part-name>X</part-name></score-part></part-list></score-timewise>"""
    (FIXTURE_DIR / "timewise.xml").write_bytes(xml)


def main():
    fixture_main()
    fixture_concert_band()
    fixture_minor_tied()
    fixture_microtone()
    fixture_mid_transpose_change()
    fixture_alto_standard_notation()
    fixture_mxl()
    fixture_broken()
    fixture_timewise()
    print("fixtures written:", sorted(p.name for p in FIXTURE_DIR.iterdir()))


if __name__ == "__main__":
    main()
