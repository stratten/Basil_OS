// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroAndPrivacy } from './IntroAndPrivacy'
import type { SetupAgentModelAccess } from '@/types'

const OPTIONS_PREFIX = '/setup-assistant/model-access/options'
const COPY_PATH = '/setup-assistant/model-access/validation/copy-model'
const SMALL_PROGRESS_PATH = '/models/predefined/Qwen/qwen35-9b-mlx-4bit/download/progress'
const LARGE_ID = 'Qwen-qwen36-35b-a3b-mlx-4bit'
const SMALL_ID = 'Qwen-qwen35-9b-mlx-4bit'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>
let onSelectModelAccess: Mock<(modelAccess: SetupAgentModelAccess) => void>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

function choices(canCopySmall: boolean) {
  return [
    { model_id: LARGE_ID, model_type: 'Qwen', variant: 'qwen36-35b-a3b-mlx-4bit', display_name: 'Qwen3.6-35B-A3B MLX 4-bit', size_description: '20GB', downloaded: false, can_copy_from_normal_basil: false },
    { model_id: SMALL_ID, model_type: 'Qwen', variant: 'qwen35-9b-mlx-4bit', display_name: 'Qwen3.5-9B MLX 4-bit', size_description: '5.6GB', downloaded: false, can_copy_from_normal_basil: canCopySmall },
  ]
}

function localOption(modelId: string, { validation = true, canCopy = false } = {}) {
  const small = modelId === SMALL_ID
  return {
    mode: 'local',
    available: false,
    unavailable_reason: 'Not downloaded yet.',
    requires_provider_key_input: false,
    local_model_id: modelId,
    display_name: small ? 'Qwen3.5-9B MLX 4-bit' : 'Qwen3.6-35B-A3B MLX 4-bit',
    downloaded: false,
    download_size_description: small ? '5.6GB' : '20GB',
    local_model_type: 'Qwen',
    local_model_variant: small ? 'qwen35-9b-mlx-4bit' : 'qwen36-35b-a3b-mlx-4bit',
    can_copy_from_normal_basil: canCopy,
    local_model_choices: validation ? choices(true) : [],
  }
}

const providerKeyOption = { mode: 'provider_key', available: true, requires_provider_key_input: true, provider_models: [] }

function installFetch({ validation = true, canCopy = true }: { validation?: boolean, canCopy?: boolean } = {}) {
  fetchMock.mockImplementation((path: string) => {
    if (path.startsWith(OPTIONS_PREFIX)) {
      const modelId = path.includes(`local_model_id=${SMALL_ID}`) ? SMALL_ID : LARGE_ID
      return Promise.resolve(jsonResponse({ options: [localOption(modelId, { validation, canCopy }), providerKeyOption] }))
    }
    if (path === COPY_PATH) return Promise.resolve(jsonResponse({ model_id: SMALL_ID, status: 'queued' }))
    if (path.startsWith('/models/predefined/')) return Promise.resolve(jsonResponse({ status: 'not_started', progress: 0 }))
    if (path === '/onboarding/download-progress') return Promise.resolve(jsonResponse({ all_complete: false, models: {} }))
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

async function renderModelStep(selectedModelAccess: SetupAgentModelAccess | null = null) {
  await act(async () => {
    root.render(<IntroAndPrivacy selectedModelAccess={selectedModelAccess} onSelectModelAccess={onSelectModelAccess} onContinue={vi.fn()} />)
    for (let index = 0; index < 4; index += 1) await Promise.resolve()
  })
  await act(async () => {
    container.querySelector<HTMLButtonElement>('.intro-step-primary')!.click()
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
  })
}

const buttonByText = (text: string) => Array.from(container.querySelectorAll('button')).find(button => button.textContent?.startsWith(text))

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  fetchMock = vi.fn()
  onSelectModelAccess = vi.fn<(modelAccess: SetupAgentModelAccess) => void>()
  vi.stubGlobal('fetch', fetchMock)
  window.matchMedia = vi.fn().mockReturnValue({ matches: true })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('reasoning route options as a radio group', () => {
  it('exposes the options as radios with a square well that carries no glyph, chosen or not', async () => {
    installFetch({ validation: false, canCopy: false })
    await renderModelStep({ mode: 'provider_key', provider: 'anthropic', resolved: false })

    expect(container.querySelector('[role="radiogroup"]')?.getAttribute('aria-label')).toBe('Where my thinking happens during setup')
    const radios = Array.from(container.querySelectorAll<HTMLElement>('.choice-option[role="radio"]'))
    expect(radios).toHaveLength(2)
    const indicators = radios.map(radio => radio.querySelector('.choice-option-indicator')?.textContent)
    const checked = radios.map(radio => radio.getAttribute('aria-checked'))
    expect(checked).toEqual(['false', 'true'])
    expect(indicators).toEqual(['', ''])
    expect(container.querySelector('.choice-option[aria-pressed]')).toBeNull()
  })
})

describe('Back from the first step', () => {
  async function renderFirstStep(onBackToStart?: () => void) {
    installFetch({ validation: false, canCopy: false })
    await act(async () => {
      root.render(<IntroAndPrivacy selectedModelAccess={null} onSelectModelAccess={onSelectModelAccess} onContinue={vi.fn()} onBackToStart={onBackToStart} />)
      for (let index = 0; index < 4; index += 1) await Promise.resolve()
    })
  }

  it('hides Back on the first step when there is no way back to the first screen', async () => {
    await renderFirstStep()

    const back = container.querySelector<HTMLButtonElement>('.intro-step-back')!
    expect(back.disabled).toBe(true)
    expect(back.getAttribute('aria-hidden')).toBe('true')
  })

  it('returns to the first screen from the first step when a way back is given', async () => {
    const onBackToStart = vi.fn()
    await renderFirstStep(onBackToStart)

    const back = container.querySelector<HTMLButtonElement>('.intro-step-back')!
    expect(back.disabled).toBe(false)
    expect(back.getAttribute('aria-hidden')).toBeNull()
    act(() => { back.click() })
    expect(onBackToStart).toHaveBeenCalledTimes(1)
  })
})

describe('validation-only local model controls on the model step', () => {
  it('shows no chooser and no copy button in a normal build', async () => {
    installFetch({ validation: false, canCopy: false })
    await renderModelStep()

    expect(container.querySelector('.local-model-chooser')).toBeNull()
    expect(buttonByText('Copy ')).toBeUndefined()
    expect(buttonByText('Download ')?.textContent).toBe('Download Qwen3.6-35B-A3B MLX 4-bit (20GB)')
  })

  it('offers a copy from the normal Basil under the Local option and starts a copy rather than a download', async () => {
    installFetch()
    await renderModelStep()

    expect(buttonByText('Download ')).toBeDefined()
    await act(async () => { buttonByText('Copy ')!.click() })
    for (let index = 0; index < 4; index += 1) await act(async () => { await Promise.resolve() })

    const posted = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST').map(([path]) => path)
    expect(posted).toEqual([COPY_PATH])
    expect(fetchMock.mock.calls.map(([path]) => path)).toContain('/models/predefined/Qwen/qwen36-35b-a3b-mlx-4bit/download/progress')
  })

  it('re-reads the Local route for the chosen model, and marks a confirmed Local choice unconfirmed when that model is not on disk', async () => {
    installFetch()
    await renderModelStep({ mode: 'local', local_model_id: LARGE_ID, resolved: true })

    await act(async () => { container.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!.click() })
    const option = Array.from(document.body.querySelectorAll<HTMLElement>('[role="option"]')).find(item => item.textContent?.includes('Qwen3.5-9B'))!
    await act(async () => { option.click() })
    for (let index = 0; index < 6; index += 1) await act(async () => { await Promise.resolve() })

    expect(fetchMock.mock.calls.map(([path]) => path)).toContain(`${OPTIONS_PREFIX}?local_model_id=${SMALL_ID}`)
    expect(fetchMock.mock.calls.map(([path]) => path)).toContain(SMALL_PROGRESS_PATH)
    expect(onSelectModelAccess).toHaveBeenCalledWith({ mode: 'local', local_model_id: SMALL_ID, resolved: false })
    expect(container.textContent).toContain('Qwen3.5-9B MLX 4-bit')
  })
})
