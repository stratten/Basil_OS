// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyMacContactsSettingsReady, onMacContactsSettingsEvent, updateMacContactsEnabled } from './macContactsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMacContactsSettingsBridge: { postMessage } } }
})

describe('macContactsBridge', () => {
  it('posts the ready handshake', () => {
    notifyMacContactsSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('posts a correlated enabled update and dispatches a queued snapshot', () => {
    const requestId = updateMacContactsEnabled(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'updateEnabled', requestId, enabled: true })

    const event = {
      type: 'init' as const,
      protocolVersion: 1 as const,
      fields: { available: true, preferenceEnabled: false, authorizationStatus: 'not_determined', canLookup: false, detail: null },
    }
    window.basilMacContactsSettings!.onEvent(event)
    const handler = vi.fn()
    const unsubscribe = onMacContactsSettingsEvent(handler)
    expect(handler.mock.calls[0]?.[0]).toEqual(event)

    window.basilMacContactsSettings!.onEvent({ type: 'snapshot', fields: { ...event.fields, preferenceEnabled: true, authorizationStatus: 'authorized', canLookup: true } })
    expect(handler).toHaveBeenCalledTimes(2)
    unsubscribe()
  })
})
