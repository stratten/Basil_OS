import type {
  ProactiveSuggestionCapability,
  ProactiveSuggestionMode,
  ProactiveSuggestionsNativeEvent,
} from '../types'

type OutgoingProactiveSuggestionsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateEnabled'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateMode'; requestId: string; mode: ProactiveSuggestionMode }
  | { type: 'requestUpdateFrequencySeconds'; requestId: string; frequencySeconds: number }
  | { type: 'requestUpdateEvaluationModel'; requestId: string; evaluationModel: string }
  | { type: 'requestUpdateMinimumConfidence'; requestId: string; minimumConfidence: number }
  | { type: 'requestUpdateCooldownMinutes'; requestId: string; cooldownMinutes: number }
  | { type: 'requestUpdateEnabledCapability'; requestId: string; capability: ProactiveSuggestionCapability; enabled: boolean }
  | { type: 'requestUpdateAutoExecuteCapability'; requestId: string; capability: ProactiveSuggestionCapability; enabled: boolean }
  | { type: 'requestUpdateExcludedAppNames'; requestId: string; excludedAppNames: string[] }

declare global {
  interface Window {
    basilProactiveSuggestionsSettings?: {
      onEvent: (event: ProactiveSuggestionsNativeEvent) => void
    }
  }
}

type EventHandler = (event: ProactiveSuggestionsNativeEvent) => void

let queuedEvents: ProactiveSuggestionsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ProactiveSuggestionsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilProactiveSuggestionsSettings = { onEvent: dispatch }

export function onProactiveSuggestionsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingProactiveSuggestionsMessage) {
  window.webkit?.messageHandlers?.basilProactiveSuggestionsSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyProactiveSuggestionsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateProactiveSuggestionsEnabled(enabled: boolean): string {
  const id = requestId('updateEnabled')
  postMessage({ type: 'requestUpdateEnabled', requestId: id, enabled })
  return id
}

export function requestUpdateProactiveSuggestionMode(mode: ProactiveSuggestionMode): string {
  const id = requestId('updateMode')
  postMessage({ type: 'requestUpdateMode', requestId: id, mode })
  return id
}

export function requestUpdateProactiveSuggestionFrequencySeconds(frequencySeconds: number): string {
  const id = requestId('updateFrequencySeconds')
  postMessage({ type: 'requestUpdateFrequencySeconds', requestId: id, frequencySeconds })
  return id
}

export function requestUpdateProactiveSuggestionEvaluationModel(evaluationModel: string): string {
  const id = requestId('updateEvaluationModel')
  postMessage({ type: 'requestUpdateEvaluationModel', requestId: id, evaluationModel })
  return id
}

export function requestUpdateProactiveSuggestionMinimumConfidence(minimumConfidence: number): string {
  const id = requestId('updateMinimumConfidence')
  postMessage({ type: 'requestUpdateMinimumConfidence', requestId: id, minimumConfidence })
  return id
}

export function requestUpdateProactiveSuggestionCooldownMinutes(cooldownMinutes: number): string {
  const id = requestId('updateCooldownMinutes')
  postMessage({ type: 'requestUpdateCooldownMinutes', requestId: id, cooldownMinutes })
  return id
}

export function requestUpdateProactiveSuggestionEnabledCapability(capability: ProactiveSuggestionCapability, enabled: boolean): string {
  const id = requestId('updateEnabledCapability')
  postMessage({ type: 'requestUpdateEnabledCapability', requestId: id, capability, enabled })
  return id
}

export function requestUpdateProactiveSuggestionAutoExecuteCapability(capability: ProactiveSuggestionCapability, enabled: boolean): string {
  const id = requestId('updateAutoExecuteCapability')
  postMessage({ type: 'requestUpdateAutoExecuteCapability', requestId: id, capability, enabled })
  return id
}

export function requestUpdateProactiveSuggestionExcludedAppNames(excludedAppNames: string[]): string {
  const id = requestId('updateExcludedAppNames')
  postMessage({ type: 'requestUpdateExcludedAppNames', requestId: id, excludedAppNames })
  return id
}
