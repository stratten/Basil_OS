import type {
  AgentTaskInputModality,
  AssistantSessionInputMode,
  ReasoningDefaultsNativeEvent,
} from '../types'

type OutgoingReasoningDefaultsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSelectedModel'; requestId: string; modelId: string }
  | { type: 'requestUpdateCloseAssistantSessionOnInsert'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoPasteAssistantOutput'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateUseRegionSelection'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAgentTaskDefaultModality'; requestId: string; modality: AgentTaskInputModality }
  | { type: 'requestUpdateAgentTaskAutoReopenOnCompletion'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAgentTaskPushToTalk'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAgentTaskPushToTalkThreshold'; requestId: string; thresholdMs: number }
  | { type: 'requestUpdateAssistantSessionDefaultModality'; requestId: string; modality: AssistantSessionInputMode }
  | { type: 'requestUpdateAssistantSessionPushToTalk'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAssistantSessionPushToTalkThreshold'; requestId: string; thresholdMs: number }
  | { type: 'requestUpdateConversationDefaultConversationOnly'; requestId: string; enabled: boolean }

declare global {
  interface Window {
    basilReasoningDefaultsSettings?: {
      onEvent: (event: ReasoningDefaultsNativeEvent) => void
    }
  }
}

type EventHandler = (event: ReasoningDefaultsNativeEvent) => void

let queuedEvents: ReasoningDefaultsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ReasoningDefaultsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilReasoningDefaultsSettings = { onEvent: dispatch }

export function onReasoningDefaultsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingReasoningDefaultsMessage) {
  window.webkit?.messageHandlers?.basilReasoningDefaultsSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyReasoningDefaultsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateSelectedModel(modelId: string): string {
  const id = requestId('updateSelectedModel')
  postMessage({ type: 'requestUpdateSelectedModel', requestId: id, modelId })
  return id
}

export function requestUpdateCloseAssistantSessionOnInsert(enabled: boolean): string {
  const id = requestId('updateCloseAssistantSessionOnInsert')
  postMessage({ type: 'requestUpdateCloseAssistantSessionOnInsert', requestId: id, enabled })
  return id
}

export function requestUpdateAutoPasteAssistantOutput(enabled: boolean): string {
  const id = requestId('updateAutoPasteAssistantOutput')
  postMessage({ type: 'requestUpdateAutoPasteAssistantOutput', requestId: id, enabled })
  return id
}

export function requestUpdateUseRegionSelection(enabled: boolean): string {
  const id = requestId('updateUseRegionSelection')
  postMessage({ type: 'requestUpdateUseRegionSelection', requestId: id, enabled })
  return id
}

export function requestUpdateAgentTaskDefaultModality(modality: AgentTaskInputModality): string {
  const id = requestId('updateAgentTaskDefaultModality')
  postMessage({ type: 'requestUpdateAgentTaskDefaultModality', requestId: id, modality })
  return id
}

export function requestUpdateAgentTaskAutoReopenOnCompletion(enabled: boolean): string {
  const id = requestId('updateAgentTaskAutoReopenOnCompletion')
  postMessage({ type: 'requestUpdateAgentTaskAutoReopenOnCompletion', requestId: id, enabled })
  return id
}

export function requestUpdateAgentTaskPushToTalk(enabled: boolean): string {
  const id = requestId('updateAgentTaskPushToTalk')
  postMessage({ type: 'requestUpdateAgentTaskPushToTalk', requestId: id, enabled })
  return id
}

export function requestUpdateAgentTaskPushToTalkThreshold(thresholdMs: number): string {
  const id = requestId('updateAgentTaskPushToTalkThreshold')
  postMessage({ type: 'requestUpdateAgentTaskPushToTalkThreshold', requestId: id, thresholdMs })
  return id
}

export function requestUpdateAssistantSessionDefaultModality(modality: AssistantSessionInputMode): string {
  const id = requestId('updateAssistantSessionDefaultModality')
  postMessage({ type: 'requestUpdateAssistantSessionDefaultModality', requestId: id, modality })
  return id
}

export function requestUpdateAssistantSessionPushToTalk(enabled: boolean): string {
  const id = requestId('updateAssistantSessionPushToTalk')
  postMessage({ type: 'requestUpdateAssistantSessionPushToTalk', requestId: id, enabled })
  return id
}

export function requestUpdateAssistantSessionPushToTalkThreshold(thresholdMs: number): string {
  const id = requestId('updateAssistantSessionPushToTalkThreshold')
  postMessage({ type: 'requestUpdateAssistantSessionPushToTalkThreshold', requestId: id, thresholdMs })
  return id
}

export function requestUpdateConversationDefaultConversationOnly(enabled: boolean): string {
  const id = requestId('updateConversationDefaultConversationOnly')
  postMessage({ type: 'requestUpdateConversationDefaultConversationOnly', requestId: id, enabled })
  return id
}
