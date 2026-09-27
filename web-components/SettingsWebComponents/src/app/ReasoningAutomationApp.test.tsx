// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ReasoningAutomationApp } from './ReasoningAutomationApp'

let container: HTMLElement
let root: Root

beforeEach(() => {
  window.webkit = {
    messageHandlers: {
      basilReasoningDefaultsSettingsBridge: { postMessage: vi.fn() },
      basilBrowserAutomationSettingsBridge: { postMessage: vi.fn() },
      basilSkillsSettingsBridge: { postMessage: vi.fn() },
      basilProactiveSuggestionsSettingsBridge: { postMessage: vi.fn() },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ReasoningAutomationApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function subTab(label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab'))
    .find((button) => button.textContent === label)!
}

describe('ReasoningAutomationApp', () => {
  it('defaults to the Settings sub-tab, matching the native ReasoningSubTab order', () => {
    expect(subTab('Settings').getAttribute('aria-selected')).toBe('true')
    expect(subTab('Browser').getAttribute('aria-selected')).toBe('false')
    expect(subTab('Settings').getAttribute('aria-controls')).toBe('reasoning-automation-panel-settings')
    expect(container.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe('reasoning-automation-tab-settings')
    expect(container.querySelector('.reasoning-defaults-status')).not.toBeNull()
    expect(container.querySelector('.browser-automation-status')).toBeNull()
  })

  it('switches to the Browser sub-tab and mounts its own independent bridge and loading state', () => {
    act(() => { subTab('Browser').click() })
    expect(subTab('Browser').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.browser-automation-status')).not.toBeNull()
    expect(container.querySelector('.reasoning-defaults-status')).toBeNull()
  })

  it('supports standard arrow-key navigation between sub-tabs', () => {
    act(() => {
      subTab('Settings').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })
    expect(subTab('Browser').getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(subTab('Browser'))
  })

  it('unmounts the previous sub-tab so switching back reloads it fresh', () => {
    act(() => { subTab('Browser').click() })
    act(() => {
      window.basilBrowserAutomationSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: false,
        settings: {
          sensitiveFillPolicy: 'never',
          foregroundControlPolicy: 'background_only',
          defaultSessionMode: 'user_browser',
          preferredUserBrowser: 'system_default',
          approvedSensitiveFillDomains: [],
          showActionHighlights: true,
          recordBrowserActionTrace: false,
          allowVisualFallback: true,
        },
      })
    })
    expect(container.querySelector('.browser-automation-shell')).not.toBeNull()
    act(() => { subTab('Settings').click() })
    expect(container.querySelector('.browser-automation-shell')).toBeNull()
    expect(container.querySelector('.reasoning-defaults-status')).not.toBeNull()
  })

  it('switches to the Skills sub-tab and mounts its own independent bridge', () => {
    act(() => { subTab('Skills').click() })
    expect(subTab('Skills').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.skills-settings-status')).not.toBeNull()
    expect(container.querySelector('.reasoning-defaults-status')).toBeNull()
  })

  it('switches to the Proactive sub-tab and mounts its own independent bridge', () => {
    act(() => { subTab('Proactive').click() })
    expect(subTab('Proactive').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.proactive-suggestions-status')).not.toBeNull()
    expect(container.querySelector('.reasoning-defaults-status')).toBeNull()
  })

  it('supports ArrowRight wrapping from the last tab back to the first', () => {
    act(() => { subTab('Proactive').click() })
    act(() => {
      subTab('Proactive').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })
    expect(subTab('Settings').getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(subTab('Settings'))
  })

  it('labels the tablist "Automation & Agents"', () => {
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Automation & Agents')
  })

  it('honors an externally requested sub-tab on mount', () => {
    act(() => { root.unmount() })
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<ReasoningAutomationApp requestedSubTab="skills" />) })
    expect(subTab('Skills').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.skills-settings-status')).not.toBeNull()
  })
})
