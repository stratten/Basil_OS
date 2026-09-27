// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MacContactsSettingsCard } from './MacContactsSettingsCard'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function emit(fields: { available: boolean; preferenceEnabled: boolean; authorizationStatus: string; canLookup: boolean; detail: string | null }) {
  act(() => {
    window.basilMacContactsSettings!.onEvent({ type: 'init', protocolVersion: 1, fields })
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMacContactsSettingsBridge: { postMessage } } }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<MacContactsSettingsCard />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('MacContactsSettingsCard', () => {
  it('loads passively without changing the preference', () => {
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    emit({ available: true, preferenceEnabled: false, authorizationStatus: 'not_determined', canLookup: false, detail: null })
    expect(container.querySelector<HTMLInputElement>('#mac-contacts-enabled')?.checked).toBe(false)
    expect(container.textContent).toContain('Contacts access has not been requested yet.')
  })

  it('locks the switch until an enabled update completes', () => {
    emit({ available: true, preferenceEnabled: false, authorizationStatus: 'not_determined', canLookup: false, detail: null })
    const toggle = container.querySelector<HTMLInputElement>('#mac-contacts-enabled')!
    act(() => { toggle.click() })
    const request = postMessage.mock.calls.find(([message]) => message.type === 'updateEnabled')![0]
    expect(toggle.disabled).toBe(true)

    act(() => {
      window.basilMacContactsSettings!.onEvent({
        type: 'snapshot',
        fields: { available: true, preferenceEnabled: true, authorizationStatus: 'authorized', canLookup: true, detail: null },
      })
      window.basilMacContactsSettings!.onEvent({ type: 'intentResult', requestId: request.requestId, status: 'success' })
    })
    expect(container.querySelector<HTMLInputElement>('#mac-contacts-enabled')?.checked).toBe(true)
    expect(container.textContent).toContain('Contacts access is enabled for personalized generation.')
  })

  it('keeps the switch off and displays the denied state', () => {
    emit({ available: true, preferenceEnabled: false, authorizationStatus: 'not_determined', canLookup: false, detail: null })
    act(() => {
      window.basilMacContactsSettings!.onEvent({
        type: 'snapshot',
        fields: { available: true, preferenceEnabled: false, authorizationStatus: 'denied', canLookup: false, detail: null },
      })
    })
    expect(container.querySelector<HTMLInputElement>('#mac-contacts-enabled')?.checked).toBe(false)
    expect(container.textContent).toContain('Contacts access is blocked.')
  })

  it('unlocks the switch and displays an error when persistence fails', () => {
    emit({ available: true, preferenceEnabled: false, authorizationStatus: 'authorized', canLookup: false, detail: null })
    const toggle = container.querySelector<HTMLInputElement>('#mac-contacts-enabled')!
    act(() => { toggle.click() })
    const request = postMessage.mock.calls.find(([message]) => message.type === 'updateEnabled')![0]
    act(() => {
      window.basilMacContactsSettings!.onEvent({
        type: 'intentResult',
        requestId: request.requestId,
        status: 'error',
        message: 'Failed to update Contacts access.',
      })
    })
    expect(toggle.checked).toBe(false)
    expect(toggle.disabled).toBe(false)
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to update Contacts access.')
  })

  it('disables an unavailable Contacts provider', () => {
    emit({ available: false, preferenceEnabled: false, authorizationStatus: 'unknown', canLookup: false, detail: 'Contacts are unavailable.' })
    expect(container.querySelector<HTMLInputElement>('#mac-contacts-enabled')?.disabled).toBe(true)
    expect(container.textContent).toContain('Contacts are unavailable.')
  })
})
