import React, { useEffect, useMemo, useRef, useState } from 'react'
import { inspectFile, transpose } from './api.js'
import { INSTRUMENT_PRESETS, RANGE_PRESETS, findPreset } from './presets.js'
import { isInt, isPitch, intervalHint, shiftDescription } from './validate.js'
import {
  loadForm, saveForm, addHistory, loadHistory, clearHistory,
  saveLastResult, loadLastResult,
} from './storage.js'
import ScorePreview from './components/ScorePreview.jsx'

const DEFAULT_FORM = {
  partId: '',
  srcPreset: 'c', srcD: 0, srcC: 0,
  dstPreset: 'eb-alto', dstD: -5, dstC: -9,
  rangePreset: 'alto-sax', rangeLow: 'Bb2', rangeHigh: 'F#5',
}

export default function App() {
  const [file, setFile] = useState(null)
  const [inspect, setInspect] = useState(null)
  const [inspectError, setInspectError] = useState(null)
  const [loadingInspect, setLoadingInspect] = useState(false)

  const [form, setForm] = useState(() => ({ ...DEFAULT_FORM, ...(loadForm() || {}) }))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)        // {message, code, detail}
  const [result, setResult] = useState(() => loadLastResult())
  const [history, setHistory] = useState(() => loadHistory())
  const fileRef = useRef(null)

  useEffect(() => { saveForm(form) }, [form])

  const patch = (p) => setForm((f) => ({ ...f, ...p }))

  async function handleFile(next) {
    setFile(next)
    setError(null)
    setInspect(null)
    setInspectError(null)
    if (!next) return
    setLoadingInspect(true)
    try {
      const info = await inspectFile(next)
      setInspect(info)
      const exists = info.parts.some((p) => p.id === form.partId)
      if (!form.partId || !exists) {
        const firstPitched = info.parts.find((p) => p.has_pitched && !p.has_unpitched)
        patch({ partId: (firstPitched || info.parts[0]).id })
      }
    } catch (e) {
      setInspectError(e)
    } finally {
      setLoadingInspect(false)
    }
  }

  function applyPreset(side, presetId) {
    const p = INSTRUMENT_PRESETS.find((x) => x.id === presetId)
    if (!p || p.id === 'custom') {
      patch({ [`${side}Preset`]: 'custom' })
      return
    }
    const key = side === 'src' ? 'src' : 'dst'
    patch({ [`${key}Preset`]: p.id, [`${key}D`]: p.d, [`${key}C`]: p.c })
  }

  function applyRangePreset(id) {
    const r = RANGE_PRESETS.find((x) => x.id === id)
    if (r) patch({ rangePreset: id, rangeLow: r.low, rangeHigh: r.high })
  }

  const clientProblems = useMemo(() => {
    const out = []
    if (!file) out.push('请先上传 MusicXML 文件。')
    if (!form.partId) out.push('请选择一个有调乐器声部。')
    const src = intervalHint(form.srcD, form.srcC)
    const dst = intervalHint(form.dstD, form.dstC)
    if (!src.ok) out.push(`原乐器音程无效：${src.msg}`)
    if (!dst.ok) out.push(`目标乐器音程无效：${dst.msg}`)
    if (!isPitch(form.rangeLow)) out.push(`目标音域下限“${form.rangeLow}”不是有效音高（如 Bb2）。`)
    if (!isPitch(form.rangeHigh)) out.push(`目标音域上限“${form.rangeHigh}”不是有效音高（如 F#5）。`)
    return out
  }, [file, form])

  async function handleTranspose() {
    setError(null)
    if (clientProblems.length) {
      setError({ message: clientProblems[0], code: 'client' })
      return
    }
    setBusy(true)
    try {
      const res = await transpose(form, file)
      setResult(res)
      saveLastResult(res)
      const entry = {
        id: `${Date.now()}`,
        at: new Date().toISOString(),
        sourceFile: file.name,
        partName: inspect?.parts.find((p) => p.id === form.partId)?.name || form.partId,
        filename: res.filename,
        meta: res.meta,
        params: {
          src: [Number(form.srcD), Number(form.srcC)],
          dst: [Number(form.dstD), Number(form.dstC)],
          range: [form.rangeLow, form.rangeHigh],
        },
      }
      setHistory(addHistory(entry))
    } catch (e) {
      setResult(null)
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  function downloadResult() {
    if (!result) return
    const blob = new Blob([result.xml], { type: 'application/vnd.recordare.musicxml+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>移调分谱生成器</h1>
        <p className="subtitle">小型合奏排练 · 上传 MusicXML → 指定源/目标移调乐器 → 生成同发声音高的移调分谱</p>
      </header>

      <main className="layout">
        <section className="panel controls">
          <FileUpload
            fileRef={fileRef} file={file} loading={loadingInspect}
            onPick={handleFile} inspectError={inspectError} inspect={inspect}
          />

          <PartSelector
            inspect={inspect} value={form.partId}
            onChange={(id) => patch({ partId: id })}
          />

          <IntervalCard
            title="① 原乐器（源分谱的记谱 → 发声）"
            preset={form.srcPreset} presetKey="src"
            d={form.srcD} c={form.srcC}
            onPreset={applyPreset}
            onD={(v) => patch({ srcPreset: 'custom', srcD: v })}
            onC={(v) => patch({ srcPreset: 'custom', srcC: v })}
          />
          <IntervalCard
            title="② 目标乐器（目标分谱的记谱 → 发声）"
            preset={form.dstPreset} presetKey="dst"
            d={form.dstD} c={form.dstC}
            onPreset={applyPreset}
            onD={(v) => patch({ dstPreset: 'custom', dstD: v })}
            onC={(v) => patch({ dstPreset: 'custom', dstC: v })}
          />

          <div className="shift-note">{shiftDescription(form.srcD, form.srcC, form.dstD, form.dstC)}</div>

          <RangeCard
            preset={form.rangePreset} low={form.rangeLow} high={form.rangeHigh}
            onPreset={applyRangePreset}
            onLow={(v) => patch({ rangePreset: 'custom', rangeLow: v })}
            onHigh={(v) => patch({ rangePreset: 'custom', rangeHigh: v })}
          />

          <button className="primary" disabled={busy || clientProblems.length > 0} onClick={handleTranspose}>
            {busy ? '正在转换…' : '生成移调分谱'}
          </button>
          {clientProblems.length > 0 && (
            <ul className="hints">{clientProblems.map((p, i) => <li key={i}>{p}</li>)}</ul>
          )}

          <ErrorBox error={error} />
        </section>

        <section className="panel preview-panel">
          {result ? (
            <>
              <div className="result-head">
                <div>
                  <strong>{result.meta.part_name}</strong>
                  <span className="muted"> · {result.meta.measures} 小节 · {result.filename}</span>
                </div>
                <button className="ghost" onClick={downloadResult}>下载 MusicXML</button>
              </div>
              <ScorePreview xml={result.xml} />
            </>
          ) : (
            <div className="empty">
              <p>转换成功后，这里会显示目标分谱预览。</p>
              <p className="muted">所有处理在本机完成；参数与最近结果仅保存在浏览器本地存储中。</p>
            </div>
          )}
        </section>
      </main>

      <HistoryPanel history={history} onClear={() => { clearHistory(); setHistory([]) }} />

      <footer className="foot">
        <span>React · FastAPI · 本地存储</span>
        <span>任何无法完整保留结构/音高的情况都会拒绝整份转换，不会输出半成品。</span>
      </footer>
    </div>
  )
}

function FileUpload({ fileRef, file, loading, onPick, inspectError, inspect }) {
  return (
    <div className="block">
      <label className="block-title">上传 MusicXML（.musicxml / .xml / .mxl）</label>
      <input
        ref={fileRef} type="file" accept=".xml,.musicxml,.mxl"
        onChange={(e) => onPick(e.target.files?.[0] || null)}
      />
      {loading && <div className="muted">解析中…</div>}
      {file && !loading && !inspectError && (
        <div className="muted small">
          已选择 “{file.name}”，识别到 {inspect?.parts.length ?? 0} 个声部。
        </div>
      )}
      {inspectError && <div className="error-text">✕ {inspectError.message}</div>}
    </div>
  )
}

function PartSelector({ inspect, value, onChange }) {
  if (!inspect) return null
  return (
    <div className="block">
      <label className="block-title">选择有调乐器声部</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {inspect.parts.map((p) => (
          <option key={p.id} value={p.id} disabled={p.has_unpitched && !p.has_pitched}>
            {p.name}（{p.note_count} 个音符{p.has_unpitched ? '，含无调打击乐' : ''}）
          </option>
        ))}
      </select>
      {inspect.parts.find((p) => p.id === value)?.has_unpitched && (
        <div className="warn-text">该声部含无调打击乐（unpitched），将被整份拒绝，请改选有调声部。</div>
      )}
    </div>
  )
}

function IntervalCard({ title, preset, d, c, onPreset, onD, onC }) {
  const hint = intervalHint(d, c)
  return (
    <div className="block interval">
      <label className="block-title">{title}</label>
      <select value={preset} onChange={(e) => onPreset(e.target.value)}>
        {INSTRUMENT_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select>
      <div className="numrow">
        <label>有向字母步数
          <input type="number" value={d} onChange={(e) => onD(e.target.value)} />
        </label>
        <label>有向半音数
          <input type="number" value={c} onChange={(e) => onC(e.target.value)} />
        </label>
      </div>
      {!hint.ok && <div className="warn-text">{hint.msg}</div>}
    </div>
  )
}

function RangeCard({ preset, low, high, onPreset, onLow, onHigh }) {
  return (
    <div className="block">
      <label className="block-title">目标书写音域</label>
      <select value={preset} onChange={(e) => onPreset(e.target.value)}>
        <option value="custom">自定义…</option>
        {RANGE_PRESETS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
      </select>
      <div className="numrow">
        <label>下限
          <input value={low} onChange={(e) => onLow(e.target.value)} placeholder="如 Bb2" />
        </label>
        <label>上限
          <input value={high} onChange={(e) => onHigh(e.target.value)} placeholder="如 F#5" />
        </label>
      </div>
    </div>
  )
}

function ErrorBox({ error }) {
  if (!error) return null
  return (
    <div className="error-box">
      <div className="error-title">转换被拒绝（未生成任何结果）</div>
      <div>{error.message}</div>
      {error.code === 'range_exceeded' && error.detail?.items && (
        <details>
          <summary>超出音域的音符（{error.detail.count} 个，未自动移动八度）</summary>
          <table className="range-table">
            <thead><tr><th>小节</th><th>目标记谱音高</th></tr></thead>
            <tbody>
              {error.detail.items.slice(0, 200).map((it, i) => (
                <tr key={i}><td>{it.measure}</td><td>{it.pitch}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}

function HistoryPanel({ history, onClear }) {
  if (!history.length) return null
  return (
    <section className="panel history">
      <div className="result-head">
        <strong>本地历史（{history.length}）</strong>
        <button className="ghost" onClick={onClear}>清空</button>
      </div>
      <ul>
        {history.map((h) => (
          <li key={h.id}>
            <span className="muted small">{new Date(h.at).toLocaleString()}</span>
            {' · '}{h.sourceFile} → {h.partName}（{h.filename}）
          </li>
        ))}
      </ul>
    </section>
  )
}
