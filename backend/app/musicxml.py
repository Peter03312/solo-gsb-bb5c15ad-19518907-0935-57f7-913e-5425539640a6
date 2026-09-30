"""MusicXML parsing and lightweight structural analysis.

Supports both plain ``.musicxml``/``.xml`` documents and compressed
``.mxl`` containers. Timewise scores and opus files are explicitly rejected.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from lxml import etree

from .theory import LETTER_INDEX, MusicTheoryError

# Tags whose order is fixed by the MusicXML DTD, used for safe insertions.
NOTE_AFTER_ACCIDENTAL = {
    "stem", "notehead", "notehead-text", "staff", "beam", "notations",
    "lyric", "play", "listen",
}
ATTRIBUTES_TRANSPOSE_BEFORE = {
    "directives", "for-part", "accordion-registration", "measure-style",
}


class ScoreFormatError(MusicTheoryError):
    """The uploaded file is not a transposable single-part MusicXML score."""


def localname(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def find_part(root: etree._Element, part_id: str):
    """Return the <part> with the given id without XPath interpolation."""
    for part in root.findall("part"):
        if part.get("id") == part_id:
            return part
    return None


def parse_score(data: bytes) -> etree._Element:
    """Parse XML bytes or an .mxl zip; return a namespace-free partwise tree."""
    try:
        parser = etree.XMLParser(remove_comments=False, resolve_entities=False)
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError:
        root = _parse_compressed_mxl(data)
    if root is None:
        raise ScoreFormatError("文件无法解析为 XML，可能已损坏或并非 MusicXML 文件。")
    _strip_namespaces(root)
    name = localname(root.tag)
    if name == "score-timewise":
        raise ScoreFormatError(
            "本应用暂不支持 timewise 结构的 MusicXML，请在制谱软件中另存为"
            " partwise（分部）格式后重新上传。"
        )
    if name == "opus":
        raise ScoreFormatError(
            "上传的是 opus 乐谱集文件，请打开其中具体的单个 MusicXML 分谱后上传。"
        )
    if name != "score-partwise":
        raise ScoreFormatError(
            f"根元素为 <{name}>，不是 <score-partwise> 的 MusicXML 总谱文件。"
        )
    return root


def _parse_compressed_mxl(data: bytes) -> etree._Element:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        raise ScoreFormatError(
            "文件既不是合法 XML，也不是合法的压缩 .mxl，文件可能已损坏。"
        )
    rootfile_path = None
    for candidate in ("META-INF/container.xml",):
        try:
            container = etree.fromstring(zf.read(candidate))
        except KeyError:
            continue
        for rf in container.iter():
            if localname(rf.tag) == "rootfile":
                rootfile_path = rf.get("full-path")
                break
        if rootfile_path:
            break
    if not rootfile_path:
        raise ScoreFormatError("压缩 .mxl 缺少 container.xml 或 rootfile 声明。")
    try:
        xml_bytes = zf.read(rootfile_path)
    except KeyError:
        raise ScoreFormatError(f".mxl 中找不到 rootfile：{rootfile_path}")
    try:
        return etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        raise ScoreFormatError(f".mxl 内部分谱 {rootfile_path} 无法解析，文件已损坏。")


def _strip_namespaces(root: etree._Element) -> None:
    for elem in root.iter():
        if isinstance(elem.tag, str) and "}" in elem.tag:
            elem.tag = localname(elem.tag)
    for ns_attr in [k for k in root.attrib if k.startswith("xmlns")]:
        del root.attrib[ns_attr]


# ---------------------------------------------------------------------------
# Part listing / analysis
# ---------------------------------------------------------------------------

@dataclass
class PartInfo:
    part_id: str
    name: str
    abbreviation: str = ""
    measures: int = 0
    note_count: int = 0
    has_unpitched: bool = False
    has_pitched: bool = False
    measure_numbers: list[str] = field(default_factory=list)


def _part_declarations(root: etree._Element):
    part_list = root.find("part-list")
    decls = []
    if part_list is not None:
        for sp in part_list.findall("score-part"):
            name_el = sp.find("part-name")
            abbr_el = sp.find("part-abbreviation")
            decls.append(
                {
                    "id": sp.get("id"),
                    "name": (name_el.text or "").strip() if name_el is not None and name_el.text else (sp.get("id") or ""),
                    "abbreviation": (abbr_el.text or "").strip() if abbr_el is not None and abbr_el.text else "",
                }
            )
    return decls


def analyze_parts(root: etree._Element) -> list[PartInfo]:
    decls = _part_declarations(root)
    seen_ids: set[str] = set()
    result: list[PartInfo] = []
    for decl in decls:
        pid = decl["id"]
        if not pid:
            raise ScoreFormatError("part-list 中存在缺少 id 的 score-part 声明。")
        if pid in seen_ids:
            raise ScoreFormatError(f"声部 id “{pid}” 在 part-list 中重复。")
        seen_ids.add(pid)
        info = PartInfo(part_id=pid, name=decl["name"], abbreviation=decl["abbreviation"])
        part = find_part(root, pid)
        if part is None:
            raise ScoreFormatError(f"part-list 声明了声部 “{pid}”，但总谱中没有对应的 <part>。")
        _scan_part(part, info)
        result.append(info)
    for part in root.findall("part"):
        if part.get("id") not in seen_ids:
            raise ScoreFormatError(f"总谱中存在未在 part-list 声明的声部 “{part.get('id')}”。")
    if not result:
        raise ScoreFormatError("总谱中没有任何声部（score-part）。")
    return result


def _scan_part(part: etree._Element, info: PartInfo) -> None:
    measure_numbers: set[str] = set()
    for mi, measure in enumerate(part.findall("measure"), start=1):
        number = measure.get("number") or str(mi)
        if number in measure_numbers:
            raise ScoreFormatError(f"声部 “{info.name or info.part_id}” 中小节号 {number} 重复。")
        measure_numbers.add(number)
        info.measure_numbers.append(number)
        for note in measure.findall("note"):
            info.note_count += 1
            if note.find("unpitched") is not None:
                info.has_unpitched = True
            if note.find("pitch") is not None:
                info.has_pitched = True
    info.measures = len(info.measure_numbers)
    if info.measures == 0:
        raise ScoreFormatError(f"声部 “{info.name or info.part_id}” 不包含任何小节。")


def read_pitch(note: etree._Element):
    """Return (step, alter, octave) of a <pitch> without validation."""
    pitch = note.find("pitch")
    step_el = pitch.find("step") if pitch is not None else None
    oct_el = pitch.find("octave") if pitch is not None else None
    alter_el = pitch.find("alter") if pitch is not None else None
    step = step_el.text.strip() if step_el is not None and step_el.text else None
    alter_text = alter_el.text.strip() if alter_el is not None and alter_el.text else None
    oct_text = oct_el.text.strip() if oct_el is not None and oct_el.text else None
    return step, alter_text, oct_text


def note_staff(note: etree._Element) -> str:
    staff_el = note.find("staff")
    return (staff_el.text or "1").strip() if staff_el is not None and staff_el.text else "1"


def note_voice(note: etree._Element) -> str:
    voice_el = note.find("voice")
    return (voice_el.text or "1").strip() if voice_el is not None and voice_el.text else "1"


def tie_types(note: etree._Element) -> list[str]:
    return [t.get("type", "") for t in note.findall("tie") if t.get("type")]
