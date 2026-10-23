// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ReasoningApiModelsPanel } from './ReasoningApiModelsPanel'
import type { ReasoningApiProviderSummary } from '../types'

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

const PROVIDERS: ReasoningApiProviderSummary[] = [
  {
    id: 'anthropic', name: 'Anthropic', enabled: true, usingOwnApiKey: true, hasKey: true,
    models: [{ id: 'claude-sonnet', name: 'Claude Sonnet', description: 'fast', capabilities: ['reasoning'], supportsExtendedThinking: true, enabled: false }],
  },
]

function sendInit(overrides: Record<string, unknown> = {}) {
  act(() => {
    window.basilReasoningApiModels!.onEvent({
      type: 'init', protocolVersion: 1, isLoading: false, useApiModels: true, providers: PROVIDERS, ...overrides,
    } as any)
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilReasoningApiModelsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ReasoningApiModelsPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ReasoningApiModelsPanel', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.reasoning-api-models-status')?.textContent).toBe('Loading reasoning API models...')
  })

  it('hides providers when the master toggle is off', () => {
    sendInit({ useApiModels: false })
    expect(container.textContent).not.toContain('Anthropic')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilReasoningApiModels!.onEvent({ type: 'loadError', message: 'Could not load reasoning API models.' }) })
    expect(container.querySelector('.reasoning-api-models-error p')?.textContent).toBe('Could not load reasoning API models.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-api-models-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('toggles the master switch and sends the desired enabled value', () => {
    sendInit({ useApiModels: false })
    const checkbox = container.querySelector<HTMLInputElement>('#reasoning-api-models-master-toggle')!
    act(() => { checkbox.click() })
    expect(lastMessageOfType('requestToggleMaster')).toEqual(expect.objectContaining({ enabled: true }))
    expect(checkbox.checked).toBe(true)
  })

  it('masks the API key input and clears it after a successful save', () => {
    sendInit()
    const input = container.querySelector<HTMLInputElement>('.reasoning-api-models-key-input')!
    expect(input.type).toBe('password')
    typeInto(input, 'sk-ant-test')
    const saveButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Update Key') as HTMLButtonElement
    act(() => { saveButton.click() })
    const requestId = lastMessageOfType('requestSaveApiKey')?.requestId
    expect(lastMessageOfType('requestSaveApiKey')).toEqual(expect.objectContaining({ providerId: 'anthropic', key: 'sk-ant-test' }))
    act(() => { window.basilReasoningApiModels!.onEvent({ type: 'intentResult', requestId, status: 'success', message: 'API key is valid and saved' }) })
    expect(input.value).toBe('')
    expect(container.querySelector('.reasoning-api-models-status-success')?.textContent).toBe('API key is valid and saved')
  })

  it('keeps the typed key on a failed save', () => {
    sendInit()
    const input = container.querySelector<HTMLInputElement>('.reasoning-api-models-key-input')!
    typeInto(input, 'bad-key')
    const saveButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Update Key') as HTMLButtonElement
    act(() => { saveButton.click() })
    const requestId = lastMessageOfType('requestSaveApiKey')?.requestId
    act(() => { window.basilReasoningApiModels!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Invalid API key' }) })
    expect(input.value).toBe('bad-key')
    expect(container.querySelector('.reasoning-api-models-status-error')?.textContent).toBe('Invalid API key')
  })

  it('toggles a model row for the owning provider and disables only that row', () => {
    sendInit()
    const providerSwitch = container.querySelector<HTMLInputElement>('#reasoning-api-models-provider-toggle-anthropic')!
    const rowSwitch = container.querySelector<HTMLInputElement>('#reasoning-api-models-toggle-anthropic-claude-sonnet')!
    expect(providerSwitch.getAttribute('aria-label')).toBe('Enable Anthropic provider')
    expect(rowSwitch.getAttribute('aria-label')).toBe('Enable Claude Sonnet')
    act(() => { rowSwitch.click() })
    expect(lastMessageOfType('requestToggleModel')).toEqual(expect.objectContaining({ providerId: 'anthropic', modelId: 'claude-sonnet', enabled: true }))
    expect(rowSwitch.disabled).toBe(true)
  })

  it('uses provider-scoped model switch IDs when providers share a model ID', () => {
    sendInit({
      providers: [
        PROVIDERS[0],
        { ...PROVIDERS[0], id: 'openai', name: 'OpenAI', models: [{ ...PROVIDERS[0].models[0], name: 'GPT-4o' }] },
      ],
    })
    expect(container.querySelector('#reasoning-api-models-toggle-anthropic-claude-sonnet')).not.toBeNull()
    expect(container.querySelector('#reasoning-api-models-toggle-openai-claude-sonnet')).not.toBeNull()
  })

  it('turning BYOK on without a saved key reveals the entry form without a bridge call', () => {
    sendInit({
      providers: [{ ...PROVIDERS[0], usingOwnApiKey: false, hasKey: false, models: [{ ...PROVIDERS[0].models[0], enabled: true }] }],
    })
    postMessage.mockClear()
    const byok = container.querySelector<HTMLInputElement>('#reasoning-api-models-key-source-anthropic')!
    expect(byok.closest('label')?.textContent).toBe('Use your Anthropic API key')
    act(() => { byok.click() })
    expect(postMessage).not.toHaveBeenCalled()
    expect(container.querySelector<HTMLInputElement>('#reasoning-api-models-toggle-anthropic-claude-sonnet')!.checked).toBe(false)
    sendInit({
      type: 'snapshot',
      providers: [{ ...PROVIDERS[0], usingOwnApiKey: false, hasKey: false, models: [{ ...PROVIDERS[0].models[0], enabled: true }] }],
    })
    expect(container.querySelector<HTMLInputElement>('#reasoning-api-models-toggle-anthropic-claude-sonnet')!.checked).toBe(false)
    expect(container.querySelector<HTMLInputElement>('#reasoning-api-models-key-source-anthropic')!.checked).toBe(true)
  })

  it('turning BYOK on when a key is already saved confirms it with the backend immediately', () => {
    sendInit({
      providers: [{ ...PROVIDERS[0], usingOwnApiKey: false, hasKey: true }],
    })
    postMessage.mockClear()
    const byok = container.querySelector<HTMLInputElement>('#reasoning-api-models-key-source-anthropic')!
    act(() => { byok.click() })
    expect(lastMessageOfType('requestToggleProviderKeySource')).toEqual(
      expect.objectContaining({ providerId: 'anthropic', useOwnKey: true }),
    )
    expect(byok.checked).toBe(true)
  })

  it('requires inline confirmation before requesting removal of a saved key', () => {
    sendInit()
    postMessage.mockClear()
    const removeButton = container.querySelector<HTMLButtonElement>('.reasoning-api-models-key-remove-button')!
    act(() => { removeButton.click() })
    expect(lastMessageOfType('requestRemoveApiKey')).toBeUndefined()
    expect(container.querySelector('.reasoning-api-models-key-remove-confirm-title')?.textContent).toBe('Remove your Anthropic API key?')
    expect(container.querySelector('.reasoning-api-models-key-input')).toBeNull()

    const cancel = Array.from(container.querySelectorAll<HTMLButtonElement>('.reasoning-api-models-key-remove-confirm button')).find((button) => button.textContent === 'Cancel')!
    act(() => { cancel.click() })
    expect(container.querySelector('.reasoning-api-models-key-remove-confirm')).toBeNull()
    expect(container.querySelector('.reasoning-api-models-key-input')).not.toBeNull()
    expect(lastMessageOfType('requestRemoveApiKey')).toBeUndefined()
  })

  it('removes a saved key after confirmation and reflects the refreshed snapshot', () => {
    sendInit()
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-api-models-key-remove-button')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-api-models-key-remove-confirm-button')!.click() })
    const request = lastMessageOfType('requestRemoveApiKey')
    expect(request).toEqual(expect.objectContaining({ providerId: 'anthropic' }))
    expect(container.querySelector('.reasoning-api-models-key-remove-confirm-button')?.textContent).toBe('Removing...')
    expect(container.querySelector<HTMLInputElement>('#reasoning-api-models-key-source-anthropic')!.disabled).toBe(true)

    act(() => {
      window.basilReasoningApiModels!.onEvent({
        type: 'snapshot', isLoading: false, useApiModels: true,
        providers: [{ ...PROVIDERS[0], usingOwnApiKey: false, hasKey: false }],
      })
      window.basilReasoningApiModels!.onEvent({ type: 'intentResult', requestId: request.requestId, status: 'success' })
    })
    expect(container.querySelector('.reasoning-api-models-key-remove-button')).toBeNull()
    expect(container.querySelector('.reasoning-api-models-key-remove-confirm')).toBeNull()
    expect(container.querySelector<HTMLInputElement>('#reasoning-api-models-key-source-anthropic')!.checked).toBe(false)
    expect(container.querySelector('.reasoning-api-models-status-success')?.textContent).toBe('Your API key was removed from this Mac.')
  })

  it('keeps the saved key visible and shows the error when removal fails', () => {
    sendInit()
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-api-models-key-remove-button')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.reasoning-api-models-key-remove-confirm-button')!.click() })
    const request = lastMessageOfType('requestRemoveApiKey')
    act(() => {
      window.basilReasoningApiModels!.onEvent({ type: 'intentResult', requestId: request.requestId, status: 'error', message: 'Keychain unavailable' })
    })
    expect(container.querySelector('.reasoning-api-models-key-remove-button')).not.toBeNull()
    expect(container.querySelector('.reasoning-api-models-status-error')?.textContent).toBe('Keychain unavailable')
  })

  it('links to where to get an API key for a provider', () => {
    sendInit()
    const explainer = container.querySelector('.reasoning-api-models-key-explainer')!
    const link = explainer.querySelector('a')!
    expect(link.textContent).toBe('Get your Anthropic API key')
    expect(link.getAttribute('href')).toBe('https://console.anthropic.com/settings/keys')
  })

  it('shows available/enabled counts in the provider header and toggles the collapse disclosure', () => {
    sendInit()
    const header = container.querySelector('.reasoning-api-models-provider-header')!
    expect(header.textContent).toContain('1 available')
    expect(header.textContent).toContain('0 enabled')

    const disclosure = container.querySelector<HTMLButtonElement>('.reasoning-api-models-provider-disclosure')!
    expect(disclosure.getAttribute('aria-expanded')).toBe('true')
    act(() => { disclosure.click() })
    expect(disclosure.getAttribute('aria-expanded')).toBe('false')
    act(() => { disclosure.click() })
    expect(disclosure.getAttribute('aria-expanded')).toBe('true')
  })

  it('disables the disclosure and reflects the enabled count when a model is toggled on', () => {
    sendInit({ providers: [{ ...PROVIDERS[0], enabled: false }] })
    const disclosure = container.querySelector<HTMLButtonElement>('.reasoning-api-models-provider-disclosure')!
    expect(disclosure.disabled).toBe(true)
    expect(disclosure.getAttribute('aria-expanded')).toBe('false')
    expect(disclosure.hasAttribute('aria-controls')).toBe(false)

    sendInit({ providers: [{ ...PROVIDERS[0], models: [{ ...PROVIDERS[0].models[0], enabled: true }] }] })
    const header = container.querySelector('.reasoning-api-models-provider-header')!
    expect(header.textContent).toContain('1 enabled')
  })
})
