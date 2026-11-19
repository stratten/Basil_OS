import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/inputs/Switch'
import TokenizedSelect from '@shared/inputs/TokenizedSelect'
import { HintTooltip } from '../components/HintTooltip'
import {
  notifyHomeSettingsReady,
  onHomeEvent,
  openHomePowerUserGuide,
  reportHomeProblem,
  openHomeSetupAssistant,
  updateHomeSelectedModel,
  updateHomeSelectedTranscriptionModel,
  updateHomeToggle,
} from '../services/homeBridge'
import type { HomeQuickToggleField, HomeSettingsFields } from '../types'
import { HOME_PRESET_LABELS, planHomePreset, type HomePresetId, type HomePresetStep } from './homePresets'
import { useOptimisticSettings } from './useOptimisticSettings'

export type HomeNavigationTarget = 'permissions' | 'models' | 'account'

interface HomeSettingsAppProps {
  onNavigate: (tab: HomeNavigationTarget) => void
}

export function HomeSettingsApp({ onNavigate }: HomeSettingsAppProps) {
  const { settings: fields, isSaving, setSettings: setFields, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<HomeSettingsFields>()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [confirmEverything, setConfirmEverything] = useState(false)
  const [presetStatus, setPresetStatus] = useState<{ tone: 'running' | 'done' | 'error'; message: string } | null>(null)
  // A preset applies one setting at a time, waiting for native to confirm each before sending the next, so the native toggle handlers never race each other.
  const fieldsRef = useRef<HomeSettingsFields | null>(null)
  fieldsRef.current = fields
  const presetQueueRef = useRef<HomePresetStep[]>([])
  const presetRequestRef = useRef<string | null>(null)
  const presetSummaryRef = useRef('')
  const advancePresetRef = useRef<() => void>(() => {})

  function advancePreset() {
    const current = fieldsRef.current
    const step = presetQueueRef.current.shift()
    if (!current) return
    if (!step) {
      presetRequestRef.current = null
      setPresetStatus({ tone: 'done', message: presetSummaryRef.current })
      return
    }
    const next = { ...current, [step.field]: step.value } as HomeSettingsFields
    fieldsRef.current = next
    setFields(next)
    presetRequestRef.current = updateHomeToggle(step.field, step.value)
    track(presetRequestRef.current)
  }
  advancePresetRef.current = advancePreset

  function applyPreset(preset: HomePresetId) {
    if (!fields || presetRequestRef.current) return
    const plan = planHomePreset(preset, fields)
    setRequestError(null)
    setConfirmEverything(false)
    const parts = [
      plan.steps.length === 0
        ? `${HOME_PRESET_LABELS[preset]}: nothing needed to change.`
        : `${HOME_PRESET_LABELS[preset]} applied: ${plan.steps.length} ${plan.steps.length === 1 ? 'setting' : 'settings'} changed.`,
    ]
    if (plan.unavailable.length > 0) parts.push(`Not changed because their status is unavailable: ${plan.unavailable.join(', ')}.`)
    if (preset === 'everything' && fields.permissionsGrantedCount < fields.permissionsTotalCount) {
      parts.push(`Permissions are ${fields.permissionsGrantedCount} of ${fields.permissionsTotalCount} granted. A preset never grants macOS permissions, so features that need the rest will not work until you do.`)
    }
    presetSummaryRef.current = parts.join(' ')
    presetQueueRef.current = plan.steps
    setPresetStatus({ tone: 'running', message: `Applying ${HOME_PRESET_LABELS[preset]}...` })
    advancePreset()
  }

  useEffect(() => {
    const unsubscribe = onHomeEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        receiveSnapshot(event.fields)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') {
        const outcome = resolveIntent(event.requestId, event.status)
        if (outcome === 'error') setRequestError(event.message ?? 'Failed to update setting.')
        if (event.requestId === presetRequestRef.current) {
          if (outcome === 'error') {
            const skipped = presetQueueRef.current.length
            presetQueueRef.current = []
            presetRequestRef.current = null
            setPresetStatus({ tone: 'error', message: `The preset stopped after a setting failed. ${skipped} ${skipped === 1 ? 'setting was' : 'settings were'} not changed.` })
          } else {
            advancePresetRef.current()
          }
        }
      }
    })
    notifyHomeSettingsReady()
    return unsubscribe
  }, [])

  function handleToggle(field: HomeQuickToggleField, value: boolean) {
    if (!fields) return
    setRequestError(null)
    setFields({ ...fields, [field]: value } as HomeSettingsFields)
    track(updateHomeToggle(field, value))
  }

  function handleModelChange(modelId: string) {
    if (!fields) return
    setRequestError(null)
    setFields({ ...fields, selectedModelId: modelId })
    track(updateHomeSelectedModel(modelId))
  }

  function handleTranscriptionModelChange(modelId: string) {
    if (!fields) return
    setRequestError(null)
    setFields({ ...fields, selectedTranscriptionModelId: modelId })
    track(updateHomeSelectedTranscriptionModel(modelId))
  }

  function handleOpenSetupAssistant() {
    setRequestError(null)
    track(openHomeSetupAssistant())
  }

  function handleReportProblem() {
    setRequestError(null)
    track(reportHomeProblem())
  }

  function handleOpenPowerUserGuide() {
    setRequestError(null)
    track(openHomePowerUserGuide())
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
  const setupNeverFinished = f.setupAssistantStateAvailable && !f.setupAssistantCompleted && !f.setupAssistantPending

  return (
    <div className="home-settings-shell">
      <div className="home-settings-layout">
      <div className="home-settings-main">
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
          {setupNeverFinished && (
            <div className="home-settings-setup-notice" role="status">
              <strong>Basil isn't fully set up yet.</strong>
              <span>Run the Setup Assistant to finish getting Basil ready to work for you.</span>
            </div>
          )}
          <div className="home-settings-setup-row">
            <button type="button" className="secondary-button home-settings-inline-action" onClick={handleOpenSetupAssistant}>
              {f.setupAssistantPending ? 'Resume Setup' : setupNeverFinished ? 'Start Setup' : 'Open Setup Assistant'}
            </button>
            {f.setupAssistantStateAvailable && (
              <span className={`home-settings-setup-badge ${f.setupAssistantCompleted ? 'is-complete' : 'is-incomplete'}`}>
                {f.setupAssistantCompleted ? 'Setup complete' : 'Setup incomplete'}
              </span>
            )}
          </div>
          <button type="button" className="secondary-button home-settings-inline-action" onClick={handleOpenPowerUserGuide}>
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
                  disabled={!f.reasoningModelsAvailable || hasNoModels}
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
                  disabled={!f.transcriptionModelsAvailable || hasNoTranscriptionModels}
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
          <div className="home-settings-switch-row">
            <Switch id="home-enable-monitoring" label="Enable hotkeys at startup" checked={f.enableMonitoringAtStartup} disabled={!f.backgroundBehaviorAvailable} onChange={(checked) => handleToggle('enableMonitoringAtStartup', checked)} />
          </div>
          <div className="home-settings-switch-row">
            <Switch id="home-enable-voice-listener" label="Enable Voice Listener at startup" checked={f.enableVoiceListenerAtStartup} disabled={!f.backgroundBehaviorAvailable} onChange={(checked) => handleToggle('enableVoiceListenerAtStartup', checked)} />
            <HintTooltip subject="Voice Listener" text="Voice Listener listens through your microphone so you can start things by voice. It needs microphone access." />
          </div>
          <div className="home-settings-switch-row">
            <Switch id="home-start-activity-capture" label="Start Activity Capture on launch" checked={f.startActivityCaptureAtLaunch} disabled={!f.activityCaptureAvailable || !f.activityCaptureEnabled} onChange={(checked) => handleToggle('startActivityCaptureAtLaunch', checked)} />
            <HintTooltip
              subject="starting Activity Capture on launch"
              text={f.activityCaptureEnabled
                ? 'Activity Capture starts by itself each time Basil opens, beginning with your next launch.'
                : 'Turn on Automatic Capture in Activity Capture settings first. Then you can have it start when Basil opens.'}
            />
          </div>
          <div className="home-settings-switch-row">
            <Switch id="home-start-meeting-detection" label="Start Meeting/Call Detection on launch" checked={f.startMeetingDetectionAtLaunch} disabled={!f.meetingDetectionAvailable} onChange={(checked) => handleToggle('startMeetingDetectionAtLaunch', checked)} />
            <HintTooltip subject="starting Meeting/Call Detection on launch" text="Turning this on also turns on Meeting/Call Detection. It starts watching for calls the next time Basil opens." />
          </div>
        </section>

        <section className="home-settings-section" aria-labelledby="home-features-heading">
          <h2 id="home-features-heading">Active Features</h2>
          {!f.activityCaptureAvailable && <p className="home-settings-section-warning">Activity Capture status is temporarily unavailable.</p>}
          <div className="home-settings-switch-row">
            <Switch id="home-activity-capture-enabled" label="Activity Capture" checked={f.activityCaptureEnabled} disabled={!f.activityCaptureAvailable} onChange={(checked) => handleToggle('activityCaptureEnabled', checked)} />
            <HintTooltip subject="Activity Capture" text="Takes a screenshot of your screen on a schedule and has a model read it. Where that reading happens depends on the model you pick in Activity Capture settings." />
          </div>
          {!f.meetingDetectionAvailable && <p className="home-settings-section-warning">Meeting/Call Detection status is temporarily unavailable.</p>}
          <div className="home-settings-switch-row">
            <Switch id="home-meeting-detection-enabled" label="Meeting/Call Detection" checked={f.meetingDetectionEnabled} disabled={!f.meetingDetectionAvailable} onChange={(checked) => handleToggle('meetingDetectionEnabled', checked)} />
            <HintTooltip subject="Meeting/Call Detection" text="Notices when a meeting or call starts on this Mac." />
          </div>
          {!f.proactiveSuggestionsAvailable && <p className="home-settings-section-warning">Proactive Suggestions status is temporarily unavailable.</p>}
          <div className="home-settings-switch-row">
            <Switch id="home-proactive-suggestions-enabled" label="Proactive Suggestions" checked={f.proactiveSuggestionsEnabled} disabled={!f.proactiveSuggestionsAvailable} onChange={(checked) => handleToggle('proactiveSuggestionsEnabled', checked)} />
            <HintTooltip subject="Proactive Suggestions" text="Lets me offer help without being asked, when your settings allow it." />
          </div>
        </section>
      </div>
      </div>

      <aside className="home-settings-rail" aria-label="Quick presets and support">
        <section className="home-settings-section" aria-labelledby="home-presets-heading">
          <h2 id="home-presets-heading">Quick Presets</h2>
          <p className="home-settings-hint">Presets only change the switches under Launch Preferences and Active Features. They never grant macOS permissions, and you can adjust any switch afterwards.</p>
          <div className="home-settings-preset">
            <button type="button" className="secondary-button home-settings-inline-action" disabled={presetStatus?.tone === 'running'} onClick={() => setConfirmEverything(true)}>
              {HOME_PRESET_LABELS.everything}
            </button>
            <details className="home-settings-preset-details">
              <summary>What this does</summary>
              <p>Turns on Voice Listener, Activity Capture, Meeting/Call Detection, Proactive Suggestions, and their startup options.</p>
            </details>
          </div>
          <div className="home-settings-preset">
            <button type="button" className="secondary-button home-settings-inline-action" disabled={presetStatus?.tone === 'running'} onClick={() => applyPreset('conservative')}>
              {HOME_PRESET_LABELS.conservative}
            </button>
            <details className="home-settings-preset-details">
              <summary>What this does</summary>
              <p>Keeps only hotkeys on and turns the rest off.</p>
            </details>
          </div>
          {confirmEverything && (
            <div className="home-settings-setup-notice" role="alertdialog" aria-labelledby="home-preset-confirm-heading">
              <strong id="home-preset-confirm-heading">Turn on everything?</strong>
              <span>Activity Capture takes a screenshot of your screen on a schedule and has a model read it, Voice Listener listens through your microphone so you can start things by voice, and Meeting/Call Detection notices when you join a call. You can review or change each one in its own settings page.</span>
              <div className="home-settings-preset-row">
                <button type="button" className="secondary-button home-settings-inline-action" onClick={() => applyPreset('everything')}>Yes, enable everything</button>
                <button type="button" className="secondary-button home-settings-inline-action" onClick={() => setConfirmEverything(false)}>Cancel</button>
              </div>
            </div>
          )}
          {presetStatus && (
            <p className={`home-settings-preset-status is-${presetStatus.tone}`} role={presetStatus.tone === 'error' ? 'alert' : 'status'}>{presetStatus.message}</p>
          )}
        </section>

        <section className="home-settings-section" aria-labelledby="home-support-heading">
          <h2 id="home-support-heading">Support</h2>
          <button type="button" className="secondary-button home-settings-inline-action" onClick={handleReportProblem}>
            Report a problem
          </button>
          <p className="home-settings-hint">Saves a diagnostics bundle on this Mac, shows it in Finder, and opens a pre-filled GitHub issue. Nothing is sent until you submit the issue.</p>
        </section>
      </aside>
      </div>

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting...' : ''}</p>
      {requestError && <p className="home-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
