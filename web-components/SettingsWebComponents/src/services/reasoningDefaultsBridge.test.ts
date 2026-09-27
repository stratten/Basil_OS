// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyReasoningDefaultsSettingsReady,
  onReasoningDefaultsEvent,
  requestUpdateAgentTaskAutoReopenOnCompletion,
  requestUpdateAgentTaskDefaultModality,
  requestUpdateAgentTaskPushToTalk,
  requestUpdateAgentTaskPushToTalkThreshold,
  requestUpdateAssistantSessionDefaultModality,
  requestUpdateAssistantSessionPushToTalk,
  requestUpdateAssistantSessionPushToTalkThreshold,
  requestUpdateAutoPasteAssistantOutput,
  requestUpdateCloseAssistantSessionOnInsert,
  requestUpdateSelectedModel,
  requestUpdateUseRegionSelection,
} from './reasoningDefaultsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilReasoningDefaultsSettingsBridge: { postMessage } } }
})

describe('reasoningDefaultsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyReasoningDefaultsSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestUpdateSelectedModel with the model id', () => {
    const id = requestUpdateSelectedModel('gpt-5')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateSelectedModel', requestId: id, modelId: 'gpt-5' })
  })

  it('sends the three behavior toggle requests', () => {
    const closeId = requestUpdateCloseAssistantSessionOnInsert(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateCloseAssistantSessionOnInsert', requestId: closeId, enabled: true })
    const pasteId = requestUpdateAutoPasteAssistantOutput(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoPasteAssistantOutput', requestId: pasteId, enabled: false })
    const regionId = requestUpdateUseRegionSelection(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateUseRegionSelection', requestId: regionId, enabled: true })
  })

  it('sends AgentTask requests with the raw modality value and numeric threshold', () => {
    const modalityId = requestUpdateAgentTaskDefaultModality('text')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAgentTaskDefaultModality', requestId: modalityId, modality: 'text' })
    const reopenId = requestUpdateAgentTaskAutoReopenOnCompletion(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAgentTaskAutoReopenOnCompletion', requestId: reopenId, enabled: false })
    const pttId = requestUpdateAgentTaskPushToTalk(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAgentTaskPushToTalk', requestId: pttId, enabled: true })
    const thresholdId = requestUpdateAgentTaskPushToTalkThreshold(1200)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAgentTaskPushToTalkThreshold', requestId: thresholdId, thresholdMs: 1200 })
  })

  it('sends AssistantSession requests with the raw modality value and numeric threshold', () => {
    const modalityId = requestUpdateAssistantSessionDefaultModality('type')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAssistantSessionDefaultModality', requestId: modalityId, modality: 'type' })
    const pttId = requestUpdateAssistantSessionPushToTalk(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAssistantSessionPushToTalk', requestId: pttId, enabled: true })
    const thresholdId = requestUpdateAssistantSessionPushToTalkThreshold(900)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAssistantSessionPushToTalkThreshold', requestId: thresholdId, thresholdMs: 900 })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilReasoningDefaultsSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onReasoningDefaultsEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilReasoningDefaultsSettings!.onEvent({ type: 'loadError', message: 'after' })
    expect(received).toEqual(['boom'])
  })
})
