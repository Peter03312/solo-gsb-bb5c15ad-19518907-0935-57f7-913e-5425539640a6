import { useMemo, useState } from 'react'
import { transpose, uploadScore } from './api'
import { INSTRUMENT_PRESETS, findPreset } from './presets'
import { useLocalStorage } from './useLocalStorage'
import ScorePreview from './ScorePreview'

const DEFAULTS = {
  srcPreset: 'c',
  srcLetters: 0,
  srcSemitones: 0,
  dstPreset: 'bb-trumpet',
  dstLetters: -1,
  dstSemitones: -2,
  rangeLow: 'C4',
  rangeHigh: 'C6',
  outputLabel: '',
}

function IntervalFields({ title, hint, presetKey, lKey, sKey, form, setForm }) {
  const preset = form[presetKey]
  const applyPreset = (id) => {
    const p = INSTRUMENT_PRESETS.find((x) => x.id === id)
    setForm((f) => ({
      ...f,
      [presetKey]: id,
      ...(id !== 'custom' && p && p.L !== null
        ? { [lKey]: p.L, [sKey]: p.S }
        : {}),
    }))
  }
  return (
    <fieldset className="interval-card">
      <legend>{title}</legend>
      <label className="preset-row">
        <span>常用乐器</span>
        <select value={preset} onChange={(e) => applyPreset(e.target.value)}>
          {INSTRUMENT_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      </label>
      <div className="num-row">
        <label>
          记谱→发声 字母步数 L
          <input
            type="number"
            value={form[lKey]}
            onChange={(e) =>
              setForm((f) => ({ ...f, [lKey]: Number(e.target.value) }))
            }
          />
        </label>
        <label>
          记谱→发声 半音数 S
          <input
            type="number"
            value={form[sKey]}
            onChange={(e) =>
              setForm((f) => ({ ...f, [sKey]: Number(e.target.value) }))
            }
          />
        </label>
      </div>
      <p className="hint">{hint}</p>
    </fieldset>
  )
}

function ErrorPanel({ error }) {
  if (!error) return null
  const violations = error.violations || []
  return (
    <div className="error-panel" role="alert">
      <div className="error-title">转换被拒绝（未输出任何分谱）</div>
      <div className="error-message">{error.message}</div>
      {violations.length > 0 && (
        <table className="violations">
          <thead>
            <tr><th>小节</th><th>目标书写音高</th><th>超出方向</th><th>边界</th></tr>
          </thead>
          <tbody>
            {violations.map((v, i) => (
              <tr key={i}>
                <td>{v.measure}</td>
                <td>{v.pitch}</td>
                <td>{v.direction}</td>
                <td>{v.bound}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function App() {
  const [form, setForm] = useLocalStorage('transposer.form', DEFAULTS)
  const [uploaded, setUploaded] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [selectedPart, setSelectedPart] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [converting, setConverting] = useState(false)
  const [dragActive, setDragActive] = useState(false)

  const selectedPartInfo = useMemo(
    () => uploaded?.parts.find((p) => p.part_id === selectedPart),
    [uploaded, selectedPart]
  )

  async function handleFile(file) {
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setResult(null)
    setError(null)
    try {
      const data = await uploadScore(file)
      setUploaded(data)
      const firstPitched =
        data.parts.find((p) => !p.has_unpitched && p.has_pitched) ||
        data.parts[0]
      setSelectedPart(firstPitched.part_id)
    } catch (err) {
      setUploaded(null)
      setUploadError(err)
    } finally {
      setUploading(false)
    }
  }

  async function handleConvert() {
    if (!uploaded) return
    setConverting(true)
    setError(null)
    setResult(null)
    try {
      const data = await transpose({
        file_id: uploaded.file_id,
        part_id: selectedPart,
        src_letters: form.srcLetters,
        src_semitones: form.srcSemitones,
        dst_letters: form.dstLetters,
        dst_semitones: form.dstSemitones,
        range_low: form.rangeLow.trim(),
        range_high: form.rangeHigh.trim(),
        output_label: form.outputLabel.trim(),
      })
      setResult(data)
    } catch (err) {
      setError(err)
    } finally {
      setConverting(false)
    }
  }

  const partPitched = selectedPartInfo && !selectedPartInfo.has_unpitched

  return (
    <main className="app">
      <header>
        <h1>移调分谱生成器</h1>
        <p className="subtitle">
          面向小型合奏排练：上传 MusicXML，选择有调乐器声部，指定原/目标乐器的
          记谱音→发声音音程与目标书写音域，生成预览并下载移调后的 MusicXML 分谱。
        </p>
      </header>

      <section className="step">
        <h2>1. 上传总谱（.musicxml / .xml / .mxl）</h2>
        <div
          className={`dropzone${dragActive ? ' active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragActive(false)
            handleFile(e.dataTransfer.files[0])
          }}
        >
          <input
            type="file"
            accept=".musicxml,.xml,.mxl,application/xml,application/vnd.recordare.musicxml,application/zip"
            onChange={(e) => handleFile(e.target.files[0])}
            id="file-input"
          />
          <label htmlFor="file-input" className="upload-btn">
            选择或拖入 MusicXML 文件
          </label>
          {uploading && <span className="muted"> 正在解析…</span>}
          {uploaded && (
            <span className="muted">
              {' '}已加载：{uploaded.original_filename}（{uploaded.parts.length} 个声部）
            </span>
          )}
        </div>
        {uploadError && (
          <div className="error-panel" role="alert">
            <div className="error-title">文件无法处理</div>
            <div className="error-message">{uploadError.message}</div>
          </div>
        )}
      </section>

      {uploaded && (
        <section className="step">
          <h2>2. 选择一个有调乐器声部</h2>
          <div className="part-grid">
            {uploaded.parts.map((p) => {
              const disabled = p.has_unpitched
              return (
                <label
                  key={p.part_id}
                  className={`part-card${disabled ? ' disabled' : ''}${
                    selectedPart === p.part_id ? ' selected' : ''
                  }`}
                >
                  <input
                    type="radio"
                    name="part"
                    checked={selectedPart === p.part_id}
                    disabled={disabled}
                    onChange={() => setSelectedPart(p.part_id)}
                  />
                  <span className="part-name">
                    {p.name || p.part_id}
                    {p.abbreviation ? `（${p.abbreviation}）` : ''}
                  </span>
                  <span className="part-meta">
                    {p.measures} 小节 · {p.notes} 音符
                    {p.has_unpitched && ' · 无调打击乐（不可选）'}
                  </span>
                </label>
              )
            })}
          </div>
        </section>
      )}

      {uploaded && (
        <section className="step">
          <h2>3. 乐器记谱→发声音音程与目标音域</h2>
          <div className="interval-grid">
            <IntervalFields
              title="原乐器（当前分谱的记谱）"
              hint="正数表示发声音比记谱音高，负数表示更低。例如 B♭ 小号：写 C4 实际发 B♭3，填 L=-1, S=-2。"
              presetKey="srcPreset"
              lKey="srcLetters"
              sKey="srcSemitones"
              form={form}
              setForm={setForm}
            />
            <IntervalFields
              title="目标乐器（要生成的分谱）"
              hint="目标分谱保证与原谱实际发声音高完全一致；应用会按两者音程差换算所有音符、调号与临时升降号。"
              presetKey="dstPreset"
              lKey="dstLetters"
              sKey="dstSemitones"
              form={form}
              setForm={setForm}
            />
          </div>
          <div className="range-row">
            <label>
              目标书写音域下限
              <input
                value={form.rangeLow}
                onChange={(e) => setForm((f) => ({ ...f, rangeLow: e.target.value }))}
                placeholder="如 E3"
              />
            </label>
            <label>
              目标书写音域上限
              <input
                value={form.rangeHigh}
                onChange={(e) => setForm((f) => ({ ...f, rangeHigh: e.target.value }))}
                placeholder="如 C6"
              />
            </label>
            <label className="label-input">
              输出文件标注（可选）
              <input
                value={form.outputLabel}
                onChange={(e) => setForm((f) => ({ ...f, outputLabel: e.target.value }))}
                placeholder="如：小号分谱"
              />
            </label>
          </div>
          <p className="hint">
            音名格式：C4、Bb3、F#5、Ebb4（支持 #/♯、b/♭、x/##、bb，数字为八度）。
            超出音域只会列出小节与音高，<strong>不会自动移动八度</strong>。
          </p>
          <button
            className="primary"
            disabled={!partPitched || converting}
            onClick={handleConvert}
          >
            {converting ? '正在转换…' : '生成目标分谱'}
          </button>
          {selectedPartInfo?.has_unpitched && (
            <p className="warn">该声部含无调打击乐，无法生成移调分谱。</p>
          )}
        </section>
      )}

      <ErrorPanel error={error} />

      {result && (
        <section className="step result">
          <h2>4. 预览与下载</h2>
          <div className="result-meta">
            <span>声部：{result.part_name}</span>
            <span>{result.measures} 小节 · {result.notes} 个音符/和弦音</span>
            <span>书写音程：{result.interval_label}</span>
            <span>
              transpose 标注：diatonic={result.transpose.diatonic}
              ，chromatic={result.transpose.chromatic}
              {result.transpose.octave_change
                ? `，octave-change=${result.transpose.octave_change}`
                : ''}
            </span>
          </div>
          <ScorePreview xml={result.preview_xml} />
          <a className="download-btn" href={result.download_url} download={result.download_name}>
            下载 MusicXML：{result.download_name}
          </a>
        </section>
      )}

      <footer>
        所有处理均在本服务本地磁盘与浏览器本地存储中完成；参数自动保存在浏览器。
      </footer>
    </main>
  )
}
