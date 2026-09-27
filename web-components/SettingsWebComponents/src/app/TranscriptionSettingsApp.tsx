import { useEffect, useRef, useState, type ReactNode } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { TranscriptionSettingsPanel } from '../components/TranscriptionSettingsPanel'
import { TranscriptionTextReplacementsPanel } from '../components/TranscriptionTextReplacementsPanel'
import { TranscriptionHistoryPanel } from '../components/TranscriptionHistoryPanel'
import { notifyTranscriptionSettingsReady, onTranscriptionSettingsEvent } from '../services/transcriptionSettingsBridge'
import type { TranscriptionSettingsFields, TranscriptionUnloadDelayOption } from '../types'
import '../styles/transcription-settings.css'

export type TranscriptionSubTab = 'settings' | 'history' | 'replacements'

export const TRANSCRIPTION_SUB_TABS: readonly SettingsSubTabDefinition<TranscriptionSubTab>[] = [
  { id: 'settings', label: 'Settings' },
  { id: 'history', label: 'History' },
  { id: 'replacements', label: 'Replacements' },
]

function tabId(id: TranscriptionSubTab): string {
  return `transcription-sub-tab-${id}`
}

function panelId(id: TranscriptionSubTab): string {
  return `transcription-sub-panel-${id}`
}

export function TranscriptionSettingsApp({ requestedSubTab }: { requestedSubTab?: TranscriptionSubTab }) {
  const [subTab, setSubTab] = useState<TranscriptionSubTab>(requestedSubTab ?? 'settings')
  const [settings, setSettings] = useState<TranscriptionSettingsFields | null>(null)
  const [unloadDelayOptions, setUnloadDelayOptions] = useState<TranscriptionUnloadDelayOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    if (requestedSubTab) setSubTab(requestedSubTab)
  }, [requestedSubTab])

  useEffect(() => {
    const unsubscribe = onTranscriptionSettingsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setSettings(event.settings)
        setLoadError(null)
        if (event.type === 'init') setUnloadDelayOptions(event.unloadDelayOptions)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current) {
        setPendingId(null)
        setRequestError(event.status === 'error' ? event.message ?? 'Failed to update setting.' : null)
      }
    })
    notifyTranscriptionSettingsReady()
    return unsubscribe
  }, [])

  function trackRequest(id: string) {
    setRequestError(null)
    setPendingId(id)
  }

  // The Settings and Replacements sub-tabs both depend on the same
  // `TranscriptionSettings` payload, so each renders this shared
  // loading/error fallback independently -- the History sub-tab uses its
  // own separate bridge and is never blocked by this state.
  function renderWhenLoaded(content: (loadedSettings: TranscriptionSettingsFields) => ReactNode): ReactNode {
    if (loadError) {
      return (
        <div className="transcription-settings-error">
          <p role="alert">{loadError}</p>
          <button type="button" className="secondary-button" onClick={notifyTranscriptionSettingsReady}>Retry</button>
        </div>
      )
    }
    if (!settings) {
      return <div className="transcription-settings-loading">Loading transcription settings…</div>
    }
    return content(settings)
  }

  const disabled = pendingId !== null

  return (
    <div className="transcription-settings-shell">
      <SettingsSubTabs
        tabs={TRANSCRIPTION_SUB_TABS}
        selected={subTab}
        onSelect={setSubTab}
        ariaLabel="Transcription sections"
        getTabId={tabId}
        getPanelId={panelId}
      />

      <div id={panelId('settings')} role="tabpanel" aria-labelledby={tabId('settings')} className={subTab === 'settings' ? '' : 'transcription-sub-tab-hidden'}>
        {renderWhenLoaded((loadedSettings) => (
          <TranscriptionSettingsPanel
            settings={loadedSettings}
            unloadDelayOptions={unloadDelayOptions}
            disabled={disabled}
            onSettingsChange={setSettings}
            onTrackRequest={trackRequest}
          />
        ))}
      </div>
      <div id={panelId('history')} role="tabpanel" aria-labelledby={tabId('history')} className={subTab === 'history' ? '' : 'transcription-sub-tab-hidden'}>
        <TranscriptionHistoryPanel />
      </div>
      <div id={panelId('replacements')} role="tabpanel" aria-labelledby={tabId('replacements')} className={subTab === 'replacements' ? '' : 'transcription-sub-tab-hidden'}>
        {renderWhenLoaded((loadedSettings) => (
          <TranscriptionTextReplacementsPanel
            rules={loadedSettings.textReplacements}
            disabled={disabled}
            onRulesChange={(rules) => setSettings({ ...loadedSettings, textReplacements: rules })}
            onTrackRequest={trackRequest}
          />
        ))}
      </div>

      {pendingId && <p className="transcription-settings-status" role="status">Saving setting…</p>}
      {requestError && <p className="transcription-settings-error" role="alert">{requestError}</p>}
    </div>
  )
}
