import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import { PolicyRadioGroup, type PolicyRadioOption } from './PolicyRadioGroup'
import { useOptimisticSettings } from '../app/useOptimisticSettings'
import {
  notifyMeetingAutomationSettingsReady,
  onMeetingAutomationEvent,
  requestUpdateAutoAnalyzeCustomInstructions,
  requestUpdateAutoAnalyzeMode,
  requestUpdateAutoAnalyzeOnComplete,
  requestUpdateAutoAnalyzeTiming,
  requestUpdateAutoRetranscribeDuringRecording,
  requestUpdateAutoRetranscribeOnStop,
  requestUpdateLiveTranscriptionByDefault,
  requestUpdateRetranscribeWindowMinutes,
} from '../services/meetingAutomationBridge'
import type { MeetingAutomationAnalysisModeOption, MeetingAutomationSettingsFields } from '../types'

const TIMING_OPTIONS: readonly PolicyRadioOption<'after' | 'before'>[] = [
  { id: 'after', label: 'After re-transcription' },
  { id: 'before', label: 'Before re-transcription' },
]

export function MeetingAutomationPanel() {
  const { settings, isSaving, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<MeetingAutomationSettingsFields>()
  const [analysisModes, setAnalysisModes] = useState<MeetingAutomationAnalysisModeOption[]>([])
  const [intervalDraft, setIntervalDraft] = useState('')
  const [instructionsDraft, setInstructionsDraft] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  useEffect(() => {
    const unsubscribe = onMeetingAutomationEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        receiveSnapshot(event.settings)
        setLoadError(null)
        if (event.type === 'init') setAnalysisModes(event.analysisModes)
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
    notifyMeetingAutomationSettingsReady()
    return unsubscribe
  }, [])

  const retranscribeWindowMinutes = settings?.retranscribeWindowMinutes
  const autoAnalyzeCustomInstructions = settings?.autoAnalyzeCustomInstructions

  useEffect(() => {
    if (retranscribeWindowMinutes !== undefined) setIntervalDraft(String(retranscribeWindowMinutes))
  }, [retranscribeWindowMinutes])

  useEffect(() => {
    if (autoAnalyzeCustomInstructions !== undefined) setInstructionsDraft(autoAnalyzeCustomInstructions)
  }, [autoAnalyzeCustomInstructions])

  function submit(id: string) {
    setRequestError(null)
    track(id)
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

  const s = settings!

  return (
    <section className="meetings-settings-section" aria-labelledby="meetings-automation-heading">
      <h2 id="meetings-automation-heading">Meeting Automation</h2>
      <Switch
        id="meetings-automation-live-transcription"
        label="Live transcription by default"
        checked={s.liveTranscriptionByDefault}
        onChange={(checked) => { setSettings({ ...s, liveTranscriptionByDefault: checked }); submit(requestUpdateLiveTranscriptionByDefault(checked)) }}
      />
      <p className="meetings-settings-hint">Transcribe meetings as they are recorded. When off, meetings are recorded only and transcribed when they end, which uses less energy. You can still switch live transcription on or off during any meeting.</p>
      <Switch
        id="meetings-automation-retranscribe-on-stop"
        label="Auto-retranscribe on stop"
        checked={s.autoRetranscribeOnStop}
        onChange={(checked) => { setSettings({ ...s, autoRetranscribeOnStop: checked }); submit(requestUpdateAutoRetranscribeOnStop(checked)) }}
      />
      <p className="meetings-settings-hint">When a recording stops, automatically re-transcribe it with the selected higher-quality model.</p>

      <Switch
        id="meetings-automation-retranscribe-during"
        label="Re-transcribe while recording"
        checked={s.autoRetranscribeDuringRecording}
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
        onChange={(checked) => { setSettings({ ...s, autoAnalyzeOnComplete: checked }); submit(requestUpdateAutoAnalyzeOnComplete(checked)) }}
      />
      {s.autoAnalyzeOnComplete && (
        <>
          <PolicyRadioGroup
            legend="Run analysis"
            name="meetings-automation-timing"
            options={TIMING_OPTIONS}
            value={s.autoAnalyzeTiming}
            onChange={(next) => { setSettings({ ...s, autoAnalyzeTiming: next }); submit(requestUpdateAutoAnalyzeTiming(next)) }}
          />
          <fieldset className="meetings-automation-modes">
            <legend>Modes</legend>
            <div className="meetings-automation-mode-grid">
              {analysisModes.map((mode) => (
                <div key={mode.id} className="meetings-automation-mode-toggle">
                  <Switch
                    id={`meetings-automation-mode-${mode.id}`}
                    label={mode.label}
                    checked={s.autoAnalyzeModes.includes(mode.id)}
                    onChange={(isOn) => {
                      const nextModes = isOn ? [...s.autoAnalyzeModes, mode.id] : s.autoAnalyzeModes.filter((id) => id !== mode.id)
                      setSettings({ ...s, autoAnalyzeModes: nextModes })
                      submit(requestUpdateAutoAnalyzeMode(mode.id, isOn))
                    }}
                  />
                </div>
              ))}
            </div>
          </fieldset>
          <label htmlFor="meetings-automation-instructions" className="meetings-settings-hint">Custom instructions (optional)</label>
          <textarea
            id="meetings-automation-instructions"
            className="meetings-exclusions-textarea"
            rows={3}
            value={instructionsDraft}
            onChange={(event) => setInstructionsDraft(event.target.value)}
            onBlur={commitInstructions}
          />
        </>
      )}

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting...' : ''}</p>
      {requestError && <p className="meetings-settings-inline-error" role="alert">{requestError}</p>}
    </section>
  )
}
