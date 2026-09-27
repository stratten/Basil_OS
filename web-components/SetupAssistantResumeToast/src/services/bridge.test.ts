// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dontRemind,
  notifyRendererReady,
  registerInitHandler,
  remindLater,
  requestResize,
  resumeSetup,
  setupAssistantResumeToastBridgeProtocolVersion,
} from './bridge'
import type { InitMessage } from '../types'

const init: InitMessage = {
  theme: {
    backgroundPrimary: '#ffffff',
    primary: '#0000ff',
    secondary: '#111111',
    textPrimary: '#000000',
    textSecondary: '#666666',
  },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
}

describe('setup assistant resume toast bridge', () => {
  afterEach(() => {
    delete window.webkit
  })

  it('buffers the init message until React registers', () => {
    window.basilSetupAssistantResumeToast?.onInit(init)
    const handler = vi.fn()

    registerInitHandler(handler)

    expect(handler).toHaveBeenCalledWith(init)
  })

  it('does not throw if it is loaded outside a native web view', () => {
    expect(() => notifyRendererReady()).not.toThrow()
    expect(() => resumeSetup()).not.toThrow()
    expect(() => remindLater()).not.toThrow()
    expect(() => dontRemind()).not.toThrow()
    expect(() => requestResize(320, 150)).not.toThrow()
  })

  it('sends native messages with the supported protocol version', () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { setupAssistantResumeToastBridge: { postMessage } } }

    resumeSetup()

    expect(postMessage).toHaveBeenCalledWith({
      type: 'resume',
      protocolVersion: setupAssistantResumeToastBridgeProtocolVersion,
    })
  })
})
