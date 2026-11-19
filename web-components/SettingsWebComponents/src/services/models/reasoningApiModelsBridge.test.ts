// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyReasoningApiModelsReady,
  onReasoningApiModelsEvent,
  requestSaveApiKey,
  requestToggleMaster,
  requestToggleModel,
  requestToggleProvider,
  requestRemoveApiKey,
  requestToggleProviderKeySource,
} from './reasoningApiModelsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilReasoningApiModelsBridge: { postMessage } } }
})

describe('reasoningApiModelsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyReasoningApiModelsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestToggleProvider with providerId', () => {
    const id = requestToggleProvider('anthropic', true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleProvider', requestId: id, providerId: 'anthropic', enabled: true })
  })

  it('sends requestRemoveApiKey with the provider id', () => {
    const id = requestRemoveApiKey('gemini')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRemoveApiKey', requestId: id, providerId: 'gemini' })
  })

  it('sends requestToggleProviderKeySource with useOwnKey false', () => {
    const id = requestToggleProviderKeySource('openai', false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleProviderKeySource', requestId: id, providerId: 'openai', useOwnKey: false })
  })

  it('sends requestToggleModel with providerId and modelId', () => {
    const id = requestToggleModel('gemini', 'gemini-2.5-pro', true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleModel', requestId: id, providerId: 'gemini', modelId: 'gemini-2.5-pro', enabled: true })
  })

  it('sends requestSaveApiKey with providerId and raw key', () => {
    const id = requestSaveApiKey('openai', 'sk-test-key')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSaveApiKey', requestId: id, providerId: 'openai', key: 'sk-test-key' })
  })

  it('sends requestToggleMaster', () => {
    const id = requestToggleMaster(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleMaster', requestId: id, enabled: true })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilReasoningApiModels!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onReasoningApiModelsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilReasoningApiModels!.onEvent({ type: 'loadError', message: 'after' })
    expect(received).toEqual(['boom'])
  })
})
