// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyTranscriptionSettingsReady,
  onTranscriptionSettingsEvent,
  requestUpdateAutoCloseOnPaste,
  requestUpdateAutoPaste,
  requestUpdateMeetingDetectionStartup,
  requestUpdatePushToTalk,
  requestUpdatePushToTalkThreshold,
  requestUpdateSelectedModel,
  requestUpdateTextReplacements,
  requestUpdateUnloadDelay,
} from './transcriptionSettingsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionSettingsBridge: { postMessage } } }
})

describe('transcriptionSettingsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyTranscriptionSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestUpdateSelectedModel with the chosen model id', () => {
    const id = requestUpdateSelectedModel('whisper-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSelectedModel', requestId: id, modelId: 'whisper-1' })
  })

  it('sends requestUpdateUnloadDelay with the chosen seconds', () => {
    const id = requestUpdateUnloadDelay(300)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateUnloadDelay', requestId: id, seconds: 300 })
  })

  it('sends requestUpdateAutoPaste and requestUpdateAutoCloseOnPaste with the toggled value', () => {
    const pasteId = requestUpdateAutoPaste(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoPaste', requestId: pasteId, enabled: true })
    const closeId = requestUpdateAutoCloseOnPaste(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoCloseOnPaste', requestId: closeId, enabled: false })
  })

  it('sends requestUpdatePushToTalk and requestUpdatePushToTalkThreshold with their values', () => {
    const enableId = requestUpdatePushToTalk(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdatePushToTalk', requestId: enableId, enabled: true })
    const thresholdId = requestUpdatePushToTalkThreshold(1200)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdatePushToTalkThreshold', requestId: thresholdId, thresholdMs: 1200 })
  })

  it('sends requestUpdateMeetingDetectionStartup with the toggled value', () => {
    const id = requestUpdateMeetingDetectionStartup(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateMeetingDetectionStartup', requestId: id, enabled: true })
  })

  it('sends requestUpdateTextReplacements with the full rule list', () => {
    const rules = [{ source: 'slash', replacement: '/' }]
    const id = requestUpdateTextReplacements(rules)

    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestUpdateTextReplacements',
      requestId: id,
      rules,
    })
  })

  it('queues events until a handler subscribes, then delivers them in order', () => {
    window.basilTranscriptionSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onTranscriptionSettingsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilTranscriptionSettings!.onEvent({ type: 'loadError', message: 'after unsubscribe' })
    expect(received).toEqual(['boom'])
  })
})
