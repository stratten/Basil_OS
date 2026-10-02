// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionsSettingsApp } from './ConnectionsSettingsApp'
import type { ConnectionsSettingsFields, MCPConnection } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const EMPTY_FIELDS: ConnectionsSettingsFields = {
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
  providerProfiles: [
    {
      id: 'profile-1',
      displayName: 'Codex CLI',
      status: 'enabled',
      capabilityState: 'unverified',
      description: null,
      routingHints: [],
      revision: 1,
      hasObservedCapabilities: false,
      activeWorkspaceGrants: [],
      isStructurallyValid: true,
      validationError: null,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    },
  ],
  isLoadingProviderProfiles: false,
  isMutatingProviderProfiles: false,
  providerProfilesStatusMessage: null,
  providerProfilesErrorMessage: null,
}

const POLICY_CONNECTION: MCPConnection = {
  id: 'conn-1',
  friendlyName: 'GitHub',
  description: 'Work account',
  serverUrl: 'https://api.githubcopilot.com/mcp',
  enabled: true,
  registeredAt: '2026-01-01T00:00:00Z',
  lastToolRefreshAt: null,
  lastConnectionCheckAt: '2026-01-02T00:00:00Z',
  lastConnectionStatus: 'healthy',
  lastConnectionStatusMessage: 'OK',
  serverName: 'github-mcp',
  serverInstructions: null,
  authKind: 'github_device',
  tools: [
    { name: 'create_issue', description: 'Create a GitHub issue', isReadOnlyHint: false, policy: 'always_ask' },
  ],
}

function sendInit(fields: ConnectionsSettingsFields) {
  act(() => {
    window.basilConnectionsSettings!.onEvent({ type: 'init', protocolVersion: 1, ...fields })
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ConnectionsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ConnectionsSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.connections-settings-status')?.textContent).toBe('Loading connections...')
  })

  it('sends reactReady on mount', () => {
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('renders starter servers inside the Add Connection modal once init arrives', () => {
    sendInit(EMPTY_FIELDS)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    expect(container.querySelector('.connections-starter-button-name')?.textContent).toBe('GitHub')
  })

  it('shows a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilConnectionsSettings!.onEvent({ type: 'loadError', message: 'Could not load connections.' }) })
    expect(container.querySelector('.connections-settings-error p')?.textContent).toBe('Could not load connections.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-settings-error .secondary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('keeps connection actions available while a tool policy change is pending and surfaces a policy failure', () => {
    sendInit({ ...EMPTY_FIELDS, connections: [POLICY_CONNECTION] })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!.click() })
    const neverAllowOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Never allow')!
    act(() => { neverAllowOption.click() })
    const policyMessage = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestUpdatePolicy')!
    expect(container.querySelector<HTMLButtonElement>('.connections-row-action-danger')!.disabled).toBe(false)
    act(() => {
      window.basilConnectionsSettings!.onEvent({ type: 'intentResult', requestId: policyMessage.requestId, status: 'error', message: 'Policy update failed.' })
    })
    expect(Array.from(container.querySelectorAll('[role="alert"]')).map((alert) => alert.textContent)).toContain('Policy update failed.')
  })

  it('surfaces a native errorMessage banner', () => {
    sendInit({ ...EMPTY_FIELDS, errorMessage: 'Could not start GitHub sign-in.' })
    expect(container.querySelector('.connections-settings-banner-error')?.textContent).toBe('Could not start GitHub sign-in.')
  })

  it('surfaces a native statusMessage banner', () => {
    sendInit({ ...EMPTY_FIELDS, statusMessage: 'Connection added. Fetching tools...' })
    expect(container.querySelector('.connections-settings-banner-info')?.textContent).toBe('Connection added. Fetching tools...')
  })

  it('defaults to the MCP sub-tab and switches to ACP on click', () => {
    sendInit(EMPTY_FIELDS)
    expect(container.querySelector('.connections-panel')).not.toBeNull()
    expect(container.querySelector('.provider-profiles-panel')).toBeNull()
    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
    const providerProfilesTab = buttons.find((button) => button.textContent === 'ACP')!
    act(() => { providerProfilesTab.click() })
    expect(container.querySelector('.provider-profiles-panel')).not.toBeNull()
    expect(container.querySelector('.connections-panel')).toBeNull()
  })

  it('renders the seeded provider profile on the ACP sub-tab', () => {
    sendInit(EMPTY_FIELDS)
    const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
    act(() => { buttons.find((button) => button.textContent === 'ACP')!.click() })
    expect(container.querySelector('.provider-profile-row-name')?.textContent).toBe('Codex CLI')
  })

  it('honors an externally requested sub-tab on mount', () => {
    act(() => { root.unmount() })
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<ConnectionsSettingsApp requestedSubTab="providerProfiles" />) })
    sendInit(EMPTY_FIELDS)
    expect(container.querySelector('.provider-profiles-panel')).not.toBeNull()
    expect(container.querySelector('.connections-panel')).toBeNull()
  })
})
