import { useCallback, useEffect, useRef, useState } from 'react'
import {
  dismissPanel,
  notifyRendererReady,
  registerInitHandler,
  registerThemeHandler,
  registerUseLocalModelsResultHandler,
  requestAddOwnKeys,
  requestResize,
  requestSignUp,
  requestUseLocalModels,
} from './services/bridge'
import type { FontConfig, InitMessage, ThemeConfig } from './types'
import { applyHostTheme } from './app/themeBootstrap'

const panelWidth = 440

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

function generateRequestId() {
  return `use-local-models-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export default function App() {
  const [config, setConfig] = useState<InitMessage | null>(null)
  const [isUpdatingLocalModels, setIsUpdatingLocalModels] = useState(false)
  const rendererReadyWasSent = useState({ sent: false })[0]
  const panelRef = useRef<HTMLDivElement>(null)
  const resizeWasSent = useRef(false)

  const reportContentHeight = useCallback(() => {
    if (resizeWasSent.current) return
    const height = panelRef.current?.getBoundingClientRect().height
    if (height && Number.isFinite(height)) {
      resizeWasSent.current = true
      requestResize(panelWidth, Math.ceil(height))
    }
  }, [])

  useEffect(() => {
    registerInitHandler((initConfig: InitMessage) => {
      applyTheme(initConfig.theme, initConfig.fonts)
      setConfig(initConfig)
    })
    registerThemeHandler(applyTheme)
    registerUseLocalModelsResultHandler(result => {
      setIsUpdatingLocalModels(false)
      if (result.status === 'success') dismissPanel()
    })
    if (!rendererReadyWasSent.sent) {
      rendererReadyWasSent.sent = true
      notifyRendererReady()
    }
  }, [rendererReadyWasSent])

  useEffect(() => {
    if (config) requestAnimationFrame(reportContentHeight)
  }, [config, reportContentHeight])

  const handleSignUp = useCallback(() => {
    requestSignUp()
  }, [])

  const handleAddOwnKeys = useCallback(() => {
    requestAddOwnKeys()
  }, [])

  const handleUseLocalModels = useCallback(() => {
    setIsUpdatingLocalModels(true)
    requestUseLocalModels(generateRequestId())
  }, [])

  if (!config) return <div className="basil-webkit-window-frame trial-exhaustion-panel-placeholder" />

  const primaryActionTitle = config.isAuthenticated ? 'Continue with Basil Cloud' : 'Sign in to Continue'

  return (
    <div className="basil-webkit-window-frame trial-exhaustion-panel-frame">
      <div
        className="trial-exhaustion-panel basil-webkit-window-surface"
        ref={panelRef}
        role="dialog"
        aria-label="Trial credit exhausted"
      >
        <header className="trial-exhaustion-header">
          <button
            type="button"
            className="trial-exhaustion-dismiss"
            onClick={dismissPanel}
            aria-label="Dismiss"
            title="Dismiss"
          >
            ×
          </button>
          <div className="trial-exhaustion-icon" aria-hidden="true">
            <span>✨</span>
          </div>
          <h1>Ready to Keep Going?</h1>
        </header>

        <section className="trial-exhaustion-message">
          <p className="trial-exhaustion-message-primary">Your included Basil Cloud credit is used up.</p>
          <p className="trial-exhaustion-message-secondary">
            Sign in to keep using cloud models with your Basil account. You can also switch to your own
            provider account or local models at any time.
          </p>
          <div className="trial-exhaustion-divider" />
          <p className="trial-exhaustion-message-secondary">
            Included credit: {config.remainingBalanceFormatted} remaining of {config.limitFormatted}.
          </p>
        </section>

        <section className="trial-exhaustion-actions">
          <button type="button" className="trial-exhaustion-primary-button" onClick={handleSignUp}>
            {primaryActionTitle}
          </button>
          <button type="button" className="trial-exhaustion-secondary-button" onClick={handleAddOwnKeys}>
            Use Your Own Provider Account
          </button>
          <button
            type="button"
            className="trial-exhaustion-tertiary-button"
            onClick={handleUseLocalModels}
            disabled={isUpdatingLocalModels}
          >
            {isUpdatingLocalModels ? 'Switching…' : 'Use Local Models'}
          </button>
        </section>
      </div>
    </div>
  )
}
