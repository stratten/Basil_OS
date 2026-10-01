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

  it('expands to show tool policies and collapses again', () => {
    render(CONNECTION)
    expect(container.querySelector('.connections-row-tools')).toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelectorAll('.connections-tool-row')).toHaveLength(2)
    act(() => { container.querySelector<HTMLButtonElement>('.connections-row-expand')!.click() })
    expect(container.querySelector('.connections-row-tools')).toBeNull()
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
