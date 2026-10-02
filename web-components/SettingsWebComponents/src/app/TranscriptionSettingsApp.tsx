import { useEffect, useState, type ReactNode } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { TranscriptionSettingsPanel } from '../components/TranscriptionSettingsPanel'
import { TranscriptionTextReplacementsPanel } from '../components/TranscriptionTextReplacementsPanel'
import { TranscriptionHistoryPanel } from '../components/TranscriptionHistoryPanel'
import { notifyTranscriptionSettingsReady, onTranscriptionSettingsEvent } from '../services/transcriptionSettingsBridge'
import type { TranscriptionSettingsFields, TranscriptionUnloadDelayOption } from '../types'
import { useOptimisticSettings } from './useOptimisticSettings'
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

export function TranscriptionSettingsApp({
  requestedSubTab,
  onSubTabChange,
}: {
  requestedSubTab?: TranscriptionSubTab
  onSubTabChange?: (subTab: TranscriptionSubTab) => void
}) {
  const [subTab, setSubTab] = useState<TranscriptionSubTab>(requestedSubTab ?? 'settings')
  const { settings, isSaving, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<TranscriptionSettingsFields>()
  const [unloadDelayOptions, setUnloadDelayOptions] = useState<TranscriptionUnloadDelayOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  useEffect(() => {
    if (requestedSubTab) setSubTab(requestedSubTab)
  }, [requestedSubTab])

  function selectSubTab(next: TranscriptionSubTab) {
    setSubTab(next)
    onSubTabChange?.(next)
  }

  useEffect(() => {
    const unsubscribe = onTranscriptionSettingsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        receiveSnapshot(event.settings)
        setLoadError(null)
        if (event.type === 'init') setUnloadDelayOptions(event.unloadDelayOptions)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && resolveIntent(event.requestId, event.status) === 'error') {
        setRequestError(event.message ?? 'Failed to update setting.')
      }
    })
    notifyTranscriptionSettingsReady()
    return unsubscribe
  }, [])

  function trackRequest(id: string) {
    setRequestError(null)
    track(id)
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

  return (
    <div className="transcription-settings-shell">
      <SettingsSubTabs
        tabs={TRANSCRIPTION_SUB_TABS}
        selected={subTab}
        onSelect={selectSubTab}
        ariaLabel="Transcription sections"
        getTabId={tabId}
        getPanelId={panelId}
      />

      <div id={panelId('settings')} role="tabpanel" aria-labelledby={tabId('settings')} className={subTab === 'settings' ? '' : 'transcription-sub-tab-hidden'}>
        {renderWhenLoaded((loadedSettings) => (
          <TranscriptionSettingsPanel
            settings={loadedSettings}
            unloadDelayOptions={unloadDelayOptions}
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
            onRulesChange={(rules) => setSettings({ ...loadedSettings, textReplacements: rules })}
            onTrackRequest={trackRequest}
          />
        ))}
      </div>

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting…' : ''}</p>
      {requestError && <p className="transcription-settings-error" role="alert">{requestError}</p>}
    </div>
  )
}
