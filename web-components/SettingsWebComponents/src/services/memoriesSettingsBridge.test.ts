// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyMemoriesSettingsReady,
  onMemoriesEvent,
  requestCancelSummarize,
  requestCollectNow,
  requestNarrativeProgress,
  requestRefreshStats,
  requestRetryFailedSummaries,
  requestSummarizeNow,
  requestUpdateMemoriesSettings,
} from './memoriesSettingsBridge'
import type { MemoriesSettingsFields } from '../types'

let postMessage: ReturnType<typeof vi.fn>

const FIXTURE_SETTINGS: MemoriesSettingsFields = {
  enabledSources: ['agent_task'],
  historyDays: 30,
  cardingEnabled: true,
  cardingIntervalMinutes: 15,
  limitPerSourcePerPass: 500,
  narrativeEnabled: true,
  narrativeModel: '',
  narrativeMode: 'scheduled',
  narrativeScheduledTime: '02:00',
  narrativeIntervalMinutes: 30,
  narrativeBatchSize: 50,
  narrativeMaxAttempts: 3,
  narrativeMaxRecords: 0,
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMemoriesSettingsBridge: { postMessage } } }
})

describe('memoriesSettingsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyMemoriesSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends the full settings object with a generated requestId', () => {
    const id = requestUpdateMemoriesSettings(FIXTURE_SETTINGS)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSettings', requestId: id, settings: FIXTURE_SETTINGS })
  })

  it('sends each action request with its own requestId', () => {
    const collectId = requestCollectNow()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCollectNow', requestId: collectId })
    const summarizeId = requestSummarizeNow()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSummarizeNow', requestId: summarizeId })
    const retryId = requestRetryFailedSummaries()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRetryFailedSummaries', requestId: retryId })
    const cancelId = requestCancelSummarize()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCancelSummarize', requestId: cancelId })
    const refreshId = requestRefreshStats()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRefreshStats', requestId: refreshId })
    const progressId = requestNarrativeProgress()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestNarrativeProgress', requestId: progressId })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilMemoriesSettings!.onEvent({ type: 'intentResult', requestId: 'r1', status: 'success' })
    const received: string[] = []
    const unsubscribe = onMemoriesEvent((event) => {
      if (event.type === 'intentResult') received.push(event.requestId)
    })
    expect(received).toEqual(['r1'])
    unsubscribe()
    window.basilMemoriesSettings!.onEvent({ type: 'intentResult', requestId: 'r2', status: 'success' })
    expect(received).toEqual(['r1'])
  })
})
