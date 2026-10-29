import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  __resetTokenConnectBridgeForTests,
  notifyTokenConnectReady,
  onTokenConnectEvent,
  requestTokenConnect,
  requestTokenConnectCancel,
} from './tokenConnectBridge'

describe('tokenConnectBridge', () => {
  const postMessage = vi.fn()

  beforeEach(() => {
    __resetTokenConnectBridgeForTests()
    postMessage.mockReset()
    window.webkit = { messageHandlers: { basilTokenConnectBridge: { postMessage } } }
  })

  afterEach(() => {
    delete window.webkit
  })

  it('sends ready, connect, and cancel without inventing extra fields', () => {
    notifyTokenConnectReady()
    requestTokenConnect('r1', 'Hugging Face (infra)', 'hf_abc', 'Write access')
    requestTokenConnectCancel('r1')
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([
      { type: 'reactReady', protocolVersion: 1 },
      { type: 'requestConnect', requestId: 'r1', friendlyName: 'Hugging Face (infra)', bearerToken: 'hf_abc', description: 'Write access' },
      { type: 'requestCancel', requestId: 'r1' },
    ])
  })

  it('queues an init event until a listener is attached', () => {
    const handler = vi.fn()
    window.basilTokenConnect!.onEvent({
      type: 'init',
      request: {
        requestId: 'r1',
        serverUrl: 'https://huggingface.co/mcp',
        host: 'huggingface.co',
        friendlyName: 'Hugging Face',
        description: null,
        existingNames: [],
        alreadyConnectedAs: null,
      },
    })
    onTokenConnectEvent(handler)
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0][0].type).toBe('init')
  })
})
