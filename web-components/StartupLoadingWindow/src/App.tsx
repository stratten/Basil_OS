import { useCallback, useEffect, useRef, useState } from 'react'
import { BasilWindowChrome } from '@shared/BasilWindowChrome'
import {
  closeWindow,
  collapseWindow,
  expandWindow,
  minimizeWindow,
  notifyDrawnIn,
  notifyRendererReady,
  registerInitHandler,
  registerStatusHandler,
  registerThemeHandler,
} from './services/bridge'
import type { FontConfig, InitMessage, ThemeConfig } from './types'
import { applyHostFonts, applyHostTheme } from './app/themeBootstrap'

const BRAILLE_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
const SYSTEM_FONT_FALLBACK = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif'

function useBrailleSpinner(): string {
  const [frame, setFrame] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => {
      setFrame((current) => (current + 1) % BRAILLE_FRAMES.length)
    }, 100)
    return () => window.clearInterval(timer)
  }, [])
  return BRAILLE_FRAMES[frame]
}

function toCssFontFamily(rawName: string | null | undefined): string {
  const trimmed = (rawName ?? '').trim()
  if (!trimmed) return SYSTEM_FONT_FALLBACK
  const base = trimmed
    .replace(
      /-(?:UltraLight|Thin|ExtraLight|Light|Regular|Book|Medium|Semibold|SemiBold|DemiBold|Bold|ExtraBold|Heavy|Black|Italic|Oblique|Condensed|Compressed|Expanded|Extended|Display|Text|MT)$/i,
      '',
    )
    .trim()
  const needsQuotes = /[\s'"]/.test(base)
  const formatted = needsQuotes ? `"${base.replace(/"/g, '\\"')}"` : base
  return `${formatted}, ${SYSTEM_FONT_FALLBACK}`
}

function applyTheme(theme: ThemeConfig, fonts: FontConfig) {
  applyHostTheme(theme)
  applyHostFonts({
    fontFamily: toCssFontFamily(fonts.fontFamily),
    fontFamilyMedium: toCssFontFamily(fonts.fontFamilyMedium),
    fontFamilyBold: toCssFontFamily(fonts.fontFamilyBold),
  })
}

export default function App() {
  const [isReady, setIsReady] = useState(false)
  const [message, setMessage] = useState('Starting Basil...')
  const rendererReadyWasSent = useRef(false)
  const spinner = useBrailleSpinner()

  const handleInit = useCallback((config: InitMessage) => {
    applyTheme(config.theme, config.fonts)
    if (config.message.trim()) setMessage(config.message)
    setIsReady(true)
  }, [])

  useEffect(() => {
    registerInitHandler(handleInit)
    registerThemeHandler(applyTheme)
    registerStatusHandler((status) => {
      if (status.message.trim()) setMessage(status.message)
    })
    if (!rendererReadyWasSent.current) {
      rendererReadyWasSent.current = true
      notifyRendererReady()
    }
  }, [handleInit])

  useEffect(() => {
    if (!isReady) return
    let sent = false
    const notify = () => {
      if (sent) return
      sent = true
      notifyDrawnIn()
    }
    const revealRequested = (window as Window & { basilBlueprintReveal?: boolean }).basilBlueprintReveal === true
    if (!revealRequested) {
      notify()
      return
    }
    const consider = () => {
      const frame = document.querySelector('.basil-webkit-window-frame')
      if (frame?.getAttribute('data-basil-blueprint') === 'reveal') notify()
    }
    consider()
    const observer = new MutationObserver(consider)
    observer.observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['data-basil-blueprint'] })
    const fallback = window.setTimeout(notify, 3000)
    return () => {
      observer.disconnect()
      window.clearTimeout(fallback)
    }
  }, [isReady])

  if (!isReady) return <div className="basil-webkit-window-frame startup-loading-placeholder" />

  return (
    <BasilWindowChrome
      title="Basil"
      onClose={closeWindow}
      onMinimize={minimizeWindow}
      onCollapse={collapseWindow}
      onExpand={expandWindow}
    >
      <div className="startup-loading-body" role="status" aria-live="polite" aria-label={message}>
        <span className="startup-loading-spinner" aria-hidden="true">{spinner}</span>
        <p className="startup-loading-message">{message}</p>
      </div>
    </BasilWindowChrome>
  )
}
