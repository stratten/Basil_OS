// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupAgentModelAccess, SetupAgentModelAccessOption } from '@/types'

import { BasilCloudAccountModal } from './BasilCloudAccountModal'
import { IntroAndPrivacy } from './IntroAndPrivacy'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

const OPTIONS = [
  { mode: 'local', available: true, requires_provider_key_input: false, local_model_id: 'phi2-2.7b', downloaded: true },
  { mode: 'basil_cloud', available: true, requires_provider_key_input: false },
  { mode: 'provider_key', available: true, requires_provider_key_input: true },
]

beforeEach(() => {
  fetchMock = vi.fn().mockImplementation((path: string) => {
    if (path === '/setup-assistant/model-access/options') return Promise.resolve(jsonResponse({ options: OPTIONS }))
    if (path.includes('/interaction-style')) return Promise.resolve(jsonResponse({ groups: [] }))
    return Promise.resolve(jsonResponse({ status: 'success', settings: {} }))
  })
  vi.stubGlobal('fetch', fetchMock)
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
})

// The flow opens on the skippable model downloads step; these tests exercise the steps after it.
async function skipDownloadsStep() {
  await act(async () => {
    container.querySelector<HTMLButtonElement>('.intro-step-primary')!.click()
    await Promise.resolve()
    await Promise.resolve()
  })
}

async function renderStep(selectedModelAccess: SetupAgentModelAccess | null) {
  await act(async () => {
    root.render(<IntroAndPrivacy selectedModelAccess={selectedModelAccess} onSelectModelAccess={vi.fn()} onContinue={vi.fn()} />)
    await Promise.resolve()
  })
  await act(async () => { await Promise.resolve() })
  await skipDownloadsStep()
}

const continueButton = () => container.querySelector<HTMLButtonElement>('.intro-step-primary')!

describe('reasoning route selection clarity', () => {
  it('tells the user to select one of the options above when nothing is selected, and marks no option', async () => {
    await renderStep(null)

    expect(continueButton().textContent).toBe('Select one of the options above to continue')
    expect(continueButton().disabled).toBe(true)
    expect(container.querySelector('.choice-option-pending-note')).toBeNull()
  })

  it('marks only the selected option with the checked box, and adds no extra badge once it is confirmed', async () => {
    await renderStep({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true })

    const checked = container.querySelectorAll('[role="radio"][aria-checked="true"]')
    expect(checked).toHaveLength(1)
    expect(checked[0].classList.contains('choice-option--local')).toBe(true)
    expect(container.querySelector('.choice-option-pending-note')).toBeNull()
    expect(container.textContent).not.toContain('Selected and confirmed')
    expect(continueButton().disabled).toBe(false)
  })

  it('keeps the box checked for a selected but unconfirmed option, says it still needs finishing, and points back to the options', async () => {
    await renderStep({ mode: 'basil_cloud', resolved: false })

    expect(container.querySelector('.choice-option--basil_cloud')?.getAttribute('aria-checked')).toBe('true')
    expect(container.querySelector('.choice-option-pending-note')?.textContent?.trim()).toBe('Selected. Finish confirming below.')
    expect(continueButton().textContent).toBe('Finish confirming your choice above')
  })

  it('explains in one line what Basil Cloud is and how it is paid for', async () => {
    await renderStep(null)

    const detail = container.querySelector('.choice-option--basil_cloud')?.textContent ?? ''
    expect(detail).toContain('Basil hosts the model')
    expect(detail).toContain('billed to a card through your Basil account')
  })
})

describe('step 3 reminder', () => {
  it('tells the user the preferences can be changed later in Settings', async () => {
    await renderStep({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true })

    act(() => { continueButton().click() })
    act(() => { continueButton().click() })

    expect(container.querySelector('.intro-step-lede')?.textContent).toContain('later in Settings')
  })
})

describe('Basil Cloud account dialog', () => {
  it('says what the account is for and what to expect before asking for anything', () => {
    const option = { mode: 'basil_cloud', available: false, requires_sign_in: true } as SetupAgentModelAccessOption

    act(() => { root.render(<BasilCloudAccountModal option={option} refreshOptions={vi.fn()} onClose={vi.fn()} />) })

    const dialog = document.body.querySelector('[role="dialog"]')!
    expect(dialog.textContent).toContain('no API key to manage')
    expect(dialog.textContent).toContain('Basil never sees it')
    expect(dialog.querySelectorAll('.basil-cloud-modal-trust li')).toHaveLength(3)
    expect(dialog.querySelector('button[type="submit"]')?.className).toBe('basil-modal-button')
    expect(dialog.closest('.basil-modal-backdrop')).not.toBeNull()
    // One Sign in action, a quiet Cancel, the shared close glyph first in the header at the top left, and no check marks used as bullets.
    const labels = Array.from(dialog.querySelectorAll('button')).map(button => button.textContent)
    expect(labels.filter(label => label === 'Sign in')).toHaveLength(1)
    expect(labels).toContain('Create account')
    expect(dialog.querySelector('.basil-modal-header')?.firstElementChild).toBe(dialog.querySelector('button[aria-label="Close"]'))
    expect(dialog.textContent).not.toContain('✓')
  })

  it('titles the dialog for the form it is showing as the user switches between signing in and creating an account', () => {
    const option = { mode: 'basil_cloud', available: false, requires_sign_in: true } as SetupAgentModelAccessOption

    act(() => { root.render(<BasilCloudAccountModal option={option} refreshOptions={vi.fn()} onClose={vi.fn()} />) })

    const title = () => document.body.querySelector('#basil-modal-title')?.textContent
    const toggle = (label: string) => Array.from(document.body.querySelectorAll('button')).find(button => button.textContent === label)!
    expect(title()).toBe('Sign in to use Basil Cloud')

    act(() => { toggle('Create account').click() })
    expect(title()).toBe('Create an account to use Basil Cloud')

    act(() => { toggle('Sign in').click() })
    expect(title()).toBe('Sign in to use Basil Cloud')
  })

  it('keeps the payment title when no sign-in is needed', () => {
    const option = { mode: 'basil_cloud', available: false, requires_sign_in: false } as SetupAgentModelAccessOption

    act(() => { root.render(<BasilCloudAccountModal option={option} refreshOptions={vi.fn()} onClose={vi.fn()} />) })

    expect(document.body.querySelector('#basil-modal-title')?.textContent).toBe('Add a payment method for Basil Cloud')
  })
})

describe('model comparison', () => {
  it('appears only after the user opens "What\'s the difference?"', async () => {
    await renderStep(null)
    expect(container.querySelector('[data-testid="model-comparison"]')).toBeNull()

    await act(async () => {
      container.querySelector<HTMLButtonElement>('.intro-help-summary')!.click()
      await Promise.resolve()
    })

    expect(container.querySelector('[data-testid="model-comparison"]')).not.toBeNull()
    expect(fetchMock.mock.calls.map(call => call[0])).toContain('/models/recommendations')
  })
})
