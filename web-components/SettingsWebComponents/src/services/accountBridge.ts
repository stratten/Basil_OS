import { postToSwiftHandler } from '@shared/swiftBridge'
import type { AccountNativeEvent, ApiKeyPreference } from '../types'

type OutgoingAccountMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestLogin'; requestId: string; email: string; password: string }
  | { type: 'requestSignup'; requestId: string; email: string; password: string; confirmPassword: string }
  | { type: 'requestGoogleSignIn'; requestId: string }
  | { type: 'requestSignOut'; requestId: string }
  | { type: 'requestSetApiKeyPreference'; requestId: string; preference: ApiKeyPreference }
  | { type: 'requestPaymentSetup'; requestId: string }
  | { type: 'requestRefreshPaymentAndUsage'; requestId: string }
  | { type: 'requestDeleteAccount'; requestId: string }

declare global {
  interface Window {
    basilAccountSettings?: {
      onEvent: (event: AccountNativeEvent) => void
    }
  }
}

type EventHandler = (event: AccountNativeEvent) => void

let queuedEvents: AccountNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: AccountNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilAccountSettings = { onEvent: dispatch }

export function onAccountEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingAccountMessage) {
  postToSwiftHandler('basilAccountSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyAccountSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestLogin(email: string, password: string): string {
  const id = requestId('login')
  postMessage({ type: 'requestLogin', requestId: id, email, password })
  return id
}

export function requestSignup(email: string, password: string, confirmPassword: string): string {
  const id = requestId('signup')
  postMessage({ type: 'requestSignup', requestId: id, email, password, confirmPassword })
  return id
}

export function requestGoogleSignIn(): string {
  const id = requestId('googleSignIn')
  postMessage({ type: 'requestGoogleSignIn', requestId: id })
  return id
}

export function requestSignOut(): string {
  const id = requestId('signOut')
  postMessage({ type: 'requestSignOut', requestId: id })
  return id
}

export function requestSetApiKeyPreference(preference: ApiKeyPreference): string {
  const id = requestId('setApiKeyPreference')
  postMessage({ type: 'requestSetApiKeyPreference', requestId: id, preference })
  return id
}

export function requestPaymentSetup(): string {
  const id = requestId('paymentSetup')
  postMessage({ type: 'requestPaymentSetup', requestId: id })
  return id
}

export function requestRefreshPaymentAndUsage(): string {
  const id = requestId('refreshPaymentAndUsage')
  postMessage({ type: 'requestRefreshPaymentAndUsage', requestId: id })
  return id
}

export function requestDeleteAccount(): string {
  const id = requestId('deleteAccount')
  postMessage({ type: 'requestDeleteAccount', requestId: id })
  return id
}
