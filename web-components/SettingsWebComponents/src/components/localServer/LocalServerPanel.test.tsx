// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ConnectionRow } from '../connections/ConnectionRow'
import { LocalServerPanel, companionStatusLabel, missingSecretNames } from './LocalServerPanel'
import type { CompanionInfo, LocalServerInfo, MCPConnection } from '../../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: ReturnType<typeof vi.fn<(id: string) => void>>

const COMPANION: CompanionInfo = {
  status: 'running',
  port: 51234,
  lastError: null,
  logTail: '',
  restartCount: 0,
  startWithBasil: true,
  fixedPort: null,
  secretEnv: [{ name: 'BRIDGE_TOKEN', saved: true }],
  commandSummary: '/usr/local/bin/go run . 51234',
}

const LOCAL: LocalServerInfo = {
  commandSummary: '/usr/bin/env uv run main.py',
  sourceUrl: 'https://github.com/example/bridge',
  secretEnv: [{ name: 'API_KEY', saved: true }],
  companion: COMPANION,
}

const CONNECTION: MCPConnection = {
  id: 'conn-local',
  friendlyName: 'WhatsApp',
  description: null,
  serverUrl: 'basil-stdio://conn-local',
  enabled: true,
  registeredAt: '2026-01-01T00:00:00Z',
  lastToolRefreshAt: null,
  lastConnectionCheckAt: null,
  lastConnectionStatus: 'healthy',
  lastConnectionStatusMessage: null,
  serverName: null,
  serverInstructions: null,
  authKind: 'local',
  tools: [],
  localServer: LOCAL,
}

function render(localServer: LocalServerInfo, disabled = false) {
  act(() => {
    root.render(<LocalServerPanel connectionId="conn-local" localServer={localServer} disabled={disabled} onTrackRequest={onTrackRequest} />)
  })
}

function withCompanion(overrides: Partial<CompanionInfo>): LocalServerInfo {
  return { ...LOCAL, companion: { ...COMPANION, ...overrides } }
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((candidate) => candidate.textContent === label)
  if (!found) throw new Error(`No button labeled ${label}`)
  return found
}

function typeInto(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
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

describe('LocalServerPanel', () => {
  it('shows the command, where it came from, and which secrets are in the Keychain without any value', () => {
    render(LOCAL)
    const text = container.textContent ?? ''
    expect(text).toContain('/usr/bin/env uv run main.py')
    expect(text).toContain('https://github.com/example/bridge')
    expect(text).toContain('API_KEY, BRIDGE_TOKEN')
    expect(container.querySelector('.connections-local-secrets')).toBeNull()
  })

  it('omits the source line when there is none', () => {
    render({ ...LOCAL, sourceUrl: null, companion: null })
    expect(container.textContent).not.toContain('From')
    expect(container.querySelector('.connections-local-companion')).toBeNull()
  })

  it('asks only for the missing secrets, keeps Save and start off until all are typed, and sends trimmed values', () => {
    render({ ...LOCAL, secretEnv: [{ name: 'API_KEY', saved: false }], companion: { ...COMPANION, secretEnv: [{ name: 'API_KEY', saved: false }, { name: 'BRIDGE_TOKEN', saved: true }] } })
    expect(missingSecretNames(LOCAL)).toEqual([])
    expect(container.querySelectorAll('input[type="password"]')).toHaveLength(1)
    const save = button('Save and start')
    expect(save.disabled).toBe(true)

    act(() => { typeInto(container.querySelector<HTMLInputElement>('input[name="secret-API_KEY"]')!, '  k-123  ') })
    expect(button('Save and start').disabled).toBe(false)
    act(() => { button('Save and start').click() })

    expect(postMessage).toHaveBeenCalledTimes(1)
    expect(postMessage.mock.calls[0][0]).toMatchObject({ type: 'requestSaveLocalServerSecrets', connectionId: 'conn-local', secretValues: { API_KEY: 'k-123' } })
    expect(onTrackRequest).toHaveBeenCalledWith(postMessage.mock.calls[0][0].requestId)
    expect(container.querySelector<HTMLInputElement>('input[name="secret-API_KEY"]')!.value).toBe('')
    expect(container.textContent).not.toContain('k-123')
  })

  it('lists a missing secret shared by the server and its background program once', () => {
    const shared = { ...LOCAL, secretEnv: [{ name: 'SHARED', saved: false }], companion: { ...COMPANION, secretEnv: [{ name: 'SHARED', saved: false }] } }
    expect(missingSecretNames(shared)).toEqual(['SHARED'])
  })

  it('shows a running program with its port, offers Stop, and sends the stop message', () => {
    render(LOCAL)
    expect(container.querySelector('.connections-local-status')?.textContent).toBe('Running on port 51234')
    expect(container.querySelector('.connections-local-status-ok')).not.toBeNull()
    expect(container.textContent).toContain('/usr/local/bin/go run . 51234')
    act(() => { button('Stop').click() })
    expect(postMessage.mock.calls[0][0]).toMatchObject({ type: 'requestStopCompanion', connectionId: 'conn-local' })
  })

  it('offers Start for a stopped program and sends the start message', () => {
    render(withCompanion({ status: 'stopped', port: null }))
    expect(container.querySelector('.connections-local-status')?.textContent).toBe('Stopped')
    act(() => { button('Start').click() })
    expect(postMessage.mock.calls[0][0]).toMatchObject({ type: 'requestStartCompanion', connectionId: 'conn-local' })
  })

  it('sends the new value when the start-with-Basil switch is toggled', () => {
    render(LOCAL)
    act(() => { container.querySelector<HTMLInputElement>('.connections-local-companion input[type="checkbox"]')!.click() })
    expect(postMessage.mock.calls[0][0]).toMatchObject({ type: 'requestSetCompanionStartWithBasil', connectionId: 'conn-local', startWithBasil: false })
  })

  it('shows the reason and the log tail for a failed program, and neither for a healthy one', () => {
    render(withCompanion({ status: 'failed', port: null, lastError: 'The background program stopped before it was ready (exit code 3).', logTail: 'panic: address already in use' }))
    expect(container.querySelector('.connections-local-error')?.textContent).toContain('exit code 3')
    expect(container.querySelector('.connections-local-log')?.textContent).toBe('panic: address already in use')
    expect(container.querySelector('.connections-local-status-error')?.textContent).toBe('Failed')
    render(withCompanion({ status: 'running', lastError: 'old error', logTail: 'old output' }))
    expect(container.querySelector('.connections-local-error')).toBeNull()
    expect(container.querySelector('.connections-local-log')).toBeNull()
  })

  it('does not offer to start a program that is waiting for secret values, nor one that is stopping', () => {
    render(withCompanion({ status: 'needs_secrets', port: null, lastError: 'Enter the values for BRIDGE_TOKEN in Settings, then start it again.' }))
    expect(companionStatusLabel({ ...COMPANION, status: 'needs_secrets' })).toBe('Needs secret values')
    expect(button('Start').disabled).toBe(true)
    render(withCompanion({ status: 'stopping' }))
    expect(button('Start').disabled).toBe(true)
    render(withCompanion({ status: 'starting', port: null }))
    expect(companionStatusLabel({ ...COMPANION, status: 'starting' })).toBe('Starting...')
    expect(button('Stop').disabled).toBe(false)
  })

  it('says how often a running program was restarted', () => {
    render(withCompanion({ restartCount: 1 }))
    expect(container.textContent).toContain('restarted it 1 time.')
    render(withCompanion({ restartCount: 3 }))
    expect(container.textContent).toContain('restarted it 3 times.')
  })

  it('disables every control while another request is pending', () => {
    render({ ...LOCAL, secretEnv: [{ name: 'API_KEY', saved: false }] }, true)
    for (const control of Array.from(container.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button, input'))) {
      expect(control.disabled).toBe(true)
    }
  })
})

describe('ConnectionRow with a local server', () => {
  it('shows the panel under the status line for a local server and not for any other connection', () => {
    act(() => { root.render(<ConnectionRow connection={CONNECTION} pendingId={null} onTrackRequest={onTrackRequest} />) })
    expect(container.querySelector('.connections-local-panel')).not.toBeNull()
    expect(container.querySelector('.connections-row-url')?.textContent).toBe('Runs on this Mac')
    act(() => { root.render(<ConnectionRow connection={{ ...CONNECTION, authKind: 'github_device', localServer: undefined }} pendingId={null} onTrackRequest={onTrackRequest} />) })
    expect(container.querySelector('.connections-local-panel')).toBeNull()
  })
})
