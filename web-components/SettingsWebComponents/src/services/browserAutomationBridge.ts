import type {
  BrowserAutomationNativeEvent,
  BrowserAutomationSessionMode,
  BrowserForegroundControlPolicy,
  BrowserPreferredUserBrowser,
  BrowserSensitiveFillPolicy,
} from '../types'

type OutgoingBrowserAutomationMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestUpdateSensitiveFillPolicy'; requestId: string; policy: BrowserSensitiveFillPolicy }
  | { type: 'requestUpdateForegroundControlPolicy'; requestId: string; policy: BrowserForegroundControlPolicy }
  | { type: 'requestUpdateDefaultSessionMode'; requestId: string; sessionMode: BrowserAutomationSessionMode }
  | { type: 'requestUpdatePreferredUserBrowser'; requestId: string; browser: BrowserPreferredUserBrowser }
  | { type: 'requestUpdateShowActionHighlights'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateRecordBrowserActionTrace'; requestId: string; enabled: boolean }
  | { type: 'requestUpdateAllowVisualFallback'; requestId: string; enabled: boolean }
  | { type: 'requestRemoveRememberedDomain'; requestId: string; domain: string }
  | { type: 'requestClearAutomationBrowserProfile'; requestId: string }

declare global {
  interface Window {
    basilBrowserAutomationSettings?: {
      onEvent: (event: BrowserAutomationNativeEvent) => void
    }
  }
}

type EventHandler = (event: BrowserAutomationNativeEvent) => void

let queuedEvents: BrowserAutomationNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: BrowserAutomationNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilBrowserAutomationSettings = { onEvent: dispatch }

export function onBrowserAutomationEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingBrowserAutomationMessage) {
  window.webkit?.messageHandlers?.basilBrowserAutomationSettingsBridge?.postMessage(message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyBrowserAutomationSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestUpdateSensitiveFillPolicy(policy: BrowserSensitiveFillPolicy): string {
  const id = requestId('updateSensitiveFillPolicy')
  postMessage({ type: 'requestUpdateSensitiveFillPolicy', requestId: id, policy })
  return id
}

export function requestUpdateForegroundControlPolicy(policy: BrowserForegroundControlPolicy): string {
  const id = requestId('updateForegroundControlPolicy')
  postMessage({ type: 'requestUpdateForegroundControlPolicy', requestId: id, policy })
  return id
}

export function requestUpdateDefaultSessionMode(sessionMode: BrowserAutomationSessionMode): string {
  const id = requestId('updateDefaultSessionMode')
  postMessage({ type: 'requestUpdateDefaultSessionMode', requestId: id, sessionMode })
  return id
}

export function requestUpdatePreferredUserBrowser(browser: BrowserPreferredUserBrowser): string {
  const id = requestId('updatePreferredUserBrowser')
  postMessage({ type: 'requestUpdatePreferredUserBrowser', requestId: id, browser })
  return id
}

export function requestUpdateShowActionHighlights(enabled: boolean): string {
  const id = requestId('updateShowActionHighlights')
  postMessage({ type: 'requestUpdateShowActionHighlights', requestId: id, enabled })
  return id
}

export function requestUpdateRecordBrowserActionTrace(enabled: boolean): string {
  const id = requestId('updateRecordBrowserActionTrace')
  postMessage({ type: 'requestUpdateRecordBrowserActionTrace', requestId: id, enabled })
  return id
}

export function requestUpdateAllowVisualFallback(enabled: boolean): string {
  const id = requestId('updateAllowVisualFallback')
  postMessage({ type: 'requestUpdateAllowVisualFallback', requestId: id, enabled })
  return id
}

export function requestRemoveRememberedDomain(domain: string): string {
  const id = requestId('removeRememberedDomain')
  postMessage({ type: 'requestRemoveRememberedDomain', requestId: id, domain })
  return id
}

export function requestClearAutomationBrowserProfile(): string {
  const id = requestId('clearAutomationBrowserProfile')
  postMessage({ type: 'requestClearAutomationBrowserProfile', requestId: id })
  return id
}
