// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyMeetingDetectionSettingsReady,
  onMeetingDetectionEvent,
  requestAddExcludedBundleId,
  requestMeetingDetectionAvailableApps,
  requestMeetingDetectionSearchApps,
  requestRemoveExcludedBundleId,
  requestUpdateExcludedAppNames,
  requestUpdateMeetingDetectionAutoEnd,
  requestUpdateMeetingDetectionCooldownMinutes,
  requestUpdateMeetingDetectionEnabled,
  requestUpdateMeetingDetectionMode,
  requestUpdateMeetingDetectionPollSeconds,
  requestUpdateRequireCalendarMatch,
  requestUpdateUseCalendarEnrichment,
  requestUpdateInactivityTimeoutMinutes,
} from './meetingDetectionBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMeetingDetectionSettingsBridge: { postMessage } } }
})

describe('meetingDetectionBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyMeetingDetectionSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends boolean toggle requests', () => {
    const enabledId = requestUpdateMeetingDetectionEnabled(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateEnabled', requestId: enabledId, enabled: true })
    const calendarId = requestUpdateUseCalendarEnrichment(false)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateUseCalendarEnrichment', requestId: calendarId, enabled: false })
    const matchId = requestUpdateRequireCalendarMatch(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateRequireCalendarMatch', requestId: matchId, enabled: true })
    const autoEndId = requestUpdateMeetingDetectionAutoEnd(true)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateAutoEnd', requestId: autoEndId, enabled: true })
  })

  it('sends requestUpdateMode with the raw mode value', () => {
    const id = requestUpdateMeetingDetectionMode('auto_start')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateMode', requestId: id, mode: 'auto_start' })
  })

  it('sends numeric field updates', () => {
    const pollId = requestUpdateMeetingDetectionPollSeconds(15)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdatePollSeconds', requestId: pollId, pollSeconds: 15 })
    const cooldownId = requestUpdateMeetingDetectionCooldownMinutes(30)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateCooldownMinutes', requestId: cooldownId, cooldownMinutes: 30 })
    const timeoutId = requestUpdateInactivityTimeoutMinutes(5)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateInactivityTimeoutMinutes', requestId: timeoutId, minutes: 5 })
  })

  it('sends requestUpdateExcludedAppNames with the array', () => {
    const id = requestUpdateExcludedAppNames(['Discord', 'Slack'])
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateExcludedAppNames', requestId: id, excludedAppNames: ['Discord', 'Slack'] })
  })

  it('sends add/remove excluded bundle id requests', () => {
    const addId = requestAddExcludedBundleId('com.apple.FaceTime')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestAddExcludedBundleId', requestId: addId, bundleId: 'com.apple.FaceTime' })
    const removeId = requestRemoveExcludedBundleId('com.apple.FaceTime')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRemoveExcludedBundleId', requestId: removeId, bundleId: 'com.apple.FaceTime' })
  })

  it('sends requestAvailableApps with no requestId', () => {
    requestMeetingDetectionAvailableApps()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestAvailableApps' })
  })

  it('sends requestSearchApps with the query', () => {
    const id = requestMeetingDetectionSearchApps('para')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestSearchApps', requestId: id, query: 'para' })
  })

  it('queues events before subscribe and stops after unsubscribe', () => {
    window.basilMeetingDetectionSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onMeetingDetectionEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
    window.basilMeetingDetectionSettings!.onEvent({ type: 'loadError', message: 'after' })
    expect(received).toEqual(['boom'])
  })
})
