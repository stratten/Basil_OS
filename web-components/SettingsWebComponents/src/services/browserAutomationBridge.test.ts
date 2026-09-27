// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyBrowserAutomationSettingsReady,
  onBrowserAutomationEvent,
  requestClearAutomationBrowserProfile,
  requestRemoveRememberedDomain,
  requestUpdateAllowVisualFallback,
  requestUpdateDefaultSessionMode,
  requestUpdateForegroundControlPolicy,
  requestUpdatePreferredUserBrowser,
  requestUpdateRecordBrowserActionTrace,
  requestUpdateSensitiveFillPolicy,
  requestUpdateShowActionHighlights,
} from './browserAutomationBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilBrowserAutomationSettingsBridge: { postMessage } } }
})

describe('browserAutomationBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyBrowserAutomationSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestUpdateSensitiveFillPolicy with the raw enum value', () => {
    const id = requestUpdateSensitiveFillPolicy('ask_every_time')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSensitiveFillPolicy', requestId: id, policy: 'ask_every_time' })
  })

  it('sends requestUpdateForegroundControlPolicy with the raw enum value', () => {
    const id = requestUpdateForegroundControlPolicy('allow_foreground_when_needed')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateForegroundControlPolicy', requestId: id, policy: 'allow_foreground_when_needed' })
  })

  it('sends requestUpdateDefaultSessionMode with the raw enum value', () => {
    const id = requestUpdateDefaultSessionMode('basil_automation_browser')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateDefaultSessionMode', requestId: id, sessionMode: 'basil_automation_browser' })
  })

  it('sends requestUpdatePreferredUserBrowser with the raw enum value', () => {
    const id = requestUpdatePreferredUserBrowser('safari')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdatePreferredUserBrowser', requestId: id, browser: 'safari' })
  })

  it('sends boolean toggle requests', () => {
    const highlightsId = requestUpdateShowActionHighlights(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateShowActionHighlights', requestId: highlightsId, enabled: true })
    const traceId = requestUpdateRecordBrowserActionTrace(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateRecordBrowserActionTrace', requestId: traceId, enabled: false })
    const fallbackId = requestUpdateAllowVisualFallback(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAllowVisualFallback', requestId: fallbackId, enabled: true })
  })

  it('sends requestRemoveRememberedDomain with the domain', () => {
    const id = requestRemoveRememberedDomain('example.com')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRemoveRememberedDomain', requestId: id, domain: 'example.com' })
  })

  it('sends requestClearAutomationBrowserProfile with no extra fields', () => {
    const id = requestClearAutomationBrowserProfile()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestClearAutomationBrowserProfile', requestId: id })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilBrowserAutomationSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onBrowserAutomationEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilBrowserAutomationSettings!.onEvent({ type: 'loadError', message: 'after' })
    expect(received).toEqual(['boom'])
  })
})
