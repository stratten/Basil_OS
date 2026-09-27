import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import { PolicyRadioGroup, type PolicyRadioOption } from '../components/PolicyRadioGroup'
import {
  notifyProactiveSuggestionsSettingsReady,
  onProactiveSuggestionsEvent,
  requestUpdateProactiveSuggestionAutoExecuteCapability,
  requestUpdateProactiveSuggestionCooldownMinutes,
  requestUpdateProactiveSuggestionEnabledCapability,
  requestUpdateProactiveSuggestionEvaluationModel,
  requestUpdateProactiveSuggestionExcludedAppNames,
  requestUpdateProactiveSuggestionFrequencySeconds,
  requestUpdateProactiveSuggestionMinimumConfidence,
  requestUpdateProactiveSuggestionMode,
  requestUpdateProactiveSuggestionsEnabled,
} from '../services/proactiveSuggestionsBridge'
import type { ProactiveSuggestionCapability, ProactiveSuggestionMode, ProactiveSuggestionsSettingsSnapshot } from '../types'

const MODE_OPTIONS: readonly PolicyRadioOption<ProactiveSuggestionMode>[] = [
  { id: 'suggestion_only', label: 'Suggestion Only', description: 'Show suggestions for you to accept or reject manually.' },
  { id: 'auto_execute', label: 'Auto Execute', description: 'Automatically run suggestions marked eligible for the enabled capabilities below.' },
]

const COOLDOWN_OPTIONS: readonly { value: number; label: string }[] = [
  { value: 5, label: '5 Minutes' },
  { value: 15, label: '15 Minutes' },
  { value: 30, label: '30 Minutes' },
  { value: 60, label: '1 Hour' },
  { value: 240, label: '4 Hours' },
]

const CAPABILITIES: readonly { id: ProactiveSuggestionCapability; label: string }[] = [
  { id: 'assistant_session', label: 'Dill Assistant Session' },
  { id: 'agent_task', label: 'Paprika Agent Task' },
]

function clampFrequency(value: number): number {
  return Math.min(3600, Math.max(1, value))
}

function FrequencySecondsField({
  valueSeconds,
  disabled,
  onCommit,
}: {
  valueSeconds: number
  disabled: boolean
  onCommit: (seconds: number) => void
}) {
  const [draftValue, setDraftValue] = useState(String(valueSeconds))

  useEffect(() => {
    setDraftValue(String(valueSeconds))
  }, [valueSeconds])

  function commitDraft() {
    const nextValue = clampFrequency(Number(draftValue) || 1)
    setDraftValue(String(nextValue))
    if (nextValue !== valueSeconds) onCommit(nextValue)
  }

  return (
    <div className="proactive-suggestions-frequency">
      <label htmlFor="proactive-suggestions-frequency-input">Capture Frequency:</label>
      <input
        id="proactive-suggestions-frequency-input"
        type="number"
        min={1}
        max={3600}
        value={draftValue}
        disabled={disabled}
        onChange={(event) => setDraftValue(event.target.value)}
        onBlur={commitDraft}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
        }}
      />
      <span>seconds</span>
      <p className="proactive-suggestions-field-hint">Controls how often Basil captures the visible window and evaluates whether a suggestion would help.</p>
    </div>
  )
}

export function ProactiveSuggestionsSettingsApp() {
  const [settings, setSettings] = useState<ProactiveSuggestionsSettingsSnapshot | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    const unsubscribe = onProactiveSuggestionsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setSettings(event.settings)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current) {
        setPendingId(null)
        setRequestError(event.status === 'error' ? event.message ?? 'Failed to update the setting.' : null)
      }
    })
    notifyProactiveSuggestionsSettingsReady()
    return unsubscribe
  }, [])

  function submit(id: string) {
    if (pendingRef.current) return
    setRequestError(null)
    setPendingId(id)
  }

  if (!settings && !loadError) {
    return <p className="proactive-suggestions-status" role="status">Loading Proactive Suggestions settings...</p>
  }

  if (loadError) {
    return (
      <div className="proactive-suggestions-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyProactiveSuggestionsSettingsReady()}>Retry</button>
      </div>
    )
  }

  const disabled = pendingId !== null
  const s = settings!
  const hasNoModels = s.localModels.length === 0 && s.apiModels.length === 0

  return (
    <div className="proactive-suggestions-shell">
      <section className="proactive-suggestions-section" aria-labelledby="proactive-suggestions-heading">
        <h2 id="proactive-suggestions-heading">Proactive Suggestions</h2>
        <Switch
          id="proactive-suggestions-enabled"
          label="Enable Proactive Suggestions"
          checked={s.enabled}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, enabled: checked }); submit(requestUpdateProactiveSuggestionsEnabled(checked)) }}
        />
        <PolicyRadioGroup
          legend="Mode"
          name="proactive-suggestions-mode"
          options={MODE_OPTIONS}
          value={s.mode}
          disabled={disabled}
          onChange={(next) => { setSettings({ ...s, mode: next }); submit(requestUpdateProactiveSuggestionMode(next)) }}
        />
        <FrequencySecondsField
          valueSeconds={s.frequencySeconds}
          disabled={disabled}
          onCommit={(seconds) => { setSettings({ ...s, frequencySeconds: seconds }); submit(requestUpdateProactiveSuggestionFrequencySeconds(seconds)) }}
        />
      </section>

      <section className="proactive-suggestions-section" aria-labelledby="proactive-suggestions-evaluation-heading">
        <h2 id="proactive-suggestions-evaluation-heading">Evaluation</h2>
        <TokenizedSelect
          value={s.evaluationModel}
          disabled={disabled || (hasNoModels && !s.evaluationModel)}
          ariaLabel="Evaluator model"
          onValueChange={(evaluationModel) => {
            setSettings({ ...s, evaluationModel })
            submit(requestUpdateProactiveSuggestionEvaluationModel(evaluationModel))
          }}
          options={[
            ...(s.selectedEvaluationModelIsUnavailable ? [{ value: s.evaluationModel, label: s.evaluationModel, group: 'Unavailable Model' }] : []),
            ...s.localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
            ...s.apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })),
            ...(hasNoModels ? [{ value: '', label: 'No models available' }] : []),
          ]}
        />
        {s.selectedEvaluationModelIsUnavailable && (
          <p className="proactive-suggestions-inline-warning" role="alert">The selected evaluator model is not currently available. Choose another model to replace it.</p>
        )}

        <div className="proactive-suggestions-confidence">
          <label htmlFor="proactive-suggestions-confidence-input">Minimum Confidence: {Math.round(s.minimumConfidence * 100)}%</label>
          <input
            id="proactive-suggestions-confidence-input"
            type="range"
            min={0}
            max={1}
            step={0.05}
            defaultValue={s.minimumConfidence}
            disabled={disabled}
            onBlur={(event) => { const next = Number(event.currentTarget.value); setSettings({ ...s, minimumConfidence: next }); submit(requestUpdateProactiveSuggestionMinimumConfidence(next)) }}
            onKeyUp={(event) => { const next = Number(event.currentTarget.value); setSettings({ ...s, minimumConfidence: next }); submit(requestUpdateProactiveSuggestionMinimumConfidence(next)) }}
            onPointerUp={(event) => { const next = Number(event.currentTarget.value); setSettings({ ...s, minimumConfidence: next }); submit(requestUpdateProactiveSuggestionMinimumConfidence(next)) }}
          />
        </div>

        <label>Cooldown</label>
        <TokenizedSelect
          value={s.cooldownMinutes}
          disabled={disabled}
          ariaLabel="Cooldown"
          onValueChange={(cooldownMinutes) => {
            setSettings({ ...s, cooldownMinutes })
            submit(requestUpdateProactiveSuggestionCooldownMinutes(cooldownMinutes))
          }}
          options={COOLDOWN_OPTIONS}
        />
      </section>

      <section className="proactive-suggestions-section" aria-labelledby="proactive-suggestions-capabilities-heading">
        <h2 id="proactive-suggestions-capabilities-heading">Capabilities</h2>
        <h3>Enabled Capabilities</h3>
        {CAPABILITIES.map((capability) => (
          <Switch
            key={`enabled-${capability.id}`}
            id={`proactive-suggestions-enabled-${capability.id}`}
            label={capability.label}
            checked={s.enabledCapabilities.includes(capability.id)}
            disabled={disabled}
            onChange={(checked) => {
              const nextEnabled = checked
                ? [...s.enabledCapabilities, capability.id]
                : s.enabledCapabilities.filter((id) => id !== capability.id)
              const nextAutoExecute = checked ? s.autoExecuteCapabilities : s.autoExecuteCapabilities.filter((id) => id !== capability.id)
              setSettings({ ...s, enabledCapabilities: nextEnabled, autoExecuteCapabilities: nextAutoExecute })
              submit(requestUpdateProactiveSuggestionEnabledCapability(capability.id, checked))
            }}
          />
        ))}
        <h3>Auto-Execute Capabilities</h3>
        {CAPABILITIES.map((capability) => (
          <Switch
            key={`auto-${capability.id}`}
            id={`proactive-suggestions-auto-execute-${capability.id}`}
            label={capability.label}
            checked={s.autoExecuteCapabilities.includes(capability.id)}
            disabled={disabled || s.mode !== 'auto_execute'}
            onChange={(checked) => {
              const nextAutoExecute = checked
                ? [...s.autoExecuteCapabilities, capability.id]
                : s.autoExecuteCapabilities.filter((id) => id !== capability.id)
              const nextEnabled = checked ? Array.from(new Set([...s.enabledCapabilities, capability.id])) : s.enabledCapabilities
              setSettings({ ...s, enabledCapabilities: nextEnabled, autoExecuteCapabilities: nextAutoExecute })
              submit(requestUpdateProactiveSuggestionAutoExecuteCapability(capability.id, checked))
            }}
          />
        ))}
        <p className="proactive-suggestions-field-hint">Auto-execute only applies when mode is Auto Execute and the suggestion is marked eligible.</p>
      </section>

      <section className="proactive-suggestions-section" aria-labelledby="proactive-suggestions-exclusions-heading">
        <h2 id="proactive-suggestions-exclusions-heading">Exclusions</h2>
        <ExcludedAppNamesField
          excludedAppNames={s.excludedAppNames}
          disabled={disabled}
          onApply={(names) => { setSettings({ ...s, excludedAppNames: names }); submit(requestUpdateProactiveSuggestionExcludedAppNames(names)) }}
        />
      </section>

      {pendingId && <p className="proactive-suggestions-status" role="status">Saving setting...</p>}
      {requestError && <p className="proactive-suggestions-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}

function ExcludedAppNamesField({
  excludedAppNames,
  disabled,
  onApply,
}: {
  excludedAppNames: string[]
  disabled: boolean
  onApply: (names: string[]) => void
}) {
  const [draftText, setDraftText] = useState(excludedAppNames.join('\n'))

  useEffect(() => {
    setDraftText(excludedAppNames.join('\n'))
  }, [excludedAppNames])

  return (
    <div className="proactive-suggestions-exclusions">
      <textarea
        aria-label="Excluded app names"
        value={draftText}
        disabled={disabled}
        onChange={(event) => setDraftText(event.target.value)}
      />
      <p className="proactive-suggestions-field-hint">Excluded app names, one per line.</p>
      <button
        type="button"
        className="secondary-button"
        disabled={disabled}
        onClick={() => onApply(draftText.split('\n').map((line) => line.trim()).filter((line) => line.length > 0))}
      >
        Apply Exclusions
      </button>
    </div>
  )
}
