// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroAndPrivacy } from './IntroAndPrivacy'
import type { SetupAgentModelAccess } from '@/types'

const OPTIONS_PREFIX = '/setup-assistant/model-access/options'
const SELECT_PATH = '/setup-assistant/model-access/select'

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
  local_model_id: 'phi2-2.7b',
  display_name: 'Phi-2',
  downloaded: true,
}

const providerModels = [
  { provider: 'anthropic', model_id: 'claude-sonnet', display_name: 'Claude Sonnet', recommended: true },
]

const savedKeyOption = { mode: 'provider_key', available: true, requires_provider_key_input: false, provider: 'anthropic', provider_models: providerModels }
const noKeyOption = { mode: 'provider_key', available: true, requires_provider_key_input: true, provider_models: providerModels }

function installFetch(providerKeyOption: Record<string, unknown>, { selectFails = false } = {}) {
  fetchMock.mockImplementation((path: string) => {
    if (path.startsWith(OPTIONS_PREFIX)) return Promise.resolve(jsonResponse({ options: [localOption, providerKeyOption] }))
    if (path === SELECT_PATH) {
      if (selectFails) return Promise.reject(new Error('The setup service did not answer.'))
      return Promise.resolve(jsonResponse({ access: { mode: 'provider_key', provider: 'anthropic', model_id: 'claude-sonnet', resolved: true } }))
    }
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

async function renderModelStep(selectedModelAccess: SetupAgentModelAccess | null) {
  await act(async () => {
    root.render(
      <IntroAndPrivacy
        selectedModelAccess={selectedModelAccess}
        onSelectModelAccess={onSelectModelAccess}
        onContinue={vi.fn()}
        initialStep="model"
      />,
    )
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
  })
}

async function clickProviderKeyRadio() {
  const radio = container.querySelector<HTMLButtonElement>('.choice-option--provider_key')!
  await act(async () => {
    radio.click()
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
  })
}

const postedPaths = () => fetchMock.mock.calls
  .filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
  .map(([path]) => path as string)

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

describe('model step with a saved provider key', () => {
  it('confirms the saved key when its route is selected but not yet confirmed', async () => {
    installFetch(savedKeyOption)
    await renderModelStep({ mode: 'provider_key', provider: 'anthropic', resolved: false })

    await clickProviderKeyRadio()

    expect(postedPaths()).toEqual([SELECT_PATH])
    expect(onSelectModelAccess).toHaveBeenCalledWith({ mode: 'provider_key', provider: 'anthropic', model_id: 'claude-sonnet', resolved: true })
  })

  it('can retry the confirmation after it failed', async () => {
    installFetch(savedKeyOption, { selectFails: true })
    await renderModelStep({ mode: 'provider_key', provider: 'anthropic', resolved: false })
    await clickProviderKeyRadio()
    expect(container.textContent).toContain('The setup service did not answer.')

    installFetch(savedKeyOption)
    await clickProviderKeyRadio()

    expect(postedPaths().filter(path => path === SELECT_PATH)).toHaveLength(2)
    expect(onSelectModelAccess).toHaveBeenLastCalledWith({ mode: 'provider_key', provider: 'anthropic', model_id: 'claude-sonnet', resolved: true })
  })

  it('does not confirm again when the saved key is already confirmed', async () => {
    installFetch(savedKeyOption)
    await renderModelStep({ mode: 'provider_key', provider: 'anthropic', model_id: 'claude-sonnet', resolved: true })

    await clickProviderKeyRadio()

    expect(postedPaths()).toEqual([])
    expect(onSelectModelAccess).not.toHaveBeenCalled()
  })

  it('does not confirm anything when there is no saved key and the key form is open', async () => {
    installFetch(noKeyOption)
    await renderModelStep({ mode: 'provider_key', provider: 'anthropic', resolved: false })

    await clickProviderKeyRadio()

    expect(postedPaths()).toEqual([])
    expect(onSelectModelAccess).not.toHaveBeenCalled()
  })
})
