// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  cancelHotkeyCapture,
  notifyHotkeySettingsReady,
  onHotkeyEvent,
  saveHotkeyBinding,
  startHotkeyCapture,
  toggleEnableMonitoringAtStartup,
} from './hotkeyBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilHotkeySettingsBridge: { postMessage } } }
})

describe('hotkeyBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyHotkeySettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends startCapture and cancelCapture with the row id', () => {
    startHotkeyCapture('agent_task')
    expect(postMessage).toHaveBeenCalledWith({ type: 'startCapture', id: 'agent_task' })

    cancelHotkeyCapture('agent_task')
    expect(postMessage).toHaveBeenCalledWith({ type: 'cancelCapture', id: 'agent_task' })
  })

  it('sends saveBinding with a fresh requestId each call', () => {
    const binding = { key: 'F8', modifiers: [], enabled: true, isDoublePress: false, doublePressKey: null }
    const first = saveHotkeyBinding('conversation_toggle', binding)
    const second = saveHotkeyBinding('conversation_toggle', binding)
    expect(first).not.toBe(second)
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'saveBinding', id: 'conversation_toggle', binding })
    )
  })

  it('sends toggleEnableMonitoring with the requested value', () => {
    toggleEnableMonitoringAtStartup(false)
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'toggleEnableMonitoring', enabled: false })
    )
  })

  it('queues events received before a handler subscribes, then flushes them in order', () => {
    window.basilHotkeySettings!.onEvent({ type: 'captureCancelled', id: 'agent_task' })
    window.basilHotkeySettings!.onEvent({ type: 'captureCancelled', id: 'conversation_toggle' })

    const received: string[] = []
    const unsubscribe = onHotkeyEvent((event) => {
      if (event.type === 'captureCancelled') received.push(event.id)
    })

    expect(received).toEqual(['agent_task', 'conversation_toggle'])
    unsubscribe()
  })
})
