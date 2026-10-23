// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ProactiveSuggestionsSettingsApp } from './ProactiveSuggestionsSettingsApp'
import type { ProactiveSuggestionsSettingsSnapshot } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: ProactiveSuggestionsSettingsSnapshot = {
  enabled: true,
  mode: 'suggestion_only',
  frequencySeconds: 120,
  evaluationModel: 'local-model-a',
  selectedEvaluationModelIsUnavailable: false,
  minimumConfidence: 0.75,
  cooldownMinutes: 30,
  enabledCapabilities: ['assistant_session'],
  autoExecuteCapabilities: [],
  excludedAppNames: ['Terminal'],
  localModels: [{ id: 'local-model-a', displayName: 'Local Model A', provider: 'local', isLocal: true }],
  apiModels: [{ id: 'api-model-a', displayName: 'API Model A', provider: 'openai', isLocal: false }],
}

function sendInit(overrides: Partial<ProactiveSuggestionsSettingsSnapshot> = {}) {
  act(() => {
    window.basilProactiveSuggestionsSettings!.onEvent({
      type: 'init', protocolVersion: 1, isLoading: false, settings: { ...SETTINGS, ...overrides },
    })
  })
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

function setNativeTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
  setter.call(textarea, value)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilProactiveSuggestionsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ProactiveSuggestionsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ProactiveSuggestionsSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.proactive-suggestions-status')?.textContent).toBe('Loading Proactive Suggestions settings...')
  })

  it('renders loaded settings, including the mode radio, evaluator model groups, and exclusions', () => {
    sendInit()
    expect(container.querySelector<HTMLInputElement>('#proactive-suggestions-enabled')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('input[name="proactive-suggestions-mode"][value="suggestion_only"]')!.checked).toBe(true)
    const evaluatorModel = container.querySelector<HTMLButtonElement>('[aria-label="Evaluator model"]')!
    expect(evaluatorModel.textContent).toContain('Local Model A')
    act(() => { evaluatorModel.click() })
    expect(document.querySelector('[role="listbox"]')?.textContent).toContain('Local Models')
    expect(document.querySelector('[role="listbox"]')?.textContent).toContain('API Model A')
    expect(container.querySelector<HTMLTextAreaElement>('[aria-label="Excluded app names"]')!.value).toBe('Terminal')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilProactiveSuggestionsSettings!.onEvent({ type: 'loadError', message: 'Could not load Proactive Suggestions settings.' }) })
    expect(container.querySelector('.proactive-suggestions-error p')?.textContent).toBe('Could not load Proactive Suggestions settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.proactive-suggestions-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a correlated update when the enable toggle changes and keeps every other control interactive while pending', () => {
    sendInit()
    const enabledToggle = container.querySelector<HTMLInputElement>('#proactive-suggestions-enabled')!
    act(() => { enabledToggle.click() })
    expect(lastMessageOfType('requestUpdateEnabled')).toEqual(expect.objectContaining({ enabled: false }))
    expect(enabledToggle.checked).toBe(false)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Evaluator model"]')!.disabled).toBe(false)
  })

  it('clears pending state and surfaces an error only for the correlated failure', () => {
    sendInit()
    const enabledToggle = container.querySelector<HTMLInputElement>('#proactive-suggestions-enabled')!
    act(() => { enabledToggle.click() })
    const requestId = lastMessageOfType('requestUpdateEnabled')!.requestId
    act(() => { window.basilProactiveSuggestionsSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Error updating Proactive Suggestions enabled state' }) })
    expect(container.querySelector('.proactive-suggestions-inline-error')?.textContent).toBe('Error updating Proactive Suggestions enabled state')
    expect(enabledToggle.disabled).toBe(false)
  })

  it('disables auto-execute capability toggles unless mode is auto_execute', () => {
    sendInit()
    expect(container.querySelector<HTMLInputElement>('#proactive-suggestions-auto-execute-assistant_session')!.disabled).toBe(true)
    sendInit({ mode: 'auto_execute' })
    expect(container.querySelector<HTMLInputElement>('#proactive-suggestions-auto-execute-assistant_session')!.disabled).toBe(false)
  })

  it('sends the correlated capability update and keeps auto-execute in sync when disabling an enabled capability', () => {
    sendInit({ mode: 'auto_execute', enabledCapabilities: ['assistant_session'], autoExecuteCapabilities: ['assistant_session'] })
    const enabledCheckbox = container.querySelector<HTMLInputElement>('#proactive-suggestions-enabled-assistant_session')!
    act(() => { enabledCheckbox.click() })
    expect(lastMessageOfType('requestUpdateEnabledCapability')).toEqual(expect.objectContaining({ capability: 'assistant_session', enabled: false }))
    expect(container.querySelector<HTMLInputElement>('#proactive-suggestions-auto-execute-assistant_session')!.checked).toBe(false)
  })

  it('applies exclusions as a trimmed, non-empty line list', () => {
    sendInit()
    const textarea = container.querySelector<HTMLTextAreaElement>('[aria-label="Excluded app names"]')!
    act(() => { setNativeTextareaValue(textarea, ' Finder \n\nMail ') })
    const applyButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Apply Exclusions')!
    act(() => { applyButton.click() })
    expect(lastMessageOfType('requestUpdateExcludedAppNames')).toEqual(expect.objectContaining({ excludedAppNames: ['Finder', 'Mail'] }))
  })
})
