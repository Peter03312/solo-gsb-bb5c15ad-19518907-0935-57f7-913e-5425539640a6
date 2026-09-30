"""MusicXML 移调主逻辑。

处理原则（对应需求条款）：
- 按有向（字母步数, 半音数）整体移调，保证发声音高不变、八度不被擅改；
- 调号按音程转换，临时升降号随音符重算并改写 <accidental> 文本；
- 延音线（tie）两端保持同一书写音高（前一遍校验、后一遍复核）；
- 小节、声部（voice）、时值（duration/type/dot/time-modification）、休止、反复记号
  等一律原样保留，本模块不新增、不删除任何小节级结构；
- 超出目标书写音域：收集小节号与音高，整体拒绝；
- 无调打击乐（unpitched）、中途变调号乐器、微音分、无法解析的变音记号等：整体拒绝。
"""
from __future__ import annotations

import copy

from lxml import etree

from .mx import (
    LoadedScore,
    ScoreError,
    ValidationError,
    RangeExceeded,
    localname,
    find_child,
    find_children,
    child_text,
    int_text,
    set_child_text,
    staff_of,
    pitch_tuple,
    pitch_string,
    letter_diatonic,
    alter_to_text,
)
from .intervals import (
    transpose_pitch,
    fifths_transposed,
    pitch_midi,
)

SHARP_ORDER = [3, 0, 4, 1, 5, 2, 6]  # F C G D A E B
FLAT_ORDER = [6, 2, 5, 1, 4, 0, 3]   # B E A D G C F
NAME_SUFFIX = "（移调分谱）"


# ================================================================ 谱面信息

def list_parts(loaded: LoadedScore) -> list[dict]:
    root = loaded.tree.getroot()
    part_list = find_child(root, "part-list")
    if part_list is None:
        raise ScoreError("文件缺少 <part-list>，不是有效的 partwise MusicXML。")
    parts = []
    part_ids = {p.get("id") for p in root if isinstance(p.tag, str) and localname(p) == "part"}
    for sp in find_children(part_list, "score-part"):
        pid = sp.get("id")
        if pid is None or pid not in part_ids:
            raise ScoreError(f"<part-list> 中的声部 “{pid}” 在谱体中缺失，文件结构不完整。")
        name = child_text(sp, "part-name") or pid
        abbr = child_text(sp, "part-abbreviation")
        pitched, unpitched, notes_n = _part_note_stats(root, pid)
        parts.append({
            "id": pid,
            "name": name,
            "abbreviation": abbr,
            "note_count": notes_n,
            "has_pitched": pitched,
            "has_unpitched": unpitched,
        })
    # 谱体里有、part-list 里没有的 part 同样是结构损坏
    listed = {p["id"] for p in parts}
    for pid in part_ids - listed:
        raise ScoreError(f"谱体声部 <part id=\"{pid}\"> 未在 <part-list> 中声明，文件结构不完整。")
    if not parts:
        raise ScoreError("文件中没有任何声部。")
    return parts


def _part_note_stats(root, pid: str):
    part = next((p for p in root if isinstance(p.tag, str) and localname(p) == "part" and p.get("id") == pid), None)
    pitched = unpitched = notes_n = 0
    for note in part.iter():
        if not isinstance(note.tag, str) or localname(note) != "note":
            continue
        notes_n += 1
        if find_child(note, "unpitched") is not None:
            unpitched += 1
        if find_child(note, "pitch") is not None:
            pitched += 1
    return pitched > 0, unpitched > 0, notes_n


# ================================================================ 第一遍：校验

def _check_transpose_changes(part, pid):
    """乐器移调记号只允许出现在第一小节，且全曲只能有一个（否则结构无法统一处理）。"""
    seen = None
    for mi, measure in enumerate(find_children(part, "measure"), start=1):
        attrs = find_child(measure, "attributes")
        if attrs is None:
            continue
        for tr in find_children(attrs, "transpose"):
            if seen is not None:
                raise ScoreError(f"声部 {pid} 在第 {seen} 小节之后再次出现 <transpose>，"
                                 "本应用不支持中途更换移调乐器，已拒绝整份转换。")
            seen = mi
    return seen


def _check_staff_key_details(part, pid):
    """拒绝 staff-details / 每 staff 独立调号、微音分、未知变音记号等复杂情形。"""
    for measure in find_children(part, "measure"):
        for attrs_el in [c for c in measure if isinstance(c.tag, str) and localname(c) == "attributes"]:
            if find_child(attrs_el, "staff-details") is not None:
                raise ScoreError(f"声部 {pid} 含 <staff-details>（特殊谱表），结构无法完整保留，已拒绝整份转换。")
            for key_el in find_children(attrs_el, "key"):
                if child_text(key_el, "staff") is not None:
                    raise ScoreError(f"声部 {pid} 含按谱表分别设置的调号（<key staff>），"
                                     "本应用无法保证其完整正确转换，已拒绝整份转换。")
                # key-accidental（自定义调号变音）：放弃
                if find_child(key_el, "key-accidental") is not None:
                    raise ScoreError(f"声部 {pid} 含自定义调号变音（key-accidental），已拒绝整份转换。")
                fifths = child_text(key_el, "fifths")
                if fifths is None:
                    if find_child(key_el, "non-key-accidental") is not None:
                        continue
                    raise ScoreError(f"声部 {pid} 存在既无 fifths 也无 non-key-accidental 的调号，已拒绝整份转换。")
                f = int_text(fifths)
                if f is None or not (-42 <= f <= 42):
                    raise ScoreError(f"声部 {pid} 的调号 fifths={fifths} 超出可处理范围，已拒绝整份转换。")


def _tie_and_note_checks(part, pid, key_state):
    """遍历所有 note：
    - 拒绝无调打击乐；
    - 拒绝微音分 alter / 未知 <accidental> 文本；
    - 校验延音线成对且书写音高一致；
    返回有调音符数。
    """
    # (staff, voice) -> 尚未闭合的延音线栈，每项 (pitch 三元组, 起始小节)
    open_ties: dict[tuple, list] = {}
    pitched_count = 0
    for measure in find_children(part, "measure"):
        mnum = measure.get("number") or "?"
        for note in [c for c in measure if isinstance(c.tag, str) and localname(c) == "note"]:
            if find_child(note, "unpitched") is not None:
                raise ScoreError(f"声部 {pid} 第 {mnum} 小节含无固定音高打击乐（unpitched），"
                                 "本应用只支持有调乐器，已拒绝整份转换。")
            pitch_el = find_child(note, "pitch")
            rest_el = find_child(note, "rest")
            if pitch_el is not None:
                tup = pitch_tuple(pitch_el)
                if tup is None:
                    raise ScoreError(f"声部 {pid} 第 {mnum} 小节存在 step/octave 缺失的音高，文件可能已损坏。")
                step, alter, octave = tup
                pitched_count += 1
                raw_alter = child_text(pitch_el, "alter")
                if raw_alter is not None:
                    a = int_text(raw_alter)
                    if a is None or a != float_safe(raw_alter):
                        raise ScoreError(f"声部 {pid} 第 {mnum} 小节含微音分/非整数变音（alter={raw_alter}），"
                                         "本应用不支持，已拒绝整份转换。")
                _check_accidental_text(note, pid, mnum)
                _apply_ties(note, step, alter, octave, open_ties, pid, mnum)
            elif rest_el is None:
                raise ScoreError(f"声部 {pid} 第 {mnum} 小节存在类型不明的 <note>，文件可能已损坏。")
    for (staff, voice), stack in open_ties.items():
        for s, a, o, m0 in stack:
            raise ScoreError(f"声部 {pid} 存在未闭合的延音线（始于第 {m0} 小节 {pitch_string(s,a,o)}），"
                             "结构不完整，已拒绝整份转换。")
    return pitched_count


def float_safe(text):
    try:
        return float(text.strip())
    except ValueError:
        return None


def _check_accidental_text(note, pid, mnum):
    acc = find_child(note, "accidental")
    if acc is None or not acc.text or not acc.text.strip():
        return
    text = acc.text.strip()
    # 括号/提示性记号是属性，正文仍应是标准词
    known = {
        "sharp", "natural", "flat", "double-sharp", "sharp-sharp", "flat-flat",
        "natural-sharp", "natural-flat", "quarter-flat", "quarter-sharp",
        "three-quarters-flat", "three-quarters-sharp", "sharp-up", "sharp-down",
        "natural-up", "natural-down", "flat-up", "flat-down",
        "double-sharp-up", "double-sharp-down", "flat-flat-up", "flat-flat-down",
        "arrow-up", "arrow-down", "other-",
    }
    if any(text == k or (k.endswith("-") and text.startswith(k)) for k in known):
        if "quarter" in text or "three-quarters" in text or text in (
                "sharp-up", "sharp-down", "natural-up", "natural-down",
                "flat-up", "flat-down", "double-sharp-up", "double-sharp-down",
                "flat-flat-up", "flat-flat-down", "arrow-up", "arrow-down") \
                or text.startswith("other-"):
            raise ScoreError(f"声部 {pid} 第 {mnum} 小节含非常规/微音分变音记号“{text}”，"
                             "本应用无法保证正确转换，已拒绝整份转换。")
        return
    raise ScoreError(f"声部 {pid} 第 {mnum} 小节含无法识别的变音记号“{text}”，"
                     "已拒绝整份转换。")


def _apply_ties(note, step, alter, octave, open_ties, pid, mnum):
    staff = staff_of(note)
    voice_el = child_text(note, "voice")
    voice = voice_el if voice_el is not None else "1"
    key = (staff, voice)
    stack = open_ties.setdefault(key, [])
    ties = find_children(note, "tie")
    types = [t.get("type") for t in ties if t.get("type")]
    if "start" in types:
        stack.append((step, alter, octave, mnum))
    if "stop" in types:
        if not stack:
            raise ScoreError(f"声部 {pid} 第 {mnum} 小节出现没有起点的延音线终点，结构异常，已拒绝整份转换。")
        s0, a0, o0, m0 = stack.pop()
        if (s0, a0, o0) != (step, alter, octave):
            raise ScoreError(
                f"声部 {pid} 的延音线两端书写音高不一致"
                f"（第 {m0} 小节 {pitch_string(s0,a0,o0)} ↔ 第 {mnum} 小节 {pitch_string(step,alter,octave)}），"
                "源文件本身已破坏该结构，已拒绝整份转换。")


# ================================================================ 调号状态

class KeyState:
    """按谱表跟踪当前调号（无 staff 属性的 key 同时作用于所有谱表）。"""

    def __init__(self):
        self._fifths = {}   # staff -> fifths
        self._default = 0

    def set_all(self, fifths):
        self._default = fifths
        self._fifths = {}

    def set_staff(self, staff, fifths):
        self._fifths[staff] = fifths

    def get(self, staff):
        return self._fifths.get(staff, self._default)


def infer_alter_from_key(step_letter: str, octave: int, fifths: int) -> int:
    """没有显式 alter 的音符，按当前调号推断其 alter。

    fifths 可为负（降号调），绝对值大于 7 时对应重升/重降。
    """
    diat = letter_diatonic(step_letter)
    n = abs(fifths)
    order = SHARP_ORDER if fifths >= 0 else FLAT_ORDER
    count = sum(1 for i in range(n) if order[i % 7] == diat)
    sign = 1 if fifths > 0 else -1
    return sign * count


# ================================================================ 第二遍：执行移调

def transpose_part_tree(tree: etree._ElementTree, part_id: str,
                        diatonic: int, chromatic: int,
                        range_lo: tuple, range_hi: tuple,
                        dst_diatonic: int = None, dst_chromatic: int = None) -> list[dict]:
    """在 tree 的副本上就地移调指定声部、删除其他声部。返回超出音域清单。

    diatonic/chromatic：实际作用于记谱音的有向位移（= 原乐器偏移 - 目标乐器偏移）；
    dst_*：输出 <transpose> 要写入的目标乐器“记谱->发声”偏移。
    """
    root = tree.getroot()
    part = next((p for p in root if isinstance(p.tag, str) and localname(p) == "part" and p.get("id") == part_id), None)
    if part is None:
        raise ScoreError(f"内部错误：找不到声部 {part_id}。")

    # ---- 校验
    _check_transpose_changes(part, part_id)
    _check_staff_key_details(part, part_id)
    key_state = KeyState()
    pitched_count = _tie_and_note_checks(part, part_id, key_state)
    if pitched_count == 0:
        raise ScoreError(f"声部 {part_id} 没有任何有音高的音符，无法生成移调分谱，已拒绝整份转换。")

    # ---- 执行
    # src_key：源谱当前调号（用于解析无 <alter> 源音的原始 alter）；
    # new_key：移调后的当前调号（用于决定临时记号是否显示）。
    src_key = KeyState()
    new_key = KeyState()
    tie_start_pitch = {}   # (staff,voice) -> 未闭合 tie 起点的【新】音高三元组
    tie_start_src = {}     # (staff,voice) -> 未闭合 tie 起点的【源】音高三元组
    out_of_range = []
    lo_midi = pitch_midi(*range_lo)
    hi_midi = pitch_midi(*range_hi)
    if lo_midi > hi_midi:
        raise ValidationError("目标音域下限高于上限，请重新填写。")

    for measure in find_children(part, "measure"):
        mnum = measure.get("number") or "?"

        # 第零步：先取出本小节声明的【源】调号（作用于本小节全部音符），
        # 但暂不改写 <key>（移调后的 fifths 在第二步写回）。
        measure_key_changes = []  # (key_el, fifths, staff_or_None)
        for attrs_el in [c for c in measure if isinstance(c.tag, str) and localname(c) == "attributes"]:
            for key_el in find_children(attrs_el, "key"):
                ft = child_text(key_el, "fifths")
                if ft is None:
                    continue
                fv = int_text(ft)
                st = child_text(key_el, "staff")
                measure_key_changes.append((key_el, fv, int(st) if st is not None else None))
        for _, fv, st in measure_key_changes:
            if st is None:
                src_key.set_all(fv)
            else:
                src_key.set_staff(st, fv)

        # 第一步：用【源调号】解析本小节源音的 alter，并计算移调后音高（暂不写回）。
        # 延音线延续音（仅 tie stop、无 <alter>）沿用本 (staff,voice) tie 起点的 alter。
        pending = []
        for note in [c for c in measure if isinstance(c.tag, str) and localname(c) == "note"]:
            pitch_el = find_child(note, "pitch")
            if pitch_el is None:
                continue  # 休止：原样保留
            step, alter, octave = pitch_tuple(pitch_el)
            staff = staff_of(note)
            voice = child_text(note, "voice") or "1"
            had_explicit = child_text(pitch_el, "alter") is not None
            tie_types = {t.get("type") for t in find_children(note, "tie") if t.get("type")}
            tkey = (staff, voice)
            if not had_explicit:
                if "stop" in tie_types and "start" not in tie_types and tie_start_src.get(tkey) is not None:
                    s0, a0, o0 = tie_start_src[tkey]
                    if (s0, o0) != (step, octave):
                        raise ScoreError(
                            f"声部 {part_id} 第 {mnum} 小节延音线两端音名/八度不一致，"
                            "源文件结构异常，已拒绝整份转换。")
                    alter = a0
                else:
                    alter = infer_alter_from_key(step, octave, src_key.get(staff))
            new_triple = transpose_pitch(step, alter, octave, diatonic, chromatic)
            if "start" in tie_types:
                tie_start_src[tkey] = (step, alter, octave)
                tie_start_pitch[tkey] = new_triple
            if "stop" in tie_types and "start" not in tie_types:
                tie_start_src.pop(tkey, None)
                tie_start_pitch.pop(tkey, None)
            pending.append((pitch_el, note, had_explicit, (step, alter, octave), new_triple, staff))

        # 第二步：改写 <key fifths> 并推进新调号状态。
        for key_el, fv, st in measure_key_changes:
            mode = (child_text(key_el, "mode") or "major").strip().lower()
            minor = mode == "minor"
            new_fifths = fifths_transposed(fv, minor, diatonic, chromatic)
            while new_fifths > 42:
                new_fifths -= 84
            while new_fifths < -42:
                new_fifths += 84
            if not (-42 <= new_fifths <= 42):
                raise ScoreError(f"声部 {part_id} 第 {mnum} 小节移调后调号超出可表示范围，已拒绝整份转换。")
            set_child_text(key_el, "fifths", str(new_fifths))
            if st is None:
                new_key.set_all(new_fifths)
            else:
                new_key.set_staff(st, new_fifths)

        # 第三步：写回移调后的音高与临时记号（依据新调号与本小节同音级状态）。
        seen_alter = {}
        for pitch_el, note, had_explicit, old_triple, (nl, na, no), staff in pending:
            key_alter = infer_alter_from_key(nl, no, new_key.get(staff))
            dkey = (staff, no * 7 + letter_diatonic(nl))
            _write_pitch(pitch_el, note, nl, na, no, key_alter, had_explicit,
                         seen_alter.get(dkey))
            seen_alter[dkey] = na
            if not (lo_midi <= pitch_midi(nl, na, no) <= hi_midi):
                out_of_range.append({
                    "measure": mnum,
                    "pitch": pitch_string(nl, na, no),
                    "sounding_check": pitch_string(*old_triple),
                })

    _transpose_harmonies(part, diatonic, chromatic)
    _rewrite_part_transpose(part,
                            dst_diatonic if dst_diatonic is not None else diatonic,
                            dst_chromatic if dst_chromatic is not None else chromatic)

    if out_of_range:
        raise RangeExceeded(out_of_range)
    return out_of_range


def _write_pitch(pitch_el, note, letter, alter, octave, key_alter,
                 src_had_explicit, prev_alter):
    """写回移调后的音高，并按记谱规则处理 <alter> 与 <accidental>。

    - key_alter：该音名在【新】调号下应有的 alter；
    - src_had_explicit：源音是否带显式 <alter>（显式变音必须保留）；
    - prev_alter：本小节同音级（同八度同音名）此前已记的 alter，用于还原号。

    <alter> 的写入规则：只要 alter != 0 或源音曾显式给出 alter，就写 <alter>，
    保证音高信息无损；<accidental>（是否印出记号）按记谱惯例决定。
    """
    set_child_text(pitch_el, "step", letter)
    set_child_text(pitch_el, "octave", str(octave))

    # 演奏者对该音级当前“预期”的 alter：
    # 本小节同音级此前出现过 -> 沿用最近一次 alter（临时号在小节内持续）；
    # 否则 -> 新调号默认 alter。实际 alter 与预期不同就必须印出记号（含还原号）。
    expected_alter = prev_alter if prev_alter is not None else key_alter
    needs_acc = (alter != expected_alter)

    # 需要印记号（含还原）时也显式写出 <alter>，保证音高信息无歧义
    if alter != 0 or src_had_explicit or needs_acc:
        set_child_text(pitch_el, "alter", str(alter))
    else:
        existing = find_child(pitch_el, "alter")
        if existing is not None:
            pitch_el.remove(existing)
    _reorder_pitch(pitch_el)

    acc_el = find_child(note, "accidental")
    # 保留源 <accidental> 上的版式属性（editorial/cautionary/brackets 等），仅改文本
    if needs_acc:
        if acc_el is None:
            acc_el = etree.SubElement(note, "accidental")
        acc_el.text = alter_to_text(alter)
        _place_accidental(note, acc_el)
    elif acc_el is not None and acc_el.get("cautionary") != "yes":
        note.remove(acc_el)
    elif acc_el is not None and acc_el.get("cautionary") == "yes":
        # 保留提示性记号但更新文本（如自然号提示）
        acc_el.text = alter_to_text(alter)


def _place_accidental(note, acc_el):
    """把 <accidental> 放到 note 内合法位置（pitch/dot/time-modification 之后）。"""
    if acc_el.getparent() is note:
        note.remove(acc_el)
    anchor = None
    priority = {"pitch", "rest", "unpitched", "dot", "time-modification",
                "stem", "notehead", "notehead-text", "grace", "cue",
                "chord", "duration", "tie", "listen", "play"}
    # 简单策略：插到 <type> 之前（accidental 允许出现在 type 前）
    for ch in note:
        if localname(ch) == "type":
            ch.addprevious(acc_el)
            return
    note.append(acc_el)


def _reorder_pitch(pitch_el):
    order = {"step": 0, "alter": 1, "octave": 2}
    children = list(pitch_el)
    children.sort(key=lambda ch: order.get(localname(ch), 9))
    for ch in children:
        pitch_el.remove(ch)
    for ch in children:
        pitch_el.append(ch)


def _transpose_harmonies(part, d, c):
    """和弦标记 <harmony>：根音/低音按同一音程移调，功能标记等文字保留。"""
    for harmony in part.iter():
        if not isinstance(harmony.tag, str) or localname(harmony) != "harmony":
            continue
        for tag in ("root-step", "bass-step"):
            pass
        root = find_child(harmony, "root")
        if root is not None:
            _move_harmony_step(root, "root-step", "root-alter", d, c)
        bass = find_child(harmony, "bass")
        if bass is not None:
            _move_harmony_step(bass, "bass-step", "bass-alter", d, c)


def _move_harmony_step(parent, step_tag, alter_tag, d, c):
    step_el = find_child(parent, step_tag)
    if step_el is None or not step_el.text or step_el.text.strip().upper() not in "CDEFGAB":
        return
    letter = step_el.text.strip().upper()
    alter_el = find_child(parent, alter_tag)
    alter = 0
    if alter_el is not None and alter_el.text is not None:
        a = int_text(alter_el.text)
        if a is None:
            raise ScoreError("和弦标记含非整数变音，无法转换，已拒绝整份转换。")
        alter = a
    # 和弦标记没有八度，用固定八度 3 参与拼写计算
    nl, na, _ = transpose_pitch(letter, alter, 3, d, c)
    step_el.text = nl
    if na == 0:
        if alter_el is not None:
            alter_el.text = "0"
    else:
        if alter_el is None:
            alter_el = etree.SubElement(parent, alter_tag)
        alter_el.text = str(na)


def _rewrite_part_transpose(part, diatonic, chromatic):
    """把输出分谱的乐器移调标记设为目标值（记谱音→实际发声音）。

    写入【完整】有向音程：diatonic/chromatic 直接保留（含真实八度差）。
    下游播放器按该标记还原后，发声音高仍等于原谱。
    """
    first = find_children(part, "measure")
    if not first:
        return
    attrs = find_child(first[0], "attributes")
    if attrs is None:
        attrs = etree.Element("attributes")
        first[0].insert(0, attrs)
    for tr in find_children(attrs, "transpose"):
        attrs.remove(tr)
    tr = etree.Element("transpose")
    d_el = etree.SubElement(tr, "diatonic")
    d_el.text = str(diatonic)
    c_el = etree.SubElement(tr, "chromatic")
    c_el.text = str(chromatic)
    # 插到 <divisions> 之后、其他属性之前（MusicXML 建议顺序）
    idx = 0
    for i, ch in enumerate(attrs):
        if localname(ch) in ("divisions",):
            idx = i + 1
    attrs.insert(idx, tr)


# ================================================================ 分谱抽取

def extract_single_part(loaded: LoadedScore, part_id: str) -> etree._ElementTree:
    """深拷贝整树后，仅保留选定声部，生成单分谱文档。"""
    tree = copy.deepcopy(loaded.tree)
    root = tree.getroot()
    part_list = find_child(root, "part-list")

    # part-list：删除其余 score-part 与所有 part-group
    for sp in list(find_children(part_list, "score-part")):
        if sp.get("id") != part_id:
            part_list.remove(sp)
    for pg in list(find_children(part_list, "part-group")):
        part_list.remove(pg)

    # 谱体：删除其余 part
    for p in [c for c in root if isinstance(c.tag, str) and localname(c) == "part"]:
        if p.get("id") != part_id:
            root.remove(p)

    # 给保留声部加“（移调分谱）”后缀
    sp = next(iter(find_children(part_list, "score-part")), None)
    if sp is not None:
        pn = find_child(sp, "part-name")
        if pn is not None and pn.text and NAME_SUFFIX not in pn.text:
            pn.text = (pn.text or "") + NAME_SUFFIX
    return tree


def count_measures(part) -> int:
    return len(find_children(part, "measure"))
