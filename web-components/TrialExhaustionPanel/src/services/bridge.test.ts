// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dismissPanel,
  registerInitHandler,
  requestAddOwnKeys,
  requestSignUp,
  requestUseLocalModels,
  trialExhaustionPanelBridgeProtocolVersion,
} from './bridge'
import type { InitMessage } from '../types'

const init: InitMessage = {
  theme: { backgroundPrimary: '#ffffff', textPrimary: '#000000', textSecondary: '#333333' },
  fonts: { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' },
  remainingBalanceFormatted: '$0.00',
  limitFormatted: '$5.00',
  isAuthenticated: false,
  userEmail: null,
}

describe('trial exhaustion panel bridge', () => {
  afterEach(() => {
    delete window.webkit
  })

  it('buffers the init message until React registers', () => {
    window.basilTrialExhaustionPanel?.onInit(init)
    const handler = vi.fn()

    registerInitHandler(handler)

    expect(handler).toHaveBeenCalledWith(init)
  })

  it('does not throw if it is loaded outside a native web view', () => {
    expect(() => dismissPanel()).not.toThrow()
    expect(() => requestSignUp()).not.toThrow()
    expect(() => requestAddOwnKeys()).not.toThrow()
    expect(() => requestUseLocalModels('req-1')).not.toThrow()
  })

  it('sends native messages with the supported protocol version', () => {
    const postMessage = vi.fn()
    window.webkit = { messageHandlers: { trialExhaustionPanelBridge: { postMessage } } }

    requestUseLocalModels('req-1')

    expect(postMessage).toHaveBeenCalledWith({
      type: 'useLocalModels',
      requestId: 'req-1',
      protocolVersion: trialExhaustionPanelBridgeProtocolVersion,
    })
  })
})
