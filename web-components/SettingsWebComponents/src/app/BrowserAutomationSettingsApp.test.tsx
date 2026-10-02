// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { BrowserAutomationSettingsApp } from './BrowserAutomationSettingsApp'
import type { BrowserAutomationSettingsSnapshot } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: BrowserAutomationSettingsSnapshot = {
  sensitiveFillPolicy: 'ask_every_time',
  foregroundControlPolicy: 'ask_before_foreground',
  defaultSessionMode: 'user_browser',
  preferredUserBrowser: 'system_default',
  approvedSensitiveFillDomains: [
    { domain: 'example.com', createdAt: '', lastUsed: '', useCount: 2, allowSensitiveFill: true },
  ],
  showActionHighlights: true,
  recordBrowserActionTrace: false,
  allowVisualFallback: true,
}

function sendInit(overrides: Partial<BrowserAutomationSettingsSnapshot> = {}) {
  act(() => {
    window.basilBrowserAutomationSettings!.onEvent({
      type: 'init', protocolVersion: 1, isLoading: false, settings: { ...SETTINGS, ...overrides },
    })
  })
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilBrowserAutomationSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<BrowserAutomationSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('BrowserAutomationSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.browser-automation-status')?.textContent).toBe('Loading Browser Automation settings...')
  })

  it('renders loaded settings, including toggle values and the remembered domain list', () => {
    sendInit()
    expect(container.querySelector<HTMLInputElement>('input[name="preferred-user-browser"][value="system_default"]')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#browser-automation-show-highlights')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#browser-automation-record-trace')!.checked).toBe(false)
    expect(container.textContent).toContain('example.com')
    expect(container.textContent).toContain('Used 2 times')
  })

  it('groups related policies into paired columns and describes the selected sensitive-fill policy', () => {
    sendInit({ sensitiveFillPolicy: 'approved_domains' })
    const headings = Array.from(container.querySelectorAll('.browser-automation-section > h2')).map((heading) => heading.textContent)
    expect(headings).toEqual(['Browser Automation', 'Browser Sessions', 'Control & Safety', 'Action Feedback & Fallback'])
    const columnLegends = Array.from(container.querySelectorAll('.browser-automation-columns')).map((columns) =>
      Array.from(columns.querySelectorAll(':scope > .browser-automation-column')).map((column) => column.querySelector('legend')?.textContent))
    expect(columnLegends).toEqual([['Preferred User Browser', 'Default Browser Session'], ['Foreground Browser Control', 'Sensitive Fill Policy']])
    const sensitiveColumn = container.querySelector('input[name="sensitive-fill-policy"]')!.closest('.browser-automation-column')!
    expect(sensitiveColumn.textContent).toContain('without asking on the remembered domains below')
    expect(sensitiveColumn.textContent).toContain('example.com')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilBrowserAutomationSettings!.onEvent({ type: 'loadError', message: 'Could not load browser automation settings.' }) })
    expect(container.querySelector('.browser-automation-error p')?.textContent).toBe('Could not load browser automation settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.browser-automation-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a correlated update when a radio option changes and keeps every other control interactive while pending', () => {
    sendInit()
    const chromeRadio = container.querySelector<HTMLInputElement>('input[name="preferred-user-browser"][value="chrome"]')!
    act(() => { chromeRadio.click() })
    expect(lastMessageOfType('requestUpdatePreferredUserBrowser')).toEqual(expect.objectContaining({ browser: 'chrome' }))
    expect(chromeRadio.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#browser-automation-show-highlights')!.disabled).toBe(false)
  })

  it('clears pending state and surfaces an error only for the correlated failure', () => {
    sendInit()
    const highlights = container.querySelector<HTMLInputElement>('#browser-automation-show-highlights')!
    act(() => { highlights.click() })
    const requestId = lastMessageOfType('requestUpdateShowActionHighlights')!.requestId
    act(() => { window.basilBrowserAutomationSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to update action highlights.' }) })
    expect(container.querySelector('.browser-automation-inline-error')?.textContent).toBe('Failed to update action highlights.')
    expect(highlights.disabled).toBe(false)
  })

  it('removes a remembered domain optimistically and sends the correlated request', () => {
    sendInit()
    const removeButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Remove')!
    act(() => { removeButton.click() })
    expect(lastMessageOfType('requestRemoveRememberedDomain')).toEqual(expect.objectContaining({ domain: 'example.com' }))
    expect(container.textContent).not.toContain('example.com')
  })

  it('clears the automation browser profile with no confirmation, matching the legacy subtab', () => {
    sendInit()
    const clearButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Clear Basil Automation Browser Profile')!
    act(() => { clearButton.click() })
    expect(lastMessageOfType('requestClearAutomationBrowserProfile')).toEqual(expect.objectContaining({ type: 'requestClearAutomationBrowserProfile' }))
  })
})
