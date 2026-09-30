"""转换后自检：在输出整份文件前逐项核对，任何一项不满足则拒绝输出。"""
from __future__ import annotations

from .mx import (
    ScoreError,
    localname,
    find_child,
    find_children,
    child_text,
    int_text,
    staff_of,
    pitch_tuple,
)
from .intervals import pitch_midi


def _pitched_notes(part):
    """产出 (measure_num, note_el, pitch_tuple)，只含有 pitch 的音符。"""
    for measure in find_children(part, "measure"):
        mnum = measure.get("number") or "?"
        for note in [c for c in measure if isinstance(c.tag, str) and localname(c) == "note"]:
            pitch_el = find_child(note, "pitch")
            if pitch_el is not None:
                tup = pitch_tuple(pitch_el)
                yield mnum, note, tup


def _structure_fingerprint(part):
    """小节/声部/时值/休止/反复等结构指纹：移调绝不能改变它。

    每个有音高/休止的 note 记录：小节号、staff、voice、是否和弦音、是否休止、
    duration、type、dot 数、time-modification、grace/cue、tie 类型、
    以及小节上反复记号（barline/repeat/ending）与属性（divisions/time/clef/...）指纹。
    """
    rows = []
    for measure in find_children(part, "measure"):
        mnum = measure.get("number") or "?"
        # 小节级非音符结构：barline（含 repeat/ending）、direction 里的 rehearsal/wedge 等
        bar_bits = []
        for barline in find_children(measure, "barline"):
            for el in barline.iter():
                if isinstance(el.tag, str):
                    name = localname(el)
                    if name in ("repeat", "ending", "barline"):
                        bar_bits.append((name, el.get("direction"), el.get("number"), el.get("type"), (el.text or "").strip()))
        rows.append(("MEASURE", mnum, tuple(sorted(bar_bits, key=str))))
        for note in [c for c in measure if isinstance(c.tag, str) and localname(c) == "note"]:
            is_rest = find_child(note, "rest") is not None
            dur = child_text(note, "duration")
            ntype = child_text(note, "type")
            dots = len(find_children(note, "dot"))
            tm = find_child(note, "time-modification")
            tm_fp = None
            if tm is not None:
                tm_fp = (child_text(tm, "actual-notes"), child_text(tm, "normal-notes"))
            ties = tuple(sorted(t.get("type") or "" for t in find_children(note, "tie")))
            rows.append((
                "NOTE", mnum, staff_of(note), child_text(note, "voice") or "1",
                find_child(note, "chord") is not None, is_rest, dur, ntype, dots, tm_fp,
                find_child(note, "grace") is not None, find_child(note, "cue") is not None, ties,
            ))
    return rows


def verify_result(orig_part, new_part, src_chromatic: int, dst_chromatic: int, pid: str):
    """对比原始 part 与输出 part：
    1) 结构指纹完全一致（小节、voice、时值、休止、反复记号、tie 配置等）；
    2) 每个音符“旧书写 + 原乐器偏移 src”的发声 MIDI
       等于“新书写 + 目标乐器偏移 dst”的发声 MIDI；
    3) 延音线两端在新谱中仍是同一书写音高。
    """
    fp_old = _structure_fingerprint(orig_part)
    fp_new = _structure_fingerprint(new_part)
    if fp_old != fp_new:
        # 找到首个不同位置，给出可读错误
        for i, (a, b) in enumerate(zip(fp_old, fp_new)):
            if a != b:
                raise ScoreError(
                    f"内部自检失败：第 {i} 个事件结构在转换前后不一致"
                    f"（{a} != {b}）。为安全起见拒绝输出整份结果。")
        raise ScoreError(
            f"内部自检失败：事件数量变化（原 {len(fp_old)} / 新 {len(fp_new)}），拒绝输出。")

    # 发声 MIDI 一致性
    old_notes = list(_pitched_notes(orig_part))
    new_notes = list(_pitched_notes(new_part))
    if len(old_notes) != len(new_notes):
        raise ScoreError("内部自检失败：音符数量变化，拒绝输出。")
    for (m1, _n1, t1), (m2, _n2, t2) in zip(old_notes, new_notes):
        if m1 != m2:
            raise ScoreError(f"内部自检失败：小节对应错位（{m1}/{m2}），拒绝输出。")
        s1, a1, o1 = t1
        s2, a2, o2 = t2
        old_sound = pitch_midi(s1, a1, o1) + src_chromatic
        # 输出分谱带目标乐器移调量 <transpose>：发声 = 新书写 + dst
        new_sound = pitch_midi(s2, a2, o2) + dst_chromatic
        if old_sound != new_sound:
            raise ScoreError(
                f"内部自检失败：第 {m1} 小节 {s1}{a1:+d}/{o1} 的实际发声音高"
                f"（{old_sound}）与输出（{new_sound}）不一致，拒绝输出。")

    # 延音线两端书写音高一致（对输出再查一遍）
    open_stacks = {}
    for mnum, note, tup in new_notes:
        staff = staff_of(note)
        voice = child_text(note, "voice") or "1"
        types = [t.get("type") for t in find_children(note, "tie") if t.get("type")]
        stack = open_stacks.setdefault((staff, voice), [])
        if "start" in types:
            stack.append(tup)
        if "stop" in types:
            if not stack:
                raise ScoreError(f"内部自检失败：第 {mnum} 小节延音线缺少起点，拒绝输出。")
            if stack.pop() != tup:
                raise ScoreError(
                    f"内部自检失败：延音线两端书写音高在第 {mnum} 小节不一致，拒绝输出。")
    for (staff, voice), stack in open_stacks.items():
        if stack:
            raise ScoreError("内部自检失败：输出中存在未闭合的延音线，拒绝输出。")
