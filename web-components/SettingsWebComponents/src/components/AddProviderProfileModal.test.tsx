// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AddProviderProfileModal } from './AddProviderProfileModal'
import type { ProviderProfileConfiguration } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void
let onDismiss: () => void

const CONFIGURATION: ProviderProfileConfiguration = {
  id: 'profile-1',
  displayName: 'Codex CLI',
  status: 'enabled',
  capabilityState: 'unverified',
  description: 'desc',
  routingHints: ['coding'],
  revision: 4,
  hasObservedCapabilities: false,
  activeWorkspaceGrants: [],
  isStructurallyValid: true,
  validationError: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  launchArgv: ['/usr/local/bin/codex', '--acp'],
  environmentAllowlist: ['OPENAI_API_KEY'],
  authenticationMethodId: 'api-key',
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

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function render(configuration: ProviderProfileConfiguration | null, disabled = false) {
  act(() => {
    root.render(
      <AddProviderProfileModal configuration={configuration} disabled={disabled} onTrackRequest={onTrackRequest} onDismiss={onDismiss} />,
    )
  })
}

describe('AddProviderProfileModal', () => {
  it('shows "Add Provider Profile" and disables Save when fields are empty in create mode', () => {
    render(null)
    expect(container.querySelector('.connections-add-modal-title')?.textContent).toBe('Add Provider Profile')
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })

  it('sends requestCreateProviderProfile with cleaned lists once required fields are filled', () => {
    render(null)
    const nameInput = container.querySelectorAll('input')[0]
    const pathInput = container.querySelectorAll('input')[1]
    act(() => {
      setNativeInputValue(nameInput, 'Codex CLI')
      setNativeInputValue(pathInput, '/usr/local/bin/codex')
    })
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save') as HTMLButtonElement
    act(() => { save.click() })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestCreateProviderProfile', displayName: 'Codex CLI', launchArgv: ['/usr/local/bin/codex'] }),
    )
    expect(onTrackRequest).toHaveBeenCalled()
  })

  it('pre-fills fields and sends requestUpdateProviderProfile with the expected revision in edit mode', () => {
    render(CONFIGURATION)
    expect(container.querySelector('.connections-add-modal-title')?.textContent).toBe('Edit Provider Profile')
    const nameInput = container.querySelectorAll('input')[0] as HTMLInputElement
    expect(nameInput.value).toBe('Codex CLI')
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save')!
    act(() => { save.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateProviderProfile', profileId: 'profile-1', expectedRevision: 4 }),
    )
  })

  it('calls onDismiss when Cancel is clicked', () => {
    render(null)
    const cancel = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Cancel')!
    act(() => { cancel.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onDismiss).toHaveBeenCalled()
  })
})
