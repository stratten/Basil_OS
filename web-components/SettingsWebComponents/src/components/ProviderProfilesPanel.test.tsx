// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ProviderProfilesPanel } from './ProviderProfilesPanel'
import type {
  ConnectionsProviderProfileConfigurationEvent,
  ConnectionsWorkspaceFolderChosenEvent,
  ProviderProfileSummary,
} from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void
let onConsumeConfigEvent: () => void
let onConsumeFolderEvent: () => void

const PROFILE: ProviderProfileSummary = {
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
}

beforeEach(() => {
  postMessage = vi.fn()
  onTrackRequest = vi.fn<(id: string) => void>()
  onConsumeConfigEvent = vi.fn<() => void>()
  onConsumeFolderEvent = vi.fn<() => void>()
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

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function render(
  profiles: ProviderProfileSummary[],
  pendingId: string | null = null,
  requestError: string | null = null,
  configEvent: ConnectionsProviderProfileConfigurationEvent | null = null,
  folderEvent: ConnectionsWorkspaceFolderChosenEvent | null = null,
) {
  act(() => {
    root.render(
      <ProviderProfilesPanel
        providerProfiles={profiles}
        isLoading={false}
        isMutating={false}
        statusMessage={null}
        errorMessage={null}
        pendingId={pendingId}
        requestError={requestError}
        onTrackRequest={onTrackRequest}
        configEvent={configEvent}
        onConsumeConfigEvent={onConsumeConfigEvent}
        folderEvent={folderEvent}
        onConsumeFolderEvent={onConsumeFolderEvent}
      />,
    )
  })
}

describe('ProviderProfilesPanel', () => {
  it('shows the empty state when there are no profiles', () => {
    render([])
    expect(container.querySelector('.connections-empty-state-title')?.textContent).toBe('No provider profiles yet.')
  })

  it('opens the Add Provider modal on click and closes it on Cancel', () => {
    render([PROFILE])
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    expect(container.querySelector('.connections-add-modal')).not.toBeNull()
    const cancel = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Cancel')!
    act(() => { cancel.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(container.querySelector('.connections-add-modal')).toBeNull()
  })

  it('sends requestRemoveProviderProfile directly with no confirmation dialog', () => {
    render([PROFILE])
    const remove = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Remove')!
    act(() => { remove.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRemoveProviderProfile', profileId: 'profile-1', expectedRevision: 1 }))
  })

  it('requests the full configuration on Edit and opens the editor once it arrives', () => {
    render([PROFILE])
    const edit = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Edit')!
    act(() => { edit.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const requestId = (onTrackRequest as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    render(
      [PROFILE],
      null,
      null,
      {
        type: 'providerProfileConfiguration',
        requestId,
        configuration: { ...PROFILE, launchArgv: ['/bin/codex'], environmentAllowlist: [], authenticationMethodId: null },
      },
    )
    expect(container.querySelector('.connections-add-modal-title')?.textContent).toBe('Edit Provider Profile')
    expect(onConsumeConfigEvent).toHaveBeenCalled()
  })

  it('requests a workspace folder on Add Workspace and opens the grant editor once chosen', () => {
    render([PROFILE])
    const addWorkspace = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Add Workspace')!
    act(() => { addWorkspace.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const requestId = (onTrackRequest as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    render(
      [PROFILE],
      null,
      null,
      null,
      { type: 'workspaceFolderChosen', requestId, profileId: 'profile-1', canonicalWorkspaceRoot: '/Users/me/proj' },
    )
    expect(container.querySelector('.connections-add-modal-title')?.textContent).toBe('Authorize Workspace')
    expect(onConsumeFolderEvent).toHaveBeenCalled()
  })

  it('closes the Add Provider modal once its tracked request resolves with no error', () => {
    render([PROFILE])
    act(() => { container.querySelector<HTMLButtonElement>('.connections-add-toggle')!.click() })
    const nameInput = container.querySelectorAll('input')[0]
    const pathInput = container.querySelectorAll('input')[1]
    act(() => {
      setNativeInputValue(nameInput, 'Codex CLI')
      setNativeInputValue(pathInput, '/bin/codex')
    })
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save')!
    act(() => { save.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const calls = (onTrackRequest as ReturnType<typeof vi.fn>).mock.calls
    const requestId = calls[calls.length - 1][0] as string
    render([PROFILE], requestId)
    render([PROFILE], null, null)
    expect(container.querySelector('.connections-add-modal')).toBeNull()
  })
})
