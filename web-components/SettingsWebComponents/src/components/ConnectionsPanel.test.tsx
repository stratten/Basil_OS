// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionsPanel } from './ConnectionsPanel'
import type { ConnectionsSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void

const BASE_FIELDS: ConnectionsSettingsFields = {
  starterServers: [
    { id: 'github', friendlyName: 'GitHub', serverUrl: 'https://api.githubcopilot.com/mcp', description: 'Manage issues and PRs.' },
    { id: 'slack', friendlyName: 'Slack', serverUrl: 'https://slack.com/mcp', description: 'Send and read messages.' },
    { id: 'linear', friendlyName: 'Linear', serverUrl: 'https://mcp.linear.app/sse', description: 'Track issues.' },
  ],
  connections: [],
  callLogEntries: [],
  isLoading: false,
  isAddingConnection: false,
  isLoadingCallLog: false,
  errorMessage: null,
  statusMessage: null,
  pendingFlowFriendlyName: null,
  githubDeviceFlow: null,
  isPollingGitHubDeviceFlow: false,
  providerProfiles: [],
  isLoadingProviderProfiles: false,
  isMutatingProviderProfiles: false,
  providerProfilesStatusMessage: null,
  providerProfilesErrorMessage: null,
}

function render(fields: ConnectionsSettingsFields, pendingId: string | null = null) {
  act(() => { root.render(<ConnectionsPanel fields={fields} pendingId={pendingId} onTrackRequest={onTrackRequest} />) })
}

beforeEach(() => {
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ConnectionsPanel', () => {
  it('shows the empty state when there are no connections', () => {
    render(BASE_FIELDS)
    expect(container.querySelector('.connections-empty-state')).not.toBeNull()
  })

  it('does not render the Add Connection modal until the toggle is clicked', () => {
    render(BASE_FIELDS)
    expect(container.querySelector('.connections-add-modal')).toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    expect(container.querySelector('.connections-add-modal')).not.toBeNull()
  })

  it('routes the GitHub starter button (inside the modal) through requestStartGitHubDeviceFlow', () => {
    render(BASE_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    const button = Array.from(container.querySelectorAll('.connections-starter-button')).find((el) => el.textContent?.includes('GitHub'))!
    act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestStartGitHubDeviceFlow', serverUrl: 'https://api.githubcopilot.com/mcp' }))
  })

  it('routes the Slack starter button (inside the modal) through requestStartSlackOAuth', () => {
    render(BASE_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    const button = Array.from(container.querySelectorAll('.connections-starter-button')).find((el) => el.textContent?.includes('Slack'))!
    act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestStartSlackOAuth', serverUrl: 'https://slack.com/mcp' }))
  })

  it('routes any other starter button (inside the modal) through the generic requestStartOAuth', () => {
    render(BASE_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    const button = Array.from(container.querySelectorAll('.connections-starter-button')).find((el) => el.textContent?.includes('Linear'))!
    act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestStartOAuth', serverUrl: 'https://mcp.linear.app/sse' }))
  })

  it('closes the modal when Cancel is clicked in the manual bearer-token section', () => {
    render(BASE_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    expect(container.querySelector('.connections-add-modal')).not.toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-form-actions button')!.click() })
    expect(container.querySelector('.connections-add-modal')).toBeNull()
  })

  const DEVICE_FLOW = {
    deviceCode: 'dc-1',
    userCode: 'WXYZ-9876',
    verificationUri: 'https://github.com/login/device',
    expiresIn: 900,
    interval: 5,
    requestedScopes: ['repo'],
  }

  it('shows the GitHub device code outside the Add modal so a reconnect can be completed', () => {
    render({ ...BASE_FIELDS, githubDeviceFlow: DEVICE_FLOW, isPollingGitHubDeviceFlow: true })
    expect(container.querySelector('.connections-add-modal')).toBeNull()
    expect(container.querySelector('.connections-device-flow-code')?.textContent).toBe('WXYZ-9876')
    act(() => { container.querySelector<HTMLButtonElement>('.connections-device-flow-cancel')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestCancelGitHubDeviceFlow' }))
  })

  it('renders the device code only once while the Add modal is open', () => {
    render({ ...BASE_FIELDS, githubDeviceFlow: DEVICE_FLOW, isPollingGitHubDeviceFlow: true })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    expect(container.querySelectorAll('.connections-device-flow-code')).toHaveLength(1)
  })

  it('shows a waiting card for a browser reconnect and lets the user hide it', () => {
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear', statusMessage: 'Complete sign-in in your browser to reconnect Linear.' })
    expect(container.querySelector('.connections-device-flow-title')?.textContent).toBe('Waiting for Linear')
    expect(container.querySelector('.connections-device-flow-hint')?.textContent).toBe('Complete sign-in in your browser to reconnect Linear.')
    const hide = Array.from(container.querySelectorAll<HTMLButtonElement>('.connections-device-flow button')).find((button) => button.textContent === 'Continue in Background')!
    act(() => { hide.click() })
    expect(container.querySelector('.connections-device-flow')).toBeNull()
  })

  it('shows the waiting card again for the next sign-in after the previous one finished', () => {
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear' })
    const hide = Array.from(container.querySelectorAll<HTMLButtonElement>('.connections-device-flow button')).find((button) => button.textContent === 'Continue in Background')!
    act(() => { hide.click() })
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: null })
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear' })
    expect(container.querySelector('.connections-device-flow-title')?.textContent).toBe('Waiting for Linear')
  })
})
