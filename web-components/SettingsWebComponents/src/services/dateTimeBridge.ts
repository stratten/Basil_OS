import { postToSwiftHandler } from '@shared/swiftBridge'
import type { DateDisplayStyle, DateTimeNativeEvent } from '../types'

type OutgoingDateTimeMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'updateDateDisplayStyle'; requestId: string; dateDisplayStyle: DateDisplayStyle }

declare global {
  interface Window {
    basilDateTimeSettings?: {
      onEvent: (event: DateTimeNativeEvent) => void
    }
  }
}

type EventHandler = (event: DateTimeNativeEvent) => void

let queuedEvents: DateTimeNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: DateTimeNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilDateTimeSettings = { onEvent: dispatch }

export function onDateTimeEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach((event) => handler(event))
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingDateTimeMessage) {
  postToSwiftHandler('basilDateTimeSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyDateTimeSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function updateDateDisplayStyle(style: DateDisplayStyle): string {
  const id = requestId('updateDateDisplayStyle')
  postMessage({ type: 'updateDateDisplayStyle', requestId: id, dateDisplayStyle: style })
  return id
}
