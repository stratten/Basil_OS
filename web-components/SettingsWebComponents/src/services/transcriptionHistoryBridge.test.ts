// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyTranscriptionHistoryReady,
  onTranscriptionHistoryEvent,
  requestDeleteTranscription,
  requestPlayAudio,
  requestRetranscribe,
  requestSetSearchText,
  requestSetTimeFrame,
  requestStopAudio,
} from './transcriptionHistoryBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionHistoryBridge: { postMessage } } }
})

describe('transcriptionHistoryBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyTranscriptionHistoryReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestSetTimeFrame with the chosen id', () => {
    const id = requestSetTimeFrame('week')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSetTimeFrame', requestId: id, timeFrameId: 'week' })
  })

  it('sends requestSetSearchText with the typed text', () => {
    const id = requestSetSearchText('meeting notes')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSetSearchText', requestId: id, text: 'meeting notes' })
  })

  it('sends requestPlayAudio and requestStopAudio', () => {
    const playId = requestPlayAudio('tx-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestPlayAudio', requestId: playId, transcriptionId: 'tx-1' })
    const stopId = requestStopAudio()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestStopAudio', requestId: stopId })
  })

  it('sends requestRetranscribe with an optional modelId', () => {
    const currentId = requestRetranscribe('tx-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRetranscribe', requestId: currentId, transcriptionId: 'tx-1', modelId: undefined })
    const specificId = requestRetranscribe('tx-1', 'whisper-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRetranscribe', requestId: specificId, transcriptionId: 'tx-1', modelId: 'whisper-1' })
  })

  it('sends requestDeleteTranscription with the target id', () => {
    const id = requestDeleteTranscription('tx-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteTranscription', requestId: id, transcriptionId: 'tx-1' })
  })

  it('queues events until a handler subscribes, then delivers them in order', () => {
    window.basilTranscriptionHistory!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onTranscriptionHistoryEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilTranscriptionHistory!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(received).toEqual(['boom'])
  })
})
