// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AddConnectionModal } from './AddConnectionModal'
import { ConnectionsPanel } from './ConnectionsPanel'
import type { ConnectionsSettingsFields } from '../../types'

let container: HTMLElement
let root: Root
let onTrackRequest: ReturnType<typeof vi.fn<(id: string) => void>>
let onDismiss: ReturnType<typeof vi.fn<() => void>>

const FIELDS: ConnectionsSettingsFields = {
  starterServers: [],
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

function dialogLabel(): string | null {
  return container.querySelector('[role="dialog"]')?.getAttribute('aria-label') ?? null
}

function button(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((candidate) => candidate.textContent === label)
  if (!found) throw new Error(`No button labeled ${label}`)
  return found
}

function entryButton(): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll<HTMLButtonElement>('.connections-starter-button')).find((candidate) => candidate.textContent?.includes('A program on this Mac'))
  if (!found) throw new Error('No local server entry button')
  return found
}

beforeEach(() => {
  onTrackRequest = vi.fn<(id: string) => void>()
  onDismiss = vi.fn<() => void>()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage: vi.fn() } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('Add Connection offers a local server', () => {
  it('opens the local server form from its own section, and Back returns to the connection list', () => {
    act(() => { root.render(<AddConnectionModal fields={FIELDS} pendingId={null} onTrackRequest={onTrackRequest} onDismiss={onDismiss} />) })
    expect(dialogLabel()).toBe('Add Connection')
    expect(container.textContent).toContain('A program on this Mac')

    act(() => { entryButton().click() })
    expect(dialogLabel()).toBe('Add a local server')

    act(() => { button('Back').click() })
    expect(dialogLabel()).toBe('Add Connection')
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('disables the entry button while another request is pending', () => {
    act(() => { root.render(<AddConnectionModal fields={FIELDS} pendingId="other-request" onTrackRequest={onTrackRequest} onDismiss={onDismiss} />) })
    expect(entryButton().disabled).toBe(true)
  })

  it('passes the request error from the panel to the form so a failed attempt is shown there', () => {
    act(() => {
      root.render(<ConnectionsPanel fields={FIELDS} pendingId={null} onTrackRequest={onTrackRequest} requestError="WhatsApp was not added, because it did not start." />)
    })
    act(() => { button('+ Add Connection').click() })
    act(() => { entryButton().click() })
    expect(dialogLabel()).toBe('Add a local server')
    expect(container.querySelector('.connections-local-error')?.textContent).toBe('WhatsApp was not added, because it did not start.')
  })
})
