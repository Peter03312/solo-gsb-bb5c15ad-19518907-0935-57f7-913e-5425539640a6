// 轻量客户端校验，用于即时反馈；最终以后端校验为准。
export function isInt(v) {
  return /^[+-]?\d+$/.test(String(v).trim())
}

const PITCH_RE = /^([A-G])(#{1,2}|b{1,2}|x)?(-?\d+)$/

export function isPitch(v) {
  return PITCH_RE.test(String(v).trim())
}

// 与后端一致的有向音程合法性快检（仅提示用）
const MAJOR_ST = [0, 2, 4, 5, 7, 9, 11]

export function intervalHint(d, c) {
  if (!isInt(d) || !isInt(c)) return { ok: false, msg: '字母步数与半音数须为整数。' }
  d = Number(d)
  c = Number(c)
  if (d < -21 || d > 21 || c < -36 || c > 36)
    return { ok: false, msg: '超出允许范围（字母 ±21、半音 ±36）。' }
  if (d === 0) {
    if (c < -2 || c > 2) return { ok: false, msg: '同度的半音数应在 −2～+2（倍增一度以内）。' }
    return { ok: true }
  }
  if ((d > 0 && c <= 0) || (d < 0 && c >= 0))
    return { ok: false, msg: '字母步数与半音数方向必须一致（同正或同负）。' }
  const n = Math.abs(d)
  const oct = Math.floor(n / 7)
  const deg = n % 7
  const base = oct * 12 + MAJOR_ST[deg]
  const cc = Math.abs(c)
  if (cc < base - 2 || cc > base + 2)
    return { ok: true, msg: `提示：${n} 级音程半音数常见为 ${base}（±2）。` }
  return { ok: true }
}

// 由 src/dst 计算实际移调方向并给出人类可读说明
export function shiftDescription(srcD, srcC, dstD, dstC) {
  if (![srcD, srcC, dstD, dstC].every(isInt)) return ''
  const d = Number(srcD) - Number(dstD)
  const c = Number(srcC) - Number(dstC)
  if (d === 0 && c === 0) return '源与目标乐器移调量相同，记谱音高不移动。'
  const dir = c > 0 ? '上移' : '下移'
  return `记谱音整体${dir} ${Math.abs(c)} 半音（${Math.abs(d)} 个字母级）。`
}
