const BASE = '/api'

async function parseError(response) {
  let detail = null
  try {
    detail = (await response.json()).detail
  } catch {
    /* non-JSON error body */
  }
  if (detail && typeof detail === 'object' && detail.message) {
    return detail
  }
  return { code: 'http_error', message: `请求失败（${response.status}）` }
}

export async function uploadScore(file) {
  const body = new FormData()
  body.append('file', file)
  const resp = await fetch(`${BASE}/scores`, { method: 'POST', body })
  if (!resp.ok) throw await parseError(resp)
  return resp.json()
}

export async function transpose(payload) {
  const resp = await fetch(`${BASE}/transpose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!resp.ok) throw await parseError(resp)
  return resp.json()
}
