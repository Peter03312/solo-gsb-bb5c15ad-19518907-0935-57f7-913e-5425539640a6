"""The transposition engine.

The whole conversion is validated before anything is returned: structural
problems, invalid intervals/ranges, unpitched content, broken tie pairs,
un-writable key signatures and out-of-range notes all reject the *entire*
conversion. No partial result is ever serialized.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from lxml import etree

from .musicxml import (
    ATTRIBUTES_TRANSPOSE_BEFORE,
    NOTE_AFTER_ACCIDENTAL,
    ScoreFormatError,
    find_part,
    localname,
    note_staff,
    note_voice,
    read_pitch,
)
from .theory import (
    ACCIDENTAL_TEXT,
    INDEX_LETTER,
    LETTER_INDEX,
    MusicTheoryError,
    Pitch,
    interval_name,
    key_base_alters,
    parse_note_name,
    spell_note_name,
    transpose_key,
    transpose_pitch,
    validate_interval,
)


class TranspositionError(MusicTheoryError):
    """Conversion rejected for a single (already user-friendly) reason."""


class OutOfRangeError(MusicTheoryError):
    def __init__(self, violations: list[dict]):
        self.violations = violations
        super().__init__(
            f"共有 {len(violations)} 个音符超出目标书写音域；已拒绝转换且未做任何八度移动。"
        )


@dataclass
class TransposeParams:
    src_letters: int
    src_semitones: int
    dst_letters: int
    dst_semitones: int
    range_low: str
    range_high: str

    @property
    def L(self) -> int:  # written_src -> written_dst letter steps
        return self.src_letters - self.dst_letters

    @property
    def S(self) -> int:  # written_src -> written_dst semitones
        return self.src_semitones - self.dst_semitones


@dataclass
class _StaffContext:
    fifths: int = 0
    mode: str = "major"
    # active alteration per letter within the current measure
    active: dict[str, int] = field(default_factory=dict)


def _pitch_from_note(note: etree._Element, measure_no: str) -> Pitch:
    step, alter_text, oct_text = read_pitch(note)
    part_hint = f"第 {measure_no} 小节"
    if step not in LETTER_INDEX:
        raise ScoreFormatError(f"{part_hint}存在缺少合法 <step> 的有音高音符。")
    if oct_text is None:
        raise ScoreFormatError(f"{part_hint}的音符 {step} 缺少 <octave>。")
    try:
        octave = int(oct_text)
    except ValueError:
        raise ScoreFormatError(f"{part_hint}的音符含有非整数八度 “{oct_text}”。")
    if alter_text is not None:
        try:
            alter_f = float(alter_text)
        except ValueError:
            raise ScoreFormatError(
                f"{part_hint}的音符含有非法升降值 “{alter_text}”，文件可能已损坏。"
            )
        if abs(alter_f - round(alter_f)) > 1e-9:
            raise TranspositionError(
                f"{part_hint}的音符包含微分音（四分音）升降号，本应用只支持"
                "常规半音体系乐器，无法完整保留该临时记号，已拒绝整份转换。"
            )
        alter = int(round(alter_f))
    else:
        alter = 0
    return Pitch(step, alter, octave)


def _is_graceless_note(note: etree._Element) -> bool:
    return note.find("grace") is None and note.find("cue") is None


def _measure_label(measure: etree._Element, index: int) -> str:
    return measure.get("number") or str(index)


def _tie_types(note: etree._Element) -> list[str]:
    types = [t.get("type", "") for t in note.findall("tie")]
    if types:
        return types
    return [
        t.get("type", "")
        for notations in note.findall("notations")
        for t in notations.findall("tied")
    ]


# ---------------------------------------------------------------------------
# Structural validation of the selected part
# ---------------------------------------------------------------------------

def validate_part(part: etree._Element, part_name: str) -> None:
    open_ties: dict[tuple, list[tuple]] = {}
    divisions_seen = False

    for index, measure in enumerate(part.findall("measure"), start=1):
        mno = _measure_label(measure, index)
        for child in measure:
            tag = localname(child.tag)
            if tag == "attributes":
                divisions = child.find("divisions")
                if divisions is not None and divisions.text:
                    try:
                        if float(divisions.text) <= 0:
                            raise ValueError
                    except ValueError:
                        raise ScoreFormatError(
                            f"第 {mno} 小节的 <divisions> 不是正数，文件可能已损坏。"
                        )
                    divisions_seen = True
                for key in child.findall("key"):
                    _check_traditional_key(key, mno)
            elif tag == "note":
                _validate_note(child, mno, divisions_seen, part_name, open_ties)
            elif tag == "forward":
                dur = child.find("duration")
                if dur is None or not _is_int_like(dur.text):
                    raise ScoreFormatError(f"第 {mno} 小节的 <forward> 缺少合法时值。")

    dangling = [
        (label, spell_note_name(INDEX_LETTER[k[2] % 7], k[3], k[2] // 7))
        for k, stack in open_ties.items()
        for label in stack
    ]
    if dangling:
        detail = "；".join(f"第 {m} 小节 {n}" for m, n in dangling[:6])
        raise ScoreFormatError(
            f"声部 “{part_name}” 存在 {len(dangling)} 处没有收束的延音线（{detail}），"
            "结构不完整，已拒绝转换。"
        )


def _is_int_like(text: str | None) -> bool:
    if text is None:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _check_traditional_key(key: etree._Element, mno: str) -> None:
    if key.find("key-step") is not None or key.find("key-alter") is not None:
        raise TranspositionError(
            f"第 {mno} 小节使用了非传统/自定义调号（key-step），无法按音程可靠转换，"
            "已拒绝整份转换。"
        )
    fifths = key.find("fifths")
    if fifths is None or not _is_int_like(fifths.text):
        raise ScoreFormatError(f"第 {mno} 小节的调号缺少整数 <fifths>，文件可能已损坏。")


def _validate_note(
    note: etree._Element,
    mno: str,
    divisions_seen: bool,
    part_name: str,
    open_ties: dict,
) -> None:
    has_pitch = note.find("pitch") is not None
    has_rest = note.find("rest") is not None
    has_unpitched = note.find("unpitched") is not None
    if has_unpitched:
        raise TranspositionError(
            f"所选声部在第 {mno} 小节包含无调打击乐（<unpitched>），"
            "无法为其生成移调分谱，已拒绝整份转换。"
        )
    if not has_pitch and not has_rest:
        raise ScoreFormatError(
            f"第 {mno} 小节存在既无音高也无休符标记的 <note>，文件可能已损坏。"
        )
    if not note.findall("chord") and note.find("duration") is None and _is_graceless_note(note):
        raise ScoreFormatError(f"第 {mno} 小节的普通音符缺少 <duration> 时值。")
    if has_pitch and not divisions_seen and _is_graceless_note(note):
        raise ScoreFormatError(
            f"声部 “{part_name}” 在声明 <divisions> 之前出现普通音符，"
            "时值信息不完整，文件可能已损坏。"
        )
    if not has_pitch:
        return

    pitch = _pitch_from_note(note, mno)
    types = _tie_types(note)
    for t in types:
        if t not in ("start", "stop"):
            raise ScoreFormatError(
                f"第 {mno} 小节音符的延音线类型 “{t}” 非法，文件可能已损坏。"
            )
    key = (
        note_voice(note),
        note_staff(note),
        pitch.diatonic_index,
        pitch.alter,
    )
    if "stop" in types:
        stack = open_ties.get(key)
        if not stack:
            raise ScoreFormatError(
                f"第 {mno} 小节的延音线终点 {pitch.name()} 没有对应的起点，"
                "文件可能已损坏，已拒绝转换。"
            )
        stack.pop()
        if not stack:
            del open_ties[key]
    if "start" in types:
        open_ties.setdefault(key, []).append((mno, pitch.name()))


# ---------------------------------------------------------------------------
# Output document construction
# ---------------------------------------------------------------------------

def transpose_hint(L: int, S: int) -> tuple[int, int, int]:
    """MusicXML <transpose> values (diatonic, chromatic, octave-change).

    Large intervals are folded into an octave change. Per MusicXML,
    chromatic + 12*octave-change == S and
    diatonic + 7*octave-change == L.
    """
    if S > 7:
        oc = 1
    elif S < -7:
        oc = -1
    else:
        oc = 0
    return L - 7 * oc, S - 12 * oc, oc


def build_transposed_score(root, part_id: str, params: TransposeParams):
    # parameters
    validate_interval(params.src_letters, params.src_semitones)
    validate_interval(params.dst_letters, params.dst_semitones)
    L, S = params.L, params.S
    validate_interval(L, S)
    low = parse_note_name(params.range_low)
    high = parse_note_name(params.range_high)
    if low.midi > high.midi:
        raise TranspositionError(
            f"目标音域无效：下限 {low.name()} 高于上限 {high.name()}。"
        )

    part = find_part(root, part_id)
    if part is None:
        raise ScoreFormatError(f"找不到声部 “{part_id}”。")

    # structural validation happens against the pristine tree
    name = part_id
    for sp in root.find("part-list").findall("score-part"):
        if sp.get("id") == part_id:
            ne = sp.find("part-name")
            name = ne.text.strip() if ne is not None and ne.text else part_id
    validate_part(part, name)

    out = copy.deepcopy(root)
    _reduce_to_single_part(out, part_id)
    out_part = find_part(out, part_id)

    ctx: dict[str, _StaffContext] = {}
    violations: list[dict] = []
    note_total = 0
    out_of_range_sounding_note = False

    for index, measure in enumerate(out_part.findall("measure"), start=1):
        mno = _measure_label(measure, index)
        # a barline cancels every in-measure accidental
        for staff_ctx in ctx.values():
            staff_ctx.active = key_base_alters(staff_ctx.fifths)
        for child in measure:
            tag = localname(child.tag)
            if tag == "attributes":
                _transform_attributes(child, L, S, ctx)
            elif tag == "note" and child.find("pitch") is not None:
                note_total += 1
                _transform_note(child, mno, L, S, ctx, low, high, violations)

    if violations:
        raise OutOfRangeError(violations)

    dia, chrom, oc = transpose_hint(L, S)
    _set_transpose_element(out_part, dia, chrom, oc)

    return out, {
        "part_name": name,
        "measures": len(out_part.findall("measure")),
        "notes": note_total,
        "interval_label": interval_name(L, S),
        "L": L,
        "S": S,
        "diatonic": dia,
        "chromatic": chrom,
        "octave_change": oc,
    }


def _reduce_to_single_part(root: etree._Element, part_id: str) -> None:
    part_list = root.find("part-list")
    if part_list is not None:
        for sp in part_list.findall("score-part"):
            if sp.get("id") != part_id:
                part_list.remove(sp)
        for pg in part_list.findall("part-group"):
            part_list.remove(pg)
    for part in root.findall("part"):
        if part.get("id") != part_id:
            root.remove(part)


def _parse_fifths(key: etree._Element) -> int:
    return int(float(key.find("fifths").text))


def _transform_attributes(attributes: etree._Element, L: int, S: int, ctx: dict) -> None:
    for key in attributes.findall("key"):
        fifths = _parse_fifths(key)
        mode_el = key.find("mode")
        mode = mode_el.text.strip() if mode_el is not None and mode_el.text else "major"
        staff = key.get("staff") or "1"
        try:
            new_fifths = transpose_key(fifths, mode, L, S)
        except MusicTheoryError as exc:
            raise TranspositionError(str(exc))
        key.find("fifths").text = str(new_fifths)
        staff_ctx = ctx.setdefault(staff, _StaffContext())
        staff_ctx.fifths = new_fifths
        staff_ctx.mode = mode
        staff_ctx.active = key_base_alters(new_fifths)


def _transform_note(
    note: etree._Element,
    mno: str,
    L: int,
    S: int,
    ctx: dict,
    low: Pitch,
    high: Pitch,
    violations: list[dict],
) -> None:
    pitch = _pitch_from_note(note, mno)
    try:
        new_pitch = transpose_pitch(pitch, L, S)
    except MusicTheoryError as exc:
        raise TranspositionError(f"第 {mno} 小节：{exc}")
    _write_pitch(note, new_pitch)

    staff = note_staff(note)
    staff_ctx = ctx.setdefault(staff, _StaffContext(active=key_base_alters(0)))
    if staff_ctx.active == {}:
        staff_ctx.active = key_base_alters(staff_ctx.fifths)

    types = _tie_types(note)
    is_tie_continuation = "stop" in types and "start" not in types

    # range check is based purely on written pitch; octaves are never moved
    if new_pitch.midi < low.midi or new_pitch.midi > high.midi:
        violations.append(
            {
                "measure": mno,
                "pitch": new_pitch.name(),
                "direction": "低于下限" if new_pitch.midi < low.midi else "高于上限",
                "bound": low.name() if new_pitch.midi < low.midi else high.name(),
            }
        )

    if is_tie_continuation:
        # a tied continuation shares the written pitch of its partner; the
        # accidental belongs to the tie's first note
        _replace_accidental(note, None)
        return

    expected_base = key_base_alters(staff_ctx.fifths).get(new_pitch.step, 0)
    current = staff_ctx.active.get(new_pitch.step, expected_base)
    show = new_pitch.alter != current
    if show:
        staff_ctx.active[new_pitch.step] = new_pitch.alter
    _replace_accidental(note, new_pitch.alter if show else None)


def _write_pitch(note: etree._Element, pitch: Pitch) -> None:
    pitch_el = note.find("pitch")
    step_el = pitch_el.find("step")
    oct_el = pitch_el.find("octave")
    alter_el = pitch_el.find("alter")
    step_el.text = pitch.step
    oct_el.text = str(pitch.octave)
    if pitch.alter != 0:
        if alter_el is None:
            alter_el = etree.SubElement(pitch_el, "alter")
            # MusicXML order inside <pitch>: step, alter, octave
            pitch_el.remove(alter_el)
            step_el.addnext(alter_el)
        alter_el.text = str(pitch.alter)
    elif alter_el is not None:
        pitch_el.remove(alter_el)


def _replace_accidental(note: etree._Element, alter: int | None) -> None:
    for acc in note.findall("accidental"):
        note.remove(acc)
    if alter is None:
        return
    acc = etree.Element("accidental")
    acc.text = ACCIDENTAL_TEXT[alter]
    anchor = None
    for child in note:
        if localname(child.tag) in NOTE_AFTER_ACCIDENTAL:
            anchor = child
            break
    if anchor is not None:
        anchor.addprevious(acc)
    else:
        note.append(acc)


def _set_transpose_element(part: etree._Element, diatonic: int, chromatic: int, octave_change: int) -> None:
    first_measure = part.find("measure")
    attributes = first_measure.find("attributes")
    if attributes is None:
        attributes = etree.Element("attributes")
        first_measure.insert(0, attributes)
    for old in attributes.findall("transpose"):
        attributes.remove(old)
    transpose = etree.Element("transpose")
    dia_el = etree.SubElement(transpose, "diatonic")
    dia_el.text = str(diatonic)
    chr_el = etree.SubElement(transpose, "chromatic")
    chr_el.text = str(chromatic)
    if octave_change:
        oc_el = etree.SubElement(transpose, "octave-change")
        oc_el.text = str(octave_change)
    anchor = None
    for child in attributes:
        if localname(child.tag) in ATTRIBUTES_TRANSPOSE_BEFORE:
            anchor = child
            break
    if anchor is not None:
        anchor.addprevious(transpose)
    else:
        attributes.append(transpose)


def serialize(root: etree._Element) -> bytes:
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )
