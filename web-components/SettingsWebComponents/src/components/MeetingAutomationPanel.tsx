import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import { PolicyRadioGroup, type PolicyRadioOption } from './PolicyRadioGroup'
import {
  notifyMeetingAutomationSettingsReady,
  onMeetingAutomationEvent,
  requestUpdateAutoAnalyzeCustomInstructions,
  requestUpdateAutoAnalyzeMode,
  requestUpdateAutoAnalyzeOnComplete,
  requestUpdateAutoAnalyzeTiming,
  requestUpdateAutoRetranscribeDuringRecording,
  requestUpdateAutoRetranscribeOnStop,
  requestUpdateRetranscribeWindowMinutes,
} from '../services/meetingAutomationBridge'
import type { MeetingAutomationAnalysisModeOption, MeetingAutomationSettingsFields } from '../types'

const TIMING_OPTIONS: readonly PolicyRadioOption<'after' | 'before'>[] = [
  { id: 'after', label: 'After re-transcription' },
  { id: 'before', label: 'Before re-transcription' },
]

export function MeetingAutomationPanel() {
  const [settings, setSettings] = useState<MeetingAutomationSettingsFields | null>(null)
  const [analysisModes, setAnalysisModes] = useState<MeetingAutomationAnalysisModeOption[]>([])
  const [intervalDraft, setIntervalDraft] = useState('')
  const [instructionsDraft, setInstructionsDraft] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    const unsubscribe = onMeetingAutomationEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setSettings(event.settings)
        setIntervalDraft(String(event.settings.retranscribeWindowMinutes))
        setInstructionsDraft(event.settings.autoAnalyzeCustomInstructions)
        setLoadError(null)
        if (event.type === 'init') setAnalysisModes(event.analysisModes)
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
    notifyMeetingAutomationSettingsReady()
    return unsubscribe
  }, [])

  function submit(id: string) {
    if (pendingRef.current) return
    setRequestError(null)
    setPendingId(id)
  }

  function commitInterval() {
    const parsed = Number(intervalDraft)
    const next = Number.isFinite(parsed) ? Math.max(1, Math.round(parsed)) : settings!.retranscribeWindowMinutes
    setIntervalDraft(String(next))
    if (next !== settings!.retranscribeWindowMinutes) {
      setSettings({ ...settings!, retranscribeWindowMinutes: next })
      submit(requestUpdateRetranscribeWindowMinutes(next))
    }
  }

  function commitInstructions() {
    if (instructionsDraft !== settings!.autoAnalyzeCustomInstructions) {
      setSettings({ ...settings!, autoAnalyzeCustomInstructions: instructionsDraft })
      submit(requestUpdateAutoAnalyzeCustomInstructions(instructionsDraft))
    }
  }

  if (!settings && !loadError) {
    return <p className="meetings-settings-status" role="status">Loading Meeting Automation settings...</p>
  }

  if (loadError) {
    return (
      <div className="meetings-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyMeetingAutomationSettingsReady()}>Retry</button>
      </div>
    )
  }

  const disabled = pendingId !== null
  const s = settings!

  return (
    <section className="meetings-settings-section" aria-labelledby="meetings-automation-heading">
      <h2 id="meetings-automation-heading">Meeting Automation</h2>
      <Switch
        id="meetings-automation-retranscribe-on-stop"
        label="Auto-retranscribe on stop"
        checked={s.autoRetranscribeOnStop}
        disabled={disabled}
        onChange={(checked) => { setSettings({ ...s, autoRetranscribeOnStop: checked }); submit(requestUpdateAutoRetranscribeOnStop(checked)) }}
      />
      <p className="meetings-settings-hint">When a recording stops, automatically re-transcribe it with the selected higher-quality model.</p>

      <Switch
        id="meetings-automation-retranscribe-during"
        label="Re-transcribe while recording"
        checked={s.autoRetranscribeDuringRecording}
        disabled={disabled}
        onChange={(checked) => { setSettings({ ...s, autoRetranscribeDuringRecording: checked }); submit(requestUpdateAutoRetranscribeDuringRecording(checked)) }}
      />
      <p className="meetings-settings-hint">Incrementally upgrade earlier audio with the higher-quality model at a fixed interval while recording continues, so less work remains when you stop.</p>
      {s.autoRetranscribeDuringRecording && (
        <div className="meetings-numeric-field">
          <label htmlFor="meetings-automation-interval">Interval</label>
          <input
            id="meetings-automation-interval"
            type="number"
            min={1}
            step={1}
            value={intervalDraft}
            disabled={disabled}
            onChange={(event) => setIntervalDraft(event.target.value)}
            onBlur={commitInterval}
            onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }}
          />
          <span>minutes</span>
        </div>
      )}

      <Switch
        id="meetings-automation-auto-analyze"
        label="Auto-analyze on complete"
        checked={s.autoAnalyzeOnComplete}
        disabled={disabled}
        onChange={(checked) => { setSettings({ ...s, autoAnalyzeOnComplete: checked }); submit(requestUpdateAutoAnalyzeOnComplete(checked)) }}
      />
      {s.autoAnalyzeOnComplete && (
        <>
          <PolicyRadioGroup
            legend="Run analysis"
            name="meetings-automation-timing"
            options={TIMING_OPTIONS}
            value={s.autoAnalyzeTiming}
            disabled={disabled}
            onChange={(next) => { setSettings({ ...s, autoAnalyzeTiming: next }); submit(requestUpdateAutoAnalyzeTiming(next)) }}
          />
          <fieldset className="meetings-automation-modes">
            <legend>Modes</legend>
            {analysisModes.map((mode) => (
              <div key={mode.id} className="meetings-automation-mode-toggle">
                <Switch
                  id={`meetings-automation-mode-${mode.id}`}
                  label={mode.label}
                  checked={s.autoAnalyzeModes.includes(mode.id)}
                  disabled={disabled}
                  onChange={(isOn) => {
                    const nextModes = isOn ? [...s.autoAnalyzeModes, mode.id] : s.autoAnalyzeModes.filter((id) => id !== mode.id)
                    setSettings({ ...s, autoAnalyzeModes: nextModes })
                    submit(requestUpdateAutoAnalyzeMode(mode.id, isOn))
                  }}
                />
              </div>
            ))}
          </fieldset>
          <label htmlFor="meetings-automation-instructions" className="meetings-settings-hint">Custom instructions (optional)</label>
          <textarea
            id="meetings-automation-instructions"
            className="meetings-exclusions-textarea"
            rows={3}
            value={instructionsDraft}
            disabled={disabled}
            onChange={(event) => setInstructionsDraft(event.target.value)}
            onBlur={commitInstructions}
          />
        </>
      )}

      {pendingId && <p className="meetings-settings-status" role="status">Saving setting...</p>}
      {requestError && <p className="meetings-settings-inline-error" role="alert">{requestError}</p>}
    </section>
  )
}
