// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  declineMemoryProposal,
  notifyMemoryIntelligenceSettingsReady,
  onMemoryIntelligenceEvent,
  openMemoryFile,
  openMemoryProposal,
  runMemoryIntelligenceNow,
  updateMemorySetting,
} from './memoryIntelligenceBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMemoryIntelligenceSettingsBridge: { postMessage } } }
})

describe('memoryIntelligenceBridge', () => {
  it('sends a ready request', () => {
    notifyMemoryIntelligenceSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a boolean setting update with a fresh request id', () => {
    const first = updateMemorySetting('memoryAfterTaskEnabled', true)
    const second = updateMemorySetting('memoryAfterTaskEnabled', true)
    expect(first).not.toBe(second)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'updateSetting',
      field: 'memoryAfterTaskEnabled',
      value: true,
    }))
  })

  it('sends the daily time as a string value', () => {
    updateMemorySetting('memoryDailyTimeLocal', '05:30')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'updateSetting',
      field: 'memoryDailyTimeLocal',
      value: '05:30',
    }))
  })

  it('sends a null evaluator model to clear the override', () => {
    updateMemorySetting('memoryProcessingModel', null)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'updateSetting',
      field: 'memoryProcessingModel',
      value: null,
    }))
  })

  it('sends run-now and decline requests with correlated request ids', () => {
    const runId = runMemoryIntelligenceNow()
    expect(postMessage).toHaveBeenCalledWith({ type: 'runIntelligenceNow', requestId: runId })
    const declineId = declineMemoryProposal('proposal-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'declineProposal', requestId: declineId, id: 'proposal-1' })
  })

  it('sends open requests without a request id', () => {
    openMemoryFile('notes.md')
    expect(postMessage).toHaveBeenCalledWith({ type: 'openMemoryFile', fileName: 'notes.md' })
    openMemoryProposal('proposal-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'openMemoryProposal', id: 'proposal-1' })
  })

  it('flushes queued native events in arrival order', () => {
    window.basilMemoryIntelligenceSettings!.onEvent({ type: 'loadError', message: 'offline' })
    const received: string[] = []
    const unsubscribe = onMemoryIntelligenceEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['offline'])
    unsubscribe()
  })
})
