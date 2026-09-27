// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyHomeSettingsReady, onHomeEvent, openHomeSetupAssistant, updateHomeSelectedModel, updateHomeSelectedTranscriptionModel, updateHomeToggle } from './homeBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilHomeSettingsBridge: { postMessage } } }
})

describe('homeBridge', () => {
  it('posts reactReady with protocolVersion 1', () => {
    notifyHomeSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('posts updateToggle with a unique requestId', () => {
    const id = updateHomeToggle('activityCaptureEnabled', true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'updateToggle', requestId: id, field: 'activityCaptureEnabled', value: true })
  })

  it('posts updateSelectedModel with a unique requestId', () => {
    const id = updateHomeSelectedModel('local-model-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'updateSelectedModel', requestId: id, modelId: 'local-model-1' })
  })

  it('posts updateSelectedTranscriptionModel with a unique requestId', () => {
    const id = updateHomeSelectedTranscriptionModel('parakeet-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'updateSelectedTranscriptionModel', requestId: id, modelId: 'parakeet-1' })
  })

  it('posts openSetupAssistant with a unique requestId', () => {
    const id = openHomeSetupAssistant()
    expect(postMessage).toHaveBeenCalledWith({ type: 'openSetupAssistant', requestId: id })
  })

  it('dispatches queued events after subscribing and stops dispatching after unsubscribe', () => {
    window.basilHomeSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      fields: {
        setupAssistantPending: true,
        setupAssistantStateAvailable: true,
        permissionsGrantedCount: 3,
        permissionsTotalCount: 5,
        enableMonitoringAtStartup: true,
        enableVoiceListenerAtStartup: false,
        startActivityCaptureAtLaunch: false,
        startMeetingDetectionAtLaunch: false,
        backgroundBehaviorAvailable: true,
        activityCaptureEnabled: true,
        activityCaptureAvailable: true,
        meetingDetectionEnabled: false,
        meetingDetectionAvailable: true,
        proactiveSuggestionsEnabled: false,
        proactiveSuggestionsAvailable: true,
        localModels: [],
        apiModels: [],
        customModels: [],
        selectedModelId: '',
        useApiModels: false,
        reasoningModelsAvailable: true,
        localTranscriptionModels: [],
        apiTranscriptionModels: [],
        selectedTranscriptionModelId: '',
        transcriptionModelsAvailable: true,
      },
    })
    const handler = vi.fn()
    const unsubscribe = onHomeEvent(handler)
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0][0].type).toBe('init')

    window.basilHomeSettings!.onEvent({ type: 'loadError', message: 'boom' })
    expect(handler).toHaveBeenCalledTimes(2)

    unsubscribe()
    window.basilHomeSettings!.onEvent({ type: 'loadError', message: 'boom again' })
    expect(handler).toHaveBeenCalledTimes(2)
  })
})
