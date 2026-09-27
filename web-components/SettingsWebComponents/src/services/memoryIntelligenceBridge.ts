import type { MemoryIntelligenceNativeEvent, MemorySettingField } from '../types'

type OutgoingMemoryIntelligenceMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'updateSetting'; requestId: string; field: 'memoryAfterTaskEnabled' | 'memoryDailyEnabled'; value: boolean }
  | { type: 'updateSetting'; requestId: string; field: 'memoryDailyTimeLocal'; value: string }
  | { type: 'updateSetting'; requestId: string; field: 'memoryProcessingModel'; value: string | null }
  | { type: 'runIntelligenceNow'; requestId: string }
  | { type: 'declineProposal'; requestId: string; id: string }
  | { type: 'openMemoryFile'; fileName: string }
  | { type: 'openMemoryProposal'; id: string }

declare global {
  interface Window {
    basilMemoryIntelligenceSettings?: {
      onEvent: (event: MemoryIntelligenceNativeEvent) => void
    }
  }
}

type EventHandler = (event: MemoryIntelligenceNativeEvent) => void

let queuedEvents: MemoryIntelligenceNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: MemoryIntelligenceNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilMemoryIntelligenceSettings = { onEvent: dispatch }

export function onMemoryIntelligenceEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMemoryIntelligenceMessage) {
  window.webkit?.messageHandlers?.basilMemoryIntelligenceSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyMemoryIntelligenceSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function updateMemorySetting(field: MemorySettingField, value: boolean | string | null): string {
  const id = requestId('updateMemorySetting')
  if (field === 'memoryAfterTaskEnabled' || field === 'memoryDailyEnabled') {
    postMessage({ type: 'updateSetting', requestId: id, field, value: value as boolean })
  } else if (field === 'memoryDailyTimeLocal') {
    postMessage({ type: 'updateSetting', requestId: id, field, value: value as string })
  } else {
    postMessage({ type: 'updateSetting', requestId: id, field, value: value as string | null })
  }
  return id
}

export function runMemoryIntelligenceNow(): string {
  const id = requestId('runIntelligenceNow')
  postMessage({ type: 'runIntelligenceNow', requestId: id })
  return id
}

export function declineMemoryProposal(proposalId: string): string {
  const id = requestId('declineProposal')
  postMessage({ type: 'declineProposal', requestId: id, id: proposalId })
  return id
}

export function openMemoryFile(fileName: string) {
  postMessage({ type: 'openMemoryFile', fileName })
}

export function openMemoryProposal(proposalId: string) {
  postMessage({ type: 'openMemoryProposal', id: proposalId })
}
