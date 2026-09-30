import { useEffect, useRef, useState } from 'react'

// OpenSheetMusicDisplay is large; load it only once a result is shown.
let osmdModulePromise = null
function loadOSMD() {
  if (!osmdModulePromise) {
    osmdModulePromise = import('opensheetmusicdisplay')
  }
  return osmdModulePromise
}

/** Renders MusicXML with OpenSheetMusicDisplay. */
export default function ScorePreview({ xml }) {
  const containerRef = useRef(null)
  const osmdRef = useRef(null)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    if (!containerRef.current || !xml) return
    let disposed = false
    ;(async () => {
      try {
        const { OpenSheetMusicDisplay } = await loadOSMD()
        if (disposed) return
        if (!osmdRef.current) {
          osmdRef.current = new OpenSheetMusicDisplay(containerRef.current, {
            autoResize: true,
            drawPartNames: true,
            drawTitle: true,
            measureNumberInterval: 4,
          })
        }
        await osmdRef.current.load(xml)
        if (!disposed) osmdRef.current.render()
      } catch (err) {
        if (!disposed) setLoadError(String(err))
      }
    })()
    return () => {
      disposed = true
    }
  }, [xml])

  if (loadError) {
    return (
      <div className="score-preview">
        <pre className="preview-error">预览渲染失败：{loadError}</pre>
      </div>
    )
  }
  return <div className="score-preview" ref={containerRef} />
}
