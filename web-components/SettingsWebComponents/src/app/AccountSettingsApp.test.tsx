// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AccountSettingsApp } from './AccountSettingsApp'
import type { AccountSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SIGNED_OUT: AccountSettingsFields = {
  isAuthenticated: false,
  userEmail: '',
  subscriptionStatus: 'none',
  hasPaymentMethod: false,
  cardBrand: '',
  cardLast4: '',
  cardExpiration: '',
  apiKeyPreference: 'trial',
  basilCloudSelected: true,
  basilCloudBadge: 'Account required',
  basilCloudDescription: 'Sign in and add payment to use Basil Cloud.',
  isLoadingUsage: false,
  currentPeriodFormatted: '',
  totalCostFormatted: '$0.00',
  totalTokensFormatted: '0',
  usageByModel: [],
}

const SIGNED_IN: AccountSettingsFields = {
  ...SIGNED_OUT,
  isAuthenticated: true,
  userEmail: 'user@example.com',
  apiKeyPreference: 'basil_cloud',
  hasPaymentMethod: true,
  cardBrand: 'Visa',
  cardLast4: '4242',
  cardExpiration: '12/2027',
  currentPeriodFormatted: 'Jan 1 - Jan 31',
  totalCostFormatted: '$4.20',
  totalTokensFormatted: '12,345',
  usageByModel: [{ model: 'gpt-5', costUsd: 4.2 }],
}

function sendInit(fields: AccountSettingsFields) {
  act(() => {
    window.basilAccountSettings!.onEvent({ type: 'init', protocolVersion: 1, ...fields })
  })
}

// Assigning `.value` directly does not go through React's tracked
// setter, so React never observes the change. Using the native
// descriptor setter (matching the established pattern in
// `ProfileSettingsApp.test.tsx`/`CustomModelEditForm.test.tsx`) is
// required for the subsequent `input` event to update React state.
function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilAccountSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<AccountSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('AccountSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.account-settings-status')?.textContent).toBe('Loading account...')
  })

  it('shows the sign-in form when signed out', () => {
    sendInit(SIGNED_OUT)
    expect(container.querySelector('input[type="email"]')).not.toBeNull()
    expect(container.querySelector('.account-status-row-signed-in')).toBeNull()
  })

  it('disables sign-in until email and password are present', () => {
    sendInit(SIGNED_OUT)
    const submit = container.querySelectorAll('.account-auth-actions button')[0] as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    act(() => { container.querySelector<HTMLInputElement>('input[type="email"]')!.dispatchEvent(new Event('input')) })
  })

  it('sends requestLogin with the entered credentials', () => {
    sendInit(SIGNED_OUT)
    const emailInput = container.querySelector<HTMLInputElement>('input[type="email"]')!
    const passwordInput = container.querySelector<HTMLInputElement>('input[type="password"]')!
    act(() => {
      setNativeInputValue(emailInput, 'a@example.com')
      setNativeInputValue(passwordInput, 'secret123')
    })
    act(() => { container.querySelectorAll('.account-auth-actions button')[0]!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    const call = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestLogin')
    expect(call).toMatchObject({ email: 'a@example.com', password: 'secret123' })
  })

  it('shows account status, payment, usage, and danger zone when signed in', () => {
    sendInit(SIGNED_IN)
    expect(container.querySelector('.account-status-row-signed-in')?.textContent).toContain('user@example.com')
    // `.account-status-row` alone also matches the signed-in status row
    // above (it carries both classes), so index into the payment
    // section's row specifically rather than taking the first match.
    expect(container.querySelectorAll('.account-status-row')[1]?.textContent).toContain('Visa')
    expect(container.querySelector('.account-usage-total-value')?.textContent).toBe('$4.20')
    expect(container.querySelector('.account-danger-zone')).not.toBeNull()
  })

  it('requires a two-step confirmation before sending requestDeleteAccount', () => {
    sendInit(SIGNED_IN)
    expect(container.querySelector('.account-delete-confirm')).toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.account-delete-button')!.click() })
    expect(container.querySelector('.account-delete-confirm')).not.toBeNull()
    act(() => { container.querySelector<HTMLButtonElement>('.account-delete-confirm-button')!.click() })
    expect(postMessage.mock.calls.map(([message]) => message).some((message) => message.type === 'requestDeleteAccount')).toBe(true)
  })

  it('surfaces a real deletion-blocked error instead of assuming success', () => {
    sendInit(SIGNED_IN)
    act(() => { container.querySelector<HTMLButtonElement>('.account-delete-button')!.click() })
    act(() => { container.querySelector<HTMLButtonElement>('.account-delete-confirm-button')!.click() })
    const requestId = postMessage.mock.calls.map(([message]) => message).find((message) => message.type === 'requestDeleteAccount')!.requestId
    act(() => {
      window.basilAccountSettings!.onEvent({
        type: 'intentResult',
        requestId,
        status: 'error',
        message: 'You have an outstanding balance of $12.34.',
      })
    })
    expect(container.querySelector('.account-settings-inline-error')?.textContent).toBe('You have an outstanding balance of $12.34.')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilAccountSettings!.onEvent({ type: 'loadError', message: 'Could not load account settings.' }) })
    expect(container.querySelector('.account-settings-error p')?.textContent).toBe('Could not load account settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.account-settings-error .secondary-button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })
})
