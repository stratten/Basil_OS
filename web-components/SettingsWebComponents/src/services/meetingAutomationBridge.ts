import type { MeetingAutomationNativeEvent } from '../types'

type OutgoingMeetingAutomationMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateLiveTranscriptionByDefault'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoRetranscribeOnStop'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoRetranscribeDuringRecording'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateRetranscribeWindowMinutes'; requestId: string; minutes: number }
  | { type: 'requestUpdateAutoAnalyzeOnComplete'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoAnalyzeMode'; requestId: string; mode: string; isOn: boolean }
  | { type: 'requestUpdateAutoAnalyzeCustomInstructions'; requestId: string; text: string }
  | { type: 'requestUpdateAutoAnalyzeTiming'; requestId: string; timing: 'after' | 'before' }

declare global {
  interface Window {
    basilMeetingAutomationSettings?: {
      onEvent: (event: MeetingAutomationNativeEvent) => void
    }
  }
}

type EventHandler = (event: MeetingAutomationNativeEvent) => void

let queuedEvents: MeetingAutomationNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: MeetingAutomationNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilMeetingAutomationSettings = { onEvent: dispatch }

export function onMeetingAutomationEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMeetingAutomationMessage) {
  window.webkit?.messageHandlers?.basilMeetingAutomationSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyMeetingAutomationSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateLiveTranscriptionByDefault(enabled: boolean): string {
  const id = requestId('updateLiveTranscriptionByDefault')
  postMessage({ type: 'requestUpdateLiveTranscriptionByDefault', requestId: id, enabled })
  return id
}

export function requestUpdateAutoRetranscribeOnStop(enabled: boolean): string {
  const id = requestId('updateAutoRetranscribeOnStop')
  postMessage({ type: 'requestUpdateAutoRetranscribeOnStop', requestId: id, enabled })
  return id
}

export function requestUpdateAutoRetranscribeDuringRecording(enabled: boolean): string {
  const id = requestId('updateAutoRetranscribeDuringRecording')
  postMessage({ type: 'requestUpdateAutoRetranscribeDuringRecording', requestId: id, enabled })
  return id
}

export function requestUpdateRetranscribeWindowMinutes(minutes: number): string {
  const id = requestId('updateRetranscribeWindowMinutes')
  postMessage({ type: 'requestUpdateRetranscribeWindowMinutes', requestId: id, minutes })
  return id
}

export function requestUpdateAutoAnalyzeOnComplete(enabled: boolean): string {
  const id = requestId('updateAutoAnalyzeOnComplete')
  postMessage({ type: 'requestUpdateAutoAnalyzeOnComplete', requestId: id, enabled })
  return id
}

export function requestUpdateAutoAnalyzeMode(mode: string, isOn: boolean): string {
  const id = requestId('updateAutoAnalyzeMode')
  postMessage({ type: 'requestUpdateAutoAnalyzeMode', requestId: id, mode, isOn })
  return id
}

export function requestUpdateAutoAnalyzeCustomInstructions(text: string): string {
  const id = requestId('updateAutoAnalyzeCustomInstructions')
  postMessage({ type: 'requestUpdateAutoAnalyzeCustomInstructions', requestId: id, text })
  return id
}

export function requestUpdateAutoAnalyzeTiming(timing: 'after' | 'before'): string {
  const id = requestId('updateAutoAnalyzeTiming')
  postMessage({ type: 'requestUpdateAutoAnalyzeTiming', requestId: id, timing })
  return id
}
