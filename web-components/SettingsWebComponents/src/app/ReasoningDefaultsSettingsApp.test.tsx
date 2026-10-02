// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { fireEvent } from '@testing-library/react'
import { createRoot, type Root } from 'react-dom/client'
import { ReasoningDefaultsSettingsApp } from './ReasoningDefaultsSettingsApp'
import type { ReasoningDefaultsSettingsSnapshot } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: ReasoningDefaultsSettingsSnapshot = {
  localModels: [{ id: 'local-1', name: 'local-1', displayName: 'Local One', provider: 'ollama', isApiModel: false }],
  apiModels: [{ id: 'gpt-5', name: 'gpt-5', displayName: 'GPT-5', provider: 'openai', isApiModel: true }],
  customModels: [],
  selectedModelId: 'local-1',
  useApiModels: true,
  closeAssistantSessionOnInsert: false,
  assistantOutputPasteMode: 'always',
  useRegionSelection: false,
  agentTaskDefaultModality: 'voice',
  agentTaskAutoReopenOnCompletion: true,
  agentTaskPushToTalk: true,
  agentTaskPushToTalkThreshold: 750,
  assistantSessionDefaultModality: 'speak',
  assistantSessionPushToTalk: false,
  assistantSessionPushToTalkThreshold: 900,
}

function sendInit(overrides: Partial<ReasoningDefaultsSettingsSnapshot> = {}) {
  act(() => {
    window.basilReasoningDefaultsSettings!.onEvent({
      type: 'init', protocolVersion: 1, isLoading: false, settings: { ...SETTINGS, ...overrides },
    })
  })
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilReasoningDefaultsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ReasoningDefaultsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ReasoningDefaultsSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.reasoning-defaults-status')?.textContent).toBe('Loading Automation & Agents settings...')
  })

  it('renders loaded settings, including the grouped model select and toggle values', () => {
    sendInit()
    const modelSelect = container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')!
    expect(modelSelect.textContent).toContain('Local One')
    act(() => { modelSelect.click() })
    expect(document.querySelector('[role="listbox"]')?.textContent).toContain('Local Models')
    expect(document.querySelector('[role="listbox"]')?.textContent).toContain('GPT-5')
    expect(container.querySelector<HTMLInputElement>('input[name="assistant-output-paste-mode"][value="always"]')!.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#reasoning-defaults-close-on-insert')!.checked).toBe(false)
  })

  it('hides the API Models optgroup when useApiModels is false', () => {
    sendInit({ useApiModels: false })
    expect(container.textContent).not.toContain('GPT-5')
  })

  it('shows the no-models hint and disables the select when every source is empty', () => {
    sendInit({ localModels: [], apiModels: [], customModels: [], useApiModels: false, selectedModelId: '' })
    expect(container.textContent).toContain('No reasoning models available')
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')!.disabled).toBe(true)
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilReasoningDefaultsSettings!.onEvent({ type: 'loadError', message: 'Could not load reasoning defaults settings.' }) })
    expect(container.querySelector('.reasoning-defaults-error p')?.textContent).toBe('Could not load reasoning defaults settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-defaults-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends a correlated update when the model select changes and keeps every other control interactive while pending', () => {
    sendInit()
    const select = container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')!
    act(() => { select.click() })
    const gptOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'GPT-5')!
    act(() => { gptOption.click() })
    expect(lastMessageOfType('requestUpdateSelectedModel')).toEqual(expect.objectContaining({ modelId: 'gpt-5' }))
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')!.textContent).toContain('GPT-5')
    expect(container.querySelector<HTMLInputElement>('input[name="assistant-output-paste-mode"][value="never"]')!.disabled).toBe(false)
  })

  it('keeps overlapping changes and reverts only the one native rejects', () => {
    sendInit()
    const pasteModeRadio = (mode: string) => container.querySelector<HTMLInputElement>(`input[name="assistant-output-paste-mode"][value="${mode}"]`)!
    const regionSelection = container.querySelector<HTMLInputElement>('#reasoning-defaults-region-selection')!
    act(() => { pasteModeRadio('never').click() })
    const pasteModeRequestId = postMessage.mock.calls[postMessage.mock.calls.length - 1][0].requestId
    act(() => { regionSelection.click() })
    expect(pasteModeRadio('never').checked).toBe(true)
    expect(regionSelection.checked).toBe(true)
    expect(container.querySelector('.settings-visually-hidden')?.textContent).toBe('Saving setting...')
    act(() => {
      window.basilReasoningDefaultsSettings!.onEvent({ type: 'intentResult', requestId: pasteModeRequestId, status: 'error', message: 'Could not save the paste setting.' })
    })
    expect(pasteModeRadio('always').checked).toBe(true)
    expect(regionSelection.checked).toBe(true)
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not save the paste setting.')
  })

  it('sends a correlated paste-mode update and shows the selected option description', () => {
    sendInit()
    act(() => { container.querySelector<HTMLInputElement>('input[name="assistant-output-paste-mode"][value="auto"]')!.click() })
    expect(lastMessageOfType('requestUpdateAssistantOutputPasteMode')).toEqual(expect.objectContaining({ mode: 'auto' }))
    expect(container.textContent).toContain('Paste drafts, replies, and rewrites')
    expect(container.textContent).toContain('Let Basil decide')
  })

  it('clears pending state and surfaces an error only for the correlated failure', () => {
    sendInit()
    const closeToggle = container.querySelector<HTMLInputElement>('#reasoning-defaults-close-on-insert')!
    act(() => { closeToggle.click() })
    const requestId = lastMessageOfType('requestUpdateCloseAssistantSessionOnInsert')!.requestId
    act(() => { window.basilReasoningDefaultsSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to update the close-on-insert setting.' }) })
    expect(container.querySelector('.reasoning-defaults-inline-error')?.textContent).toBe('Failed to update the close-on-insert setting.')
    expect(closeToggle.disabled).toBe(false)
  })

  it('commits a typed AgentTask threshold on blur and clamps it to 500-5000ms', () => {
    sendInit()
    const numberInput = container.querySelector<HTMLInputElement>('#agent-task-threshold-input')!
    expect(numberInput).not.toBeNull()
    act(() => { fireEvent.change(numberInput, { target: { value: '9999' } }) })
    expect(lastMessageOfType('requestUpdateAgentTaskPushToTalkThreshold')).toBeUndefined()
    expect(numberInput.disabled).toBe(false)
    act(() => { fireEvent.blur(numberInput) })
    expect(lastMessageOfType('requestUpdateAgentTaskPushToTalkThreshold')).toEqual(expect.objectContaining({ thresholdMs: 5000 }))
  })

  it('hides the AssistantSession threshold slider when push-to-talk is disabled', () => {
    sendInit()
    expect(container.querySelector('#assistant-session-threshold-input')).toBeNull()
  })

  it('sends a correlated AgentTask modality update from the radio group', () => {
    sendInit()
    const textRadio = container.querySelector<HTMLInputElement>('input[name="agent-task-default-modality"][value="text"]')!
    act(() => { textRadio.click() })
    expect(lastMessageOfType('requestUpdateAgentTaskDefaultModality')).toEqual(expect.objectContaining({ modality: 'text' }))
  })

  it('keeps the loading state when init arrives without settings', () => {
    act(() => {
      window.basilReasoningDefaultsSettings!.onEvent({ type: 'init', protocolVersion: 1, isLoading: true, settings: null })
    })
    expect(container.querySelector('.reasoning-defaults-status')?.textContent).toBe('Loading Automation & Agents settings...')
  })
})
