// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionApiModelsPanel } from './TranscriptionApiModelsPanel'
import type { TranscriptionApiModelSummary } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  act(() => {
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const MODELS: TranscriptionApiModelSummary[] = [
  { id: 'openai-whisper-1', displayName: 'Whisper (OpenAI API)', description: 'proven', enabled: true },
  { id: 'openai-gpt-4o-transcribe', displayName: 'GPT-4o Transcribe (OpenAI API)', description: 'accurate', enabled: false },
]

function sendInit(overrides: Record<string, unknown> = {}) {
  act(() => {
    window.basilTranscriptionApiModels!.onEvent({
      type: 'init',
      protocolVersion: 1,
      isLoading: false,
      useApiTranscriptionModels: true,
      openaiEnabled: true,
      openaiHasKey: true,
      models: MODELS,
      ...overrides,
    } as any)
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionApiModelsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<TranscriptionApiModelsPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('TranscriptionApiModelsPanel', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.transcription-api-models-status')?.textContent).toBe('Loading transcription API models...')
  })

  it('hides the provider section when the master toggle is off', () => {
    sendInit({ useApiTranscriptionModels: false })
    expect(container.textContent).not.toContain('OpenAI')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilTranscriptionApiModels!.onEvent({ type: 'loadError', message: 'Could not load transcription API models.' }) })
    expect(container.querySelector('.transcription-api-models-error p')?.textContent).toBe('Could not load transcription API models.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.transcription-api-models-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('toggles the master switch optimistically and sends the desired enabled value', () => {
    sendInit({ useApiTranscriptionModels: false })
    const checkbox = container.querySelector<HTMLInputElement>('#transcription-api-models-master-toggle')!
    act(() => { checkbox.click() })
    expect(lastMessageOfType('requestToggleMaster')).toEqual(expect.objectContaining({ enabled: true }))
    expect(checkbox.checked).toBe(true)
  })

  it('masks the API key input and clears it after a successful save', () => {
    sendInit()
    const input = container.querySelector<HTMLInputElement>('.transcription-api-models-key-input')!
    expect(input.type).toBe('password')
    typeInto(input, 'sk-test')
    const saveButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Update Key') as HTMLButtonElement
    act(() => { saveButton.click() })
    const requestId = lastMessageOfType('requestSaveApiKey')?.requestId
    expect(lastMessageOfType('requestSaveApiKey')?.key).toBe('sk-test')
    act(() => { window.basilTranscriptionApiModels!.onEvent({ type: 'intentResult', requestId, status: 'success', message: 'API key is valid and saved' }) })
    expect(input.value).toBe('')
    expect(container.querySelector('.transcription-api-models-status-success')?.textContent).toBe('API key is valid and saved')
  })

  it('keeps the typed key on a failed save and shows the validation error', () => {
    sendInit()
    const input = container.querySelector<HTMLInputElement>('.transcription-api-models-key-input')!
    typeInto(input, 'bad-key')
    const saveButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Update Key') as HTMLButtonElement
    act(() => { saveButton.click() })
    const requestId = lastMessageOfType('requestSaveApiKey')?.requestId
    act(() => { window.basilTranscriptionApiModels!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Invalid API key' }) })
    expect(input.value).toBe('bad-key')
    expect(container.querySelector('.transcription-api-models-status-error')?.textContent).toBe('Invalid API key')
  })

  it('toggles a model row and disables only that row while pending', () => {
    sendInit()
    const rows = container.querySelectorAll('.transcription-api-models-row')
    const secondRowSwitch = rows[1].querySelector<HTMLInputElement>('.basil-switch-input')!
    act(() => { secondRowSwitch.click() })
    expect(lastMessageOfType('requestToggleModel')).toEqual(expect.objectContaining({ modelId: 'openai-gpt-4o-transcribe', enabled: true }))
    expect(secondRowSwitch.disabled).toBe(true)
    expect(rows[0].querySelector<HTMLInputElement>('.basil-switch-input')!.disabled).toBe(false)
  })
})
