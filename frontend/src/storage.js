// 本地存储：参数预设、最近一次表单、历史记录。全部只存在浏览器 localStorage。
const KEY_FORM = 'tp.form.v1'
const KEY_HISTORY = 'tp.history.v1'
const KEY_CUSTOM_PRESETS = 'tp.presets.v1'

export const HISTORY_LIMIT = 20

function safeParse(text, fallback) {
  try {
    return text == null ? fallback : JSON.parse(text)
  } catch {
    return fallback
  }
}

export function loadForm() {
  return safeParse(localStorage.getItem(KEY_FORM), null)
}

export function saveForm(form) {
  try {
    localStorage.setItem(KEY_FORM, JSON.stringify(form))
  } catch {
    /* 存储已满或被禁用：静默忽略，不影响转换本身 */
  }
}

export function loadHistory() {
  const list = safeParse(localStorage.getItem(KEY_HISTORY), [])
  return Array.isArray(list) ? list : []
}

export function addHistory(entry) {
  // 只存元信息（不含 MusicXML 正文，避免占用过多配额）
  const list = loadHistory().filter((h) => h.id !== entry.id)
  list.unshift(entry)
  try {
    localStorage.setItem(KEY_HISTORY, JSON.stringify(list.slice(0, HISTORY_LIMIT)))
  } catch {
    /* ignore */
  }
  return list.slice(0, HISTORY_LIMIT)
}

export function clearHistory() {
  localStorage.removeItem(KEY_HISTORY)
}

export function loadCustomPresets() {
  return safeParse(localStorage.getItem(KEY_CUSTOM_PRESETS), [])
}

export function saveCustomPreset(preset) {
  const list = loadCustomPresets()
  const idx = list.findIndex((p) => p.id === preset.id)
  if (idx >= 0) list[idx] = preset
  else list.push(preset)
  localStorage.setItem(KEY_CUSTOM_PRESETS, JSON.stringify(list))
  return list
}

// 最近一次成功生成的 MusicXML 正文单独存（用于刷新后仍可预览/下载）
const KEY_LAST_XML = 'tp.lastXml.v1'

export function saveLastResult({ filename, xml, meta }) {
  try {
    localStorage.setItem(
      KEY_LAST_XML,
      JSON.stringify({ filename, xml, meta, savedAt: new Date().toISOString() }),
    )
  } catch {
    /* 大谱可能超配额：忽略，不阻断主流程 */
  }
}

export function loadLastResult() {
  return safeParse(localStorage.getItem(KEY_LAST_XML), null)
}
