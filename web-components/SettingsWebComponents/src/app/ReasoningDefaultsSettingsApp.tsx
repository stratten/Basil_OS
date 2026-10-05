import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import { BASIL_TEAM } from '@shared/teamIdentity'
import TokenizedSelect from '@shared/TokenizedSelect'
import { PolicyRadioGroup, type PolicyRadioOption } from '../components/PolicyRadioGroup'
import { useOptimisticSettings } from './useOptimisticSettings'
import {
  notifyReasoningDefaultsSettingsReady,
  onReasoningDefaultsEvent,
  requestUpdateAgentTaskAutoReopenOnCompletion,
  requestUpdateAgentTaskDefaultModality,
  requestUpdateAgentTaskPushToTalk,
  requestUpdateAgentTaskPushToTalkThreshold,
  requestUpdateAssistantSessionDefaultModality,
  requestUpdateAssistantSessionPushToTalk,
  requestUpdateAssistantSessionPushToTalkThreshold,
  requestUpdateAssistantOutputPasteMode,
  requestUpdateCloseAssistantSessionOnInsert,
  requestUpdateConversationDefaultConversationOnly,
  requestUpdateSelectedModel,
  requestUpdateUseRegionSelection,
} from '../services/reasoningDefaultsBridge'
import type {
  AgentTaskInputModality,
  AssistantOutputPasteMode,
  AssistantSessionInputMode,
  ReasoningDefaultsSettingsSnapshot,
} from '../types'

const DEBUG_LOG_PREFIX = '[ReasoningDefaultsSettings]'

function debugLog(step: string, detail?: unknown): void {
  const timestamp = new Date().toISOString().slice(11, 23)
  if (detail !== undefined) {
    console.log(`${DEBUG_LOG_PREFIX} ${timestamp} ${step}`, detail)
  } else {
    console.log(`${DEBUG_LOG_PREFIX} ${timestamp} ${step}`)
  }
}

const AGENT_TASK_MODALITY_OPTIONS: readonly PolicyRadioOption<AgentTaskInputModality>[] = [
  { id: 'voice', label: 'Voice' },
  { id: 'text', label: 'Text' },
]

const ASSISTANT_SESSION_MODALITY_OPTIONS: readonly PolicyRadioOption<AssistantSessionInputMode>[] = [
  { id: 'speak', label: 'Speak' },
  { id: 'type', label: 'Type' },
]

const ASSISTANT_OUTPUT_PASTE_MODE_OPTIONS: readonly PolicyRadioOption<AssistantOutputPasteMode>[] = [
  { id: 'always', label: 'Always', description: 'Paste every finished response into the app you started from.' },
  { id: 'auto', label: 'Let Basil decide', description: 'Paste drafts, replies, and rewrites; keep explanations, answers, and research in the widget. If the model does not say, the response stays in the widget.' },
  { id: 'never', label: 'Never', description: 'Keep every response in the widget; copy it from there.' },
]

function clampThreshold(value: number): number {
  return Math.min(5000, Math.max(500, value))
}

function PushToTalkThreshold({
  idPrefix,
  valueMs,
  disabled,
  onCommit,
}: {
  idPrefix: string
  valueMs: number
  disabled?: boolean
  onCommit: (thresholdMs: number) => void
}) {
  const [draftValue, setDraftValue] = useState(String(valueMs))

  useEffect(() => {
    setDraftValue(String(valueMs))
  }, [valueMs])

  function commitDraft() {
    const nextValue = clampThreshold(Number(draftValue) || 500)
    setDraftValue(String(nextValue))
    if (nextValue !== valueMs) onCommit(nextValue)
  }

  return (
    <div className="reasoning-defaults-threshold">
      <div className="reasoning-defaults-threshold-row">
        <label htmlFor={`${idPrefix}-threshold-input`}>Threshold duration:</label>
        <input
          id={`${idPrefix}-threshold-input`}
          type="number"
          min={500}
          max={5000}
          value={draftValue}
          disabled={disabled}
          onChange={(event) => setDraftValue(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.currentTarget.blur()
          }}
        />
        <span>ms</span>
      </div>
      <p className="reasoning-defaults-field-hint">Current: {(valueMs / 1000).toFixed(2)} seconds</p>
      <input
        type="range"
        min={500}
        max={5000}
        step={50}
        value={draftValue}
        disabled={disabled}
        aria-label={`${idPrefix} push-to-talk threshold`}
        onChange={(event) => setDraftValue(event.target.value)}
        onBlur={commitDraft}
        onKeyUp={commitDraft}
        onPointerUp={commitDraft}
      />
      <p className="reasoning-defaults-field-hint">Range: 0.5 - 5.0 seconds</p>
    </div>
  )
}

export function ReasoningDefaultsSettingsApp() {
  const { settings, isSaving, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<ReasoningDefaultsSettingsSnapshot>()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  useEffect(() => {
    debugLog('mount: subscribing to native events')
    const unsubscribe = onReasoningDefaultsEvent((event) => {
      debugLog(`event received: ${event.type}`, event)
      if (event.type === 'init' || event.type === 'snapshot') {
        debugLog(`applying ${event.type} -> agentTaskDefaultModality=${event.settings?.agentTaskDefaultModality}, assistantSessionDefaultModality=${event.settings?.assistantSessionDefaultModality}`)
        receiveSnapshot(event.settings)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        debugLog('load error', event.message)
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') {
        const outcome = resolveIntent(event.requestId, event.status)
        debugLog(`intentResult requestId=${event.requestId} status=${event.status} outcome=${outcome}`)
        if (outcome === 'error') setRequestError(event.message ?? 'Failed to update the setting.')
      }
    })
    debugLog('mount: notifying native side ready')
    notifyReasoningDefaultsSettingsReady()
    return () => {
      debugLog('unmount: unsubscribing from native events')
      unsubscribe()
    }
  }, [])

  function submit(id: string) {
    debugLog(`submit: request ${id} now pending`)
    setRequestError(null)
    track(id)
  }

  if (!settings && !loadError) {
    return <p className="reasoning-defaults-status" role="status">Loading Automation & Agents settings...</p>
  }

  if (loadError) {
    return (
      <div className="reasoning-defaults-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyReasoningDefaultsSettingsReady()}>Retry</button>
      </div>
    )
  }

  const s = settings!
  const hasNoModels =
    s.localModels.length === 0 &&
    (s.apiModels.length === 0 || !s.useApiModels) &&
    (s.customModels.length === 0 || !s.useApiModels)

  return (
    <div className="reasoning-defaults-shell">
      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-model-heading">
        <h2 id="reasoning-defaults-model-heading">Default Model</h2>
        <TokenizedSelect
          value={s.selectedModelId}
          disabled={hasNoModels}
          ariaLabel="Default reasoning model"
          onValueChange={(next) => {
            setSettings({ ...s, selectedModelId: next })
            submit(requestUpdateSelectedModel(next))
          }}
          options={[
            ...s.localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
            ...(s.useApiModels ? s.apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })) : []),
            ...(s.useApiModels ? s.customModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Custom Models' })) : []),
          ]}
        />
        {hasNoModels && <p className="reasoning-defaults-field-hint">No reasoning models available</p>}
      </section>

      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-agent-task-heading">
        <h2 id="reasoning-defaults-agent-task-heading">{BASIL_TEAM.agentTask.pairedName}</h2>
        <PolicyRadioGroup
          legend="Default input mode"
          name="agent-task-default-modality"
          options={AGENT_TASK_MODALITY_OPTIONS}
          value={s.agentTaskDefaultModality}
          onChange={(next) => {
            debugLog(`AgentTask radio clicked: ${s.agentTaskDefaultModality} -> ${next} (optimistic setSettings)`)
            setSettings({ ...s, agentTaskDefaultModality: next })
            const requestId = requestUpdateAgentTaskDefaultModality(next)
            debugLog(`AgentTask update sent to native, requestId=${requestId}`)
            submit(requestId)
          }}
        />
        <p className="reasoning-defaults-field-hint">Chooses whether new Paprika tasks open the mic immediately or begin in the text editor. Affects the initial capture widget and the new-task overlay; voice follow-ups are unaffected.</p>
        <Switch
          id="reasoning-defaults-agent-task-auto-reopen"
          label="Automatically reopen collapsed Paprika tasks when they finish"
          checked={s.agentTaskAutoReopenOnCompletion}
          onChange={(checked) => { setSettings({ ...s, agentTaskAutoReopenOnCompletion: checked }); submit(requestUpdateAgentTaskAutoReopenOnCompletion(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When a focused Paprika task completes or fails while its result window is collapsed, reopen the window to show the final update.</p>
        <Switch
          id="reasoning-defaults-agent-task-ptt"
          label="Enable push-to-talk mode"
          checked={s.agentTaskPushToTalk}
          onChange={(checked) => { setSettings({ ...s, agentTaskPushToTalk: checked }); submit(requestUpdateAgentTaskPushToTalk(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, holding the Paprika hotkey for longer than the threshold will automatically process when released.</p>
        {s.agentTaskPushToTalk && (
          <PushToTalkThreshold
            idPrefix="agent-task"
            valueMs={s.agentTaskPushToTalkThreshold}
            onCommit={(thresholdMs) => { setSettings({ ...s, agentTaskPushToTalkThreshold: thresholdMs }); submit(requestUpdateAgentTaskPushToTalkThreshold(thresholdMs)) }}
          />
        )}
      </section>

      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-assistant-session-heading">
        <h2 id="reasoning-defaults-assistant-session-heading">{BASIL_TEAM.assistantSession.pairedName}</h2>
        <div className="reasoning-defaults-columns">
          <div className="reasoning-defaults-column" role="group" aria-labelledby="reasoning-defaults-assistant-session-input-heading">
            <h3 id="reasoning-defaults-assistant-session-input-heading">Input</h3>
        <PolicyRadioGroup
          legend="Default input mode"
          name="assistant-session-default-modality"
          options={ASSISTANT_SESSION_MODALITY_OPTIONS}
          value={s.assistantSessionDefaultModality}
          onChange={(next) => {
            debugLog(`AssistantSession radio clicked: ${s.assistantSessionDefaultModality} -> ${next} (optimistic setSettings)`)
            setSettings({ ...s, assistantSessionDefaultModality: next })
            const requestId = requestUpdateAssistantSessionDefaultModality(next)
            debugLog(`AssistantSession update sent to native, requestId=${requestId}`)
            submit(requestId)
          }}
        />
        <p className="reasoning-defaults-field-hint">Chooses whether the suggestion widget opens with the mic recording or in the typed-instruction editor. The Speak/Type toggle in the widget's header still overrides this per-session.</p>
        <Switch
          id="reasoning-defaults-assistant-session-ptt"
          label="Enable push-to-talk mode"
          checked={s.assistantSessionPushToTalk}
          onChange={(checked) => { setSettings({ ...s, assistantSessionPushToTalk: checked }); submit(requestUpdateAssistantSessionPushToTalk(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, holding the Dill hotkey for longer than the threshold will automatically process when released.</p>
        {s.assistantSessionPushToTalk && (
          <PushToTalkThreshold
            idPrefix="assistant-session"
            valueMs={s.assistantSessionPushToTalkThreshold}
            onCommit={(thresholdMs) => { setSettings({ ...s, assistantSessionPushToTalkThreshold: thresholdMs }); submit(requestUpdateAssistantSessionPushToTalkThreshold(thresholdMs)) }}
          />
        )}
          </div>
          <div className="reasoning-defaults-column" role="group" aria-labelledby="reasoning-defaults-behavior-heading">
            <h3 id="reasoning-defaults-behavior-heading">Behavior</h3>
        <Switch
          id="reasoning-defaults-close-on-insert"
          label="Close Dill after inserting"
          checked={s.closeAssistantSessionOnInsert}
          onChange={(checked) => { setSettings({ ...s, closeAssistantSessionOnInsert: checked }); submit(requestUpdateCloseAssistantSessionOnInsert(checked)) }}
        />
        <PolicyRadioGroup
          legend="Paste output"
          name="assistant-output-paste-mode"
          options={ASSISTANT_OUTPUT_PASTE_MODE_OPTIONS}
          value={s.assistantOutputPasteMode}
          onChange={(next) => { setSettings({ ...s, assistantOutputPasteMode: next }); submit(requestUpdateAssistantOutputPasteMode(next)) }}
        />
        <p className="reasoning-defaults-field-hint">Output is only pasted into the app that was in front when you started the session. If you switch to another app before it finishes, the response stays in the widget.</p>
        <Switch
          id="reasoning-defaults-region-selection"
          label="Use region selection for capture"
          checked={s.useRegionSelection}
          onChange={(checked) => { setSettings({ ...s, useRegionSelection: checked }); submit(requestUpdateUseRegionSelection(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, allows manual screen region selection instead of automatic window capture for Enhanced and Dill.</p>
          </div>
        </div>
      </section>

      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-conversation-heading">
        <h2 id="reasoning-defaults-conversation-heading">Conversation</h2>
        <Switch
          id="reasoning-defaults-conversation-only-default"
          label="Start new conversations in Conversation only"
          checked={s.conversationDefaultConversationOnly === true}
          onChange={(checked) => { setSettings({ ...s, conversationDefaultConversationOnly: checked }); submit(requestUpdateConversationDefaultConversationOnly(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">New conversations keep replies in the conversation instead of starting Paprika tasks. Each conversation remembers its own Conversation only choice, so changing this default does not change existing conversations.</p>
      </section>

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting...' : ''}</p>
      {requestError && <p className="reasoning-defaults-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
