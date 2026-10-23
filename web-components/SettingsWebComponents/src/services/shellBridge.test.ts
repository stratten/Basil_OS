// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { closeSettingsShell, collapseSettingsShell, expandSettingsShell, minimizeSettingsShell } from './shellBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilSettingsShellBridge: { postMessage } } }
})

describe('shellBridge', () => {
  it('sends close on the shell-level channel', () => {
    closeSettingsShell()
    expect(postMessage).toHaveBeenCalledWith({ type: 'close' })
  })

  it('sends minimize on the shell-level channel', () => {
    minimizeSettingsShell()
    expect(postMessage).toHaveBeenCalledWith({ type: 'minimize' })
  })

  it('sends collapse on the shell-level channel', () => {
    collapseSettingsShell()
    expect(postMessage).toHaveBeenCalledWith({ type: 'collapse' })
  })

  it('sends expand on the shell-level channel', () => {
    expandSettingsShell()
    expect(postMessage).toHaveBeenCalledWith({ type: 'expand' })
  })

  it('does nothing (no throw) when the handler is not registered', () => {
    window.webkit = undefined
    expect(() => closeSettingsShell()).not.toThrow()
    expect(() => minimizeSettingsShell()).not.toThrow()
    expect(() => collapseSettingsShell()).not.toThrow()
    expect(() => expandSettingsShell()).not.toThrow()
  })
})
