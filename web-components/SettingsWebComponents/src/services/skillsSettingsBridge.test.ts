// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  focusReconciliationWorkspace,
  notifySkillsSettingsReady,
  onSkillsEvent,
  openReconciliationWorkspace,
  openSkill,
  openSkillCandidate,
  requestDeclineCandidate,
  requestDeleteSkill,
  requestRunIntelligenceNow,
  requestUpdateSkillAfterTaskEnabled,
  requestUpdateSkillDailyEnabled,
  requestUpdateSkillDailyTimeLocal,
  requestUpdateSkillProcessingModel,
  requestUpdateSkillReconciliationMinInstances,
} from './skillsSettingsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilSkillsSettingsBridge: { postMessage } } }
})

describe('skillsSettingsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifySkillsSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends the five settings-field update requests', () => {
    const afterTaskId = requestUpdateSkillAfterTaskEnabled(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillAfterTaskEnabled', requestId: afterTaskId, enabled: true })
    const dailyId = requestUpdateSkillDailyEnabled(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillDailyEnabled', requestId: dailyId, enabled: false })
    const timeId = requestUpdateSkillDailyTimeLocal('04:30')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillDailyTimeLocal', requestId: timeId, time: '04:30' })
    const modelId = requestUpdateSkillProcessingModel('local-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillProcessingModel', requestId: modelId, modelId: 'local-1' })
    const nullModelId = requestUpdateSkillProcessingModel(null)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillProcessingModel', requestId: nullModelId, modelId: null })
    const thresholdId = requestUpdateSkillReconciliationMinInstances(4)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSkillReconciliationMinInstances', requestId: thresholdId, minInstances: 4 })
  })

  it('sends decline/delete/run-now requests with a requestId', () => {
    const declineId = requestDeclineCandidate('cand-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeclineCandidate', requestId: declineId, id: 'cand-1' })
    const deleteId = requestDeleteSkill('weekly-report')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteSkill', requestId: deleteId, slug: 'weekly-report' })
    const runId = requestRunIntelligenceNow()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRunIntelligenceNow', requestId: runId })
  })

  it('sends fire-and-forget window-launch messages with no requestId', () => {
    openSkillCandidate('cand-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'openSkillCandidate', id: 'cand-1' })
    openSkill('weekly-report')
    expect(postMessage).toHaveBeenCalledWith({ type: 'openSkill', slug: 'weekly-report' })
    openReconciliationWorkspace()
    expect(postMessage).toHaveBeenCalledWith({ type: 'openReconciliationWorkspace' })
    focusReconciliationWorkspace()
    expect(postMessage).toHaveBeenCalledWith({ type: 'focusReconciliationWorkspace' })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilSkillsSettings!.onEvent({ type: 'intentResult', requestId: 'r1', status: 'success' })
    const received: string[] = []
    const unsubscribe = onSkillsEvent((event) => {
      if (event.type === 'intentResult') received.push(event.requestId)
    })
    expect(received).toEqual(['r1'])
    unsubscribe()
    window.basilSkillsSettings!.onEvent({ type: 'intentResult', requestId: 'r2', status: 'success' })
    expect(received).toEqual(['r1'])
  })
})
