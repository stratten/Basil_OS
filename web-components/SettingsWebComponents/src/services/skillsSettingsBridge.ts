import type { SkillsNativeEvent } from '../types'

type OutgoingSkillsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSkillAfterTaskEnabled'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateSkillDailyEnabled'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateSkillDailyTimeLocal'; requestId: string; time: string }
  | { type: 'requestUpdateSkillProcessingModel'; requestId: string; modelId: string | null }
  | { type: 'requestUpdateSkillReconciliationMinInstances'; requestId: string; minInstances: number }
  | { type: 'requestDeclineCandidate'; requestId: string; id: string }
  | { type: 'requestDeleteSkill'; requestId: string; slug: string }
  | { type: 'requestRunIntelligenceNow'; requestId: string }
  | { type: 'openSkillCandidate'; id: string }
  | { type: 'openSkill'; slug: string }
  | { type: 'openReconciliationWorkspace' }
  | { type: 'focusReconciliationWorkspace' }

declare global {
  interface Window {
    basilSkillsSettings?: {
      onEvent: (event: SkillsNativeEvent) => void
    }
  }
}

type EventHandler = (event: SkillsNativeEvent) => void

let queuedEvents: SkillsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: SkillsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilSkillsSettings = { onEvent: dispatch }

export function onSkillsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingSkillsMessage) {
  window.webkit?.messageHandlers?.basilSkillsSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifySkillsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateSkillAfterTaskEnabled(enabled: boolean): string {
  const id = requestId('updateSkillAfterTaskEnabled')
  postMessage({ type: 'requestUpdateSkillAfterTaskEnabled', requestId: id, enabled })
  return id
}

export function requestUpdateSkillDailyEnabled(enabled: boolean): string {
  const id = requestId('updateSkillDailyEnabled')
  postMessage({ type: 'requestUpdateSkillDailyEnabled', requestId: id, enabled })
  return id
}

export function requestUpdateSkillDailyTimeLocal(time: string): string {
  const id = requestId('updateSkillDailyTimeLocal')
  postMessage({ type: 'requestUpdateSkillDailyTimeLocal', requestId: id, time })
  return id
}

export function requestUpdateSkillProcessingModel(modelId: string | null): string {
  const id = requestId('updateSkillProcessingModel')
  postMessage({ type: 'requestUpdateSkillProcessingModel', requestId: id, modelId })
  return id
}

export function requestUpdateSkillReconciliationMinInstances(minInstances: number): string {
  const id = requestId('updateSkillReconciliationMinInstances')
  postMessage({ type: 'requestUpdateSkillReconciliationMinInstances', requestId: id, minInstances })
  return id
}

export function requestDeclineCandidate(candidateId: string): string {
  const id = requestId('declineCandidate')
  postMessage({ type: 'requestDeclineCandidate', requestId: id, id: candidateId })
  return id
}

export function requestDeleteSkill(slug: string): string {
  const id = requestId('deleteSkill')
  postMessage({ type: 'requestDeleteSkill', requestId: id, slug })
  return id
}

export function requestRunIntelligenceNow(): string {
  const id = requestId('runIntelligenceNow')
  postMessage({ type: 'requestRunIntelligenceNow', requestId: id })
  return id
}

export function openSkillCandidate(candidateId: string) {
  postMessage({ type: 'openSkillCandidate', id: candidateId })
}

export function openSkill(slug: string) {
  postMessage({ type: 'openSkill', slug })
}

export function openReconciliationWorkspace() {
  postMessage({ type: 'openReconciliationWorkspace' })
}

export function focusReconciliationWorkspace() {
  postMessage({ type: 'focusReconciliationWorkspace' })
}
