// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { SetupAgentModelAccess } from '@/types'

import { IntroAndPrivacy } from './IntroAndPrivacy'

let container: HTMLElement
let root: Root

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

const OPTIONS = [
  { mode: 'local', available: true, requires_provider_key_input: false, local_model_id: 'phi2-2.7b', downloaded: true },
  { mode: 'basil_cloud', available: true, requires_provider_key_input: false },
  { mode: 'provider_key', available: true, requires_provider_key_input: true },
]

beforeEach(() => {
  const fetchMock = vi.fn().mockImplementation((path: string) => {
    if (path === '/setup-assistant/model-access/options') return Promise.resolve(jsonResponse({ options: OPTIONS }))
    if (path === '/models/recommendations') return Promise.reject(new Error('offline'))
    if (path.includes('/interaction-style')) return Promise.resolve(jsonResponse({ groups: [] }))
    return Promise.resolve(jsonResponse({
      status: 'success',
      settings: { memory_after_task_enabled: false, skill_after_task_enabled: false },
    }))
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

async function flush() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve()
  })
}

async function renderFlow(selectedModelAccess: SetupAgentModelAccess | null, options: { skipDownloads: boolean }) {
  await act(async () => {
    root.render(<IntroAndPrivacy selectedModelAccess={selectedModelAccess} onSelectModelAccess={vi.fn()} onContinue={vi.fn()} />)
    await Promise.resolve()
  })
  await flush()
  if (options.skipDownloads) {
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.intro-step-primary')!.click()
      await Promise.resolve()
    })
    await flush()
  }
}

const continueButton = () => container.querySelector<HTMLButtonElement>('.intro-step-primary')!

describe('plain words in the setup preference steps', () => {
  it('tells the person where the model downloads can be changed later', async () => {
    await renderFlow({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }, { skipDownloads: false })

    expect(container.querySelector('h3')?.textContent).toBe('Model downloads')
    expect(container.querySelector('.intro-step-lede')?.textContent).toContain('You can download or change any of them later in Settings, Models.')
  })

  it('names the model step for what it does and keeps the cards short and free of developer words', async () => {
    await renderFlow({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }, { skipDownloads: true })

    expect(container.querySelector('h3')?.textContent).toBe('How I think during setup')
    expect(container.querySelector('[role="radiogroup"]')?.getAttribute('aria-label')).toBe('Where my thinking happens during setup')
    const local = container.querySelector('.choice-option--local')?.textContent ?? ''
    expect(local).toContain('On this Mac')
    expect(local).toContain('Private. Nothing leaves this Mac.')
    expect(container.querySelector('.choice-option--provider_key')?.textContent).toContain('Use your own account with an AI company.')
    expect(container.querySelector('.intro-step-later')?.textContent).toBe('You can change my main models any time in Settings, Models.')
    expect(container.textContent?.toLowerCase()).not.toContain('reasoning route')
  })

  it('explains what an API key is, in the place it is asked for, and calls the dropdown AI company', async () => {
    await renderFlow({ mode: 'provider_key', provider: 'anthropic', resolved: false }, { skipDownloads: true })

    expect(container.querySelector('.choice-option-key-help')?.textContent).toContain(
      'An API key is a password-like code that lets Basil use your account with Anthropic (Claude).',
    )
    expect(container.querySelector('.choice-option-provider-field span')?.textContent).toBe('AI company')
  })

  it('describes each option in plain words in the help, and the comparison falls back in plain words too', async () => {
    await renderFlow({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }, { skipDownloads: true })
    await act(async () => {
      container.querySelector<HTMLButtonElement>('.intro-help-summary')!.click()
      await Promise.resolve()
    })
    await flush()

    const help = container.querySelector('#intro-help-body')?.textContent ?? ''
    expect(help).toContain('I think using an AI model stored on this Mac.')
    expect(help).toContain("I think using a stronger model that runs on Basil's servers.")
    expect(help).toContain('I’ll send setup requests straight to the AI company you choose, using the key you enter here.')
    expect(help).toContain('This only decides how I think during setup.')
    expect(container.querySelector('[data-testid="model-comparison"]')?.textContent).toContain('The AI company you choose')
    expect(help).toContain('The two options above still apply.')
  })

  it('puts a visible change-later line under both learning choices and explains what a skill is', async () => {
    await renderFlow({ mode: 'local', local_model_id: 'phi2-2.7b', resolved: true }, { skipDownloads: true })
    act(() => { continueButton().click() })
    await flush()

    expect(container.querySelector('.intro-capture-toggle--memory .intro-toggle-later')?.textContent).toBe(
      'Change this later in Personalization > Personal Context.',
    )
    expect(container.querySelector('.intro-capture-toggle--skill .intro-toggle-later')?.textContent).toBe(
      'Change this later in Capabilities > Automation & Agents > Skills.',
    )
    expect(container.querySelector('.intro-capture-toggle--memory')?.textContent).toContain(
      "After work we do together, I'll suggest notes to add to your profile.",
    )
    expect(container.querySelector('.intro-capture-toggle--skill')?.textContent).toContain('a named set of steps I can run again')
  })
})
