"""MusicXML 解析与命名空间辅助。"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from lxml import etree

MUSICXML_NS = "http://www.musicxml.org/xsd/MusicXML"
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20MB 上限，防御压缩包炸弹
MAX_MXL_ENTRIES = 200
MAX_UNCOMPRESSED = 100 * 1024 * 1024

# 音名字母到 diatonic 音级（C=0）
_LETTER_STEP = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
_STEP_LETTER = "CDEFGAB"

# 升降号文本：alter -> <accidental> 文本（仅覆盖两升/两降以内，
# 超出范围的非常规变音记号直接拒绝，避免输出不可读记谱）
_ALTER_TEXT = {
    -2: "flat-flat",
    -1: "flat",
    0: "natural",
    1: "sharp",
    2: "double-sharp",
}
# <accidental> 文本 -> alter（常见的兼容写法）
_ACCIDENTAL_ALTER = {
    "flat-flat": -2, "double-flat": -2,
    "flat": -1, "natural-sharp": 1, "natural-flat": -1,
    "natural": 0,
    "sharp": 1, "double-sharp": 2, "sharp-sharp": 2,
}


class ScoreError(Exception):
    """文件损坏 / 结构无法保留等致命错误（整份拒绝）。"""


class ValidationError(Exception):
    """参数（音程、音域、乐器类型等）无效。"""


class RangeExceeded(Exception):
    """超出目标书写音域，携带具体小节与音高清单。"""

    def __init__(self, items: list[dict]):
        self.items = items
        super().__init__("目标音域不足")


def ln(tag) -> str:
    """去掉命名空间的本地标签名。"""
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def localname(el: etree._Element) -> str:
    return etree.QName(el.tag).localname


def find_child(el: etree._Element, name: str):
    for child in el:
        if isinstance(child.tag, str) and localname(child) == name:
            return child
    return None


def find_children(el: etree._Element, name: str):
    return [c for c in el if isinstance(c.tag, str) and localname(c) == name]


def child_text(el: etree._Element, name: str) -> str | None:
    child = find_child(el, name)
    return child.text if child is not None and child.text is not None else None


def set_child_text(el: etree._Element, name: str, value: str):
    child = find_child(el, name)
    if child is None:
        child = etree.SubElement(el, name)
    child.text = value
    return child


def int_text(text: str | None):
    if text is None:
        return None
    text = text.strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        return None
    return int(text)


def staff_of(el: etree._Element):
    """元素上的 staff 编号，缺省为 1。"""
    v = child_text(el, "staff")
    return int_text(v) or 1


# ---------------------------------------------------------------- 音高工具

def letter_diatonic(step_letter: str) -> int:
    return _LETTER_STEP[step_letter.upper()]


def diatonic_letter(d: int) -> str:
    return _STEP_LETTER[d % 7]


def pitch_tuple(pitch_el) -> tuple[str, int, int] | None:
    """<pitch> -> (step, alter, octave)。rest/unpitched 返回 None。"""
    step = child_text(pitch_el, "step")
    if step is None or step.upper() not in _LETTER_STEP:
        return None
    octave = int_text(child_text(pitch_el, "octave"))
    if octave is None:
        return None
    alter = int_text(child_text(pitch_el, "alter"))
    if alter is None:
        alter = 0
    return step.upper(), alter, octave


def alter_to_text(alter: int) -> str:
    return _ALTER_TEXT[alter]


def accidental_text_to_alter(text: str):
    return _ACCIDENTAL_ALTER.get(text.strip())


def pitch_string(step: str, alter: int, octave: int) -> str:
    acc = {0: "", 1: "#", 2: "x", -1: "b", -2: "bb"}.get(alter)
    return f"{step}{acc if acc is not None else '?'}{octave}"


# ---------------------------------------------------------------- 文件载入

@dataclass
class LoadedScore:
    tree: etree._ElementTree
    is_compressed: bool  # 原文件是否为 .mxl 压缩包
    kind: str            # partwise / timewise / opus


def _parse_xml(data: bytes) -> etree._ElementTree:
    # no_network=True：绝不抓取外部 DTD（安全 + 离线可用）。
    parser = etree.XMLParser(
        no_network=True,
        resolve_entities=False,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        recover=False,
    )
    try:
        return etree.parse(io.BytesIO(data), parser)
    except etree.XMLSyntaxError as exc:
        raise ScoreError(f"XML 解析失败，文件可能已损坏：{exc.msg}") from exc


def _detect_kind(root: etree._Element) -> str:
    name = localname(root)
    if name == "score-partwise":
        return "partwise"
    if name == "score-timewise":
        return "timewise"
    if name == "opus":
        return "opus"
    raise ScoreError(
        f"根元素 <{name}> 不是 score-partwise / score-timewise / opus，"
        "无法识别为单份 MusicXML 总谱。"
    )


def load_score(data: bytes, filename: str = "") -> LoadedScore:
    """载入 MusicXML（.xml/.musicxml 或压缩 .mxl）。"""
    if not data or not data.strip():
        raise ScoreError("文件为空。")
    if len(data) > MAX_FILE_BYTES:
        raise ScoreError(f"文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB 上限。")

    is_zip = data[:2] == b"PK"
    if is_zip or filename.lower().endswith(".mxl"):
        xml_bytes = _extract_mxl(data)
        is_compressed = True
    else:
        xml_bytes = data
        is_compressed = False

    tree = _parse_xml(xml_bytes)
    root = tree.getroot()
    if not isinstance(root.tag, str):
        raise ScoreError("XML 根节点不是元素，文件可能已损坏。")
    kind = _detect_kind(root)
    if kind == "opus":
        raise ScoreError("这是 MusicXML opus（作品集索引）而非单份总谱，请上传其中的单个分谱文件。")
    if kind == "timewise":
        raise ScoreError("文件为 timewise（按小节排列）格式，请在制谱软件中另存为 partwise（按声部排列）MusicXML 后再上传。")
    version = root.get("version") or "(未标注版本)"
    if version.startswith("1."):
        raise ScoreError(f"MusicXML {version} 过旧，仅支持 2.0 及以上版本。")
    return LoadedScore(tree=tree, is_compressed=is_compressed, kind=kind)


def _extract_mxl(data: bytes) -> bytes:
    """从压缩 .mxl 中取出 META-INF/container.xml 指向的根谱。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ScoreError(".mxl 压缩包损坏，无法打开。") from exc

    names = zf.namelist()
    if len(names) > MAX_MXL_ENTRIES:
        raise ScoreError(f".mxl 内条目超过 {MAX_MXL_ENTRIES}，疑似异常文件。")

    bad = zf.testzip()
    if bad is not None:
        raise ScoreError(f".mxl 压缩包条目校验失败（{bad}），文件已损坏。")

    root_path = None
    if "META-INF/container.xml" in names:
        try:
            container = etree.fromstring(zf.read("META-INF/container.xml"))
        except etree.XMLSyntaxError as exc:
            raise ScoreError(".mxl 的 META-INF/container.xml 已损坏。") from exc
        for rf in container.iter():
            if isinstance(rf.tag, str) and localname(rf) == "rootfile":
                media = rf.get("media-type", "")
                path = rf.get("full-path")
                if path and (not media or "musicxml" in media or path.endswith((".xml", ".musicxml"))):
                    root_path = path
                    break
    if root_path is None:
        # 回退：包里唯一的 .xml/.musicxml
        candidates = [n for n in names if n.endswith((".xml", ".musicxml"))]
        if len(candidates) == 1:
            root_path = candidates[0]
    if root_path is None or root_path not in names:
        raise ScoreError(".mxl 中找不到 container.xml 指向的根谱文件，压缩包结构不完整。")

    payload = zf.read(root_path)
    if len(payload) > MAX_UNCOMPRESSED:
        raise ScoreError("解压后的 MusicXML 超过 100MB 上限。")
    if payload[:5].lstrip().startswith(b"<?xml") is False and not payload.lstrip().startswith(b"<"):
        raise ScoreError(".mxl 根谱条目不是 XML，文件可能已损坏。")
    return payload


def get_doctype(data: bytes) -> str | None:
    """保留原文件 DOCTYPE 声明（不联网解析 DTD）。"""
    head = data[:4096]
    m = re.search(rb"<!DOCTYPE[^>]*>", head, flags=re.S)
    return m.group(0).decode("ascii", errors="ignore") if m else None


def serialize(tree: etree._ElementTree, doctype: str | None = None) -> bytes:
    return etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        doctype=doctype,
        pretty_print=False,
    )
