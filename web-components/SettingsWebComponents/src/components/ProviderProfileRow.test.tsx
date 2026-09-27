// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ProviderProfileRow } from './ProviderProfileRow'
import type { ProviderProfileSummary, ProviderProfileWorkspaceGrant } from '../types'

let container: HTMLElement
let root: Root
let onEdit: (profile: ProviderProfileSummary) => void
let onToggleEnabled: (profile: ProviderProfileSummary) => void
let onAddWorkspace: (profile: ProviderProfileSummary) => void
let onRemove: (profile: ProviderProfileSummary) => void
let onEditGrant: (profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void
let onRevokeGrant: (profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void

const PROFILE: ProviderProfileSummary = {
  id: 'profile-1',
  displayName: 'Codex CLI',
  status: 'enabled',
  capabilityState: 'unverified',
  description: 'Local coding agent.',
  routingHints: ['coding'],
  revision: 2,
  hasObservedCapabilities: false,
  activeWorkspaceGrants: [
    { id: 'grant-1', canonicalWorkspaceRoot: '/Users/me/proj', status: 'active', workspaceLabel: 'proj', description: null, routingHints: [], revision: 1 },
  ],
  isStructurallyValid: true,
  validationError: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  onEdit = vi.fn<(profile: ProviderProfileSummary) => void>()
  onToggleEnabled = vi.fn<(profile: ProviderProfileSummary) => void>()
  onAddWorkspace = vi.fn<(profile: ProviderProfileSummary) => void>()
  onRemove = vi.fn<(profile: ProviderProfileSummary) => void>()
  onEditGrant = vi.fn<(profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void>()
  onRevokeGrant = vi.fn<(profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void>()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function render(profile: ProviderProfileSummary, disabled = false) {
  act(() => {
    root.render(
      <ProviderProfileRow
        profile={profile}
        disabled={disabled}
        onEdit={onEdit}
        onToggleEnabled={onToggleEnabled}
        onAddWorkspace={onAddWorkspace}
        onRemove={onRemove}
        onEditGrant={onEditGrant}
        onRevokeGrant={onRevokeGrant}
      />,
    )
  })
}

describe('ProviderProfileRow', () => {
  it('renders the display name, description, and status', () => {
    render(PROFILE)
    expect(container.querySelector('.provider-profile-row-name')?.textContent).toBe('Codex CLI')
    expect(container.querySelector('.provider-profile-row-description')?.textContent).toBe('Local coding agent.')
    expect(container.querySelector('.provider-profile-status')?.textContent).toContain('Enabled')
  })

  it('shows "Enabled, invalid" when structurally invalid', () => {
    render({ ...PROFILE, isStructurallyValid: false })
    expect(container.querySelector('.provider-profile-status')?.textContent).toContain('Enabled, invalid')
  })

  it('renders a validation error when present', () => {
    render({ ...PROFILE, validationError: 'Executable not found.' })
    expect(container.querySelector('.provider-profile-validation-error')?.textContent).toBe('Executable not found.')
  })

  it('calls onEdit with the profile when Edit is clicked', () => {
    render(PROFILE)
    const button = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Edit')!
    act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onEdit).toHaveBeenCalledWith(PROFILE)
  })

  it('labels the toggle button "Disable" when enabled and calls onToggleEnabled', () => {
    render(PROFILE)
    const button = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Disable')!
    act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onToggleEnabled).toHaveBeenCalledWith(PROFILE)
  })

  it('renders the active workspace grant and wires its Edit/Revoke actions', () => {
    render(PROFILE)
    expect(container.querySelector('.provider-profile-grant-label')?.textContent).toBe('proj')
    const revokeButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Revoke')!
    act(() => { revokeButton.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onRevokeGrant).toHaveBeenCalledWith(PROFILE, PROFILE.activeWorkspaceGrants[0])
  })

  it('shows "No active workspace grant." when there are none', () => {
    render({ ...PROFILE, activeWorkspaceGrants: [] })
    expect(container.querySelector('.connections-row-tools-empty')?.textContent).toBe('No active workspace grant.')
  })

  it('disables all action buttons when disabled is true', () => {
    render(PROFILE, true)
    const editButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Edit') as HTMLButtonElement
    expect(editButton.disabled).toBe(true)
  })
})
