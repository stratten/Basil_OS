// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyAccountSettingsReady,
  onAccountEvent,
  requestDeleteAccount,
  requestGoogleSignIn,
  requestLogin,
  requestPaymentSetup,
  requestRefreshPaymentAndUsage,
  requestSetApiKeyPreference,
  requestSignOut,
  requestSignup,
} from './accountBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilAccountSettingsBridge: { postMessage } } }
})

describe('accountBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyAccountSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestLogin with the credentials', () => {
    const id = requestLogin('a@example.com', 'secret123')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestLogin', requestId: id, email: 'a@example.com', password: 'secret123' })
  })

  it('sends requestSignup with confirmPassword included', () => {
    const id = requestSignup('a@example.com', 'secret123', 'secret123')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSignup', requestId: id, email: 'a@example.com', password: 'secret123', confirmPassword: 'secret123' })
  })

  it('sends requestGoogleSignIn and requestSignOut with only a requestId', () => {
    const googleId = requestGoogleSignIn()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestGoogleSignIn', requestId: googleId })
    const signOutId = requestSignOut()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSignOut', requestId: signOutId })
  })

  it('sends requestSetApiKeyPreference with the chosen preference', () => {
    const id = requestSetApiKeyPreference('own_keys')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSetApiKeyPreference', requestId: id, preference: 'own_keys' })
  })

  it('sends requestPaymentSetup and requestRefreshPaymentAndUsage with only a requestId', () => {
    const setupId = requestPaymentSetup()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestPaymentSetup', requestId: setupId })
    const refreshId = requestRefreshPaymentAndUsage()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRefreshPaymentAndUsage', requestId: refreshId })
  })

  it('sends requestDeleteAccount with only a requestId', () => {
    const id = requestDeleteAccount()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteAccount', requestId: id })
  })

  it('queues events until a live handler subscribes, then flushes them in order', () => {
    window.basilAccountSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onAccountEvent((event) => received.push(event.type))
    expect(received).toEqual(['loadError'])
    window.basilAccountSettings!.onEvent({ type: 'intentResult', requestId: 'x', status: 'success' })
    expect(received).toEqual(['loadError', 'intentResult'])
    unsubscribe()
  })
})
