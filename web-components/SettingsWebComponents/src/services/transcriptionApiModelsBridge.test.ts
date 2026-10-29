// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyTranscriptionApiModelsReady,
  onTranscriptionApiModelsEvent,
  requestSaveApiKey,
  requestToggleMaster,
  requestToggleModel,
  requestToggleProvider,
} from './transcriptionApiModelsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionApiModelsBridge: { postMessage } } }
})

describe('transcriptionApiModelsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyTranscriptionApiModelsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestToggleMaster with a generated requestId and the desired enabled value', () => {
    const id = requestToggleMaster(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleMaster', requestId: id, enabled: true })
  })

  it('sends requestToggleProvider with a generated requestId and the desired enabled value', () => {
    const id = requestToggleProvider(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestToggleProvider', requestId: id, enabled: false })
  })

  it('sends requestToggleModel with the model id, requestId, and desired enabled value', () => {
    const id = requestToggleModel('openai-whisper-1', true)
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestToggleModel', requestId: id, modelId: 'openai-whisper-1', enabled: true,
    })
  })

  it('sends requestSaveApiKey with the raw key and a generated requestId', () => {
    const id = requestSaveApiKey('sk-test-key')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSaveApiKey', requestId: id, key: 'sk-test-key' })
  })

  it('generates distinct requestIds across calls', () => {
    const first = requestToggleModel('openai-whisper-1', true)
    const second = requestToggleModel('openai-whisper-1', false)
    expect(first).not.toEqual(second)
  })

  it('queues events dispatched before a handler subscribes, then flushes them in order', () => {
    window.basilTranscriptionApiModels!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onTranscriptionApiModelsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
  })

  it('stops delivering to a handler after it unsubscribes', () => {
    const handler = vi.fn()
    const unsubscribe = onTranscriptionApiModelsEvent(handler)
    unsubscribe()
    window.basilTranscriptionApiModels!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(handler).not.toHaveBeenCalled()
  })
})
