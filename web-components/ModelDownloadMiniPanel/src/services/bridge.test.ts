// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dismissPanel,
  modelDownloadPanelBridgeProtocolVersion,
  registerInitHandler,
  requestResize,
  retryModel,
} from './bridge'
import type { InitMessage } from '../types'

const init: InitMessage = {
  theme: {
    backgroundPrimary: '#ffffff',
    primary: '#0000ff',
    secondary: '#111111',
    textPrimary: '#000000',
    successBase: '#008000',
    warningBase: '#cc8800',
    recordingBase: '#cc0000',
  },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
  snapshot: { phaseMessage: 'Preparing...', isComplete: false, quantizedPercentage: 0, appIconDataUrl: null, models: [] },
}

describe('model download panel bridge', () => {
  afterEach(() => {
    delete window.webkit
  })

  it('buffers the init message until React registers', () => {
    window.basilModelDownloadPanel?.onInit(init)
    const handler = vi.fn()

    registerInitHandler(handler)

    expect(handler).toHaveBeenCalledWith(init)
  })

  it('does not throw if it is loaded outside a native web view', () => {
    expect(() => dismissPanel()).not.toThrow()
    expect(() => retryModel('OpenAI-whisper-tiny.en')).not.toThrow()
  })

  it('sends native messages with the supported protocol version', () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { modelDownloadPanelBridge: { postMessage } } }

    requestResize(260, 220)

    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestResize',
      width: 260,
      height: 220,
      protocolVersion: modelDownloadPanelBridgeProtocolVersion,
    })
  })
})
