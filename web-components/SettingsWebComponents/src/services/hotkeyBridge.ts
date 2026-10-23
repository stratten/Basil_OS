import { postToSwiftHandler } from '@shared/swiftBridge'
import type { HotkeyBinding, HotkeyNativeEvent } from '../types'

interface OutgoingIntentMessage {
  type: 'reactReady' | 'startCapture' | 'cancelCapture' | 'saveBinding' | 'toggleEnableMonitoring'
  protocolVersion?: 1
  id?: string
  requestId?: string
  binding?: HotkeyBinding
  enabled?: boolean
}

declare global {
  interface Window {
    basilHotkeySettings?: {
      onEvent: (event: HotkeyNativeEvent) => void
    }
  }
}

type EventHandler = (event: HotkeyNativeEvent) => void

let queuedEvents: HotkeyNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: HotkeyNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilHotkeySettings = {
  onEvent: dispatch,
}

/** Subscribe to native hotkey events, flushing anything queued before mount. */
export function onHotkeyEvent(handler: EventHandler): () => void {
  liveHandler = handler
  if (queuedEvents.length > 0) {
    const toFlush = queuedEvents
    queuedEvents = []
    for (const event of toFlush) {
      handler(event)
    }
  }
  return () => {
    if (liveHandler === handler) {
      liveHandler = null
    }
  }
}

function postMessage(message: OutgoingIntentMessage) {
  postToSwiftHandler('basilHotkeySettingsBridge', message)
}

export function notifyHotkeySettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function startHotkeyCapture(id: string) {
  postMessage({ type: 'startCapture', id })
}

export function cancelHotkeyCapture(id: string) {
  postMessage({ type: 'cancelCapture', id })
}

function generateRequestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function saveHotkeyBinding(id: string, binding: HotkeyBinding): string {
  const requestId = generateRequestId('saveBinding')
  postMessage({ type: 'saveBinding', requestId, id, binding })
  return requestId
}

export function toggleEnableMonitoringAtStartup(enabled: boolean): string {
  const requestId = generateRequestId('toggleEnableMonitoring')
  postMessage({ type: 'toggleEnableMonitoring', requestId, enabled })
  return requestId
}
