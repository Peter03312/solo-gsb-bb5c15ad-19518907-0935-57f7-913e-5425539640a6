import React, { useEffect, useRef, useState } from 'react'

// OSMD 体积较大，按需动态加载（仅在有结果要预览时才拉取）。
// 使用 OpenSheetMusicDisplay 在浏览器本地渲染移调后的 MusicXML（不发往外部）。
export default function ScorePreview({ xml }) {
  const containerRef = useRef(null)
  const osmdRef = useRef(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function render() {
      if (!containerRef.current || !xml) return
      setFailed(false)
      try {
        const { OpenSheetMusicDisplay } = await import('opensheetmusicdisplay')
        if (cancelled) return
        if (!osmdRef.current) {
          osmdRef.current = new OpenSheetMusicDisplay(containerRef.current, {
            autoResize: true,
            drawTitle: true,
            drawPartNames: true,
            backend: 'svg',
          })
        }
        await osmdRef.current.load(xml)
        if (!cancelled) osmdRef.current.render()
      } catch (e) {
        if (!cancelled) setFailed(true)
      }
    }
    render()
    return () => { cancelled = true }
  }, [xml])

  if (failed) {
    return (
      <div className="preview-fail">
        乐谱预览组件无法渲染该文件，但生成的 MusicXML 仍可下载并在制谱软件中打开。
      </div>
    )
  }
  return <div ref={containerRef} className="osmd-container" />
}
