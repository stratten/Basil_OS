// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import {
  ACCOUNT_POLL_INTERVAL_MS,
  ACCOUNT_POLL_LIMIT_MS,
  BasilCloudAccountPanel,
  validateAccountForm,
} from './BasilCloudAccountPanel'
import type { SetupAgentModelAccessOption } from '@/types'

const bridge = vi.hoisted(() => ({
  requestAccountLogin: vi.fn(),
  requestAccountSignup: vi.fn(),
  requestAccountGoogleSignIn: vi.fn(),
  requestAccountPaymentSetup: vi.fn(),
  requestAccountRefresh: vi.fn(),
}))

vi.mock('@/services/bridge', () => bridge)

const signedOut: SetupAgentModelAccessOption = {
  mode: 'basil_cloud',
  available: false,
  unavailable_reason: 'Sign in to Basil Cloud to use this route.',
  requires_provider_key_input: false,
  requires_sign_in: true,
}
const needsPayment: SetupAgentModelAccessOption = {
  mode: 'basil_cloud',
  available: false,
  unavailable_reason: 'Add a payment method to use Basil Cloud.',
  requires_provider_key_input: false,
  requires_payment_method: true,
}

let container: HTMLElement
let root: Root
let refreshOptions: Mock<() => Promise<void>>

const ok = (message = '') => Promise.resolve({ requestId: 'r', status: 'executed' as const, message })

async function render(option: SetupAgentModelAccessOption) {
  await act(async () => {
    root.render(<BasilCloudAccountPanel option={option} refreshOptions={refreshOptions} />)
  })
}

function setValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  setter?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function fill(label: string, value: string) {
  const labelNode = Array.from(container.querySelectorAll('label')).find(node => node.textContent?.startsWith(label))
  const input = labelNode?.querySelector('input') as HTMLInputElement
  await act(async () => setValue(input, value))
}

function button(text: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll('button')).find(node => node.textContent?.trim() === text)
  if (!found) throw new Error(`No button "${text}"`)
  return found as HTMLButtonElement
}

async function click(text: string) {
  await act(async () => {
    button(text).click()
  })
}

async function submitForm() {
  await act(async () => {
    container.querySelector('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  Object.values(bridge).forEach(mock => mock.mockReset())
  refreshOptions = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
})

describe('validateAccountForm', () => {
  it('requires an email, a password, and for sign-up a long enough matching password', () => {
    expect(validateAccountForm('signIn', '', 'x', '')).toMatch(/email/i)
    expect(validateAccountForm('signIn', 'no-at-sign', 'x', '')).toMatch(/email/i)
    expect(validateAccountForm('signIn', 'a@b.co', '', '')).toMatch(/password/i)
    expect(validateAccountForm('signIn', 'a@b.co', 'short', '')).toBeNull()
    expect(validateAccountForm('signUp', 'a@b.co', 'short', 'short')).toMatch(/at least 8/)
    expect(validateAccountForm('signUp', 'a@b.co', 'longenough', 'different1')).toMatch(/match/)
    expect(validateAccountForm('signUp', 'a@b.co', 'longenough', 'longenough')).toBeNull()
  })
})

describe('BasilCloudAccountPanel', () => {
  it('renders nothing when the route needs no account action', async () => {
    await render({ ...signedOut, requires_sign_in: false })
    expect(container.querySelector('[data-testid="basil-cloud-account-panel"]')).toBeNull()
  })

  it('signs in through the native bridge and re-reads the options', async () => {
    bridge.requestAccountLogin.mockReturnValue(ok())
    await render(signedOut)

    await fill('Email', ' me@example.com ')
    await fill('Password', 'hunter22hunter')
    await submitForm()

    expect(bridge.requestAccountLogin).toHaveBeenCalledWith('me@example.com', 'hunter22hunter')
    expect(refreshOptions).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('shows the native error and does not refresh when sign-in fails', async () => {
    bridge.requestAccountLogin.mockRejectedValue(new Error('Invalid email or password'))
    await render(signedOut)

    await fill('Email', 'me@example.com')
    await fill('Password', 'wrongpassword')
    await submitForm()

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Invalid email or password')
    expect(refreshOptions).not.toHaveBeenCalled()
  })

  it('blocks an invalid form before it reaches the bridge', async () => {
    await render(signedOut)

    await submitForm()

    expect(container.querySelector('[role="alert"]')?.textContent).toMatch(/email/i)
    expect(bridge.requestAccountLogin).not.toHaveBeenCalled()
  })

  it('creates an account with a confirmation field and explains the Stripe step', async () => {
    bridge.requestAccountSignup.mockReturnValue(ok())
    await render(signedOut)

    await click('Create account')
    expect(container.textContent).toContain('Stripe')
    await fill('Email', 'new@example.com')
    await fill('Password', 'longenough1')
    await fill('Confirm password', 'longenough1')
    await submitForm()

    expect(bridge.requestAccountSignup).toHaveBeenCalledWith('new@example.com', 'longenough1', 'longenough1')
    expect(refreshOptions).toHaveBeenCalledTimes(1)
  })

  it('rejects mismatched sign-up passwords without calling the bridge', async () => {
    await render(signedOut)

    await click('Create account')
    await fill('Email', 'new@example.com')
    await fill('Password', 'longenough1')
    await fill('Confirm password', 'longenough2')
    await submitForm()

    expect(container.querySelector('[role="alert"]')?.textContent).toMatch(/match/)
    expect(bridge.requestAccountSignup).not.toHaveBeenCalled()
  })

  it('opens Google sign-in and keeps checking the account until the browser finishes', async () => {
    bridge.requestAccountGoogleSignIn.mockReturnValue(ok('Complete sign-in in your browser, then return here.'))
    await render(signedOut)

    await click('Continue with Google')
    expect(container.textContent).toContain('Complete sign-in in your browser')
    expect(refreshOptions).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS)
    })
    expect(refreshOptions).toHaveBeenCalledTimes(1)
    expect(bridge.requestAccountRefresh).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS)
    })
    expect(refreshOptions).toHaveBeenCalledTimes(2)
  })

  it('stops polling after the limit and says so', async () => {
    bridge.requestAccountGoogleSignIn.mockReturnValue(ok())
    await render(signedOut)
    await click('Continue with Google')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_LIMIT_MS + ACCOUNT_POLL_INTERVAL_MS * 2)
    })
    const callsAtTimeout = refreshOptions.mock.calls.length
    expect(container.textContent).toContain('I stopped waiting')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS * 3)
    })
    expect(refreshOptions.mock.calls.length).toBe(callsAtTimeout)
  })

  it('reports a Google sign-in that could not start', async () => {
    bridge.requestAccountGoogleSignIn.mockRejectedValue(new Error('Failed to start Google sign-in.'))
    await render(signedOut)

    await click('Continue with Google')

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to start Google sign-in.')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS * 2)
    })
    expect(refreshOptions).not.toHaveBeenCalled()
  })

  it('sends a signed-in account without a card to the Stripe page and watches for the card', async () => {
    bridge.requestAccountPaymentSetup.mockReturnValue(ok())
    bridge.requestAccountRefresh.mockReturnValue(ok())
    await render(needsPayment)

    expect(container.querySelector('form')).toBeNull()
    await click('Add payment method')
    expect(bridge.requestAccountPaymentSetup).toHaveBeenCalledTimes(1)
    expect(container.textContent).toContain('Stripe page in your browser')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS)
    })
    expect(bridge.requestAccountRefresh).toHaveBeenCalledTimes(1)
    expect(refreshOptions).toHaveBeenCalledTimes(1)
  })

  it('lets the user check immediately with "I’ve added it"', async () => {
    bridge.requestAccountRefresh.mockReturnValue(ok())
    await render(needsPayment)

    await click('I’ve added it')

    expect(bridge.requestAccountRefresh).toHaveBeenCalledTimes(1)
    expect(refreshOptions).toHaveBeenCalledTimes(1)
    expect(container.textContent).toContain('Not ready yet')
  })

  it('stops polling when the panel unmounts', async () => {
    bridge.requestAccountGoogleSignIn.mockReturnValue(ok())
    await render(signedOut)
    await click('Continue with Google')

    await act(async () => root.unmount())
    root = createRoot(container)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ACCOUNT_POLL_INTERVAL_MS * 3)
    })

    expect(refreshOptions).not.toHaveBeenCalled()
  })
})
