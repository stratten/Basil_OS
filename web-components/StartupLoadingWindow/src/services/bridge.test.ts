// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  closeWindow,
  collapseWindow,
  expandWindow,
  minimizeWindow,
  notifyDrawnIn,
  notifyRendererReady,
  registerInitHandler,
  registerStatusHandler,
  startupLoadingWindowBridgeProtocolVersion,
} from './bridge'
import type { InitMessage } from '../types'

const init: InitMessage = {
  theme: { backgroundPrimary: '#ffffff', primary: '#0000ff', secondary: '#111111', textPrimary: '#000000' },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
  message: 'Starting Basil...',
}

describe('startup loading window bridge', () => {
  afterEach(() => {
    delete window.webkit
  })

  it('buffers the init and status messages until React registers', () => {
    window.basilStartupLoadingWindow?.onInit(init)
    window.basilStartupLoadingWindow?.onStatus({ message: 'Loading models' })
    const initHandler = vi.fn()
    const statusHandler = vi.fn()

    registerInitHandler(initHandler)
    registerStatusHandler(statusHandler)

    expect(initHandler).toHaveBeenCalledWith(init)
    expect(statusHandler).toHaveBeenCalledWith({ message: 'Loading models' })
  })

  it('does not throw if it is loaded outside a native web view', () => {
    expect(() => notifyRendererReady()).not.toThrow()
    expect(() => notifyDrawnIn()).not.toThrow()
    expect(() => closeWindow()).not.toThrow()
    expect(() => minimizeWindow()).not.toThrow()
    expect(() => collapseWindow()).not.toThrow()
    expect(() => expandWindow()).not.toThrow()
  })

  it('sends native messages with the supported protocol version', () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { startupLoadingWindowBridge: { postMessage } } }

    closeWindow()

    expect(postMessage).toHaveBeenCalledWith({
      type: 'close',
      protocolVersion: startupLoadingWindowBridgeProtocolVersion,
    })
  })
})
