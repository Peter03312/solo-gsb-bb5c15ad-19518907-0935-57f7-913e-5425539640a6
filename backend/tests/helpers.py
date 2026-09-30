"""Test-suite helpers: build minimal valid partwise MusicXML documents."""

from __future__ import annotations

from lxml import etree


def make_xml(
    measures: list[list[dict]],
    *,
    fifths: int = 0,
    mode: str = "major",
    divisions: int = 1,
    part_id: str = "P1",
    part_name: str = "Test",
    with_divisions: bool = True,
    include_forward: bool = False,
) -> bytes:
    root = etree.Element("score-partwise", version="3.1")
    plist = etree.SubElement(root, "part-list")
    sp = etree.SubElement(plist, "score-part", id=part_id)
    pn = etree.SubElement(sp, "part-name")
    pn.text = part_name
    part = etree.SubElement(root, "part", id=part_id)

    for i, notes in enumerate(measures, start=1):
        measure = etree.SubElement(part, "measure", number=str(i))
        if i == 1:
            attrs = etree.SubElement(measure, "attributes")
            if with_divisions:
                d = etree.SubElement(attrs, "divisions")
                d.text = str(divisions)
            key = etree.SubElement(attrs, "key")
            f = etree.SubElement(key, "fifths")
            f.text = str(fifths)
            m = etree.SubElement(key, "mode")
            m.text = mode
            ts = etree.SubElement(attrs, "time")
            etree.SubElement(ts, "beats").text = "4"
            etree.SubElement(ts, "beat-type").text = "4"
            clef = etree.SubElement(attrs, "clef")
            etree.SubElement(clef, "sign").text = "G"
            etree.SubElement(clef, "line").text = "2"
        if include_forward:
            fw = etree.SubElement(measure, "forward")
            etree.SubElement(fw, "duration").text = "1"
        for spec in notes:
            _add_note(measure, spec)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def _add_note(measure, spec: dict) -> None:
    note = etree.SubElement(measure, "note")
    if spec.get("chord"):
        etree.SubElement(note, "chord")
    if spec.get("rest"):
        etree.SubElement(note, "rest")
        etree.SubElement(note, "duration").text = str(spec.get("dur", 1))
        return
    if spec.get("unpitched"):
        etree.SubElement(note, "unpitched")
        etree.SubElement(note, "display-step").text = "B"
        etree.SubElement(note, "display-octave").text = "4"
        etree.SubElement(note, "duration").text = "1"
        return
    if spec.get("grace"):
        etree.SubElement(note, "grace")
    else:
        etree.SubElement(note, "duration").text = str(spec.get("dur", 1))
    pitch = etree.SubElement(note, "pitch")
    etree.SubElement(pitch, "step").text = spec["step"]
    if spec.get("alter", 0) != 0:
        etree.SubElement(pitch, "alter").text = str(spec["alter"])
    etree.SubElement(pitch, "octave").text = str(spec["octave"])
    if spec.get("type"):
        etree.SubElement(note, "type").text = spec["type"]
    if spec.get("staff"):
        etree.SubElement(note, "staff").text = str(spec["staff"])
    if spec.get("voice") is not None:
        etree.SubElement(note, "voice").text = str(spec["voice"])
    for tt in spec.get("ties", []):
        etree.SubElement(note, "tie", type=tt)
    if spec.get("ties"):
        notations = etree.SubElement(note, "notations")
        for tt in spec["ties"]:
            etree.SubElement(notations, "tied", type=tt)
