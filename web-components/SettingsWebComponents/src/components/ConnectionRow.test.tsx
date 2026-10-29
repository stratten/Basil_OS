// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionRow } from './ConnectionRow'
import type { MCPConnection } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void

const CONNECTION: MCPConnection = {
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
    { name: 'list_issues', description: 'List issues', isReadOnlyHint: true, policy: 'always_allow' },
  ],
}

function render(connection: MCPConnection, pendingId: string | null = null) {
  act(() => { root.render(<ConnectionRow connection={connection} pendingId={pendingId} onTrackRequest={onTrackRequest} />) })
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

describe('ConnectionRow', () => {
  it('renders a healthy status badge', () => {
    render(CONNECTION)
    expect(container.querySelector('.connections-row-status-healthy')?.textContent).toContain('Healthy')
  })

  it('shows the check and last successful use in local time on the status line, with the Gmail mechanism beside them', () => {
    const pad = (n: number) => String(n).padStart(2, '0')
    const local = (iso: string) => {
      const d = new Date(iso)
      const h = d.getHours()
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${h % 12 || 12}:${pad(d.getMinutes())} ${h >= 12 ? 'pm' : 'am'}`
    }
    act(() => {
      root.render(
        <ConnectionRow
          connection={{ ...CONNECTION, serverUrl: 'https://gmailmcp.googleapis.com/mcp/v1', lastConnectionCheckAt: '2026-10-28T19:34:26Z', lastSuccessfulUseAt: '2026-10-28T20:10:00Z' }}
          pendingId={null}
          onTrackRequest={onTrackRequest}
          gmailTransport="direct"
          dateDisplayStyle="absolute"
        />,
      )
    })
    const status = container.querySelector('.connections-row-status')!
    const text = status.textContent ?? ''
    expect(text).toContain(`Checked ${local('2026-10-28T19:34:26Z')}`)
    expect(text).toContain(`Last used successfully ${local('2026-10-28T20:10:00Z')}`)
    expect(text).not.toContain('2026-10-28T')
    expect(status.querySelector('.connections-row-transport')?.textContent).toBe('Connects through the Gmail API.')
  })

  it('omits the last-used time when the connection has never been used successfully', () => {
    render({ ...CONNECTION, lastSuccessfulUseAt: null })
    expect(container.querySelector('.connections-row-status')?.textContent).not.toContain('Last used')
  })

  it('expands to show tool policies and collapses again', () => {
    render(CONNECTION)
    expect(container.querySelector('.connections-row-tools')).toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelectorAll('.connections-tool-row')).toHaveLength(2)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelector('.connections-row-tools')).toBeNull()
  })

  it('marks each tool row with its policy so the list can be color coded', () => {
    render(CONNECTION)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    const rows = Array.from(container.querySelectorAll<HTMLElement>('.connections-tool-row'))
    expect(rows.map((row) => row.dataset.policy)).toEqual(['always_ask', 'always_allow'])
  })

  it('recolors a tool row as soon as its policy is changed', () => {
    render(CONNECTION)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!.click() })
    const neverAllowOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Never allow')!
    act(() => { neverAllowOption.click() })
    const rows = Array.from(container.querySelectorAll<HTMLElement>('.connections-tool-row'))
    expect(rows.map((row) => row.dataset.policy)).toEqual(['never_allow', 'always_allow'])
  })

  it('dispatches requestUpdatePolicy when a tool policy changes', () => {
    render(CONNECTION)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    const select = container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!
    act(() => { select.click() })
    const neverAllowOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Never allow')!
    act(() => { neverAllowOption.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdatePolicy', connectionId: 'conn-1', toolName: 'create_issue', policy: 'never_allow' }))
  })

  it('keeps tool policies interactive and shows the chosen policy while another request is pending', () => {
    render(CONNECTION, 'other-request')
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    const select = container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!
    expect(select.disabled).toBe(false)
    act(() => { select.click() })
    const neverAllowOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Never allow')!
    act(() => { neverAllowOption.click() })
    expect(container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!.textContent).toContain('Never allow')
    expect(onTrackRequest).toHaveBeenCalledTimes(1)
  })

  it('routes policy requests through the non-blocking tracker and returns to the snapshot value', () => {
    const onTrackPolicyRequest = vi.fn<(id: string) => void>()
    act(() => { root.render(<ConnectionRow connection={CONNECTION} pendingId={null} onTrackRequest={onTrackRequest} onTrackPolicyRequest={onTrackPolicyRequest} />) })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!.click() })
    const neverAllowOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Never allow')!
    act(() => { neverAllowOption.click() })
    expect(onTrackPolicyRequest).toHaveBeenCalledTimes(1)
    expect(onTrackRequest).not.toHaveBeenCalled()
    act(() => { root.render(<ConnectionRow connection={{ ...CONNECTION, tools: [...CONNECTION.tools] }} pendingId={null} onTrackRequest={onTrackRequest} onTrackPolicyRequest={onTrackPolicyRequest} />) })
    expect(container.querySelector<HTMLButtonElement>('.connections-tool-row-policy')!.textContent).toContain('Always ask')
  })

  it('dispatches requestDeleteConnection when Remove is clicked (native confirms)', () => {
    render(CONNECTION)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-action-danger')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestDeleteConnection', connectionId: 'conn-1' }))
  })

  it('allows editing and saving the friendly name and description', () => {
    render(CONNECTION)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-action-button')!.click() })
    const nameInput = container.querySelector<HTMLInputElement>('.connections-row-edit-name')!
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      setter.call(nameInput, 'GitHub (work)')
      nameInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-action-primary')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateConnectionMetadata', connectionId: 'conn-1', friendlyName: 'GitHub (work)' }))
  })

  function buttonLabeled(label: string): HTMLButtonElement | undefined {
    return Array.from(container.querySelectorAll<HTMLButtonElement>('.connections-row-action-button')).find((button) => button.textContent === label)
  }

  function setInputValue(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      setter.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
  }

  it('shows Check Status and no Reconnect for a healthy connection', () => {
    render(CONNECTION)
    expect(buttonLabeled('Check Status')).toBeDefined()
    expect(buttonLabeled('Reconnect')).toBeUndefined()
  })

  it('keeps Check Status when the last check failed for a non-credential reason', () => {
    render({ ...CONNECTION, lastConnectionStatus: 'error' })
    expect(buttonLabeled('Check Status')).toBeDefined()
    expect(buttonLabeled('Reconnect')).toBeUndefined()
  })

  it('replaces Check Status with Reconnect when credentials need reconnecting', () => {
    render({ ...CONNECTION, lastConnectionStatus: 'needs_reconnect' })
    expect(buttonLabeled('Check Status')).toBeUndefined()
    act(() => { buttonLabeled('Reconnect')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestReconnectConnection', connectionId: 'conn-1' }))
    expect(onTrackRequest).toHaveBeenCalled()
  })

  it('offers Reconnect when the stored token is unavailable', () => {
    render({ ...CONNECTION, authKind: 'oauth', lastConnectionStatus: 'token_unavailable' })
    act(() => { buttonLabeled('Reconnect')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestReconnectConnection', connectionId: 'conn-1' }))
  })

  it('disables Reconnect while another request is pending', () => {
    render({ ...CONNECTION, lastConnectionStatus: 'needs_reconnect' }, 'other-request')
    expect(buttonLabeled('Reconnect')!.disabled).toBe(true)
  })

  it('asks for a replacement token instead of starting a browser flow for pasted-token connections', () => {
    render({ ...CONNECTION, authKind: 'manual_token', lastConnectionStatus: 'needs_reconnect' })
    act(() => { buttonLabeled('Reconnect')!.click() })
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestReconnectConnection' }))
    const tokenInput = container.querySelector<HTMLInputElement>('.connections-row-edit-token')!
    expect(tokenInput.type).toBe('password')
    expect(buttonLabeled('Save Token')!.disabled).toBe(true)

    setInputValue(tokenInput, '   ')
    expect(buttonLabeled('Save Token')!.disabled).toBe(true)

    setInputValue(tokenInput, '  new-secret  ')
    act(() => { buttonLabeled('Save Token')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestReplaceConnectionToken', connectionId: 'conn-1', bearerToken: 'new-secret' }))
    expect(container.querySelector('.connections-row-edit-token')).toBeNull()
  })

  it('cancels token replacement without sending anything', () => {
    render({ ...CONNECTION, authKind: 'manual_token', lastConnectionStatus: 'token_unavailable' })
    act(() => { buttonLabeled('Reconnect')!.click() })
    setInputValue(container.querySelector<HTMLInputElement>('.connections-row-edit-token')!, 'typed-but-abandoned')
    act(() => { buttonLabeled('Cancel')!.click() })
    expect(container.querySelector('.connections-row-edit-token')).toBeNull()
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestReplaceConnectionToken' }))
    act(() => { buttonLabeled('Reconnect')!.click() })
    expect(container.querySelector<HTMLInputElement>('.connections-row-edit-token')!.value).toBe('')
  })
})
