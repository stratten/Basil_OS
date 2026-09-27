import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'
import Transcription from './components/sections/Transcription'
import AssistantSession from './components/sections/AssistantSession'
import AgentTasks from './components/sections/AgentTasks'
import VoiceComparison from './components/sections/VoiceComparison'
import Conversation from './components/sections/Conversation'
import ActivityCapture from './components/sections/ActivityCapture'
import Models from './components/sections/Models'
import { dismissPanel, notifyRendererReady, registerInitHandler, registerThemeHandler } from './services/bridge'
import type { FontConfig, SectionId, ThemeConfig } from './types'
import { applyHostTheme } from './app/themeBootstrap'

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

const sectionComponents: Record<SectionId, () => JSX.Element> = {
  transcription: Transcription,
  assistantSession: AssistantSession,
  agentTasks: AgentTasks,
  voiceComparison: VoiceComparison,
  conversation: Conversation,
  activityCapture: ActivityCapture,
  models: Models,
}

export default function App() {
  const [isReady, setIsReady] = useState(false)
  const [selectedSection, setSelectedSection] = useState<SectionId>('transcription')
  const rendererReadyWasSent = useState({ sent: false })[0]

  useEffect(() => {
    registerInitHandler(config => {
      applyTheme(config.theme, config.fonts)
      setIsReady(true)
    })
    registerThemeHandler(applyTheme)
    if (!rendererReadyWasSent.sent) {
      rendererReadyWasSent.sent = true
      notifyRendererReady()
    }
  }, [rendererReadyWasSent])

  if (!isReady) return <div className="basil-webkit-window-frame pug-placeholder" />

  const SectionComponent = sectionComponents[selectedSection]

  return (
    <div className="basil-webkit-window-frame pug-frame">
      <div className="pug-shell basil-webkit-window-surface">
        <header className="pug-header">
          <span className="pug-header-title">Basil's Capabilities</span>
          <button type="button" className="pug-header-close" onClick={dismissPanel} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="pug-body">
          <Sidebar selected={selectedSection} onSelect={setSelectedSection} />
          <main className="pug-content" role="main">
            <SectionComponent />
          </main>
        </div>
        <footer className="pug-footer">
          <button type="button" className="pug-done-button" onClick={dismissPanel}>
            Done
          </button>
        </footer>
      </div>
    </div>
  )
}
