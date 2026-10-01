import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import { PolicyRadioGroup, type PolicyRadioOption } from '../components/PolicyRadioGroup'
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
  requestUpdateAutoPasteAssistantOutput,
  requestUpdateCloseAssistantSessionOnInsert,
  requestUpdateConversationDefaultConversationOnly,
  requestUpdateSelectedModel,
  requestUpdateUseRegionSelection,
} from '../services/reasoningDefaultsBridge'
import type {
  AgentTaskInputModality,
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
  disabled: boolean
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
  const [settings, setSettings] = useState<ReasoningDefaultsSettingsSnapshot | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    debugLog('mount: subscribing to native events')
    const unsubscribe = onReasoningDefaultsEvent((event) => {
      debugLog(`event received: ${event.type}`, event)
      if (event.type === 'init' || event.type === 'snapshot') {
        debugLog(`applying ${event.type} -> agentTaskDefaultModality=${event.settings?.agentTaskDefaultModality}, assistantSessionDefaultModality=${event.settings?.assistantSessionDefaultModality}`)
        setSettings(event.settings)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        debugLog('load error', event.message)
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') {
        const matchesPending = event.requestId === pendingRef.current
        debugLog(`intentResult requestId=${event.requestId} status=${event.status} matchesPending=${matchesPending} (pendingRef=${pendingRef.current})`)
        if (matchesPending) {
          setPendingId(null)
          setRequestError(event.status === 'error' ? event.message ?? 'Failed to update the setting.' : null)
        }
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
    if (pendingRef.current) {
      debugLog(`submit blocked: request ${id} ignored because ${pendingRef.current} is still pending`)
      return
    }
    debugLog(`submit: request ${id} now pending`)
    setRequestError(null)
    setPendingId(id)
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

  const disabled = pendingId !== null
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
          disabled={disabled || hasNoModels}
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
        <h2 id="reasoning-defaults-agent-task-heading">AgentTask</h2>
        <PolicyRadioGroup
          legend="Default input mode"
          name="agent-task-default-modality"
          options={AGENT_TASK_MODALITY_OPTIONS}
          value={s.agentTaskDefaultModality}
          disabled={disabled}
          onChange={(next) => {
            debugLog(`AgentTask radio clicked: ${s.agentTaskDefaultModality} -> ${next} (optimistic setSettings)`)
            setSettings({ ...s, agentTaskDefaultModality: next })
            const requestId = requestUpdateAgentTaskDefaultModality(next)
            debugLog(`AgentTask update sent to native, requestId=${requestId}`)
            submit(requestId)
          }}
        />
        <p className="reasoning-defaults-field-hint">Chooses whether new agentTasks open the mic immediately or begin in the text editor. Affects the initial capture widget and the new-AgentTask overlay -- voice follow-ups are unaffected.</p>
        <Switch
          id="reasoning-defaults-agent-task-auto-reopen"
          label="Automatically reopen collapsed agent tasks when they finish"
          checked={s.agentTaskAutoReopenOnCompletion}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, agentTaskAutoReopenOnCompletion: checked }); submit(requestUpdateAgentTaskAutoReopenOnCompletion(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When a focused agent task completes or fails while its result window is collapsed, reopen the window to show the final update.</p>
        <Switch
          id="reasoning-defaults-agent-task-ptt"
          label="Enable push-to-talk mode"
          checked={s.agentTaskPushToTalk}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, agentTaskPushToTalk: checked }); submit(requestUpdateAgentTaskPushToTalk(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, holding the agentTask hotkey for longer than the threshold will automatically process when released.</p>
        {s.agentTaskPushToTalk && (
          <PushToTalkThreshold
            idPrefix="agent-task"
            valueMs={s.agentTaskPushToTalkThreshold}
            disabled={disabled}
            onCommit={(thresholdMs) => { setSettings({ ...s, agentTaskPushToTalkThreshold: thresholdMs }); submit(requestUpdateAgentTaskPushToTalkThreshold(thresholdMs)) }}
          />
        )}
      </section>

      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-assistant-session-heading">
        <h2 id="reasoning-defaults-assistant-session-heading">AssistantSession</h2>
        <div className="reasoning-defaults-columns">
          <div className="reasoning-defaults-column" role="group" aria-labelledby="reasoning-defaults-assistant-session-input-heading">
            <h3 id="reasoning-defaults-assistant-session-input-heading">Input</h3>
        <PolicyRadioGroup
          legend="Default input mode"
          name="assistant-session-default-modality"
          options={ASSISTANT_SESSION_MODALITY_OPTIONS}
          value={s.assistantSessionDefaultModality}
          disabled={disabled}
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
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, assistantSessionPushToTalk: checked }); submit(requestUpdateAssistantSessionPushToTalk(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, holding the AssistantSession hotkey for longer than the threshold will automatically process when released.</p>
        {s.assistantSessionPushToTalk && (
          <PushToTalkThreshold
            idPrefix="assistant-session"
            valueMs={s.assistantSessionPushToTalkThreshold}
            disabled={disabled}
            onCommit={(thresholdMs) => { setSettings({ ...s, assistantSessionPushToTalkThreshold: thresholdMs }); submit(requestUpdateAssistantSessionPushToTalkThreshold(thresholdMs)) }}
          />
        )}
          </div>
          <div className="reasoning-defaults-column" role="group" aria-labelledby="reasoning-defaults-behavior-heading">
            <h3 id="reasoning-defaults-behavior-heading">Behavior</h3>
        <Switch
          id="reasoning-defaults-close-on-insert"
          label="Close AssistantSession after inserting"
          checked={s.closeAssistantSessionOnInsert}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, closeAssistantSessionOnInsert: checked }); submit(requestUpdateCloseAssistantSessionOnInsert(checked)) }}
        />
        <Switch
          id="reasoning-defaults-auto-paste"
          label="Auto paste AssistantSession output"
          checked={s.autoPasteAssistantOutput}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, autoPasteAssistantOutput: checked }); submit(requestUpdateAutoPasteAssistantOutput(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">Automatically paste AssistantSession output when generation is complete.</p>
        <Switch
          id="reasoning-defaults-region-selection"
          label="Use region selection for capture"
          checked={s.useRegionSelection}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, useRegionSelection: checked }); submit(requestUpdateUseRegionSelection(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">When enabled, allows manual screen region selection instead of automatic window capture for Enhanced and AssistantSession.</p>
          </div>
        </div>
      </section>

      <section className="reasoning-defaults-section" aria-labelledby="reasoning-defaults-conversation-heading">
        <h2 id="reasoning-defaults-conversation-heading">Conversation</h2>
        <Switch
          id="reasoning-defaults-conversation-only-default"
          label="Start new conversations in Conversation only"
          checked={s.conversationDefaultConversationOnly === true}
          disabled={disabled}
          onChange={(checked) => { setSettings({ ...s, conversationDefaultConversationOnly: checked }); submit(requestUpdateConversationDefaultConversationOnly(checked)) }}
        />
        <p className="reasoning-defaults-field-hint">New conversations keep replies in the conversation instead of starting agent tasks. Each conversation remembers its own Conversation only choice, so changing this default does not change existing conversations.</p>
      </section>

      {pendingId && <p className="reasoning-defaults-status" role="status">Saving setting...</p>}
      {requestError && <p className="reasoning-defaults-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
