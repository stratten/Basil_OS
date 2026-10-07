import { postToSwiftHandler } from '@shared/swiftBridge'
import type { MacContactsSettingsNativeEvent } from '../types'

type OutgoingMacContactsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'updateEnabled'; requestId: string; enabled: boolean }

declare global {
  interface Window {
    basilMacContactsSettings?: {
      onEvent: (event: MacContactsSettingsNativeEvent) => void
    }
  }
}

type EventHandler = (event: MacContactsSettingsNativeEvent) => void

let queuedEvents: MacContactsSettingsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: MacContactsSettingsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilMacContactsSettings = { onEvent: dispatch }

function postMessage(message: OutgoingMacContactsMessage) {
  postToSwiftHandler('basilMacContactsSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function onMacContactsSettingsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

export function notifyMacContactsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function updateMacContactsEnabled(enabled: boolean): string {
  const id = requestId('updateEnabled')
  postMessage({ type: 'updateEnabled', requestId: id, enabled })
  return id
}
