// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionSignInProgress } from './ConnectionSignInProgress'
import type { ConnectionsSettingsFields } from '../../types'

vi.mock('../../services/connections/connectionsBridge', () => ({
  requestCancelGitHubDeviceFlow: vi.fn(() => 'cancel-id'),
  requestCancelPendingOAuthFlow: vi.fn(() => 'cancel-pending-id'),
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

describe('ConnectionSignInProgress automatic copy', () => {
  let container: HTMLDivElement
  let root: Root

  function withCode(userCode: string): ConnectionsSettingsFields {
    const base = fields as unknown as { githubDeviceFlow: Record<string, unknown> }
    return { ...fields, githubDeviceFlow: { ...base.githubDeviceFlow, userCode } } as unknown as ConnectionsSettingsFields
  }

  async function render(next: ConnectionsSettingsFields) {
    await act(async () => {
      root.render(<ConnectionSignInProgress fields={next} onTrackRequest={() => undefined} onContinueInBackground={() => undefined} />)
    })
  }

  function hint(): string {
    return container.querySelector('.connections-device-flow-hint')?.textContent ?? ''
  }

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => {
      root.unmount()
    })
    container.remove()
  })

  it('copies the code as soon as it is shown and says so once the write has succeeded', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    await render(fields)
    expect(writeText).toHaveBeenCalledWith('ABCD-1234')
    expect(hint()).toContain('This code is now on your clipboard')
  })

  it('copies a new code when the code changes, and not again for a re-render with the same code', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    await render(withCode('AAAA-1111'))
    await render(withCode('AAAA-1111'))
    expect(writeText).toHaveBeenCalledTimes(1)
    await render(withCode('BBBB-2222'))
    expect(writeText).toHaveBeenLastCalledWith('BBBB-2222')
    expect(writeText).toHaveBeenCalledTimes(2)
  })

  it('does not claim the code was copied when the clipboard write is rejected', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard denied'))
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    await render(fields)
    expect(writeText).toHaveBeenCalledWith('ABCD-1234')
    expect(hint()).toBe('Enter this code at GitHub. Basil will continue automatically after approval.')
  })

  it('still shows the code and the normal hint when there is no clipboard', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    await render(fields)
    expect(container.querySelector('.connections-device-flow-code')?.textContent).toBe('ABCD-1234')
    expect(hint()).toContain('Enter this code at GitHub')
  })
})

describe('ConnectionSignInProgress pending browser sign-in', () => {
  it('offers Cancel Sign-in that sends requestCancelPendingOAuthFlow', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const onTrackRequest = vi.fn()
    const pending = { statusMessage: null, pendingFlowFriendlyName: 'Gmail', isPollingGitHubDeviceFlow: false, githubDeviceFlow: null } as unknown as ConnectionsSettingsFields
    await act(async () => {
      root.render(<ConnectionSignInProgress fields={pending} onTrackRequest={onTrackRequest} onContinueInBackground={() => undefined} />)
    })
    const cancel = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Cancel Sign-in')!
    expect(cancel).toBeTruthy()
    await act(async () => {
      cancel.click()
    })
    expect(onTrackRequest).toHaveBeenCalledWith('cancel-pending-id')
    act(() => root.unmount())
    container.remove()
  })
})
