// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyMeetingAutomationSettingsReady,
  onMeetingAutomationEvent,
  requestUpdateAutoAnalyzeCustomInstructions,
  requestUpdateAutoAnalyzeMode,
  requestUpdateAutoAnalyzeOnComplete,
  requestUpdateAutoAnalyzeTiming,
  requestUpdateAutoRetranscribeDuringRecording,
  requestUpdateAutoRetranscribeOnStop,
  requestUpdateRetranscribeWindowMinutes,
} from './meetingAutomationBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMeetingAutomationSettingsBridge: { postMessage } } }
})

describe('meetingAutomationBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyMeetingAutomationSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends boolean toggle requests', () => {
    const stopId = requestUpdateAutoRetranscribeOnStop(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoRetranscribeOnStop', requestId: stopId, enabled: true })
    const duringId = requestUpdateAutoRetranscribeDuringRecording(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoRetranscribeDuringRecording', requestId: duringId, enabled: false })
    const analyzeId = requestUpdateAutoAnalyzeOnComplete(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoAnalyzeOnComplete', requestId: analyzeId, enabled: true })
  })

  it('sends the numeric interval update', () => {
    const id = requestUpdateRetranscribeWindowMinutes(15)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateRetranscribeWindowMinutes', requestId: id, minutes: 15 })
  })

  it('sends a mode toggle with its on/off state', () => {
    const id = requestUpdateAutoAnalyzeMode('summary', true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoAnalyzeMode', requestId: id, mode: 'summary', isOn: true })
  })

  it('sends the custom instructions text', () => {
    const id = requestUpdateAutoAnalyzeCustomInstructions('Focus on blockers.')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoAnalyzeCustomInstructions', requestId: id, text: 'Focus on blockers.' })
  })

  it('sends the analysis timing with a restricted value', () => {
    const id = requestUpdateAutoAnalyzeTiming('before')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoAnalyzeTiming', requestId: id, timing: 'before' })
  })

  it('queues events until a live handler subscribes, then flushes them in order', () => {
    window.basilMeetingAutomationSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onMeetingAutomationEvent((event) => received.push(event.type))
    expect(received).toEqual(['loadError'])
    window.basilMeetingAutomationSettings!.onEvent({ type: 'intentResult', requestId: 'x', status: 'success' })
    expect(received).toEqual(['loadError', 'intentResult'])
    unsubscribe()
  })
})
