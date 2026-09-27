import type { MeetingDetectionNativeEvent } from '../types'

type OutgoingMeetingDetectionMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateEnabled'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateMode'; requestId: string; mode: 'prompt' | 'auto_start' }
  | { type: 'requestUpdatePollSeconds'; requestId: string; pollSeconds: number }
  | { type: 'requestUpdateCooldownMinutes'; requestId: string; cooldownMinutes: number }
  | { type: 'requestUpdateUseCalendarEnrichment'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateRequireCalendarMatch'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAutoEnd'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateInactivityTimeoutMinutes'; requestId: string; minutes: number }
  | { type: 'requestUpdateExcludedAppNames'; requestId: string; excludedAppNames: string[] }
  | { type: 'requestAddExcludedBundleId'; requestId: string; bundleId: string }
  | { type: 'requestRemoveExcludedBundleId'; requestId: string; bundleId: string }
  | { type: 'requestAvailableApps' }
  | { type: 'requestSearchApps'; requestId: string; query: string }

declare global {
  interface Window {
    basilMeetingDetectionSettings?: {
      onEvent: (event: MeetingDetectionNativeEvent) => void
    }
  }
}

type EventHandler = (event: MeetingDetectionNativeEvent) => void

let queuedEvents: MeetingDetectionNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: MeetingDetectionNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilMeetingDetectionSettings = { onEvent: dispatch }

export function onMeetingDetectionEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingMeetingDetectionMessage) {
  window.webkit?.messageHandlers?.basilMeetingDetectionSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyMeetingDetectionSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateMeetingDetectionEnabled(enabled: boolean): string {
  const id = requestId('updateEnabled')
  postMessage({ type: 'requestUpdateEnabled', requestId: id, enabled })
  return id
}

export function requestUpdateMeetingDetectionMode(mode: 'prompt' | 'auto_start'): string {
  const id = requestId('updateMode')
  postMessage({ type: 'requestUpdateMode', requestId: id, mode })
  return id
}

export function requestUpdateMeetingDetectionPollSeconds(pollSeconds: number): string {
  const id = requestId('updatePollSeconds')
  postMessage({ type: 'requestUpdatePollSeconds', requestId: id, pollSeconds })
  return id
}

export function requestUpdateMeetingDetectionCooldownMinutes(cooldownMinutes: number): string {
  const id = requestId('updateCooldownMinutes')
  postMessage({ type: 'requestUpdateCooldownMinutes', requestId: id, cooldownMinutes })
  return id
}

export function requestUpdateUseCalendarEnrichment(enabled: boolean): string {
  const id = requestId('updateUseCalendarEnrichment')
  postMessage({ type: 'requestUpdateUseCalendarEnrichment', requestId: id, enabled })
  return id
}

export function requestUpdateRequireCalendarMatch(enabled: boolean): string {
  const id = requestId('updateRequireCalendarMatch')
  postMessage({ type: 'requestUpdateRequireCalendarMatch', requestId: id, enabled })
  return id
}

export function requestUpdateMeetingDetectionAutoEnd(enabled: boolean): string {
  const id = requestId('updateAutoEnd')
  postMessage({ type: 'requestUpdateAutoEnd', requestId: id, enabled })
  return id
}

export function requestUpdateInactivityTimeoutMinutes(minutes: number): string {
  const id = requestId('updateInactivityTimeoutMinutes')
  postMessage({ type: 'requestUpdateInactivityTimeoutMinutes', requestId: id, minutes })
  return id
}

export function requestUpdateExcludedAppNames(excludedAppNames: string[]): string {
  const id = requestId('updateExcludedAppNames')
  postMessage({ type: 'requestUpdateExcludedAppNames', requestId: id, excludedAppNames })
  return id
}

export function requestAddExcludedBundleId(bundleId: string): string {
  const id = requestId('addExcludedBundleId')
  postMessage({ type: 'requestAddExcludedBundleId', requestId: id, bundleId })
  return id
}

export function requestRemoveExcludedBundleId(bundleId: string): string {
  const id = requestId('removeExcludedBundleId')
  postMessage({ type: 'requestRemoveExcludedBundleId', requestId: id, bundleId })
  return id
}

export function requestMeetingDetectionAvailableApps() {
  postMessage({ type: 'requestAvailableApps' })
}

export function requestMeetingDetectionSearchApps(query: string): string {
  const id = requestId('searchApps')
  postMessage({ type: 'requestSearchApps', requestId: id, query })
  return id
}
