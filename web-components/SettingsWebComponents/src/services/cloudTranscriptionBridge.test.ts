// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyCloudTranscriptionReady,
  onCloudTranscriptionEvent,
  requestCheckCloudConnection,
  requestRemoveCloudKey,
  requestSaveCloudKey,
  requestUpdateCloudSettings,
} from './cloudTranscriptionBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilCloudTranscriptionBridge: { postMessage } } }
})

describe('cloudTranscriptionBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyCloudTranscriptionReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a settings patch with a generated requestId', () => {
    const id = requestUpdateCloudSettings({ enabled: true, acknowledge_disclosure: true })
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSettings', requestId: id, patch: { enabled: true, acknowledge_disclosure: true } })
  })

  it('sends the key, remove and check intents with the provider', () => {
    const save = requestSaveCloudKey('deepgram', 'dg-key-123456')
    const remove = requestRemoveCloudKey('assemblyai')
    const check = requestCheckCloudConnection('deepgram')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSaveKey', requestId: save, provider: 'deepgram', key: 'dg-key-123456' })
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRemoveKey', requestId: remove, provider: 'assemblyai' })
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCheck', requestId: check, provider: 'deepgram' })
  })

  it('generates distinct requestIds across calls', () => {
    expect(requestUpdateCloudSettings({ enabled: true })).not.toEqual(requestUpdateCloudSettings({ enabled: false }))
  })

  it('queues events dispatched before a handler subscribes, then flushes them in order', () => {
    window.basilCloudTranscription!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onCloudTranscriptionEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
  })

  it('stops delivering to a handler after it unsubscribes', () => {
    const handler = vi.fn()
    const unsubscribe = onCloudTranscriptionEvent(handler)
    unsubscribe()
    window.basilCloudTranscription!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(handler).not.toHaveBeenCalled()
  })
})
