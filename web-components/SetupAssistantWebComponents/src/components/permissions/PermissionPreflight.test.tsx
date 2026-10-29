// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

vi.mock('@shared/swiftBridge', () => ({ postToSwiftHandler: vi.fn() }))
vi.mock('@/services/bridge', () => ({
  closeSetupAssistant: vi.fn(),
  continueSetupAssistant: vi.fn(),
  openSystemSettings: vi.fn(),
  requestPermission: vi.fn(),
  restartApplication: vi.fn(),
}))

import { PermissionPreflight } from './PermissionPreflight'

let container: HTMLElement
let root: Root

function render(isReturningUserCheck: boolean) {
  window.basilSetupAssistantConfig = { isReturningUserCheck } as typeof window.basilSetupAssistantConfig
  act(() => {
    root.render(<PermissionPreflight />)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  window.basilSetupAssistantConfig = undefined
})

describe('PermissionPreflight copy', () => {
  it('frames the first-run screen as the step before setup, not the last step', () => {
    render(false)

    expect(container.querySelector('h1')?.textContent).toBe('Permissions')
    expect(container.textContent).toContain('Before we start, grant these permissions.')
    expect(container.textContent).not.toContain('Last step')
  })

  it('keeps the returning-user copy for a user whose permissions need rechecking', () => {
    render(true)

    expect(container.querySelector('h1')?.textContent).toBe('Welcome Back')
    expect(container.textContent).toContain('confirm your permissions are still set')
    expect(container.textContent).not.toContain('Before we start')
  })
})
