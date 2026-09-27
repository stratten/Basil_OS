// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { PermissionsCommandSecurityPanel } from './PermissionsCommandSecurityPanel'
import type { ApprovalSettingsFields, WhitelistPatternFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const BASE_SETTINGS: ApprovalSettingsFields = {
  approvalMode: 'whitelist_only',
  showFullCommandInPrompt: true,
  rememberChoiceOption: true,
  autoApproveReadOnly: false,
  blockDangerousPatterns: true,
  whitelistedCount: 0,
  safeExecutionMode: false,
  approvalTimeoutSeconds: 120,
  timeoutBehavior: 'wait_forever',
}

function initEvent(overrides: Partial<ApprovalSettingsFields> = {}, whitelistPatterns: WhitelistPatternFields[] = []) {
  return {
    type: 'init' as const,
    protocolVersion: 1 as const,
    isLoading: false,
    error: null,
    approvalSettings: { ...BASE_SETTINGS, ...overrides },
    whitelistPatterns,
  }
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilPermissionsCommandSecurityBridge: { postMessage } } }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<PermissionsCommandSecurityPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('PermissionsCommandSecurityPanel', () => {
  it('shows a loading state before init arrives, then notifies ready', () => {
    expect(container.textContent).toContain('Loading command approval settings')
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('renders the empty whitelist state once init arrives', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    expect(container.textContent).toContain('No whitelisted commands yet')
  })

  it('sends a safeExecutionMode patch when the toggle is flipped', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    const toggle = container.querySelector('input[type="checkbox"]') as HTMLInputElement
    act(() => { toggle.click() })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateApprovalSetting', patch: { safeExecutionMode: true } }),
    )
  })

  it('disables an approval control until its matching intent result and surfaces a failure', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    const toggle = container.querySelector('input[type="checkbox"]') as HTMLInputElement
    act(() => { toggle.click() })
    const requestId = postMessage.mock.calls.find(([message]) => message.type === 'requestUpdateApprovalSetting')![0].requestId
    expect(toggle.disabled).toBe(true)
    act(() => { window.basilPermissionsCommandSecurity!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Save failed.' }) })
    expect(toggle.disabled).toBe(false)
    expect(container.textContent).toContain('Save failed.')
  })

  it('renders whitelist rows and sends requestDeleteWhitelistPattern on delete', () => {
    act(() => {
      window.basilPermissionsCommandSecurity!.onEvent(
        initEvent({}, [{ id: 'pat-1', pattern: 'git status', patternType: 'exact', description: '', addedDate: null, lastUsed: null, useCount: 3, riskLevel: 'low' }]),
      )
    })
    expect(container.textContent).toContain('git status')
    const deleteButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestDeleteWhitelistPattern', id: 'pat-1' }))
  })

  it('opens an edit form directly below the selected whitelist item', () => {
    act(() => {
      window.basilPermissionsCommandSecurity!.onEvent(
        initEvent({}, [
          { id: 'pat-1', pattern: 'git status', patternType: 'exact', description: '', addedDate: null, lastUsed: null, useCount: 3, riskLevel: 'low' },
          { id: 'pat-2', pattern: 'git log --oneline', patternType: 'prefix', description: '', addedDate: null, lastUsed: null, useCount: 1, riskLevel: 'low' },
        ]),
      )
    })
    const editButtons = Array.from(container.querySelectorAll('button')).filter((element) => element.textContent === 'Edit')
    act(() => { editButtons[1].click() })
    const items = container.querySelectorAll('.permissions-whitelist-item')
    expect(items[0].querySelector('.permissions-whitelist-form')).toBeNull()
    expect(items[1].querySelector('.permissions-whitelist-form input')?.getAttribute('value')).toBe('git log --oneline')
    expect(items[1].querySelectorAll('.permissions-pattern-type-option')).toHaveLength(3)
  })

  it('validates an empty pattern before submitting the add-pattern form', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    const addButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === '+ Add Pattern')!
    act(() => { addButton.click() })
    const submitButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Add Pattern')!
    expect(submitButton.hasAttribute('disabled')).toBe(true)
  })

  it('sends requestAddWhitelistPattern with the entered fields on submit', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    const addButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === '+ Add Pattern')!
    act(() => { addButton.click() })
    const patternInput = container.querySelector('input[type="text"]') as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      setter.call(patternInput, 'git status')
      patternInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const submitButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Add Pattern')!
    act(() => { submitButton.click() })
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestAddWhitelistPattern', pattern: 'git status', patternType: 'exact' }),
    )
  })

  it('keeps the whitelist form open when the native mutation fails', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent(initEvent()) })
    const addButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === '+ Add Pattern')!
    act(() => { addButton.click() })
    const patternInput = container.querySelector('input[type="text"]') as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      setter.call(patternInput, 'git status')
      patternInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const submitButton = Array.from(container.querySelectorAll('button')).find((el) => el.textContent === 'Add Pattern')!
    act(() => { submitButton.click() })
    const requestId = postMessage.mock.calls.find(([message]) => message.type === 'requestAddWhitelistPattern')![0].requestId
    act(() => { window.basilPermissionsCommandSecurity!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Pattern already exists.' }) })
    expect(container.textContent).toContain('Pattern already exists.')
    expect(container.querySelector<HTMLInputElement>('input[type="text"]')?.value).toBe('git status')
  })

  it('shows the loadError message and a retry action when native reports one', () => {
    act(() => { window.basilPermissionsCommandSecurity!.onEvent({ type: 'loadError', message: 'boom' }) })
    expect(container.textContent).toContain('boom')
    expect(container.textContent).toContain('Retry')
  })
})
