// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { WorkspaceGrantModal } from './WorkspaceGrantModal'
import type { ProviderProfileSummary, ProviderProfileWorkspaceGrant } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onTrackRequest: (id: string) => void
let onDismiss: () => void

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

const GRANT: ProviderProfileWorkspaceGrant = {
  id: 'grant-1',
  canonicalWorkspaceRoot: '/Users/me/proj',
  status: 'active',
  workspaceLabel: 'My Project',
  description: null,
  routingHints: [],
  revision: 2,
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

function render(existingGrant: ProviderProfileWorkspaceGrant | null, canonicalWorkspaceRoot = '/Users/me/proj') {
  act(() => {
    root.render(
      <WorkspaceGrantModal
        profile={PROFILE}
        existingGrant={existingGrant}
        canonicalWorkspaceRoot={canonicalWorkspaceRoot}
        disabled={false}
        onTrackRequest={onTrackRequest}
        onDismiss={onDismiss}
      />,
    )
  })
}

describe('WorkspaceGrantModal', () => {
  it('shows "Authorize Workspace" and defaults the label to the last path component in create mode', () => {
    render(null, '/Users/me/proj')
    expect(container.querySelector('.connections-add-modal-title')?.textContent).toBe('Authorize Workspace')
    const labelInput = container.querySelectorAll('input')[0] as HTMLInputElement
    expect(labelInput.value).toBe('proj')
  })

  it('displays the canonical root path', () => {
    render(null, '/Users/me/proj')
    expect(container.querySelector('.connections-workspace-grant-path')?.textContent).toBe('/Users/me/proj')
  })

  it('sends requestCreateWorkspaceGrant with the canonical root on Save', () => {
    render(null, '/Users/me/proj')
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save')!
    act(() => { save.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestCreateWorkspaceGrant', profileId: 'profile-1', canonicalWorkspaceRoot: '/Users/me/proj' }),
    )
  })

  it('pre-fills the label and sends requestUpdateWorkspaceGrant with the expected revision in edit mode', () => {
    render(GRANT)
    const labelInput = container.querySelectorAll('input')[0] as HTMLInputElement
    expect(labelInput.value).toBe('My Project')
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save')!
    act(() => { save.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateWorkspaceGrant', profileId: 'profile-1', grantId: 'grant-1', expectedRevision: 2 }),
    )
  })

  it('disables Save when the label is blank', () => {
    render(GRANT)
    const labelInput = container.querySelectorAll('input')[0] as HTMLInputElement
    act(() => { setNativeInputValue(labelInput, '   ') })
    const save = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
  })
})
