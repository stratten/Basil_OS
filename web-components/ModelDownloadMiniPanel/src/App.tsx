import { useCallback, useEffect, useRef, useState } from 'react'
import ExplanationTray from './components/ExplanationTray'
import ModelRow from './components/ModelRow'
import { orderModelIds } from './helpers/modelDisplay'
import {
  cancelModel,
  dismissPanel,
  notifyRendererReady,
  registerInitHandler,
  registerSnapshotHandler,
  registerThemeHandler,
  requestResize,
  retryModel,
} from './services/bridge'
import type { FontConfig, InitMessage, PanelSnapshot, ThemeConfig } from './types'
import { applyHostTheme } from './app/themeBootstrap'

const panelWidth = 272

function toCssFontFamily(fontName: string) {
  const trimmed = fontName.trim()
  if (!trimmed) return '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'
  const base = trimmed.replace(/-(?:Light|Regular|Medium|SemiBold|Semibold|Bold)$/i, '')
  return `"${base}", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif`
}

function applyTheme(theme: ThemeConfig, fonts: FontConfig) {
  applyHostTheme(theme)
  const root = document.documentElement
  root.style.setProperty('--font-family-light', toCssFontFamily(fonts.fontFamily))
  root.style.setProperty('--font-family-medium', toCssFontFamily(fonts.fontFamilyMedium))
  root.style.setProperty('--font-family-bold', toCssFontFamily(fonts.fontFamilyBold))
}

export default function App() {
  const [snapshot, setSnapshot] = useState<PanelSnapshot | null>(null)
  const [pendingActionIds, setPendingActionIds] = useState<Set<string>>(new Set())
  const panelRef = useRef<HTMLDivElement>(null)
  const rendererReadyWasSent = useRef(false)

  const reportContentHeight = useCallback(() => {
    const height = panelRef.current?.getBoundingClientRect().height
    if (height && Number.isFinite(height)) requestResize(panelWidth, Math.ceil(height))
  }, [])

  useEffect(() => {
    registerInitHandler((config: InitMessage) => {
      applyTheme(config.theme, config.fonts)
      setSnapshot(config.snapshot)
    })
    registerSnapshotHandler(nextSnapshot => {
      setSnapshot(previousSnapshot => ({
        ...nextSnapshot,
        appIconDataUrl: nextSnapshot.appIconDataUrl ?? previousSnapshot?.appIconDataUrl ?? null,
      }))
      setPendingActionIds(new Set())
    })
    registerThemeHandler(applyTheme)
    if (!rendererReadyWasSent.current) {
      rendererReadyWasSent.current = true
      notifyRendererReady()
    }
  }, [])

  useEffect(() => {
    requestAnimationFrame(reportContentHeight)
  }, [reportContentHeight, snapshot])

  const handleRetry = useCallback((modelId: string) => {
    setPendingActionIds(previous => new Set(previous).add(modelId))
    retryModel(modelId)
  }, [])

  const handleCancel = useCallback((modelId: string) => {
    setPendingActionIds(previous => new Set(previous).add(modelId))
    cancelModel(modelId)
  }, [])

  if (!snapshot) return <div className="basil-webkit-window-frame model-download-panel-placeholder" />

  const rowsById = new Map(snapshot.models.map(row => [row.modelId, row]))

  return (
    <div className="basil-webkit-window-frame model-download-panel-frame">
      <div className="model-download-panel basil-webkit-window-surface" ref={panelRef} role="region" aria-label="Model download progress">
      <header className="model-download-header">
        <span>Model Downloads</span>
        <button type="button" className="model-download-dismiss" onClick={dismissPanel} aria-label="Dismiss model download panel">
          ×
        </button>
      </header>
      <section className="model-download-summary">
        <div className={`model-download-ring${snapshot.isComplete ? ' model-download-ring--complete' : ''}`} style={{ '--progress': `${snapshot.quantizedPercentage}%` } as React.CSSProperties}>
          {snapshot.isComplete ? <span aria-label="All models downloaded">✓</span> : (
            snapshot.appIconDataUrl ? <img src={snapshot.appIconDataUrl} alt="Basil" /> : <span aria-label="Basil">B</span>
          )}
        </div>
        <div className="model-download-summary-copy">
          <div className="model-download-phase" title={snapshot.phaseMessage}>{snapshot.isComplete ? 'Models ready' : snapshot.phaseMessage}</div>
          <div className={`model-download-percentage${snapshot.isComplete ? ' model-download-percentage--complete' : ''}`}>{snapshot.quantizedPercentage}%</div>
        </div>
      </section>
      <div className="model-download-divider" />
      <section className="model-download-rows">
        {orderModelIds(snapshot.models.map(row => row.modelId)).map(modelId => {
          const row = rowsById.get(modelId)
          return row ? <ModelRow key={modelId} row={row} isActionPending={pendingActionIds.has(modelId)} onRetry={handleRetry} onCancel={handleCancel} /> : null
        })}
      </section>
        <ExplanationTray onSizeChanged={reportContentHeight} />
      </div>
    </div>
  )
}
