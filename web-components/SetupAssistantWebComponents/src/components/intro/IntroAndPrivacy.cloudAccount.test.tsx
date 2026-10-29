// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroAndPrivacy } from './IntroAndPrivacy'
import type { SetupAgentModelAccess } from '@/types'

const OPTIONS_PATH = '/setup-assistant/model-access/options'
const CHECKED_OPTIONS_PATH = '/setup-assistant/model-access/options?check_account=true'
const SELECT_PATH = '/setup-assistant/model-access/select'

const bridge = vi.hoisted(() => ({
  requestAccountLogin: vi.fn(),
  requestAccountSignup: vi.fn(),
  requestAccountGoogleSignIn: vi.fn(),
  requestAccountPaymentSetup: vi.fn(),
  requestAccountRefresh: vi.fn(),
}))

vi.mock('@/services/bridge', () => bridge)

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>
let onSelectModelAccess: Mock<(modelAccess: SetupAgentModelAccess) => void>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

const localOption = {
  mode: 'local',
  available: true,
  requires_provider_key_input: false,
  local_model_id: 'Qwen-qwen35-9b-q4km',
  display_name: 'Qwen3.5-9B',
  downloaded: true,
}
const providerKeyOption = { mode: 'provider_key', available: true, requires_provider_key_input: true, provider_models: [] }
const uncheckedCloudOption = {
  mode: 'basil_cloud',
  available: true,
  requires_provider_key_input: false,
  requires_account_check: true,
}
const cloudStage = (stage: 'signedOut' | 'needsPayment' | 'eligible') => ({
  mode: 'basil_cloud',
  available: stage === 'eligible',
  unavailable_reason: stage === 'signedOut' ? 'Sign in to Basil Cloud to use this route.' : stage === 'needsPayment' ? 'Add a payment method to use Basil Cloud.' : null,
  requires_provider_key_input: false,
  requires_sign_in: stage === 'signedOut',
  requires_payment_method: stage === 'needsPayment',
})

let stage: 'signedOut' | 'needsPayment' | 'eligible'

async function renderStep(selectedModelAccess: SetupAgentModelAccess | null = null) {
  await act(async () => {
    root.render(
      <IntroAndPrivacy selectedModelAccess={selectedModelAccess} onSelectModelAccess={onSelectModelAccess} onContinue={vi.fn()} />,
    )
    await Promise.resolve()
    await Promise.resolve()
  })
}

function setValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  setter?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

async function fill(label: string, value: string) {
  const labelNode = Array.from(document.body.querySelectorAll('label')).find(node => node.textContent?.startsWith(label))
  await act(async () => setValue(labelNode?.querySelector('input') as HTMLInputElement, value))
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

const dialog = () => document.body.querySelector('[role="dialog"]')
const cloudRow = () => container.querySelector<HTMLButtonElement>('.choice-option--basil_cloud')!

async function chooseBasilCloud() {
  await act(async () => {
    cloudRow().click()
  })
  await flush()
}

function formIn(node: ParentNode | null) {
  return node?.querySelector('form') ?? null
}

beforeEach(() => {
  fetchMock = vi.fn()
  onSelectModelAccess = vi.fn<(modelAccess: SetupAgentModelAccess) => void>()
  vi.stubGlobal('fetch', fetchMock)
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  Object.values(bridge).forEach(mock => mock.mockReset())
  stage = 'signedOut'
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (path === OPTIONS_PATH) {
      return Promise.resolve(jsonResponse({ options: [localOption, providerKeyOption, uncheckedCloudOption] }))
    }
    if (path === CHECKED_OPTIONS_PATH) {
      return Promise.resolve(jsonResponse({ options: [localOption, providerKeyOption, cloudStage(stage)] }))
    }
    if (path === SELECT_PATH && init?.method === 'POST') {
      return Promise.resolve(jsonResponse({ access: { mode: 'basil_cloud', resolved: true } }))
    }
    return Promise.reject(new Error(`unexpected ${path}`))
  })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

describe('IntroAndPrivacy Basil Cloud account flow', () => {
  it('keeps the reasoning step light: one short lede, short card details, and no explainer under the API key option', async () => {
    await renderStep()

    expect(container.querySelector('.intro-step-lede')?.textContent).toBe('Pick how I should think during setup.')
    expect(container.querySelector('.choice-option--provider_key')?.textContent).toContain('Use your own provider account.')
    expect(container.textContent).not.toContain('Select this if you already have your own API key')
    expect(container.querySelector('.choice-option-note')).toBeNull()
  })

  it('does not read the account or show any account form until Basil Cloud is chosen', async () => {
    await renderStep()

    const optionRequests = fetchMock.mock.calls.map(call => call[0]).filter(path => String(path).includes('/model-access/options'))
    expect(optionRequests).toEqual([OPTIONS_PATH])
    expect(dialog()).toBeNull()
    expect(document.body.querySelector('form')).toBeNull()
    expect(cloudRow().disabled).toBe(false)
    expect(cloudRow().textContent).not.toContain('Sign in')
  })

  it('checks the account only when Basil Cloud is chosen and then opens the sign-in dialog for a signed-out user', async () => {
    await renderStep()

    await chooseBasilCloud()

    expect(fetchMock.mock.calls.map(call => call[0])).toContain(CHECKED_OPTIONS_PATH)
    expect(dialog()).not.toBeNull()
    expect(dialog()?.getAttribute('aria-modal')).toBe('true')
    expect(formIn(dialog())).not.toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(onSelectModelAccess).not.toHaveBeenCalled()
  })

  it('selects Basil Cloud without any dialog when the account is already eligible', async () => {
    stage = 'eligible'
    await renderStep()

    await chooseBasilCloud()

    expect(dialog()).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(SELECT_PATH, expect.objectContaining({ method: 'POST' }))
    expect(onSelectModelAccess).toHaveBeenCalledWith({ mode: 'basil_cloud', resolved: true })
  })

  it('signs in inside the dialog, then selects Basil Cloud on its own and closes the dialog', async () => {
    bridge.requestAccountLogin.mockImplementation(() => {
      stage = 'eligible'
      return Promise.resolve({ requestId: 'r', status: 'executed', message: '' })
    })
    await renderStep()
    await chooseBasilCloud()

    await fill('Email', 'me@example.com')
    await fill('Password', 'hunter22hunter')
    await act(async () => {
      formIn(dialog())?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    await flush()

    expect(bridge.requestAccountLogin).toHaveBeenCalledWith('me@example.com', 'hunter22hunter')
    expect(fetchMock).toHaveBeenCalledWith(SELECT_PATH, expect.objectContaining({ method: 'POST' }))
    expect(onSelectModelAccess).toHaveBeenCalledWith({ mode: 'basil_cloud', resolved: true })
    expect(dialog()).toBeNull()
  })

  it('moves from sign-up to the payment prompt in the same dialog when the new account has no card', async () => {
    bridge.requestAccountSignup.mockImplementation(() => {
      stage = 'needsPayment'
      return Promise.resolve({ requestId: 'r', status: 'executed', message: '' })
    })
    await renderStep()
    await chooseBasilCloud()

    const createTab = Array.from(document.body.querySelectorAll('button')).find(node => node.textContent === 'Create account')
    await act(async () => createTab?.click())
    await fill('Email', 'new@example.com')
    await fill('Password', 'longenough1')
    await fill('Confirm password', 'longenough1')
    await act(async () => {
      formIn(dialog())?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    await flush()

    expect(dialog()).not.toBeNull()
    expect(formIn(dialog())).toBeNull()
    expect(dialog()?.textContent).toContain('Add payment method')
    expect(onSelectModelAccess).not.toHaveBeenCalled()
  })

  it('closes with the Close button or Escape without selecting anything, and reopens when Basil Cloud is chosen again', async () => {
    await renderStep()
    await chooseBasilCloud()
    const closeButton = dialog()?.querySelector<HTMLButtonElement>('button[aria-label="Close"]')
    await act(async () => closeButton?.click())

    expect(dialog()).toBeNull()
    expect(onSelectModelAccess).not.toHaveBeenCalled()

    await chooseBasilCloud()
    expect(dialog()).not.toBeNull()
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })

    expect(dialog()).toBeNull()
    expect(onSelectModelAccess).not.toHaveBeenCalled()
  })

  it('shows the local model name under the description only while Local is selected', async () => {
    await renderStep()
    expect(container.querySelector('.choice-option--local')?.textContent).not.toContain('Qwen3.5-9B')

    act(() => { root.unmount() })
    root = createRoot(container)
    await renderStep({ mode: 'local', resolved: true })

    const localText = container.querySelector('.choice-option--local')?.textContent ?? ''
    expect(localText).toContain('Private. Nothing leaves this machine.')
    expect(localText).toContain('Model: Qwen3.5-9B')
  })
})
