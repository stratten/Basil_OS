// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionSignInProgress } from './ConnectionSignInProgress'
import type { ConnectionsSettingsFields } from '../types'

vi.mock('../services/connectionsBridge', () => ({
  requestCancelGitHubDeviceFlow: vi.fn(() => 'cancel-id'),
  requestOpenExternalUrl: vi.fn(() => 'open-id'),
}))

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const fields = {
  statusMessage: null,
  pendingFlowFriendlyName: null,
  isPollingGitHubDeviceFlow: false,
  githubDeviceFlow: {
    deviceCode: 'device-code',
    userCode: 'ABCD-1234',
    verificationUri: 'https://github.com/login/device',
    expiresIn: 900,
    interval: 5,
    requestedScopes: [],
  },
} as unknown as ConnectionsSettingsFields

describe('ConnectionSignInProgress copy code', () => {
  let container: HTMLDivElement
  let root: Root
  let writeText: ReturnType<typeof vi.fn>

  function copyButton(): HTMLButtonElement {
    return Array.from(container.querySelectorAll('button')).find((button) => /^(Copy Code|Copied)$/.test(button.textContent ?? ''))!
  }

  async function render() {
    await act(async () => {
      root.render(<ConnectionSignInProgress fields={fields} onTrackRequest={() => undefined} onContinueInBackground={() => undefined} />)
    })
  }

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
    vi.useRealTimers()
  })

  it('copies the user code and confirms with a Copied label that reverts at 1500 ms', async () => {
    await render()
    expect(copyButton().textContent).toBe('Copy Code')

    await act(async () => {
      copyButton().click()
    })
    expect(writeText).toHaveBeenCalledWith('ABCD-1234')
    expect(copyButton().textContent).toBe('Copied')

    await act(async () => {
      vi.advanceTimersByTime(1499)
    })
    expect(copyButton().textContent).toBe('Copied')

    await act(async () => {
      vi.advanceTimersByTime(1)
    })
    expect(copyButton().textContent).toBe('Copy Code')
  })

  it('does not claim Copied when the clipboard write is rejected', async () => {
    writeText.mockRejectedValue(new Error('clipboard denied'))
    await render()

    await act(async () => {
      copyButton().click()
    })
    expect(writeText).toHaveBeenCalledWith('ABCD-1234')
    expect(copyButton().textContent).toBe('Copy Code')
  })
})
