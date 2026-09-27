// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AddConnectionModal } from './AddConnectionModal'
import type { ConnectionsSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void
let onDismiss: () => void

const BASE_FIELDS: ConnectionsSettingsFields = {
  starterServers: [
    { id: 'github', friendlyName: 'GitHub', serverUrl: 'https://api.githubcopilot.com/mcp', description: 'Manage issues and PRs.' },
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

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function render(fields: ConnectionsSettingsFields, pendingId: string | null = null) {
  act(() => {
    root.render(
      <AddConnectionModal fields={fields} pendingId={pendingId} onTrackRequest={onTrackRequest} onDismiss={onDismiss} />
    )
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  onDismiss = vi.fn<() => void>()
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

describe('AddConnectionModal', () => {
  it('renders the GitHub device-flow code and lets Cancel work even while the start request is still pending', () => {
    render(
      {
        ...BASE_FIELDS,
        githubDeviceFlow: {
          deviceCode: 'dc-1',
          userCode: 'ABCD-1234',
          verificationUri: 'https://github.com/login/device',
          expiresIn: 900,
          interval: 5,
          requestedScopes: ['repo'],
        },
        isPollingGitHubDeviceFlow: true,
      },
      'startGitHubDeviceFlow-pending-id'
    )
    expect(container.querySelector('.connections-device-flow-code')?.textContent).toBe('ABCD-1234')
    const cancelButton = container.querySelector<HTMLButtonElement>('.connections-device-flow-cancel')!
    expect(cancelButton.disabled).toBe(false)
    act(() => { cancelButton.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestCancelGitHubDeviceFlow' }))
  })

  it('dispatches requestRegisterManualToken and closes once the request resolves without an error', () => {
    render(BASE_FIELDS)
    const nameInput = container.querySelectorAll<HTMLInputElement>('.connections-add-form-field input[type="text"]')[0]!
    const urlInput = container.querySelectorAll<HTMLInputElement>('.connections-add-form-field input[type="text"]')[1]!
    const tokenInput = container.querySelector<HTMLInputElement>('.connections-add-form-field input[type="password"]')!
    act(() => {
      setNativeInputValue(nameInput, 'Notion')
      setNativeInputValue(urlInput, 'https://mcp.notion.com/sse')
      setNativeInputValue(tokenInput, 'secret-token')
    })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-form-actions .primary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'requestRegisterManualToken',
      serverUrl: 'https://mcp.notion.com/sse',
      friendlyName: 'Notion',
      bearerToken: 'secret-token',
    }))
    expect(onTrackRequest).toHaveBeenCalled()
    const trackedId = (onTrackRequest as ReturnType<typeof vi.fn>).mock.calls[0][0] as string

    // Simulate the request resolving: pendingId returns to null once the
    // parent app clears it after receiving the intentResult.
    render({ ...BASE_FIELDS }, trackedId)
    render({ ...BASE_FIELDS }, null)
    expect(onDismiss).toHaveBeenCalled()
  })

  it('keeps the modal open showing a waiting state after starting a generic OAuth flow, and only dismisses once pendingFlowFriendlyName clears with no error', () => {
    render({ ...BASE_FIELDS, starterServers: [{ id: 'linear', friendlyName: 'Linear', serverUrl: 'https://mcp.linear.app/sse', description: 'Track issues.' }] })
    const button = container.querySelector<HTMLButtonElement>('.connections-starter-button')!
    act(() => { button.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestStartOAuth', serverUrl: 'https://mcp.linear.app/sse' }))
    const trackedId = (onTrackRequest as ReturnType<typeof vi.fn>).mock.calls[0][0] as string

    // The start intent resolves quickly (browser opened), well before the
    // flow itself completes -- the modal must not close yet.
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear' }, trackedId)
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear' }, null)
    expect(onDismiss).not.toHaveBeenCalled()
    expect(container.querySelector('.connections-device-flow-title')?.textContent).toBe('Waiting for Linear')

    // Native clears `pendingFlowFriendlyName` once the OAuth callback lands.
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: null }, null)
    expect(onDismiss).toHaveBeenCalled()
  })

  it('does not dismiss the waiting panel if the flow completes with an error', () => {
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: 'Linear' })
    render({ ...BASE_FIELDS, pendingFlowFriendlyName: null, errorMessage: 'Connection failed: denied' })
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('disables the manual Connect button until name, URL, and token are all filled', () => {
    render(BASE_FIELDS)
    const submit = container.querySelector<HTMLButtonElement>('.connections-add-form-actions .primary-button')!
    expect(submit.disabled).toBe(true)
  })

  it('calls onDismiss when the manual-form Cancel button is clicked without dispatching a request', () => {
    render(BASE_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-form-actions .secondary-button')!.click() })
    expect(onDismiss).toHaveBeenCalled()
    expect(onTrackRequest).not.toHaveBeenCalled()
  })
})
