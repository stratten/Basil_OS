// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ProfileSettingsApp } from './ProfileSettingsApp'
import type { ProfileFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const FIELDS: ProfileFields = {
  fullName: 'Ada Lovelace',
  preferredName: null,
  email: null,
  jobTitle: null,
  companyName: null,
  industry: null,
  formality: null,
  tone: null,
  customInstructions: null,
}

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function setNativeTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
  setter.call(textarea, value)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

function findButton(text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent === text)!
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilProfileSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ProfileSettingsApp />) })
  act(() => {
    window.basilProfileSettings!.onEvent({ type: 'init', protocolVersion: 1, profile: FIELDS })
  })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ProfileSettingsApp', () => {
  it('hydrates form fields from the init event', () => {
    const fullName = container.querySelector<HTMLInputElement>('input[placeholder="Your full name"]')!
    expect(fullName.value).toBe('Ada Lovelace')
  })

  it('sends a correlated save request with the edited draft', () => {
    const fullName = container.querySelector<HTMLInputElement>('input[placeholder="Your full name"]')!
    act(() => { setNativeInputValue(fullName, 'Grace Hopper') })
    act(() => { findButton('Save Profile').click() })
    const message = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'saveProfile')
    expect(message).toMatchObject({ profile: expect.objectContaining({ fullName: 'Grace Hopper' }) })
  })

  it('surfaces a save error inline and re-enables the form', () => {
    act(() => { findButton('Save Profile').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'saveProfile').requestId
    act(() => {
      window.basilProfileSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to save profile.' })
    })
    expect(container.querySelector('.profile-settings-inline-error')?.textContent).toBe('Failed to save profile.')
    expect(findButton('Save Profile').disabled).toBe(false)
  })

  it('keeps the Saved state until the draft changes', () => {
    act(() => { findButton('Save Profile').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'saveProfile').requestId
    act(() => {
      window.basilProfileSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' })
    })
    expect(findButton('Saved!')).not.toBeNull()

    const fullName = container.querySelector<HTMLInputElement>('input[placeholder="Your full name"]')!
    act(() => { setNativeInputValue(fullName, 'Grace Hopper') })
    expect(findButton('Save Profile')).not.toBeNull()
  })

  it('emits only one clear request for rapid repeated clicks', () => {
    act(() => {
      const clearButton = findButton('Clear All')
      clearButton.click()
      clearButton.click()
    })
    expect(postMessage.mock.calls.filter(([value]) => value.type === 'requestClearProfile')).toHaveLength(1)
  })

  it('requests confirmation before clearing and surfaces cancellation without an error', () => {
    act(() => { findButton('Clear All').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestClearProfile').requestId
    act(() => {
      window.basilProfileSettings!.onEvent({ type: 'intentResult', requestId, status: 'cancelled' })
    })
    expect(container.querySelector('.profile-settings-inline-error')).toBeNull()
    const fullName = container.querySelector<HTMLInputElement>('input[placeholder="Your full name"]')!
    expect(fullName.value).toBe('Ada Lovelace')
  })

  it('clears the form after a confirmed delete', () => {
    act(() => { findButton('Clear All').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestClearProfile').requestId
    act(() => {
      window.basilProfileSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' })
      window.basilProfileSettings!.onEvent({
        type: 'snapshot',
        profile: { fullName: null, preferredName: null, email: null, jobTitle: null, companyName: null, industry: null, formality: null, tone: null, customInstructions: null },
      })
    })
    const fullName = container.querySelector<HTMLInputElement>('input[placeholder="Your full name"]')!
    expect(fullName.value).toBe('')
  })

  it('saves edited custom instructions', () => {
    const textarea = container.querySelector<HTMLTextAreaElement>('.profile-settings-textarea')!
    act(() => { setNativeTextareaValue(textarea, 'No em dashes. No exclamation points.') })
    act(() => { findButton('Save Profile').click() })
    const message = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'saveProfile')
    expect(message).toMatchObject({
      profile: expect.objectContaining({ customInstructions: 'No em dashes. No exclamation points.' }),
    })
  })
})
