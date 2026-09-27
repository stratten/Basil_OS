// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { dismissPanel, notifyRendererReady, powerUserGuidePanelBridgeProtocolVersion, registerInitHandler } from './bridge'
import type { InitMessage } from '../types'

const init: InitMessage = {
  theme: {
    backgroundPrimary: '#ffffff',
    backgroundSecondary: '#f5f5f7',
    primary: '#0a84ff',
    textPrimary: '#000000',
    textSecondary: '#333333',
  },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
}

describe('power user guide panel bridge', () => {
  afterEach(() => {
    delete window.webkit
  })

  it('buffers the init message until React registers', () => {
    window.basilPowerUserGuidePanel?.onInit(init)
    const handler = vi.fn()

    registerInitHandler(handler)

    expect(handler).toHaveBeenCalledWith(init)
  })

  it('does not throw if it is loaded outside a native web view', () => {
    expect(() => dismissPanel()).not.toThrow()
    expect(() => notifyRendererReady()).not.toThrow()
  })

  it('sends native messages with the supported protocol version', () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { powerUserGuidePanelBridge: { postMessage } } }

    dismissPanel()

    expect(postMessage).toHaveBeenCalledWith({
      type: 'dismiss',
      protocolVersion: powerUserGuidePanelBridgeProtocolVersion,
    })
  })
})
