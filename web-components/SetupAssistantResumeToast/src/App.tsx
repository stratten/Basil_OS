import { useCallback, useEffect, useRef, useState } from 'react'
import {
  dontRemind,
  notifyRendererReady,
  registerInitHandler,
  registerThemeHandler,
  remindLater,
  requestResize,
  resumeSetup,
} from './services/bridge'
import type { FontConfig, InitMessage, ThemeConfig } from './types'
import { applyHostTheme } from './app/themeBootstrap'

const toastWidth = 320

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
  const [isReady, setIsReady] = useState(false)
  const toastRef = useRef<HTMLDivElement>(null)
  const rendererReadyWasSent = useRef(false)
  const resizeWasSent = useRef(false)

  const reportContentHeight = useCallback(() => {
    if (resizeWasSent.current) return
    const height = toastRef.current?.getBoundingClientRect().height
    if (height && Number.isFinite(height)) {
      resizeWasSent.current = true
      requestResize(toastWidth, Math.ceil(height))
    }
  }, [])

  useEffect(() => {
    registerInitHandler((config: InitMessage) => {
      applyTheme(config.theme, config.fonts)
      setIsReady(true)
    })
    registerThemeHandler(applyTheme)
    if (!rendererReadyWasSent.current) {
      rendererReadyWasSent.current = true
      notifyRendererReady()
    }
  }, [])

  useEffect(() => {
    // Deliberately not requestAnimationFrame: this panel's native host keeps
    // the window off-screen (never ordered front) until this measurement
    // resizes it, and WebKit does not reliably schedule rAF callbacks for a
    // WKWebView whose window has never been ordered onto the screen -- that
    // combination deadlocked the toast (invisible forever, waiting on a
    // callback that only fires once visible). getBoundingClientRect forces a
    // synchronous layout, so measuring directly here (after the DOM commit
    // this effect runs after) is both correct and independent of paint
    // scheduling.
    if (isReady) reportContentHeight()
  }, [isReady, reportContentHeight])

  if (!isReady) return <div className="basil-webkit-window-frame setup-assistant-resume-toast-placeholder" />

  return (
    <div className="basil-webkit-window-frame setup-assistant-resume-toast-frame">
      <div
        className="setup-assistant-resume-toast basil-webkit-window-surface"
        ref={toastRef}
        role="dialog"
        aria-label="Resume setup"
      >
        <div className="setup-assistant-resume-toast-copy">
          <h1>Want to resume your setup?</h1>
          <p>We saved your progress from last time.</p>
        </div>
        <div className="setup-assistant-resume-toast-actions">
          <button type="button" className="setup-assistant-resume-toast-primary" onClick={resumeSetup}>
            Resume now
          </button>
          <button type="button" className="setup-assistant-resume-toast-secondary" onClick={remindLater}>
            Remind me later
          </button>
        </div>
        <button type="button" className="setup-assistant-resume-toast-tertiary" onClick={dontRemind}>
          Don't remind me again
        </button>
      </div>
    </div>
  )
}
