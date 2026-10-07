import { postToSwiftHandler } from '@shared/swiftBridge'
import type {
  ActivityCaptureNativeEvent,
  ActivityCaptureProcessingMode,
} from '../types'

type OutgoingActivityCaptureMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateEnabled'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateFrequencySeconds'; requestId: string; frequencySeconds: number }
  | { type: 'requestUpdateIdleThresholdSeconds'; requestId: string; idleThresholdSeconds: number }
  | { type: 'requestUpdatePostWakeGraceSeconds'; requestId: string; postWakeGraceSeconds: number }
  | { type: 'requestAddExcludedBundleId'; requestId: string; bundleId: string }
  | { type: 'requestRemoveExcludedBundleId'; requestId: string; bundleId: string }
  | { type: 'requestAvailableApps' }
  | { type: 'requestSearchApps'; requestId: string; query: string }
  | { type: 'requestUpdateProcessingModel'; requestId: string; processingModel: string }
  | { type: 'requestUpdateProcessingMode'; requestId: string; processingMode: ActivityCaptureProcessingMode }
  | { type: 'requestUpdateScheduledProcessingTime'; requestId: string; scheduledProcessingTime: string }
  | { type: 'requestUpdateProcessingMaxRecords'; requestId: string; processingMaxRecords: number }
  | { type: 'requestUpdateAutoCleanupEnabled'; requestId: string; autoCleanupEnabled: boolean }
  | { type: 'requestUpdateRetentionDays'; requestId: string; retentionDays: number }
  | { type: 'requestUpdateCleanupTime'; requestId: string; cleanupHour: number; cleanupMinute: number }
  | { type: 'requestUpdateMaxStorageMb'; requestId: string; maxStorageMb: number }
  | { type: 'requestTestCapture'; requestId: string }
  | { type: 'requestProcessBacklog'; requestId: string }
  | { type: 'requestCancelProcessing'; requestId: string }
  | { type: 'requestClearBacklog'; requestId: string }
  | { type: 'requestClearAllCaptures'; requestId: string }
  | { type: 'requestStatus' }
  | { type: 'requestProcessingProgress'; requestId?: string }

declare global {
  interface Window {
    basilActivityCaptureSettings?: {
      onEvent: (event: ActivityCaptureNativeEvent) => void
    }
  }
}

type EventHandler = (event: ActivityCaptureNativeEvent) => void

let queuedEvents: ActivityCaptureNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ActivityCaptureNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilActivityCaptureSettings = { onEvent: dispatch }

export function onActivityCaptureEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingActivityCaptureMessage) {
  postToSwiftHandler('basilActivityCaptureSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyActivityCaptureSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateActivityCaptureEnabled(enabled: boolean): string {
  const id = requestId('updateEnabled')
  postMessage({ type: 'requestUpdateEnabled', requestId: id, enabled })
  return id
}

export function requestUpdateActivityCaptureFrequencySeconds(frequencySeconds: number): string {
  const id = requestId('updateFrequencySeconds')
  postMessage({ type: 'requestUpdateFrequencySeconds', requestId: id, frequencySeconds })
  return id
}

export function requestUpdateActivityCaptureIdleThresholdSeconds(idleThresholdSeconds: number): string {
  const id = requestId('updateIdleThresholdSeconds')
  postMessage({ type: 'requestUpdateIdleThresholdSeconds', requestId: id, idleThresholdSeconds })
  return id
}

export function requestUpdateActivityCapturePostWakeGraceSeconds(postWakeGraceSeconds: number): string {
  const id = requestId('updatePostWakeGraceSeconds')
  postMessage({ type: 'requestUpdatePostWakeGraceSeconds', requestId: id, postWakeGraceSeconds })
  return id
}

export function requestAddActivityCaptureExcludedBundleId(bundleId: string): string {
  const id = requestId('addExcludedBundleId')
  postMessage({ type: 'requestAddExcludedBundleId', requestId: id, bundleId })
  return id
}

export function requestRemoveActivityCaptureExcludedBundleId(bundleId: string): string {
  const id = requestId('removeExcludedBundleId')
  postMessage({ type: 'requestRemoveExcludedBundleId', requestId: id, bundleId })
  return id
}

export function requestActivityCaptureAvailableApps() {
  postMessage({ type: 'requestAvailableApps' })
}

export function requestActivityCaptureSearchApps(query: string): string {
  const id = requestId('searchApps')
  postMessage({ type: 'requestSearchApps', requestId: id, query })
  return id
}

export function requestUpdateActivityCaptureProcessingModel(processingModel: string): string {
  const id = requestId('updateProcessingModel')
  postMessage({ type: 'requestUpdateProcessingModel', requestId: id, processingModel })
  return id
}

export function requestUpdateActivityCaptureProcessingMode(processingMode: ActivityCaptureProcessingMode): string {
  const id = requestId('updateProcessingMode')
  postMessage({ type: 'requestUpdateProcessingMode', requestId: id, processingMode })
  return id
}

export function requestUpdateActivityCaptureScheduledProcessingTime(scheduledProcessingTime: string): string {
  const id = requestId('updateScheduledProcessingTime')
  postMessage({ type: 'requestUpdateScheduledProcessingTime', requestId: id, scheduledProcessingTime })
  return id
}

export function requestUpdateActivityCaptureProcessingMaxRecords(processingMaxRecords: number): string {
  const id = requestId('updateProcessingMaxRecords')
  postMessage({ type: 'requestUpdateProcessingMaxRecords', requestId: id, processingMaxRecords })
  return id
}

export function requestUpdateActivityCaptureAutoCleanupEnabled(autoCleanupEnabled: boolean): string {
  const id = requestId('updateAutoCleanupEnabled')
  postMessage({ type: 'requestUpdateAutoCleanupEnabled', requestId: id, autoCleanupEnabled })
  return id
}

export function requestUpdateActivityCaptureRetentionDays(retentionDays: number): string {
  const id = requestId('updateRetentionDays')
  postMessage({ type: 'requestUpdateRetentionDays', requestId: id, retentionDays })
  return id
}

export function requestUpdateActivityCaptureCleanupTime(cleanupHour: number, cleanupMinute: number): string {
  const id = requestId('updateCleanupTime')
  postMessage({ type: 'requestUpdateCleanupTime', requestId: id, cleanupHour, cleanupMinute })
  return id
}

export function requestUpdateActivityCaptureMaxStorageMb(maxStorageMb: number): string {
  const id = requestId('updateMaxStorageMb')
  postMessage({ type: 'requestUpdateMaxStorageMb', requestId: id, maxStorageMb })
  return id
}

export function requestActivityCaptureTestCapture(): string {
  const id = requestId('testCapture')
  postMessage({ type: 'requestTestCapture', requestId: id })
  return id
}

export function requestActivityCaptureProcessBacklog(): string {
  const id = requestId('processBacklog')
  postMessage({ type: 'requestProcessBacklog', requestId: id })
  return id
}

export function requestActivityCaptureCancelProcessing(): string {
  const id = requestId('cancelProcessing')
  postMessage({ type: 'requestCancelProcessing', requestId: id })
  return id
}

export function requestActivityCaptureClearBacklog(): string {
  const id = requestId('clearBacklog')
  postMessage({ type: 'requestClearBacklog', requestId: id })
  return id
}

export function requestActivityCaptureClearAllCaptures(): string {
  const id = requestId('clearAllCaptures')
  postMessage({ type: 'requestClearAllCaptures', requestId: id })
  return id
}

export function requestActivityCaptureStatus() {
  postMessage({ type: 'requestStatus' })
}

export function requestActivityCaptureProcessingProgress() {
  postMessage({ type: 'requestProcessingProgress' })
}
