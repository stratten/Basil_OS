// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionsPanel, sortConnectionsByProvider } from './ConnectionsPanel'
import type { ConnectionsSettingsFields, MCPConnection } from '../types'

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
  gmailTransport: 'direct',
  gmailTransportPinnedByEnvironment: false,
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

  describe('Gmail connection mechanism', () => {
    const GMAIL_STARTER = { id: 'gmail', friendlyName: 'Gmail', serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1', description: 'Search, read, draft, label, trash, and send email.' }
    const GMAIL_CONNECTION: ConnectionsSettingsFields['connections'][number] = {
      id: 'gmail-1',
      friendlyName: 'Gmail',
      description: null,
      serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1',
      enabled: true,
      registeredAt: '2026-10-28T14:55:44',
      lastToolRefreshAt: null,
      lastConnectionCheckAt: null,
      lastConnectionStatus: null,
      lastConnectionStatusMessage: null,
      serverName: null,
      serverInstructions: null,
      authKind: 'oauth',
      tools: [],
    }
    const LINEAR_CONNECTION = { ...GMAIL_CONNECTION, id: 'linear-1', friendlyName: 'Linear', serverUrl: 'https://mcp.linear.app/sse' }
    const WITH_GMAIL_STARTER = { ...BASE_FIELDS, starterServers: [GMAIL_STARTER, ...BASE_FIELDS.starterServers] }

    let resolvePending: () => void

    // Tracks the pending request the way the real app does, so one action can wait for another.
    function Harness({ fields }: { fields: ConnectionsSettingsFields }) {
      const [pendingId, setPendingId] = useState<string | null>(null)
      resolvePending = () => setPendingId(null)
      return <ConnectionsPanel fields={fields} pendingId={pendingId} onTrackRequest={(id) => { onTrackRequest(id); setPendingId(id) }} />
    }

    function renderHarness(fields: ConnectionsSettingsFields) {
      act(() => { root.render(<Harness fields={fields} />) })
    }

    function radio(value: string): HTMLInputElement | null {
      return container.querySelector<HTMLInputElement>(`input[name="gmail-transport"][value="${value}"]`)
    }

    function sentTypes(): string[] {
      return postMessage.mock.calls.map((call) => (call[0] as { type: string }).type)
    }

    function clickButton(label: string) {
      const button = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((candidate) => candidate.textContent?.trim() === label)!
      act(() => { button.click() })
    }

    function openGmailPage(fields: ConnectionsSettingsFields) {
      renderHarness(fields)
      act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
      const gmail = Array.from(container.querySelectorAll<HTMLButtonElement>('.connections-starter-button')).find((el) => el.textContent?.includes('Gmail'))!
      act(() => { gmail.click() })
    }

    it('never appears at the top of the connections area or on the Add Connection list', () => {
      renderHarness({ ...WITH_GMAIL_STARTER, connections: [GMAIL_CONNECTION] })
      expect(container.querySelector('.connections-gmail-transport')).toBeNull()
      act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
      expect(container.querySelector('.connections-gmail-transport')).toBeNull()
    })

    it('is a further page after choosing Gmail, with a way back', () => {
      openGmailPage(WITH_GMAIL_STARTER)
      expect(container.querySelector('.connections-add-modal')?.getAttribute('aria-label')).toBe('Sign in with Google')
      expect(radio('direct')!.checked).toBe(true)
      expect(container.querySelector('.connections-starter-list')).toBeNull()
      expect(sentTypes()).toEqual([])
      clickButton('Back')
      expect(container.querySelector('.connections-starter-list')).not.toBeNull()
      expect(container.querySelector('.connections-gmail-transport')).toBeNull()
    })

    it('signs in straight away when the choice is unchanged', () => {
      openGmailPage(WITH_GMAIL_STARTER)
      clickButton('Sign in with Google')
      expect(sentTypes()).toEqual(['requestStartOAuth'])
      expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ serverUrl: GMAIL_STARTER.serverUrl }))
    })

    it('saves a changed choice first and only then opens the browser', () => {
      openGmailPage(WITH_GMAIL_STARTER)
      act(() => { radio('mcp')!.click() })
      expect(sentTypes()).toEqual([])
      clickButton('Sign in with Google')
      expect(sentTypes()).toEqual(['requestSetGmailTransport'])
      expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ transport: 'mcp' }))
      act(() => { resolvePending() })
      expect(sentTypes()).toEqual(['requestSetGmailTransport', 'requestStartOAuth'])
    })

    it('does not open the browser when saving the choice failed', () => {
      openGmailPage(WITH_GMAIL_STARTER)
      act(() => { radio('mcp')!.click() })
      clickButton('Sign in with Google')
      renderHarness({ ...WITH_GMAIL_STARTER, errorMessage: 'Could not change the Gmail connection mechanism.' })
      act(() => { resolvePending() })
      expect(sentTypes()).toEqual(['requestSetGmailTransport'])
    })

    it('shows the saved choice and locks it while the environment variable pins the mechanism', () => {
      openGmailPage({ ...WITH_GMAIL_STARTER, gmailTransport: 'mcp', gmailTransportPinnedByEnvironment: true })
      expect(radio('mcp')!.checked).toBe(true)
      expect(radio('direct')!.disabled).toBe(true)
      expect(container.querySelector('.connections-gmail-transport')?.textContent).toContain('BASIL_GMAIL_TRANSPORT')
      clickButton('Sign in with Google')
      expect(sentTypes()).toEqual(['requestStartOAuth'])
    })

    it('shows only a note on an existing Gmail connection', () => {
      renderHarness({ ...BASE_FIELDS, connections: [GMAIL_CONNECTION, LINEAR_CONNECTION] })
      const notes = container.querySelectorAll('.connections-row-transport')
      expect(notes).toHaveLength(1)
      expect(notes[0].textContent).toBe('Connects through the Gmail API.')
      renderHarness({ ...BASE_FIELDS, connections: [GMAIL_CONNECTION], gmailTransport: 'mcp' })
      expect(container.querySelector('.connections-row-transport')?.textContent).toBe("Connects through Google's hosted Gmail server.")
      expect(container.querySelector('.connections-gmail-transport')).toBeNull()
    })

    it('offers the choice when editing a Gmail connection and saves it after the name and context', () => {
      renderHarness({ ...BASE_FIELDS, connections: [GMAIL_CONNECTION] })
      clickButton('Edit')
      expect(radio('direct')!.checked).toBe(true)
      act(() => { radio('mcp')!.click() })
      clickButton('Save')
      expect(sentTypes()).toEqual(['requestUpdateConnectionMetadata'])
      act(() => { resolvePending() })
      expect(sentTypes()).toEqual(['requestUpdateConnectionMetadata', 'requestSetGmailTransport'])
      expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ transport: 'mcp' }))
    })

    it('does not send a mechanism change when editing without changing it', () => {
      renderHarness({ ...BASE_FIELDS, connections: [GMAIL_CONNECTION] })
      clickButton('Edit')
      clickButton('Save')
      act(() => { resolvePending() })
      expect(sentTypes()).toEqual(['requestUpdateConnectionMetadata'])
    })

    it('offers no choice when editing a non-Gmail connection', () => {
      renderHarness({ ...BASE_FIELDS, connections: [LINEAR_CONNECTION] })
      clickButton('Edit')
      expect(container.querySelector('.connections-gmail-transport')).toBeNull()
    })
  })

  function listedConnection(overrides: Partial<MCPConnection> & Pick<MCPConnection, 'id' | 'friendlyName' | 'serverUrl'>): MCPConnection {
    return {
      description: null,
      enabled: true,
      registeredAt: '2026-10-29T00:00:00Z',
      lastToolRefreshAt: null,
      lastConnectionCheckAt: null,
      lastConnectionStatus: 'healthy',
      lastConnectionStatusMessage: null,
      serverName: null,
      serverInstructions: null,
      authKind: 'oauth',
      tools: [],
      ...overrides,
    }
  }

  it('sorts connections by provider so matching hosts stay together, then by name', () => {
    const workGmail = listedConnection({ id: 'gmail-work', friendlyName: 'Work inbox', serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1' })
    const personalGmail = listedConnection({ id: 'gmail-home', friendlyName: 'Personal inbox', serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1' })
    const slack = listedConnection({ id: 'slack-1', friendlyName: 'Slack', serverUrl: 'https://slack.com/mcp' })
    const linear = listedConnection({ id: 'linear-1', friendlyName: 'Linear', serverUrl: 'https://mcp.linear.app/sse' })
    const custom = listedConnection({ id: 'hf-1', friendlyName: 'Research models', serverUrl: 'https://huggingface.co/mcp', serverName: 'Hugging Face' })
    render({
      ...BASE_FIELDS,
      connections: [slack, workGmail, linear, custom, personalGmail],
    })
    const names = Array.from(container.querySelectorAll('.connections-row-name')).map((node) => node.textContent)
    expect(names).toEqual(['Personal inbox', 'Work inbox', 'Research models', 'Linear', 'Slack'])
    expect(sortConnectionsByProvider([slack, workGmail, linear, custom, personalGmail], BASE_FIELDS.starterServers).map((connection) => connection.id)).toEqual([
      'gmail-home',
      'gmail-work',
      'hf-1',
      'linear-1',
      'slack-1',
    ])
  })

  it('does not show Check Status for All when the list is empty', () => {
    render(BASE_FIELDS)
    const labels = Array.from(container.querySelectorAll('button')).map((button) => button.textContent?.trim())
    expect(labels).not.toContain('Check Status for All')
  })

  it('checks every connection in the sorted list, one after another', () => {
    const slack = listedConnection({ id: 'slack-1', friendlyName: 'Slack', serverUrl: 'https://slack.com/mcp' })
    const gmail = listedConnection({ id: 'gmail-1', friendlyName: 'Gmail', serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1' })
    let resolvePending: () => void = () => undefined
    function Harness() {
      const [pendingId, setPendingId] = useState<string | null>(null)
      resolvePending = () => setPendingId(null)
      return <ConnectionsPanel fields={{ ...BASE_FIELDS, connections: [slack, gmail] }} pendingId={pendingId} onTrackRequest={(id) => { onTrackRequest(id); setPendingId(id) }} />
    }
    act(() => { root.render(<Harness />) })
    const checkAll = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.trim() === 'Check Status for All')!
    act(() => { checkAll.click() })
    expect(postMessage.mock.calls).toHaveLength(1)
    expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'requestCheckConnectionStatus', connectionId: 'gmail-1' }))
    act(() => { resolvePending() })
    expect(postMessage.mock.calls).toHaveLength(2)
    expect(postMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'requestCheckConnectionStatus', connectionId: 'slack-1' }))
  })
})
