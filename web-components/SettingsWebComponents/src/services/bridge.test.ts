// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cancelDraft, notifyAppearanceSettingsReady, onAppearanceEvent, previewDraft, resetDraft, saveDraft } from './bridge'
import type { AppearanceNativeEvent } from '../types'
import { APPEARANCE_FIXTURE_SETTINGS } from '../fixtures/appearanceFixture'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilAppearanceSettingsBridge: { postMessage } } }
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('bridge', () => {
  it('queues events that arrive before a handler subscribes, then flushes them in order on subscribe', () => {
    const initEvent: AppearanceNativeEvent = {
      type: 'init',
      protocolVersion: 1,
      revision: 1,
      settings: APPEARANCE_FIXTURE_SETTINGS,
      availableFonts: ['Helvetica-Light'],
      theme: {} as AppearanceNativeEvent extends { theme: infer T } ? T : never,
      fonts: {} as AppearanceNativeEvent extends { fonts: infer T } ? T : never,
    }
    window.basilAppearanceSettings!.onEvent(initEvent)

    const received: AppearanceNativeEvent[] = []
    const unsubscribe = onAppearanceEvent((event) => received.push(event))

    expect(received).toEqual([initEvent])
    unsubscribe()
  })

  it('delivers events immediately once a handler is subscribed', () => {
    const received: AppearanceNativeEvent[] = []
    const unsubscribe = onAppearanceEvent((event) => received.push(event))

    const snapshotEvent: AppearanceNativeEvent = {
      type: 'snapshot',
      protocolVersion: 1,
      revision: 2,
      settings: APPEARANCE_FIXTURE_SETTINGS,
      availableFonts: ['Helvetica-Light'],
    }
    window.basilAppearanceSettings!.onEvent(snapshotEvent)

    expect(received).toEqual([snapshotEvent])
    unsubscribe()
  })

  it('stops delivering events to a handler after it unsubscribes', () => {
    const received: AppearanceNativeEvent[] = []
    const unsubscribe = onAppearanceEvent((event) => received.push(event))
    unsubscribe()

    window.basilAppearanceSettings!.onEvent({
      type: 'snapshot',
      protocolVersion: 1,
      revision: 3,
      settings: APPEARANCE_FIXTURE_SETTINGS,
      availableFonts: ['Helvetica-Light'],
    })

    expect(received).toEqual([])
  })

  it('coalesces multiple previewDraft calls within one animation frame into a single postMessage', async () => {
    const first = { ...APPEARANCE_FIXTURE_SETTINGS, preferredFont: 'Arial' }
    const second = { ...APPEARANCE_FIXTURE_SETTINGS, preferredFont: 'Menlo' }

    previewDraft(first)
    previewDraft(second)

    await new Promise((resolve) => window.requestAnimationFrame(resolve))

    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage).toHaveBeenCalledWith({ type: 'previewDraft', draft: second })
  })

  it('sends save/cancel/reset with a unique generated requestId', () => {
    const saveRequestId = saveDraft(APPEARANCE_FIXTURE_SETTINGS)
    const cancelRequestId = cancelDraft()
    const resetRequestId = resetDraft()

    expect(postMessage).toHaveBeenNthCalledWith(1, { type: 'saveDraft', requestId: saveRequestId, draft: APPEARANCE_FIXTURE_SETTINGS })
    expect(postMessage).toHaveBeenNthCalledWith(2, { type: 'cancelDraft', requestId: cancelRequestId })
    expect(postMessage).toHaveBeenNthCalledWith(3, { type: 'resetDraft', requestId: resetRequestId })
    expect(new Set([saveRequestId, cancelRequestId, resetRequestId]).size).toBe(3)
  })

  it('sends reactReady as a bare intent', () => {
    notifyAppearanceSettingsReady()

    expect(postMessage).toHaveBeenNthCalledWith(1, { type: 'reactReady', protocolVersion: 1 })
  })
})
