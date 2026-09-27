import type { ModelsNativeEvent } from '../types'

type OutgoingModelsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestDownloadModel'; requestId: string; modelId: string }
  | { type: 'requestCancelDownload'; requestId: string; modelId: string }
  | { type: 'requestDeleteModel'; requestId: string; modelId: string }
  | { type: 'requestUpdateVisionFallback'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateReasoningFallback'; requestId: string; enabled: boolean; modelId: string }

declare global {
  interface Window {
    basilModelsSettings?: {
      onEvent: (event: ModelsNativeEvent) => void
    }
  }
}

type EventHandler = (event: ModelsNativeEvent) => void

let queuedEvents: ModelsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ModelsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilModelsSettings = { onEvent: dispatch }

export function onModelsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingModelsMessage) {
  window.webkit?.messageHandlers?.basilModelsSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyModelsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestDownloadModel(modelId: string): string {
  const requestIdValue = requestId('requestDownloadModel')
  postMessage({ type: 'requestDownloadModel', requestId: requestIdValue, modelId })
  return requestIdValue
}

export function requestCancelDownload(modelId: string): string {
  const requestIdValue = requestId('requestCancelDownload')
  postMessage({ type: 'requestCancelDownload', requestId: requestIdValue, modelId })
  return requestIdValue
}

export function requestDeleteModel(modelId: string): string {
  const requestIdValue = requestId('requestDeleteModel')
  postMessage({ type: 'requestDeleteModel', requestId: requestIdValue, modelId })
  return requestIdValue
}

export function requestUpdateVisionFallback(enabled: boolean): string {
  const requestIdValue = requestId('requestUpdateVisionFallback')
  postMessage({ type: 'requestUpdateVisionFallback', requestId: requestIdValue, enabled })
  return requestIdValue
}

export function requestUpdateReasoningFallback(enabled: boolean, modelId: string): string {
  const requestIdValue = requestId('requestUpdateReasoningFallback')
  postMessage({ type: 'requestUpdateReasoningFallback', requestId: requestIdValue, enabled, modelId })
  return requestIdValue
}
