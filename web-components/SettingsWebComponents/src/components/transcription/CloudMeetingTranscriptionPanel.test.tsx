// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { CloudMeetingTranscriptionPanel, resetCloudMeetingTranscriptionCache } from './CloudMeetingTranscriptionPanel'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function backendState(overrides: Record<string, unknown> = {}) {
  return {
    enabled: false,
    provider: 'deepgram',
    connection: 'own_key',
    acknowledged: false,
    account_available: false,
    providers: [
      { id: 'deepgram', label: 'Deepgram', has_key: false },
      { id: 'assemblyai', label: 'AssemblyAI', has_key: false },
    ],
    status: { state: 'off', provider: null, tier: null, reason: null },
    ...overrides,
  }
}

function sendState(overrides: Record<string, unknown> = {}) {
  act(() => { window.basilCloudTranscription!.onEvent({ type: 'state', state: backendState(overrides) }) })
}

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

function click(element: Element | null) {
  expect(element).not.toBeNull()
  act(() => { (element as HTMLElement).click() })
}

function buttonByText(text: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === text)
  expect(found, `button "${text}"`).toBeDefined()
  return found as HTMLButtonElement
}

function inputByLabel(text: string): HTMLInputElement {
  const label = Array.from(container.querySelectorAll('label')).find((item) => item.textContent?.includes(text))
  expect(label, `label "${text}"`).toBeDefined()
  return label!.querySelector('input') as HTMLInputElement
}

function result(requestId: string, status: 'success' | 'error', message?: string) {
  act(() => { window.basilCloudTranscription!.onEvent({ type: 'intentResult', requestId, status, message }) })
}

beforeEach(() => {
  resetCloudMeetingTranscriptionCache()
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilCloudTranscriptionBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<CloudMeetingTranscriptionPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('CloudMeetingTranscriptionPanel', () => {
  it('asks the host for the state on mount and shows loading until it arrives', () => {
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    expect(container.textContent).toContain('Loading cloud meeting transcription...')
  })

  it('shows a load error with a retry that asks again', () => {
    act(() => { window.basilCloudTranscription!.onEvent({ type: 'loadError', message: 'Could not load the cloud transcription settings.' }) })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not load the cloud transcription settings.')
    postMessage.mockClear()
    click(buttonByText('Retry'))
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('rejects a state it cannot parse', () => {
    act(() => { window.basilCloudTranscription!.onEvent({ type: 'state', state: { enabled: 'yes' } }) })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Basil returned cloud transcription settings it could not read.')
  })

  it('keeps the switch off until the disclosure is confirmed, saves the confirmation at once, then lets the switch turn on', () => {
    sendState({ providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] })
    expect(container.textContent).toContain('live meeting audio is sent to that service')
    const toggle = container.querySelector('#cloud-meeting-transcription-toggle') as HTMLInputElement
    expect(toggle.disabled).toBe(true)
    expect(container.textContent).toContain('Confirm the statement above first.')
    click(inputByLabel('I understand that live meeting audio will be sent'))
    expect(lastMessageOfType('requestUpdateSettings').patch).toEqual({ acknowledge_disclosure: true })
    expect(toggle.disabled).toBe(false)
    click(toggle)
    expect(lastMessageOfType('requestUpdateSettings').patch).toEqual({ enabled: true, acknowledge_disclosure: true })
  })

  it('words the switch as the default and says saved services stay available for a single recording', () => {
    sendState({ acknowledged: true })
    expect(container.textContent).toContain('Use cloud transcription by default')
    expect(container.textContent).toContain("stays in the Notetaker's model menu either way")
  })

  it('skips the confirmation once acknowledged and can turn the switch off', () => {
    sendState({ enabled: true, acknowledged: true })
    expect(container.textContent).not.toContain('I understand that live meeting audio')
    click(container.querySelector('#cloud-meeting-transcription-toggle'))
    expect(lastMessageOfType('requestUpdateSettings')).toMatchObject({ patch: { enabled: false } })
  })

  it('chooses the connection and the service', () => {
    sendState({ acknowledged: true })
    click(inputByLabel('AssemblyAI'))
    const first = lastMessageOfType('requestUpdateSettings')
    expect(first.patch).toEqual({ provider: 'assemblyai' })
    result(first.requestId, 'success')
    click(inputByLabel('My Basil account'))
    expect(lastMessageOfType('requestUpdateSettings').patch).toEqual({ connection: 'basil_account' })
  })

  it('hides the key controls and explains sign-in for the account connection', () => {
    sendState({ connection: 'basil_account', acknowledged: true, account_available: false })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    expect(container.textContent).toContain('Sign in to Basil to use your account.')
  })

  it('saves a trimmed key, clears the field once saved and never shows the key back', () => {
    sendState({ acknowledged: true })
    const input = container.querySelector('input[type="password"]') as HTMLInputElement
    expect(buttonByText('Save Key').disabled).toBe(true)
    typeInto(input, 'short')
    expect(buttonByText('Save Key').disabled).toBe(true)
    typeInto(input, '  dg-key-123456  ')
    expect(buttonByText('Save Key').disabled).toBe(false)
    click(buttonByText('Save Key'))
    const message = lastMessageOfType('requestSaveKey')
    expect(message).toMatchObject({ provider: 'deepgram', key: 'dg-key-123456' })
    expect(input.value).toBe('  dg-key-123456  ')
    sendState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] })
    result(message.requestId, 'success')
    expect(input.value).toBe('')
    expect(container.textContent).toContain('Deepgram (key saved)')
    expect(container.textContent).not.toContain('dg-key-123456')
  })

  it('keeps the draft and shows the host error when saving the key fails', () => {
    sendState({ acknowledged: true })
    const input = container.querySelector('input[type="password"]') as HTMLInputElement
    typeInto(input, 'dg-key-123456')
    click(buttonByText('Save Key'))
    result(lastMessageOfType('requestSaveKey').requestId, 'error', 'Could not save the key to the system credential store.')
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not save the key to the system credential store.')
    expect(input.value).toBe('dg-key-123456')
  })

  it('tests and removes a saved key and shows the check result', () => {
    sendState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] })
    click(buttonByText('Test Connection'))
    const check = lastMessageOfType('requestCheck')
    expect(check).toMatchObject({ provider: 'deepgram' })
    result(check.requestId, 'error', 'Deepgram rejected the API key.')
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Deepgram rejected the API key.')
    click(buttonByText('Test Connection'))
    result(lastMessageOfType('requestCheck').requestId, 'success', 'Connected to Deepgram. No meeting audio was sent.')
    expect(container.querySelector('[role="status"]')?.textContent).toBe('Connected to Deepgram. No meeting audio was sent.')
    click(buttonByText('Remove Key'))
    expect(lastMessageOfType('requestRemoveKey')).toMatchObject({ provider: 'deepgram' })
  })

  it('disables test and remove when no key is saved for the selected service', () => {
    sendState({ acknowledged: true })
    expect(buttonByText('Test Connection').disabled).toBe(true)
    expect(buttonByText('Remove Key').disabled).toBe(true)
  })

  it('shows the host error for a rejected setting change and puts the choice back', () => {
    sendState({ acknowledged: true })
    click(inputByLabel('AssemblyAI'))
    expect(inputByLabel('AssemblyAI').checked).toBe(true)
    result(lastMessageOfType('requestUpdateSettings').requestId, 'error', 'Add a AssemblyAI API key first.')
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Add a AssemblyAI API key first.')
    expect(inputByLabel('AssemblyAI').checked).toBe(false)
    expect(inputByLabel('Deepgram').checked).toBe(true)
  })

  it('applies a change at once and keeps every control usable while the host confirms it', () => {
    sendState({ enabled: false, acknowledged: true })
    const toggle = container.querySelector('#cloud-meeting-transcription-toggle') as HTMLInputElement
    click(toggle)
    expect(toggle.checked).toBe(true)
    expect(toggle.disabled).toBe(false)
    expect(inputByLabel('AssemblyAI').closest('fieldset')?.disabled).toBe(false)
    click(inputByLabel('AssemblyAI'))
    const updates = postMessage.mock.calls.map(([message]) => message).filter((message) => message.type === 'requestUpdateSettings')
    expect(updates.map((message) => message.patch)).toEqual([{ enabled: true }, { provider: 'assemblyai' }])
  })

  it('does not repaint a pending choice back when the host sends an unrelated state first', () => {
    sendState({ enabled: false, acknowledged: true })
    click(container.querySelector('#cloud-meeting-transcription-toggle'))
    sendState({ enabled: false, acknowledged: true, status: { state: 'off', provider: null, tier: null, reason: null } })
    expect((container.querySelector('#cloud-meeting-transcription-toggle') as HTMLInputElement).checked).toBe(true)
  })

  it('shows the last known state on a remount instead of a loading message, then refreshes it', () => {
    sendState({ acknowledged: true, provider: 'assemblyai' })
    act(() => { root.unmount() })
    root = createRoot(container)
    act(() => { root.render(<CloudMeetingTranscriptionPanel />) })
    expect(container.textContent).not.toContain('Loading cloud meeting transcription...')
    expect(inputByLabel('AssemblyAI').checked).toBe(true)
    sendState({ acknowledged: true, provider: 'deepgram' })
    expect(inputByLabel('Deepgram').checked).toBe(true)
  })

  it('collapses the key section through a presence region when the connection changes to the Basil account', () => {
    sendState({ acknowledged: true })
    expect(container.querySelector('.cloud-meeting-transcription-collapse input[type="password"]')).not.toBeNull()
    sendState({ acknowledged: true, connection: 'basil_account' })
    expect(container.querySelector('input[type="password"]')).toBeNull()
    sendState({ acknowledged: true, connection: 'own_key' })
    const region = container.querySelector('.cloud-meeting-transcription-collapse') as HTMLElement
    expect(region.className).toContain('basil-presence')
    expect(container.querySelector('input[type="password"]')).not.toBeNull()
  })

  it('locks only the key buttons while a key request runs', () => {
    sendState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] })
    click(buttonByText('Test Connection'))
    expect(buttonByText('Testing...').disabled).toBe(true)
    expect(buttonByText('Remove Key').disabled).toBe(true)
    expect((container.querySelector('#cloud-meeting-transcription-toggle') as HTMLInputElement).disabled).toBe(false)
    expect(inputByLabel('AssemblyAI').disabled).toBe(false)
    result(lastMessageOfType('requestCheck').requestId, 'success', 'Connected.')
    expect(buttonByText('Test Connection').disabled).toBe(false)
  })

  it('ignores a result for a request it did not make', () => {
    sendState({ enabled: true, acknowledged: true })
    click(container.querySelector('#cloud-meeting-transcription-toggle'))
    result('someone-else', 'error', 'unrelated')
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect((container.querySelector('#cloud-meeting-transcription-toggle') as HTMLInputElement).checked).toBe(false)
  })
})
