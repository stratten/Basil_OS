// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyModelsSettingsReady,
  onModelsEvent,
  requestCancelDownload,
  requestDeleteModel,
  requestDownloadModel,
  requestUpdateVisionFallback,
} from './modelsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilModelsSettingsBridge: { postMessage } } }
})

describe('modelsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyModelsSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestDownloadModel with a generated requestId and returns it', () => {
    const id = requestDownloadModel('Qwen-a')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDownloadModel', requestId: id, modelId: 'Qwen-a' })
  })

  it('sends requestCancelDownload with a generated requestId and returns it', () => {
    const id = requestCancelDownload('Qwen-a')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCancelDownload', requestId: id, modelId: 'Qwen-a' })
  })

  it('sends requestDeleteModel with a generated requestId and returns it', () => {
    const id = requestDeleteModel('Qwen-a')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteModel', requestId: id, modelId: 'Qwen-a' })
  })

  it('sends requestUpdateVisionFallback with the desired enabled value and a generated requestId', () => {
    const id = requestUpdateVisionFallback(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateVisionFallback', requestId: id, enabled: true })
  })

  it('generates distinct requestIds across calls', () => {
    const first = requestDownloadModel('Qwen-a')
    const second = requestDownloadModel('Qwen-b')
    expect(first).not.toEqual(second)
  })

  it('queues events dispatched before a handler subscribes, then flushes them in order', () => {
    window.basilModelsSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onModelsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
  })

  it('stops delivering to a handler after it unsubscribes', () => {
    const handler = vi.fn()
    const unsubscribe = onModelsEvent(handler)
    unsubscribe()
    window.basilModelsSettings!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(handler).not.toHaveBeenCalled()
  })
})
