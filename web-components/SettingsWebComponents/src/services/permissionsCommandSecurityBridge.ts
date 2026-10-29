import { postToSwiftHandler } from '@shared/swiftBridge'
import type { ApprovalSettingsPatch, PermissionsCommandSecurityNativeEvent } from '../types'

type OutgoingPermissionsCommandSecurityMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateApprovalSetting'; requestId: string; patch: ApprovalSettingsPatch }
  | { type: 'requestAddWhitelistPattern'; requestId: string; pattern: string; patternType: string; description: string }
  | { type: 'requestUpdateWhitelistPattern'; requestId: string; id: string; pattern: string; patternType: string; description: string }
  | { type: 'requestDeleteWhitelistPattern'; requestId: string; id: string }

declare global {
  interface Window {
    basilPermissionsCommandSecurity?: {
      onEvent: (event: PermissionsCommandSecurityNativeEvent) => void
    }
  }
}

type EventHandler = (event: PermissionsCommandSecurityNativeEvent) => void

let queuedEvents: PermissionsCommandSecurityNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: PermissionsCommandSecurityNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilPermissionsCommandSecurity = { onEvent: dispatch }

export function onPermissionsCommandSecurityEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingPermissionsCommandSecurityMessage) {
  postToSwiftHandler('basilPermissionsCommandSecurityBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyPermissionsCommandSecurityReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateApprovalSetting(patch: ApprovalSettingsPatch): string {
  const id = requestId('updateApprovalSetting')
  postMessage({ type: 'requestUpdateApprovalSetting', requestId: id, patch })
  return id
}

export function requestAddWhitelistPattern(pattern: string, patternType: string, description: string): string {
  const id = requestId('addWhitelistPattern')
  postMessage({ type: 'requestAddWhitelistPattern', requestId: id, pattern, patternType, description })
  return id
}

export function requestUpdateWhitelistPattern(id: string, pattern: string, patternType: string, description: string): string {
  const requestIdValue = requestId('updateWhitelistPattern')
  postMessage({ type: 'requestUpdateWhitelistPattern', requestId: requestIdValue, id, pattern, patternType, description })
  return requestIdValue
}

export function requestDeleteWhitelistPattern(id: string): string {
  const requestIdValue = requestId('deleteWhitelistPattern')
  postMessage({ type: 'requestDeleteWhitelistPattern', requestId: requestIdValue, id })
  return requestIdValue
}
