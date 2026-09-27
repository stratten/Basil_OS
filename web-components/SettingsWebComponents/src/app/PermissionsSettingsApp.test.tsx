// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { PermissionsSettingsApp } from './PermissionsSettingsApp'

let container: HTMLElement
let root: Root

beforeEach(() => {
  window.webkit = {
    messageHandlers: {
      basilPermissionsApplicationBridge: { postMessage: vi.fn() },
      basilPermissionsCommandSecurityBridge: { postMessage: vi.fn() },
    },
  }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<PermissionsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('PermissionsSettingsApp', () => {
  it('defaults to the Application sub-tab', () => {
    const applicationTab = container.querySelector('[role="tab"]')!
    expect(applicationTab.getAttribute('aria-selected')).toBe('true')
    expect(container.textContent).toContain('Application Permissions')
  })

  it('switches to the Command Security sub-tab on click without unmounting the Application panel state', () => {
    const commandSecurityTab = Array.from(container.querySelectorAll('[role="tab"]')).find((el) => el.textContent === 'Command Security')!
    act(() => { (commandSecurityTab as HTMLButtonElement).click() })
    expect(commandSecurityTab.getAttribute('aria-selected')).toBe('true')
    expect(container.textContent).toContain('Loading command approval settings')
  })

  it('mounts both panels immediately so switching tabs never re-triggers a native load', () => {
    expect(container.textContent).toContain('Application Permissions')
    const applicationHidden = container.querySelector('.permissions-sub-tab-hidden')
    expect(applicationHidden?.textContent).toContain('Loading command approval settings')
  })

  it('uses linked ARIA tabs and supports ArrowRight keyboard navigation', () => {
    const applicationTab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === 'Application')!
    expect(applicationTab.getAttribute('aria-controls')).toBe('permissions-sub-panel-application')
    expect(container.querySelector('#permissions-sub-panel-application')?.getAttribute('aria-labelledby')).toBe(applicationTab.id)
    act(() => { applicationTab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    const commandSecurityTab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === 'Command Security')!
    expect(commandSecurityTab.getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(commandSecurityTab)
  })

  it('honors an externally requested sub-tab on mount', () => {
    act(() => { root.unmount() })
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<PermissionsSettingsApp requestedSubTab="command-security" />) })
    const commandSecurityTab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === 'Command Security')!
    expect(commandSecurityTab.getAttribute('aria-selected')).toBe('true')
  })
})
