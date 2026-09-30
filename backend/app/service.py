"""编排：载入 -> 列声部 -> 校验参数 -> 移调 -> 自检 -> 序列化。"""
from __future__ import annotations

import re

from lxml import etree

from .mx import (
    load_score,
    serialize,
    get_doctype,
    localname,
    find_child,
    find_children,
    child_text,
    int_text,
    ScoreError,
    ValidationError,
    LoadedScore,
)
from .intervals import validate_interval, parse_pitch
from .transposer import (
    list_parts,
    extract_single_part,
    transpose_part_tree,
)
from .verify import verify_result


def inspect(data: bytes, filename: str) -> dict:
    loaded = load_score(data, filename)
    parts = list_parts(loaded)
    root = loaded.tree.getroot()
    return {
        "work_title": child_text(root, "movement-title"),
        "is_compressed": loaded.is_compressed,
        "parts": parts,
    }


def _read_existing_transpose(part) -> tuple[int, int] | None:
    """读取第一小节 <transpose>。

    返回 (diatonic, chromatic_full)：
    - diatonic 按 MusicXML 语义原样保留（octave-change 不影响 diatonic）；
    - chromatic_full = chromatic + 12*octave-change（含真实八度差）。
    """
    first = find_children(part, "measure")
    if not first:
        return None
    attrs = find_child(first[0], "attributes")
    if attrs is None:
        return None
    tr = find_child(attrs, "transpose")
    if tr is None:
        return None
    chromatic = int_text(child_text(tr, "chromatic"))
    diatonic = int_text(child_text(tr, "diatonic"))
    if chromatic is None:
        chromatic = 0
    if diatonic is None:
        diatonic = 0
    octave_change = int_text(child_text(tr, "octave-change")) or 0
    return diatonic, chromatic + octave_change * 12


def _equivalent_interval(file_pair: tuple[int, int], user_pair: tuple[int, int]) -> bool:
    """文件 <transpose> 记录与用户填写的完整有向音程是否表示同一移调。

    MusicXML 中 diatonic 不随 octave-change 变化，而 chromatic 含 octave-change。
    因此判定：含八度的半音数必须精确相等，diatonic 允许相差整 7（八度）。
    """
    fd, fc = file_pair
    ud, uc = user_pair
    if fc != uc:
        return False
    return (fd - ud) % 7 == 0


def transpose(data: bytes, filename: str, part_id: str,
              src_d: int, src_c: int, dst_d: int, dst_c: int,
              range_lo_text: str, range_hi_text: str) -> tuple[bytes, str, dict]:
    """执行转换。返回 (MusicXML 字节, 下载文件名, 元信息)。

    移调音程 = dst(书写->发声) − src(书写->发声)。
    """
    # 参数校验
    validate_interval(src_d, src_c, "原乐器移调音程")
    validate_interval(dst_d, dst_c, "目标乐器移调音程")
    range_lo = parse_pitch(range_lo_text, "目标音域下限")
    range_hi = parse_pitch(range_hi_text, "目标音域上限")

    # 记 S=原乐器“书写->发声”偏移，D=目标乐器偏移，W0/W1 为新旧书写音。
    # 发声不变：W0 + S = W1 + D  =>  W1 = W0 + (S - D)。
    d = src_d - dst_d
    c = src_c - dst_c

    loaded = load_score(data, filename)
    parts = list_parts(loaded)
    part_info = next((p for p in parts if p["id"] == part_id), None)
    if part_info is None:
        raise ValidationError(f"声部“{part_id}”不存在，请重新选择。")
    if part_info["has_unpitched"]:
        raise ValidationError(f"声部“{part_info['name']}”含无调打击乐（unpitched），不能移调。")

    root = loaded.tree.getroot()
    orig_part = next(p for p in root if isinstance(p.tag, str) and localname(p) == "part" and p.get("id") == part_id)
    # 与文件里已有 <transpose> 交叉核对（允许八度等价写法）
    existing = _read_existing_transpose(orig_part)
    if existing is not None and not _equivalent_interval(existing, (src_d, src_c)):
        ed, ec = existing
        raise ValidationError(
            f"填写的原乐器移调量（字母 {src_d:+d} / 半音 {src_c:+d}）与文件第一小节 "
            f"<transpose> 记录（字母 {ed:+d} / 半音 {ec:+d}，含八度）不一致。"
            "请核对原乐器参数后重试。")

    # 1) 抽出单分谱（深拷贝），2) 在其上执行移调与校验
    out_tree = extract_single_part(loaded, part_id)
    out_root = out_tree.getroot()
    out_part = next(p for p in out_root if isinstance(p.tag, str) and localname(p) == "part")
    transpose_part_tree(out_tree, part_id, d, c, range_lo, range_hi,
                        dst_diatonic=dst_d, dst_chromatic=dst_c)

    # 自检：结构指纹 + 发声 MIDI（发声 = 书写 + 乐器偏移；两端分别加 src/dst）+ tie
    verify_result(orig_part, out_part, src_c, dst_c, part_id)

    # 输出文件的 <transpose> 必须精确等于用户指定的目标乐器完整有向移调音程。
    final_tr = _read_existing_transpose(out_part)
    if final_tr != (dst_d, dst_c):
        raise ScoreError("内部自检失败：输出乐器移调标记不正确，拒绝输出。")

    xml = serialize(out_tree, doctype=get_doctype(data))
    # 再解析一次，确认序列化产物本身合法
    from lxml import etree as _etree
    try:
        _etree.fromstring(xml)
    except Exception as exc:  # noqa: BLE001
        raise ScoreError(f"输出 MusicXML 无法通过 XML 解析：{exc}") from exc

    stem = re.sub(r"\.(mxl|musicxml|xml)$", "", filename, flags=re.I) or "score"
    safe_name = re.sub(r"[^\w\-.一-鿿()]+", "_", part_info["name"]).strip("_") or part_id
    download_name = f"{stem}.{safe_name}.musicxml"
    meta = {
        "part_id": part_id,
        "part_name": part_info["name"],
        "interval_diatonic": d,
        "interval_chromatic": c,
        "measures": len(find_children(out_part, "measure")),
        "filename": download_name,
    }
    return xml, download_name, meta
