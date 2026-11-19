// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyPermissionsApplicationReady,
  onPermissionsApplicationEvent,
  openSystemSettings,
  requestPermission,
  requestPermissionStatus,
} from './permissionsApplicationBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilPermissionsApplicationBridge: { postMessage } } }
})

describe('permissionsApplicationBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyPermissionsApplicationReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestPermissionStatus with a generated requestId', () => {
    const id = requestPermissionStatus()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestPermissionStatus', requestId: id })
  })

  it('sends requestPermission with the target kind', () => {
    const id = requestPermission('microphone')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestPermission', requestId: id, kind: 'microphone' })
  })

  it('sends openSystemSettings with the target kind', () => {
    const id = openSystemSettings('screen_recording')
    expect(postMessage).toHaveBeenCalledWith({ type: 'openSystemSettings', requestId: id, kind: 'screen_recording' })
  })

  it('queues events until a handler subscribes, then delivers them in order', () => {
    window.basilPermissionsApplication!.onEvent({
      type: 'snapshot',
      permissions: {
        microphone: 'granted',
        accessibility: 'denied',
        inputMonitoring: 'unknown',
        screenRecording: 'not_determined',
        appleEvents: 'granted',
      },
    })
    const received: string[] = []
    const unsubscribe = onPermissionsApplicationEvent((event) => {
      if (event.type === 'snapshot') received.push(event.permissions.microphone)
    })
    expect(received).toEqual(['granted'])
    unsubscribe()
  })
})
