import type { ProfileFields, ProfileNativeEvent } from '../types'

type OutgoingProfileMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'saveProfile'; requestId: string; profile: ProfileFields }
  | { type: 'requestClearProfile'; requestId: string }

declare global {
  interface Window {
    basilProfileSettings?: {
      onEvent: (event: ProfileNativeEvent) => void
    }
  }
}

type EventHandler = (event: ProfileNativeEvent) => void

let queuedEvents: ProfileNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ProfileNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilProfileSettings = { onEvent: dispatch }

export function onProfileEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingProfileMessage) {
  window.webkit?.messageHandlers?.basilProfileSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyProfileSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function saveProfile(profile: ProfileFields): string {
  const id = requestId('saveProfile')
  postMessage({ type: 'saveProfile', requestId: id, profile })
  return id
}

export function requestClearProfile(): string {
  const id = requestId('requestClearProfile')
  postMessage({ type: 'requestClearProfile', requestId: id })
  return id
}
