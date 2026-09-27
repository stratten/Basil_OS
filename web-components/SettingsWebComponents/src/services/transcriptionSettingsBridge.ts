import type {
  TranscriptionSettingsNativeEvent,
  TranscriptionTextReplacementFields,
} from '../types'

type OutgoingTranscriptionSettingsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSelectedModel'; requestId: string; modelId: string }
  | { type: 'requestUpdateUnloadDelay'; requestId: string; seconds: number }
  | { type: 'requestUpdateAutoPaste'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoCloseOnPaste'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateMeetingDetectionStartup'; requestId: string; enabled: boolean }
  | { type: 'requestUpdatePushToTalk'; requestId: string; enabled: boolean }
  | { type: 'requestUpdatePushToTalkThreshold'; requestId: string; thresholdMs: number }
  | { type: 'requestUpdateTextReplacements'; requestId: string; rules: TranscriptionTextReplacementFields[] }

declare global {
  interface Window {
    basilTranscriptionSettings?: {
      onEvent: (event: TranscriptionSettingsNativeEvent) => void
    }
  }
}

type EventHandler = (event: TranscriptionSettingsNativeEvent) => void

let queuedEvents: TranscriptionSettingsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: TranscriptionSettingsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilTranscriptionSettings = { onEvent: dispatch }

export function onTranscriptionSettingsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingTranscriptionSettingsMessage) {
  window.webkit?.messageHandlers?.basilTranscriptionSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyTranscriptionSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateSelectedModel(modelId: string): string {
  const id = requestId('updateSelectedModel')
  postMessage({ type: 'requestUpdateSelectedModel', requestId: id, modelId })
  return id
}

export function requestUpdateUnloadDelay(seconds: number): string {
  const id = requestId('updateUnloadDelay')
  postMessage({ type: 'requestUpdateUnloadDelay', requestId: id, seconds })
  return id
}

export function requestUpdateAutoPaste(enabled: boolean): string {
  const id = requestId('updateAutoPaste')
  postMessage({ type: 'requestUpdateAutoPaste', requestId: id, enabled })
  return id
}

export function requestUpdateAutoCloseOnPaste(enabled: boolean): string {
  const id = requestId('updateAutoCloseOnPaste')
  postMessage({ type: 'requestUpdateAutoCloseOnPaste', requestId: id, enabled })
  return id
}

export function requestUpdateMeetingDetectionStartup(enabled: boolean): string {
  const id = requestId('updateMeetingDetectionStartup')
  postMessage({ type: 'requestUpdateMeetingDetectionStartup', requestId: id, enabled })
  return id
}

export function requestUpdatePushToTalk(enabled: boolean): string {
  const id = requestId('updatePushToTalk')
  postMessage({ type: 'requestUpdatePushToTalk', requestId: id, enabled })
  return id
}

export function requestUpdatePushToTalkThreshold(thresholdMs: number): string {
  const id = requestId('updatePushToTalkThreshold')
  postMessage({ type: 'requestUpdatePushToTalkThreshold', requestId: id, thresholdMs })
  return id
}

export function requestUpdateTextReplacements(rules: TranscriptionTextReplacementFields[]): string {
  const id = requestId('updateTextReplacements')
  postMessage({ type: 'requestUpdateTextReplacements', requestId: id, rules })
  return id
}
