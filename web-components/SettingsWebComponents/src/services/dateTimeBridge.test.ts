// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notifyDateTimeSettingsReady, onDateTimeEvent, updateDateDisplayStyle } from './dateTimeBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilDateTimeSettingsBridge: { postMessage } } }
})

describe('dateTimeBridge', () => {
  it('posts reactReady with protocolVersion 1', () => {
    notifyDateTimeSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('posts updateDateDisplayStyle with a unique requestId and dispatches queued events after subscribing', () => {
    const id = updateDateDisplayStyle('absolute')
    expect(postMessage).toHaveBeenCalledWith({ type: 'updateDateDisplayStyle', requestId: id, dateDisplayStyle: 'absolute' })

    window.basilDateTimeSettings!.onEvent({ type: 'init', protocolVersion: 1, dateDisplayStyle: 'relative' })
    const handler = vi.fn()
    const unsubscribe = onDateTimeEvent(handler)
    expect(handler).toHaveBeenCalledWith({ type: 'init', protocolVersion: 1, dateDisplayStyle: 'relative' })

    window.basilDateTimeSettings!.onEvent({ type: 'snapshot', dateDisplayStyle: 'absolute' })
    expect(handler).toHaveBeenCalledWith({ type: 'snapshot', dateDisplayStyle: 'absolute' })

    unsubscribe()
    window.basilDateTimeSettings!.onEvent({ type: 'snapshot', dateDisplayStyle: 'relative' })
    expect(handler).toHaveBeenCalledTimes(2)
  })
})
