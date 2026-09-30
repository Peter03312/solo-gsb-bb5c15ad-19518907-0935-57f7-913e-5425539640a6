// 后端 API 封装。统一把 FastAPI 的 HTTPException / JSON 错误转成可读异常。
const BASE = import.meta.env.VITE_API_BASE || ''

async function parseError(res) {
  let payload = null
  try {
    payload = await res.json()
  } catch {
    /* 非 JSON 响应 */
  }
  const detail = payload?.detail
  if (detail && typeof detail === 'object' && detail.error) {
    return {
      message: detail.error,
      code: detail.code || 'error',
      detail: detail.detail || null,
    }
  }
  if (payload?.error) {
    return {
      message: payload.error,
      code: payload.code || 'error',
      detail: payload.detail || null,
    }
  }
  return {
    message: `请求失败（HTTP ${res.status}）`,
    code: 'network_error',
    detail: null,
  }
}

export async function inspectFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}/api/inspect`, { method: 'POST', body: fd })
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function transpose(form, file) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('part_id', form.partId)
  fd.append('src_diatonic', String(form.srcD))
  fd.append('src_chromatic', String(form.srcC))
  fd.append('dst_diatonic', String(form.dstD))
  fd.append('dst_chromatic', String(form.dstC))
  fd.append('range_low', form.rangeLow)
  fd.append('range_high', form.rangeHigh)
  const res = await fetch(`${BASE}/api/transpose`, { method: 'POST', body: fd })
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  // base64 -> UTF-8 XML 字符串
  const bytes = Uint8Array.from(atob(payload.musicxml_base64), (ch) => ch.charCodeAt(0))
  const xml = new TextDecoder('utf-8').decode(bytes)
  return { xml, filename: payload.filename, meta: payload.meta }
}
