import { postToSwiftHandler } from '@shared/swiftBridge'
import type { CloudProviderId, CloudSettingsPatch } from '@shared/cloudTranscriptionTypes'

/** Native events for the cloud meeting transcription setup. `state` carries the backend's cloud transcription state untouched so the web side parses it. */
export type CloudTranscriptionNativeEvent =
  | { type: 'state'; state: unknown }
  | { type: 'loadError'; message: string }
  | { type: 'intentResult'; requestId: string; status: 'success' | 'error'; message?: string }

type OutgoingMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSettings'; requestId: string; patch: CloudSettingsPatch }
  | { type: 'requestSaveKey'; requestId: string; provider: CloudProviderId; key: string }
  | { type: 'requestRemoveKey'; requestId: string; provider: CloudProviderId }
  | { type: 'requestCheck'; requestId: string; provider: CloudProviderId }

declare global {
  interface Window {
    basilCloudTranscription?: {
      onEvent: (event: CloudTranscriptionNativeEvent) => void
    }
  }
}

type EventHandler = (event: CloudTranscriptionNativeEvent) => void

let queuedEvents: CloudTranscriptionNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: CloudTranscriptionNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilCloudTranscription = { onEvent: dispatch }

export function onCloudTranscriptionEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMessage) {
  postToSwiftHandler('basilCloudTranscriptionBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyCloudTranscriptionReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateCloudSettings(patch: CloudSettingsPatch): string {
  const requestIdValue = requestId('requestUpdateSettings')
  postMessage({ type: 'requestUpdateSettings', requestId: requestIdValue, patch })
  return requestIdValue
}

export function requestSaveCloudKey(provider: CloudProviderId, key: string): string {
  const requestIdValue = requestId('requestSaveKey')
  postMessage({ type: 'requestSaveKey', requestId: requestIdValue, provider, key })
  return requestIdValue
}

export function requestRemoveCloudKey(provider: CloudProviderId): string {
  const requestIdValue = requestId('requestRemoveKey')
  postMessage({ type: 'requestRemoveKey', requestId: requestIdValue, provider })
  return requestIdValue
}

export function requestCheckCloudConnection(provider: CloudProviderId): string {
  const requestIdValue = requestId('requestCheck')
  postMessage({ type: 'requestCheck', requestId: requestIdValue, provider })
  return requestIdValue
}
