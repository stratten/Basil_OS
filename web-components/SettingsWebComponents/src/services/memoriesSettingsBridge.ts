import { postToSwiftHandler } from '@shared/swiftBridge'
import type { MemoriesNativeEvent, MemoriesSettingsFields } from '../types'

type OutgoingMemoriesMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSettings'; requestId: string; settings: MemoriesSettingsFields }
  | { type: 'requestCollectNow'; requestId: string }
  | { type: 'requestSummarizeNow'; requestId: string }
  | { type: 'requestRetryFailedSummaries'; requestId: string }
  | { type: 'requestCancelSummarize'; requestId: string }
  | { type: 'requestRefreshStats'; requestId: string }
  | { type: 'requestNarrativeProgress'; requestId: string }

declare global {
  interface Window {
    basilMemoriesSettings?: {
      onEvent: (event: MemoriesNativeEvent) => void
    }
  }
}

type EventHandler = (event: MemoriesNativeEvent) => void

let queuedEvents: MemoriesNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: MemoriesNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilMemoriesSettings = { onEvent: dispatch }

export function onMemoriesEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMemoriesMessage) {
  postToSwiftHandler('basilMemoriesSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyMemoriesSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateMemoriesSettings(settings: MemoriesSettingsFields): string {
  const id = requestId('updateMemoriesSettings')
  postMessage({ type: 'requestUpdateSettings', requestId: id, settings })
  return id
}

export function requestCollectNow(): string {
  const id = requestId('collectNow')
  postMessage({ type: 'requestCollectNow', requestId: id })
  return id
}

export function requestSummarizeNow(): string {
  const id = requestId('summarizeNow')
  postMessage({ type: 'requestSummarizeNow', requestId: id })
  return id
}

export function requestRetryFailedSummaries(): string {
  const id = requestId('retryFailedSummaries')
  postMessage({ type: 'requestRetryFailedSummaries', requestId: id })
  return id
}

export function requestCancelSummarize(): string {
  const id = requestId('cancelSummarize')
  postMessage({ type: 'requestCancelSummarize', requestId: id })
  return id
}

export function requestRefreshStats(): string {
  const id = requestId('refreshStats')
  postMessage({ type: 'requestRefreshStats', requestId: id })
  return id
}

export function requestNarrativeProgress(): string {
  const id = requestId('narrativeProgress')
  postMessage({ type: 'requestNarrativeProgress', requestId: id })
  return id
}
