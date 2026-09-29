// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  analyzeWritingStyle,
  copyWritingSampleToClipboard,
  notifyWritingExamplesSettingsReady,
  onWritingExamplesEvent,
  requestAddWritingSample,
  requestDeleteAllWritingSamples,
  requestDeleteWritingSample,
  requestUpdateWritingSample,
  setWritingExamplesContextFilter,
} from './writingExamplesBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilWritingExamplesSettingsBridge: { postMessage } } }
})

describe('writingExamplesBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyWritingExamplesSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends setContextFilter as fire-and-forget with no requestId', () => {
    setWritingExamplesContextFilter('email_reply')
    expect(postMessage).toHaveBeenCalledWith({ type: 'setContextFilter', filter: 'email_reply' })
  })

  it('sends requestDeleteSample with a generated requestId and returns it', () => {
    const id = requestDeleteWritingSample('sample-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteSample', requestId: id, id: 'sample-1' })
  })

  it('sends requestUpdateSample with the sample id, content, context, recipient, and a generated requestId', () => {
    const id = requestUpdateWritingSample('sample-1', 'Updated content', 'document', '')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestUpdateSample',
      requestId: id,
      id: 'sample-1',
      content: 'Updated content',
      contextType: 'document',
      recipient: '',
    })
  })

  it('sends requestAddSample with the selected context and optional recipient', () => {
    const id = requestAddWritingSample('New content', 'document', 'jordan@example.com')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestAddSample',
      requestId: id,
      content: 'New content',
      contextType: 'document',
      recipient: 'jordan@example.com',
    })
  })

  it('sends requestDeleteAllSamples with the active filter and a generated requestId', () => {
    const id = requestDeleteAllWritingSamples('document')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteAllSamples', requestId: id, filter: 'document' })
  })

  it('sends analyzeStyle with the active filter and a generated requestId', () => {
    const id = analyzeWritingStyle('social_media')
    expect(postMessage).toHaveBeenCalledWith({ type: 'analyzeStyle', requestId: id, filter: 'social_media' })
  })

  it('sends copySampleToClipboard as fire-and-forget with the full content', () => {
    copyWritingSampleToClipboard('Hello there')
    expect(postMessage).toHaveBeenCalledWith({ type: 'copySampleToClipboard', content: 'Hello there' })
  })

  it('generates distinct requestIds across calls', () => {
    const first = requestDeleteWritingSample('a')
    const second = requestDeleteWritingSample('b')
    expect(first).not.toEqual(second)
  })

  it('queues events dispatched before a handler subscribes, then flushes them in order', () => {
    window.basilWritingExamplesSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onWritingExamplesEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
  })

  it('stops delivering to a handler after it unsubscribes', () => {
    const handler = vi.fn()
    const unsubscribe = onWritingExamplesEvent(handler)
    unsubscribe()
    window.basilWritingExamplesSettings!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(handler).not.toHaveBeenCalled()
  })
})
