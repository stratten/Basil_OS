// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HotkeySettingsApp } from './HotkeySettingsApp'
import { HOTKEY_FIXTURE_ENABLE_MONITORING_AT_STARTUP, HOTKEY_FIXTURE_ROWS } from '../fixtures/hotkeyFixture'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map((call) => call[0]).reverse().find((message) => message.type === type)
}

function sendInit() {
  window.basilHotkeySettings!.onEvent({
    type: 'init',
    protocolVersion: 1,
    rows: HOTKEY_FIXTURE_ROWS,
    enableMonitoringAtStartup: HOTKEY_FIXTURE_ENABLE_MONITORING_AT_STARTUP,
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilHotkeySettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<HotkeySettingsApp />) })
  act(sendInit)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('HotkeySettingsApp', () => {
  it('sends reactReady exactly once on mount', () => {
    expect(postMessage.mock.calls.filter((call) => call[0].type === 'reactReady').length).toBe(1)
  })

  it('renders rows after native initialization', () => {
    expect(container.querySelectorAll('.hotkey-row').length).toBe(HOTKEY_FIXTURE_ROWS.length)
  })

  it('starts capture on Edit and immediately saves once captured, without a Save button', () => {
    const editButtons = container.querySelectorAll<HTMLButtonElement>('.hotkey-row button')
    postMessage.mockImplementation((message) => {
      if (message.type === 'startCapture') {
        expect(container.querySelector('.hotkey-row-recording-indicator')).not.toBeNull()
      }
    })
    act(() => { editButtons[1].dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith({ type: 'startCapture', id: 'conversation_toggle' })
    expect(container.querySelector('.hotkey-row-recording-indicator')).not.toBeNull()

    act(() => {
      window.basilHotkeySettings!.onEvent({
        type: 'captured',
        id: 'conversation_toggle',
        binding: { key: 'F9', modifiers: [], enabled: true, isDoublePress: false, doublePressKey: null },
      })
    })

    const saveMessage = lastMessageOfType('saveBinding')
    expect(saveMessage).toMatchObject({ id: 'conversation_toggle', binding: { key: 'F9' } })
    expect(container.querySelector('.hotkey-row-recording-indicator')).toBeNull()
  })

  it('sends cancelCapture when Cancel is clicked while editing', () => {
    const editButtons = container.querySelectorAll<HTMLButtonElement>('.hotkey-row button')
    act(() => { editButtons[0].dispatchEvent(new MouseEvent('click', { bubbles: true })) })

    const cancelButton = container.querySelector<HTMLButtonElement>('.hotkey-row button')!
    act(() => { cancelButton.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

    expect(postMessage).toHaveBeenCalledWith({ type: 'cancelCapture', id: 'transcribe_audio' })
  })

  it('sends cancelCapture for an abandoned row on unmount (e.g. switching Settings tabs mid-capture)', () => {
    const localContainer = document.createElement('div')
    document.body.appendChild(localContainer)
    const localRoot = createRoot(localContainer)
    act(() => { localRoot.render(<HotkeySettingsApp />) })
    act(sendInit)

    const editButtons = localContainer.querySelectorAll<HTMLButtonElement>('.hotkey-row button')
    act(() => { editButtons[0].dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    postMessage.mockClear()

    act(() => { localRoot.unmount() })
    localContainer.remove()

    expect(postMessage).toHaveBeenCalledWith({ type: 'cancelCapture', id: 'transcribe_audio' })
  })

  it('keeps controls disabled and shows the native load error when initialization fails', () => {
    act(() => {
      window.basilHotkeySettings!.onEvent({ type: 'loadError', message: 'Failed to load hotkey settings.' })
    })

    expect(container.querySelector('.hotkey-row-error')?.textContent).toBe('Failed to load hotkey settings.')
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(true)
  })

  it('retries native initialization after a load error', () => {
    act(() => {
      window.basilHotkeySettings!.onEvent({ type: 'loadError', message: 'Failed to load hotkey settings.' })
    })
    postMessage.mockClear()

    act(() => {
      container.querySelector<HTMLButtonElement>('.hotkey-load-error button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('reverts the checkbox on toggleEnableMonitoring failure', () => {
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!
    const initialChecked = checkbox.checked
    act(() => { checkbox.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(checkbox.checked).toBe(!initialChecked)

    const requestId = lastMessageOfType('toggleEnableMonitoring')!.requestId as string
    act(() => {
      window.basilHotkeySettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'nope' })
    })
    expect(checkbox.checked).toBe(initialChecked)
  })

  it('shows an inline error and reverts the displayed binding when saveBinding fails', () => {
    const editButtons = container.querySelectorAll<HTMLButtonElement>('.hotkey-row button')
    act(() => { editButtons[2].dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    act(() => {
      window.basilHotkeySettings!.onEvent({
        type: 'captured',
        id: 'assistant_session',
        binding: { key: 'X', modifiers: [], enabled: true, isDoublePress: false, doublePressKey: null },
      })
    })
    const requestId = lastMessageOfType('saveBinding')!.requestId as string
    act(() => {
      window.basilHotkeySettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to save hotkey.' })
    })
    expect(container.querySelector('.hotkey-row-error')?.textContent).toBe('Failed to save hotkey.')
  })
})
