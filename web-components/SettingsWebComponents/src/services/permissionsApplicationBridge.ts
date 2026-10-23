import { postToSwiftHandler } from '@shared/swiftBridge'
import type { PermissionKind, PermissionsApplicationNativeEvent } from '../types'

type OutgoingPermissionsApplicationMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestPermissionStatus'; requestId: string }
  | { type: 'requestPermission'; requestId: string; kind: PermissionKind }
  | { type: 'openSystemSettings'; requestId: string; kind: PermissionKind }

declare global {
  interface Window {
    basilPermissionsApplication?: {
      onEvent: (event: PermissionsApplicationNativeEvent) => void
    }
  }
}

type EventHandler = (event: PermissionsApplicationNativeEvent) => void

let queuedEvents: PermissionsApplicationNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: PermissionsApplicationNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilPermissionsApplication = { onEvent: dispatch }

export function onPermissionsApplicationEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingPermissionsApplicationMessage) {
  postToSwiftHandler('basilPermissionsApplicationBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyPermissionsApplicationReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestPermissionStatus(): string {
  const id = requestId('permissionStatus')
  postMessage({ type: 'requestPermissionStatus', requestId: id })
  return id
}

export function requestPermission(kind: PermissionKind): string {
  const id = requestId('requestPermission')
  postMessage({ type: 'requestPermission', requestId: id, kind })
  return id
}

export function openSystemSettings(kind: PermissionKind): string {
  const id = requestId('openSystemSettings')
  postMessage({ type: 'openSystemSettings', requestId: id, kind })
  return id
}
