import { postToSwiftHandler } from '@shared/swiftBridge'
import type { ReasoningApiModelsNativeEvent } from '../types'

type OutgoingMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestToggleMaster'; requestId: string; enabled: boolean }
  | { type: 'requestToggleProvider'; requestId: string; providerId: string; enabled: boolean }
  | { type: 'requestToggleProviderKeySource'; requestId: string; providerId: string; useOwnKey: boolean }
  | { type: 'requestToggleModel'; requestId: string; providerId: string; modelId: string; enabled: boolean }
  | { type: 'requestSaveApiKey'; requestId: string; providerId: string; key: string }
  | { type: 'requestRemoveApiKey'; requestId: string; providerId: string }

declare global {
  interface Window {
    basilReasoningApiModels?: {
      onEvent: (event: ReasoningApiModelsNativeEvent) => void
    }
  }
}

type EventHandler = (event: ReasoningApiModelsNativeEvent) => void

let queuedEvents: ReasoningApiModelsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ReasoningApiModelsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilReasoningApiModels = { onEvent: dispatch }

export function onReasoningApiModelsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMessage) {
  postToSwiftHandler('basilReasoningApiModelsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyReasoningApiModelsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestToggleMaster(enabled: boolean): string {
  const requestIdValue = requestId('requestToggleMaster')
  postMessage({ type: 'requestToggleMaster', requestId: requestIdValue, enabled })
  return requestIdValue
}

export function requestToggleProvider(providerId: string, enabled: boolean): string {
  const requestIdValue = requestId('requestToggleProvider')
  postMessage({ type: 'requestToggleProvider', requestId: requestIdValue, providerId, enabled })
  return requestIdValue
}

export function requestToggleProviderKeySource(providerId: string, useOwnKey: boolean): string {
  const requestIdValue = requestId('requestToggleProviderKeySource')
  postMessage({ type: 'requestToggleProviderKeySource', requestId: requestIdValue, providerId, useOwnKey })
  return requestIdValue
}

export function requestToggleModel(providerId: string, modelId: string, enabled: boolean): string {
  const requestIdValue = requestId('requestToggleModel')
  postMessage({ type: 'requestToggleModel', requestId: requestIdValue, providerId, modelId, enabled })
  return requestIdValue
}

export function requestSaveApiKey(providerId: string, key: string): string {
  const requestIdValue = requestId('requestSaveApiKey')
  postMessage({ type: 'requestSaveApiKey', requestId: requestIdValue, providerId, key })
  return requestIdValue
}

export function requestRemoveApiKey(providerId: string): string {
  const requestIdValue = requestId('requestRemoveApiKey')
  postMessage({ type: 'requestRemoveApiKey', requestId: requestIdValue, providerId })
  return requestIdValue
}
