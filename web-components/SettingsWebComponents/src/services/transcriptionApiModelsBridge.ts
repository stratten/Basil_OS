import type { TranscriptionApiModelsNativeEvent } from '../types'

type OutgoingMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestToggleMaster'; requestId: string; enabled: boolean }
  | { type: 'requestToggleProvider'; requestId: string; enabled: boolean }
  | { type: 'requestToggleModel'; requestId: string; modelId: string; enabled: boolean }
  | { type: 'requestSaveApiKey'; requestId: string; key: string }

declare global {
  interface Window {
    basilTranscriptionApiModels?: {
      onEvent: (event: TranscriptionApiModelsNativeEvent) => void
    }
  }
}

type EventHandler = (event: TranscriptionApiModelsNativeEvent) => void

let queuedEvents: TranscriptionApiModelsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: TranscriptionApiModelsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilTranscriptionApiModels = { onEvent: dispatch }

export function onTranscriptionApiModelsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMessage) {
  window.webkit?.messageHandlers?.basilTranscriptionApiModelsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyTranscriptionApiModelsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestToggleMaster(enabled: boolean): string {
  const requestIdValue = requestId('requestToggleMaster')
  postMessage({ type: 'requestToggleMaster', requestId: requestIdValue, enabled })
  return requestIdValue
}

export function requestToggleProvider(enabled: boolean): string {
  const requestIdValue = requestId('requestToggleProvider')
  postMessage({ type: 'requestToggleProvider', requestId: requestIdValue, enabled })
  return requestIdValue
}

export function requestToggleModel(modelId: string, enabled: boolean): string {
  const requestIdValue = requestId('requestToggleModel')
  postMessage({ type: 'requestToggleModel', requestId: requestIdValue, modelId, enabled })
  return requestIdValue
}

export function requestSaveApiKey(key: string): string {
  const requestIdValue = requestId('requestSaveApiKey')
  postMessage({ type: 'requestSaveApiKey', requestId: requestIdValue, key })
  return requestIdValue
}
