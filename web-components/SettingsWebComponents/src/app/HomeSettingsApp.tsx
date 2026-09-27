import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  notifyHomeSettingsReady,
  onHomeEvent,
  openHomePowerUserGuide,
  openHomeSetupAssistant,
  updateHomeSelectedModel,
  updateHomeSelectedTranscriptionModel,
  updateHomeToggle,
} from '../services/homeBridge'
import type { HomeQuickToggleField, HomeSettingsFields } from '../types'

export type HomeNavigationTarget = 'permissions' | 'models' | 'account'

interface HomeSettingsAppProps {
  onNavigate: (tab: HomeNavigationTarget) => void
}

interface PendingRequest {
  id: string
}

export function HomeSettingsApp({ onNavigate }: HomeSettingsAppProps) {
  const [fields, setFields] = useState<HomeSettingsFields | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingRequest | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingRef = useRef<PendingRequest | null>(null)
  pendingRef.current = pending

  useEffect(() => {
    const unsubscribe = onHomeEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setFields(event.fields)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current?.id) {
        setPending(null)
        setRequestError(event.status === 'error' ? event.message ?? 'Failed to update setting.' : null)
      }
    })
    notifyHomeSettingsReady()
    return unsubscribe
  }, [])

  function handleToggle(field: HomeQuickToggleField, value: boolean) {
    if (!fields || pending) return
    setRequestError(null)
    setPending({ id: updateHomeToggle(field, value) })
  }

  function handleModelChange(modelId: string) {
    if (!fields || pending) return
    setRequestError(null)
    setPending({ id: updateHomeSelectedModel(modelId) })
  }

  function handleTranscriptionModelChange(modelId: string) {
    if (!fields || pending) return
    setRequestError(null)
    setPending({ id: updateHomeSelectedTranscriptionModel(modelId) })
  }

  function handleOpenSetupAssistant() {
    if (pending) return
    setRequestError(null)
    setPending({ id: openHomeSetupAssistant() })
  }

  function handleOpenPowerUserGuide() {
    if (pending) return
    setRequestError(null)
    setPending({ id: openHomePowerUserGuide() })
  }

  if (!fields && !loadError) {
    return <p className="home-settings-status" role="status">Loading Home...</p>
  }

  if (loadError) {
    return (
      <div className="home-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyHomeSettingsReady()}>Retry</button>
      </div>
    )
  }

  const f = fields!
  const availableModels = f.useApiModels ? [...f.localModels, ...f.apiModels, ...f.customModels] : f.localModels
  const hasNoModels = availableModels.length === 0
  const availableTranscriptionModels = [...f.localTranscriptionModels, ...f.apiTranscriptionModels]
  const hasNoTranscriptionModels = availableTranscriptionModels.length === 0
  const permissionsComplete = f.permissionsGrantedCount >= f.permissionsTotalCount

  return (
    <div className="home-settings-shell">
      <div className="home-settings-overview-grid">
        <section className="home-settings-section" aria-labelledby="home-setup-heading">
          <h2 id="home-setup-heading">Setup &amp; Readiness</h2>
          <p className="home-settings-readiness-row">
            <span>Permissions: {f.permissionsGrantedCount} of {f.permissionsTotalCount} granted</span>
            {!permissionsComplete && (
              <button type="button" className="secondary-button" onClick={() => onNavigate('permissions')}>Review</button>
            )}
          </p>
          {!f.setupAssistantStateAvailable && <p className="home-settings-section-warning">Setup status is unavailable. You can still open the Setup Assistant.</p>}
          {f.setupAssistantPending && (
            <div className="home-settings-resume-card" role="status">
              <span>You stepped out of setup before finishing. Pick up where you left off any time.</span>
            </div>
          )}
          <button type="button" className="secondary-button home-settings-inline-action" disabled={pending !== null} onClick={handleOpenSetupAssistant}>
            {f.setupAssistantPending ? 'Resume Setup' : 'Open Setup Assistant'}
          </button>
          <button type="button" className="secondary-button home-settings-inline-action" disabled={pending !== null} onClick={handleOpenPowerUserGuide}>
            Explore Basil's Capabilities
          </button>
          <p className="home-settings-hint">Learn about all of Basil's features in detail.</p>
        </section>

        <div className="home-settings-model-stack">
          <section className="home-settings-section home-settings-model-defaults" aria-labelledby="home-model-heading">
            <div className="home-settings-model-defaults-heading">
              <h2 id="home-model-heading">Default Models</h2>
              <button type="button" className="secondary-button home-settings-inline-action" onClick={() => onNavigate('models')}>Manage models</button>
            </div>
            <div className="home-settings-model-default-group">
              <h3>Reasoning</h3>
              <div className="home-settings-model-controls">
                <label className="home-settings-label">Model:</label>
                <TokenizedSelect
                  className="home-settings-select"
                  value={f.selectedModelId}
                  disabled={pending !== null || !f.reasoningModelsAvailable || hasNoModels}
                  ariaLabel="Default reasoning model"
                  onValueChange={handleModelChange}
                  options={[
                    ...(f.selectedModelId && !availableModels.some((model) => model.id === f.selectedModelId)
                      ? [{ value: f.selectedModelId, label: `${f.selectedModelId} (unavailable)` }]
                      : []),
                    ...f.localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
                    ...(f.useApiModels ? f.apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })) : []),
                    ...(f.useApiModels ? f.customModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Custom Models' })) : []),
                  ]}
                />
              </div>
              {!f.reasoningModelsAvailable && <p className="home-settings-section-warning">Reasoning model options are temporarily unavailable.</p>}
              {f.reasoningModelsAvailable && hasNoModels && <p className="home-settings-section-warning">No reasoning models are available.</p>}
            </div>

            <div className="home-settings-model-default-group">
              <h3>Transcription</h3>
              <div className="home-settings-model-controls">
                <label className="home-settings-label">Model:</label>
                <TokenizedSelect
                  className="home-settings-select"
                  value={f.selectedTranscriptionModelId}
                  disabled={pending !== null || !f.transcriptionModelsAvailable || hasNoTranscriptionModels}
                  ariaLabel="Default transcription model"
                  onValueChange={handleTranscriptionModelChange}
                  options={[
                    ...(f.selectedTranscriptionModelId && !availableTranscriptionModels.some((model) => model.id === f.selectedTranscriptionModelId)
                      ? [{ value: f.selectedTranscriptionModelId, label: `${f.selectedTranscriptionModelId} (unavailable)` }]
                      : []),
                    ...f.localTranscriptionModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
                    ...f.apiTranscriptionModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })),
                  ]}
                />
              </div>
              {!f.transcriptionModelsAvailable && <p className="home-settings-section-warning">Transcription model options are temporarily unavailable.</p>}
              {f.transcriptionModelsAvailable && hasNoTranscriptionModels && <p className="home-settings-section-warning">No transcription models are available.</p>}
            </div>
          </section>
        </div>
      </div>

      <div className="home-settings-compact-grid">
        <section className="home-settings-section" aria-labelledby="home-launch-heading">
          <h2 id="home-launch-heading">Launch Preferences</h2>
          {!f.backgroundBehaviorAvailable && <p className="home-settings-section-warning">Hotkey and Voice Listener preferences are temporarily unavailable.</p>}
          <Switch id="home-enable-monitoring" label="Enable hotkey monitoring at startup" checked={f.enableMonitoringAtStartup} disabled={pending !== null || !f.backgroundBehaviorAvailable} onChange={(checked) => handleToggle('enableMonitoringAtStartup', checked)} />
          <Switch id="home-enable-voice-listener" label="Enable Voice Listener at startup" checked={f.enableVoiceListenerAtStartup} disabled={pending !== null || !f.backgroundBehaviorAvailable} onChange={(checked) => handleToggle('enableVoiceListenerAtStartup', checked)} />
          <Switch id="home-start-activity-capture" label="Start Activity Capture on launch" checked={f.startActivityCaptureAtLaunch} disabled={pending !== null || !f.activityCaptureAvailable || !f.activityCaptureEnabled} onChange={(checked) => handleToggle('startActivityCaptureAtLaunch', checked)} />
          <p className="home-settings-hint">
            {f.activityCaptureEnabled
              ? 'Starts the capture scheduler after Basil reconnects to its backend on your next launch.'
              : 'Enable Automatic Capture in Activity Capture settings before choosing a startup schedule.'}
          </p>
          <Switch id="home-start-meeting-detection" label="Start Meeting Detection on launch" checked={f.startMeetingDetectionAtLaunch} disabled={pending !== null || !f.meetingDetectionAvailable} onChange={(checked) => handleToggle('startMeetingDetectionAtLaunch', checked)} />
          <p className="home-settings-hint">
            Turning this on also enables Meeting Detection; it won't start the monitor until the next launch.
          </p>
        </section>

        <section className="home-settings-section" aria-labelledby="home-features-heading">
          <h2 id="home-features-heading">Active Features</h2>
          {!f.activityCaptureAvailable && <p className="home-settings-section-warning">Activity Capture status is temporarily unavailable.</p>}
          <Switch id="home-activity-capture-enabled" label="Activity Capture" checked={f.activityCaptureEnabled} disabled={pending !== null || !f.activityCaptureAvailable} onChange={(checked) => handleToggle('activityCaptureEnabled', checked)} />
          {!f.meetingDetectionAvailable && <p className="home-settings-section-warning">Meeting Detection status is temporarily unavailable.</p>}
          <Switch id="home-meeting-detection-enabled" label="Meeting Detection" checked={f.meetingDetectionEnabled} disabled={pending !== null || !f.meetingDetectionAvailable} onChange={(checked) => handleToggle('meetingDetectionEnabled', checked)} />
          {!f.proactiveSuggestionsAvailable && <p className="home-settings-section-warning">Proactive Suggestions status is temporarily unavailable.</p>}
          <Switch id="home-proactive-suggestions-enabled" label="Proactive Suggestions" checked={f.proactiveSuggestionsEnabled} disabled={pending !== null || !f.proactiveSuggestionsAvailable} onChange={(checked) => handleToggle('proactiveSuggestionsEnabled', checked)} />
        </section>
      </div>

      {pending && <p className="home-settings-status" role="status">Saving setting...</p>}
      {requestError && <p className="home-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
