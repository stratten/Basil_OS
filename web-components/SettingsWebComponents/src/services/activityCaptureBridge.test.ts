// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyActivityCaptureSettingsReady,
  onActivityCaptureEvent,
  requestActivityCaptureAvailableApps,
  requestActivityCaptureCancelProcessing,
  requestActivityCaptureClearAllCaptures,
  requestActivityCaptureClearBacklog,
  requestActivityCaptureProcessBacklog,
  requestActivityCaptureProcessingProgress,
  requestActivityCaptureSearchApps,
  requestActivityCaptureStatus,
  requestActivityCaptureTestCapture,
  requestAddActivityCaptureExcludedBundleId,
  requestRemoveActivityCaptureExcludedBundleId,
  requestUpdateActivityCaptureCleanupTime,
  requestUpdateActivityCaptureEnabled,
  requestUpdateActivityCaptureFrequencySeconds,
  requestUpdateActivityCaptureMaxStorageMb,
  requestUpdateActivityCaptureProcessingMode,
} from './activityCaptureBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilActivityCaptureSettingsBridge: { postMessage } } }
})

describe('activityCaptureBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyActivityCaptureSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends field updates with a generated requestId', () => {
    const enabledId = requestUpdateActivityCaptureEnabled(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateEnabled', requestId: enabledId, enabled: true })
    const frequencyId = requestUpdateActivityCaptureFrequencySeconds(60)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateFrequencySeconds', requestId: frequencyId, frequencySeconds: 60 })
    const addExcludedId = requestAddActivityCaptureExcludedBundleId('com.apple.Terminal')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestAddExcludedBundleId', requestId: addExcludedId, bundleId: 'com.apple.Terminal' })
    const removeExcludedId = requestRemoveActivityCaptureExcludedBundleId('com.apple.Terminal')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRemoveExcludedBundleId', requestId: removeExcludedId, bundleId: 'com.apple.Terminal' })
    requestActivityCaptureAvailableApps()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestAvailableApps' })
    const searchId = requestActivityCaptureSearchApps('paral')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSearchApps', requestId: searchId, query: 'paral' })
    const modeId = requestUpdateActivityCaptureProcessingMode('scheduled')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateProcessingMode', requestId: modeId, processingMode: 'scheduled' })
    const storageId = requestUpdateActivityCaptureMaxStorageMb(1000)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateMaxStorageMb', requestId: storageId, maxStorageMb: 1000 })
    const cleanupId = requestUpdateActivityCaptureCleanupTime(3, 30)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateCleanupTime', requestId: cleanupId, cleanupHour: 3, cleanupMinute: 30 })
  })

  it('sends each manual-control action request with its own requestId', () => {
    const testId = requestActivityCaptureTestCapture()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestTestCapture', requestId: testId })
    const processId = requestActivityCaptureProcessBacklog()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestProcessBacklog', requestId: processId })
    const cancelId = requestActivityCaptureCancelProcessing()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCancelProcessing', requestId: cancelId })
    const clearBacklogId = requestActivityCaptureClearBacklog()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestClearBacklog', requestId: clearBacklogId })
    const clearAllId = requestActivityCaptureClearAllCaptures()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestClearAllCaptures', requestId: clearAllId })
  })

  it('sends the two poll triggers with no requestId', () => {
    requestActivityCaptureStatus()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestStatus' })
    requestActivityCaptureProcessingProgress()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestProcessingProgress' })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilActivityCaptureSettings!.onEvent({ type: 'intentResult', requestId: 'r1', status: 'success' })
    const received: string[] = []
    const unsubscribe = onActivityCaptureEvent((event) => {
      if (event.type === 'intentResult') received.push(event.requestId)
    })
    expect(received).toEqual(['r1'])
    unsubscribe()
    window.basilActivityCaptureSettings!.onEvent({ type: 'intentResult', requestId: 'r2', status: 'success' })
    expect(received).toEqual(['r1'])
  })
})
