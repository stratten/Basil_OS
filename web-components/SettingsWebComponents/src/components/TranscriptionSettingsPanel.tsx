import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  requestUpdateAutoCloseOnPaste,
  requestUpdateAutoPaste,
  requestUpdateMeetingDetectionStartup,
  requestUpdatePushToTalk,
  requestUpdatePushToTalkThreshold,
  requestUpdateSelectedModel,
  requestUpdateUnloadDelay,
} from '../services/transcriptionSettingsBridge'
import type { TranscriptionSettingsFields, TranscriptionUnloadDelayOption } from '../types'

const PUSH_TO_TALK_MIN_MS = 500
const PUSH_TO_TALK_MAX_MS = 5000

interface TranscriptionSettingsPanelProps {
  settings: TranscriptionSettingsFields
  unloadDelayOptions: TranscriptionUnloadDelayOption[]
  disabled?: boolean
  onSettingsChange: (settings: TranscriptionSettingsFields) => void
  onTrackRequest: (id: string) => void
}

export function TranscriptionSettingsPanel({
  settings,
  unloadDelayOptions,
  disabled,
  onSettingsChange,
  onTrackRequest,
}: TranscriptionSettingsPanelProps) {
  const [thresholdDraft, setThresholdDraft] = useState(String(settings.pushToTalkThresholdMs))

  useEffect(() => {
    setThresholdDraft(String(settings.pushToTalkThresholdMs))
  }, [settings.pushToTalkThresholdMs])

  function commitThreshold() {
    const parsed = Number(thresholdDraft)
    const next = Number.isFinite(parsed)
      ? Math.min(PUSH_TO_TALK_MAX_MS, Math.max(PUSH_TO_TALK_MIN_MS, Math.round(parsed)))
      : settings.pushToTalkThresholdMs
    setThresholdDraft(String(next))
    if (next !== settings.pushToTalkThresholdMs) {
      onSettingsChange({ ...settings, pushToTalkThresholdMs: next })
      onTrackRequest(requestUpdatePushToTalkThreshold(next))
    }
  }

  const hasModels = settings.localModels.length > 0 || settings.apiModels.length > 0

  return (
    <div className="transcription-settings-panel">
      <section className="transcription-settings-section">
        <h2>Model Settings</h2>
        <div className="transcription-model-settings-fields">
          <div className="transcription-model-setting-field">
            <label htmlFor="transcription-default-model">Default model</label>
            <TokenizedSelect
              className="transcription-model-select"
              value={settings.selectedModel}
              disabled={disabled || !hasModels}
              ariaLabel="Default model"
              onValueChange={(modelId) => {
                onSettingsChange({ ...settings, selectedModel: modelId })
                onTrackRequest(requestUpdateSelectedModel(modelId))
              }}
              options={[
                ...settings.localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
                ...settings.apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })),
              ]}
            />
            {!hasModels && <p className="transcription-settings-hint">No transcription models available</p>}
          </div>
          <div className="transcription-model-setting-field">
            <label htmlFor="transcription-unload-delay">Unload model after closing widget</label>
            <TokenizedSelect
              className="transcription-unload-delay-select"
              value={settings.unloadDelaySeconds}
              disabled={disabled}
              ariaLabel="Unload model after closing widget"
              onValueChange={(seconds) => {
                onSettingsChange({ ...settings, unloadDelaySeconds: seconds })
                onTrackRequest(requestUpdateUnloadDelay(seconds))
              }}
              options={unloadDelayOptions.map((option) => ({ value: option.seconds, label: option.label }))}
            />
            <p className="transcription-settings-hint">This setting determines how long to keep the transcription model loaded after closing the widget.</p>
          </div>
        </div>
      </section>

      <section className="transcription-settings-section">
        <h2>Behavior</h2>
        <Switch
          id="transcription-auto-paste"
          label="Auto paste transcription"
          checked={settings.autoPasteTranscription}
          disabled={disabled}
          onChange={(checked) => {
            onSettingsChange({ ...settings, autoPasteTranscription: checked })
            onTrackRequest(requestUpdateAutoPaste(checked))
          }}
        />
        <p className="transcription-settings-hint">Automatically paste transcribed text when transcription is complete.</p>
        {settings.autoPasteTranscription && (
          <>
            <Switch
              id="transcription-auto-close"
              label="Auto close widget after pasting"
              checked={settings.autoCloseOnPaste}
              disabled={disabled}
              onChange={(checked) => {
                onSettingsChange({ ...settings, autoCloseOnPaste: checked })
                onTrackRequest(requestUpdateAutoCloseOnPaste(checked))
              }}
            />
            <p className="transcription-settings-hint">The transcription widget will automatically close after transcription is complete and text is pasted.</p>
          </>
        )}
        <Switch
          id="transcription-start-meeting-detection"
          label="Start Meeting/Call Detection at launch"
          checked={settings.startMeetingDetectionAtStartup}
          disabled={disabled}
          onChange={(checked) => {
            onSettingsChange({ ...settings, startMeetingDetectionAtStartup: checked })
            onTrackRequest(requestUpdateMeetingDetectionStartup(checked))
          }}
        />
        <p className="transcription-settings-hint">Automatically begin watching for meetings each time Basil launches. Turning this on also enables Meeting/Call Detection; it will not start the monitor until the next launch.</p>
      </section>

      <section className="transcription-settings-section">
        <h2>Push-to-Talk Mode</h2>
        <Switch
          id="transcription-push-to-talk"
          label="Enable push-to-talk mode"
          checked={settings.enablePushToTalk}
          disabled={disabled}
          onChange={(checked) => {
            onSettingsChange({ ...settings, enablePushToTalk: checked })
            onTrackRequest(requestUpdatePushToTalk(checked))
          }}
        />
        <p className="transcription-settings-hint">When enabled, holding the hotkey for longer than the threshold will automatically process when released.</p>
        {settings.enablePushToTalk && (
          <div className="transcription-push-to-talk-threshold">
            <label htmlFor="transcription-ptt-threshold">Threshold duration</label>
            <input
              id="transcription-ptt-threshold"
              type="number"
              min={PUSH_TO_TALK_MIN_MS}
              max={PUSH_TO_TALK_MAX_MS}
              step={50}
              value={thresholdDraft}
              disabled={disabled}
              onChange={(event) => setThresholdDraft(event.target.value)}
              onBlur={commitThreshold}
              onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }}
            />
            <span>ms</span>
            <p className="transcription-settings-hint">
              Current: {(settings.pushToTalkThresholdMs / 1000).toFixed(2)} seconds (range: 0.5 - 5.0 seconds)
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
