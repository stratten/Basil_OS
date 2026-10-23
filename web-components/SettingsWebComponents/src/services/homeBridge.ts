import { postToSwiftHandler } from '@shared/swiftBridge'
import type { HomeNativeEvent, HomeQuickToggleField } from '../types'

type OutgoingHomeMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'updateToggle'; requestId: string; field: HomeQuickToggleField; value: boolean }
  | { type: 'updateSelectedModel'; requestId: string; modelId: string }
  | { type: 'updateSelectedTranscriptionModel'; requestId: string; modelId: string }
  | { type: 'openSetupAssistant'; requestId: string }
  | { type: 'openPowerUserGuide'; requestId: string }

declare global {
  interface Window {
    basilHomeSettings?: {
      onEvent: (event: HomeNativeEvent) => void
    }
  }
}

type EventHandler = (event: HomeNativeEvent) => void

let queuedEvents: HomeNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: HomeNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilHomeSettings = { onEvent: dispatch }

export function onHomeEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach((event) => handler(event))
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingHomeMessage) {
  postToSwiftHandler('basilHomeSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyHomeSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function updateHomeToggle(field: HomeQuickToggleField, value: boolean): string {
  const id = requestId('updateToggle')
  postMessage({ type: 'updateToggle', requestId: id, field, value })
  return id
}

export function updateHomeSelectedModel(modelId: string): string {
  const id = requestId('updateSelectedModel')
  postMessage({ type: 'updateSelectedModel', requestId: id, modelId })
  return id
}

export function updateHomeSelectedTranscriptionModel(modelId: string): string {
  const id = requestId('updateSelectedTranscriptionModel')
  postMessage({ type: 'updateSelectedTranscriptionModel', requestId: id, modelId })
  return id
}

export function openHomeSetupAssistant(): string {
  const id = requestId('openSetupAssistant')
  postMessage({ type: 'openSetupAssistant', requestId: id })
  return id
}

export function openHomePowerUserGuide(): string {
  const id = requestId('openPowerUserGuide')
  postMessage({ type: 'openPowerUserGuide', requestId: id })
  return id
}
