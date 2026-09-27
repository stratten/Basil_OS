import type { TranscriptionHistoryNativeEvent, TranscriptionHistoryTimeFrameId } from '../types'

type OutgoingTranscriptionHistoryMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestSetTimeFrame'; requestId: string; timeFrameId: TranscriptionHistoryTimeFrameId }
  | { type: 'requestSetSearchText'; requestId: string; text: string }
  | { type: 'requestPlayAudio'; requestId: string; transcriptionId: string }
  | { type: 'requestStopAudio'; requestId: string }
  | { type: 'requestRetranscribe'; requestId: string; transcriptionId: string; modelId?: string }
  | { type: 'requestDeleteTranscription'; requestId: string; transcriptionId: string }

declare global {
  interface Window {
    basilTranscriptionHistory?: {
      onEvent: (event: TranscriptionHistoryNativeEvent) => void
    }
  }
}

type EventHandler = (event: TranscriptionHistoryNativeEvent) => void

let queuedEvents: TranscriptionHistoryNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: TranscriptionHistoryNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilTranscriptionHistory = { onEvent: dispatch }

export function onTranscriptionHistoryEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingTranscriptionHistoryMessage) {
  window.webkit?.messageHandlers?.basilTranscriptionHistoryBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyTranscriptionHistoryReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestSetTimeFrame(timeFrameId: TranscriptionHistoryTimeFrameId): string {
  const id = requestId('setTimeFrame')
  postMessage({ type: 'requestSetTimeFrame', requestId: id, timeFrameId })
  return id
}

export function requestSetSearchText(text: string): string {
  const id = requestId('setSearchText')
  postMessage({ type: 'requestSetSearchText', requestId: id, text })
  return id
}

export function requestPlayAudio(transcriptionId: string): string {
  const id = requestId('playAudio')
  postMessage({ type: 'requestPlayAudio', requestId: id, transcriptionId })
  return id
}

export function requestStopAudio(): string {
  const id = requestId('stopAudio')
  postMessage({ type: 'requestStopAudio', requestId: id })
  return id
}

export function requestRetranscribe(transcriptionId: string, modelId?: string): string {
  const id = requestId('retranscribe')
  postMessage({ type: 'requestRetranscribe', requestId: id, transcriptionId, modelId })
  return id
}

export function requestDeleteTranscription(transcriptionId: string): string {
  const id = requestId('deleteTranscription')
  postMessage({ type: 'requestDeleteTranscription', requestId: id, transcriptionId })
  return id
}
