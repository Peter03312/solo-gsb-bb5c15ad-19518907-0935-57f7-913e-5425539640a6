"""音程与音域的校验、计算。

约定（与界面文案一致）：
- “有向字母步数” diatonic：记谱音到发声音跨越的音级数量（C4→D4=1，C4→C5=7），
  下行取负（C4→B3=-1）。
- “有向半音数” chromatic：同一有向音程包含的半音数，下行取负。
"""
from __future__ import annotations

import re

from .mx import (
    ValidationError,
    letter_diatonic,
    diatonic_letter,
)

# |字母步数| -> 该音级数可能覆盖的半音区间。允许从“倍减”到“倍增”较宽范围，
# 但仍须落在真实可拼写的区间内。
# 依据：n 级音程的半音数基准（大/完全），向两侧放宽 2 个半音。
_MAJOR_ST = (0, 2, 4, 5, 7, 9, 11)
MIN_CHROM = -3 * 12
MAX_CHROM = 3 * 12
MIN_DIAT = -3 * 7
MAX_DIAT = 3 * 7

_PITCH_RE = re.compile(r"^([A-Ga-g])(#{1,2}|b{1,2}|x)?(-?\d+)$")
_ACC_SEMI = {"": 0, "#": 1, "x": 2, "b": -1, "bb": -2}


def validate_interval(diatonic: int, chromatic: int, what: str = "音程"):
    """校验一对有向（字母步数, 半音数）是否构成合法有向音程。"""
    if not isinstance(diatonic, int) or not isinstance(chromatic, int):
        raise ValidationError(f"{what}必须为整数。")
    if not (MIN_DIAT <= diatonic <= MAX_DIAT):
        raise ValidationError(f"{what}的字母步数超出 ±{MAX_DIAT}（三个八度）范围。")
    if not (MIN_CHROM <= chromatic <= MAX_CHROM):
        raise ValidationError(f"{what}的半音数超出 ±{MAX_CHROM}（三个八度）范围。")

    if diatonic == 0:
        # 仅允许同度附近：倍减/减/纯/增/倍增一度 -> 半音 -2..2
        if not (-2 <= chromatic <= 2):
            raise ValidationError(
                f"{what}无效：字母步数为 {diatonic}（同度），半音数 {chromatic} 无法拼写。"
            )
        return

    same_sign = (diatonic > 0 and chromatic > 0) or (diatonic < 0 and chromatic < 0)
    if not same_sign:
        raise ValidationError(
            f"{what}无效：字母步数 {diatonic} 与半音数 {chromatic} 方向不一致（上下行必须同号）。"
        )

    n = abs(diatonic)
    octv, deg = divmod(n, 7)  # deg: 0=八度倍数, 1..6=二度..七度
    base = octv * 12 + (_MAJOR_ST[deg] if deg else 0)
    c = abs(chromatic)
    # 允许倍减 ~ 倍增：基准两侧各 2 个半音。
    if not (base - 2 <= c <= base + 2):
        raise ValidationError(
            f"{what}无效：{n} 级音程不可能包含 {c} 个半音"
            f"（合法范围约 {base - 2}–{base + 2}）。"
        )


# ---------------------------------------------------------------- 移调计算

def spell_note(diat_num: int, chrom: int):
    """给定绝对“自然音级数/半音数”坐标，返回 (字母, alter)，要求 alter ∈ [-2,2]。

    diat_num：自然音级绝对编号（C 八度数*7 + 音级，如 C4=28）。
    chrom：    半音绝对数（MIDI 号）。
    """
    letter = diat_num % 7
    natural_st = [0, 2, 4, 5, 7, 9, 11][letter]
    octave_natural = natural_st + (diat_num // 7) * 12
    alter = chrom - octave_natural
    if alter < -2 or alter > 2:
        raise ValidationError(
            f"移调后 {diatonic_letter(letter)} 音需要 {alter:+d} 个半音变音记号，"
            "超出两升/两降范围，该移调音程无法用常规记谱书写。"
        )
    return letter, alter


def transpose_pitch(step: str, alter: int, octave: int, d: int, c: int):
    """移调单个音高（不改变八度原则由 d/c 本身保证）。

    返回 (新字母, 新 alter, 新八度)。
    """
    dnum = octave * 7 + letter_diatonic(step) + d
    new_oct, rem = divmod(dnum, 7)
    new_letter = diatonic_letter(rem)
    natural = [0, 2, 4, 5, 7, 9, 11][rem]
    old_chrom = octave * 12 + [0, 2, 4, 5, 7, 9, 11][letter_diatonic(step)] + alter + c
    new_alter = old_chrom - (new_oct * 12 + natural)
    if new_alter < -2 or new_alter > 2:
        raise ValidationError(
            f"音符 {step}{octave} 移调后需 {new_alter:+d} 个变音半音，"
            "超出两升/两降，无法常规记谱。"
        )
    return new_letter, new_alter, new_oct


def fifths_transposed(old_fifths: int, minor: bool, d: int, c: int) -> int:
    """求移调后的调号 fifths。

    利用调主音坐标（相对调号 K 与模式）：
      大调主音 letter=4K (mod7)，chroma=7K (mod12)；
      小调主音 letter=4K-2 (mod7)，chroma=7K-3 (mod12)（关系小调）。
    主音按 (d,c) 移调后，用中国剩余定理反求新调号 K'（7 与 12 互素）。
    """
    K = old_fifths
    L = (4 * K - (2 if minor else 0)) % 7
    p = (7 * K - (3 if minor else 0)) % 12
    L2 = (L + d) % 7
    p2 = (p + c) % 12
    if minor:
        r7 = (2 * (L2 + 2)) % 7
        r12 = (7 * (p2 + 3)) % 12
    else:
        r7 = (2 * L2) % 7
        r12 = (7 * p2) % 12
    k = ((r12 - r7) * _INV7_MOD12) % 12
    nf = r7 + 7 * k
    while nf > 42:
        nf -= 84
    while nf < -42:
        nf += 84
    return nf


_INV7_MOD12 = 7  # 7*7=49 ≡ 1 (mod 12)


def normalize_fifths(new_fifths: int, old_fifths: int) -> int:
    """把目标调号折叠到 MusicXML 常用范围 -7..7。

    |fifths|==7 为 C#/Cb 等边界调，优先保留与原调同侧的拼写。
    """
    f = new_fifths
    while f > 7:
        f -= 12
    while f < -7:
        f += 12
    if f == 7 and old_fifths < 0:
        return -5
    if f == -7 and old_fifths > 0:
        return 5
    return f


# ---------------------------------------------------------------- 目标音域

def parse_pitch(text: str, what: str = "音高"):
    """解析如 C4 / Bb3 / F#5 / Cx4 形式的音高，返回 (step, alter, octave)。"""
    if text is None:
        raise ValidationError(f"{what}不能为空。")
    m = _PITCH_RE.match(text.strip())
    if not m:
        raise ValidationError(f"{what}“{text}”格式无效，示例：C4、Bb3、F#5。")
    step, acc, octv = m.group(1).upper(), m.group(2) or "", int(m.group(3))
    if octv < -1 or octv > 12:
        raise ValidationError(f"{what}的八度 {octv} 不合理（允许 -1 至 12）。")
    return step, _ACC_SEMI[acc], octv


def pitch_midi(step: str, alter: int, octave: int) -> int:
    """标准 MIDI 号：C4 = 60。"""
    return (octave + 1) * 12 + [0, 2, 4, 5, 7, 9, 11][letter_diatonic(step)] + alter
