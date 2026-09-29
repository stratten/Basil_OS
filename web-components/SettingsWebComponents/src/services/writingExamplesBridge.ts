import type { WritingExamplesContextFilter, WritingExamplesNativeEvent } from '../types'

type OutgoingWritingExamplesMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'setContextFilter'; filter: WritingExamplesContextFilter }
  | { type: 'requestDeleteSample'; requestId: string; id: string }
  | { type: 'requestUpdateSample'; requestId: string; id: string; content: string; contextType: string; recipient: string }
  | { type: 'requestAddSample'; requestId: string; content: string; contextType: WritingExamplesContextFilter; recipient?: string }
  | { type: 'requestDeleteAllSamples'; requestId: string; filter: WritingExamplesContextFilter }
  | { type: 'analyzeStyle'; requestId: string; filter: WritingExamplesContextFilter }
  | { type: 'copySampleToClipboard'; content: string }

declare global {
  interface Window {
    basilWritingExamplesSettings?: {
      onEvent: (event: WritingExamplesNativeEvent) => void
    }
  }
}

type EventHandler = (event: WritingExamplesNativeEvent) => void

let queuedEvents: WritingExamplesNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: WritingExamplesNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilWritingExamplesSettings = { onEvent: dispatch }

export function onWritingExamplesEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingWritingExamplesMessage) {
  window.webkit?.messageHandlers?.basilWritingExamplesSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyWritingExamplesSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function setWritingExamplesContextFilter(filter: WritingExamplesContextFilter) {
  postMessage({ type: 'setContextFilter', filter })
}

export function requestDeleteWritingSample(id: string): string {
  const requestIdValue = requestId('requestDeleteSample')
  postMessage({ type: 'requestDeleteSample', requestId: requestIdValue, id })
  return requestIdValue
}

export function requestUpdateWritingSample(id: string, content: string, contextType: string, recipient: string): string {
  const requestIdValue = requestId('requestUpdateSample')
  postMessage({ type: 'requestUpdateSample', requestId: requestIdValue, id, content, contextType, recipient })
  return requestIdValue
}

export function requestAddWritingSample(content: string, contextType: WritingExamplesContextFilter, recipient?: string): string {
  const requestIdValue = requestId('requestAddSample')
  postMessage({
    type: 'requestAddSample',
    requestId: requestIdValue,
    content,
    contextType,
    ...(recipient ? { recipient } : {}),
  })
  return requestIdValue
}

export function requestDeleteAllWritingSamples(filter: WritingExamplesContextFilter): string {
  const requestIdValue = requestId('requestDeleteAllSamples')
  postMessage({ type: 'requestDeleteAllSamples', requestId: requestIdValue, filter })
  return requestIdValue
}

export function analyzeWritingStyle(filter: WritingExamplesContextFilter): string {
  const requestIdValue = requestId('analyzeStyle')
  postMessage({ type: 'analyzeStyle', requestId: requestIdValue, filter })
  return requestIdValue
}

export function copyWritingSampleToClipboard(content: string) {
  postMessage({ type: 'copySampleToClipboard', content })
}
