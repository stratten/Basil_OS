// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroDownloadsStep } from './IntroDownloadsStep'

const PROGRESS_PATH = '/onboarding/download-progress'
const OPTIONS_PREFIX = '/setup-assistant/model-access/options'
const LOCAL_PROGRESS_PATH = '/models/predefined/Qwen/qwen35-9b-mlx-4bit/download/progress'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

function voiceProgress(tiny: string, parakeet: string, canCopy = false) {
  return {
    all_complete: false,
    models: {
      'OpenAI-whisper-tiny.en': { status: tiny, progress: tiny === 'completed' ? 100 : 0, description: 'Fast English transcription (151MB)', display_name: 'Whisper Tiny (English)', can_copy_from_normal_basil: canCopy },
      'NVIDIA-parakeet-tdt-0.6b-v3-quantized': { status: parakeet, progress: parakeet === 'completed' ? 100 : 0, description: 'High-quality multilingual transcription (670MB)', display_name: 'Parakeet TDT 0.6B v3', can_copy_from_normal_basil: canCopy },
      'Qwen-qwen36-35b-a3b-mlx-4bit': { status: 'pending', progress: 0, description: 'Starter reasoning model', display_name: 'Qwen3.6-35B-A3B MLX 4-bit' },
    },
  }
}

function localOption({ downloaded = false, choices = false, canCopy = false, modelId = 'Qwen-qwen35-9b-mlx-4bit' } = {}) {
  const is9b = modelId === 'Qwen-qwen35-9b-mlx-4bit'
  return {
    mode: 'local',
    available: downloaded,
    requires_provider_key_input: false,
    local_model_id: modelId,
    display_name: is9b ? 'Qwen3.5-9B MLX 4-bit' : 'Qwen3.6-35B-A3B MLX 4-bit',
    downloaded,
    download_size_description: is9b ? '5.6GB' : '20GB',
    local_model_type: 'Qwen',
    local_model_variant: is9b ? 'qwen35-9b-mlx-4bit' : 'qwen36-35b-a3b-mlx-4bit',
    can_copy_from_normal_basil: canCopy,
    local_model_choices: choices
      ? [
        { model_id: 'Qwen-qwen36-35b-a3b-mlx-4bit', model_type: 'Qwen', variant: 'qwen36-35b-a3b-mlx-4bit', display_name: 'Qwen3.6-35B-A3B MLX 4-bit', size_description: '20GB', downloaded: false, can_copy_from_normal_basil: false },
        { model_id: 'Qwen-qwen35-9b-mlx-4bit', model_type: 'Qwen', variant: 'qwen35-9b-mlx-4bit', display_name: 'Qwen3.5-9B MLX 4-bit', size_description: '5.6GB', downloaded, can_copy_from_normal_basil: canCopy },
      ]
      : [],
  }
}

interface Fixture {
  progress?: unknown
  option?: ReturnType<typeof localOption>
  progressFails?: boolean
  optionsFail?: boolean
}

function installFetch({ progress = voiceProgress('pending', 'pending'), option = localOption(), progressFails = false, optionsFail = false }: Fixture = {}) {
  fetchMock.mockImplementation((path: string) => {
    if (path === PROGRESS_PATH) return progressFails ? Promise.reject(new Error('offline')) : Promise.resolve(jsonResponse(progress))
    if (path.startsWith(OPTIONS_PREFIX)) return optionsFail ? Promise.reject(new Error('offline')) : Promise.resolve(jsonResponse({ options: [option] }))
    if (path === LOCAL_PROGRESS_PATH) return Promise.resolve(jsonResponse({ status: 'not_started', progress: 0 }))
    if (path === '/models/download' || path.includes('copy-model')) return Promise.resolve(jsonResponse({ model_id: 'x', status: 'queued' }))
    return Promise.reject(new Error(`unexpected ${path}`))
  })
}

async function flush() {
  await act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve()
  })
}

function renderStep(onChange = vi.fn(), chosen: string | null = null) {
  act(() => {
    root.render(<IntroDownloadsStep chosenLocalModelId={chosen} onChosenLocalModelIdChange={onChange} />)
  })
  return onChange
}

const buttonByLabel = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
const buttonByText = (text: string) => Array.from(container.querySelectorAll('button')).find(button => button.textContent === text)
const postedPaths = () => fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST').map(([path]) => path)

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
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

describe('IntroDownloadsStep', () => {
  it('lists the two voice models and the thinking model the Local route names, each by its own name', async () => {
    installFetch()
    renderStep()
    await flush()

    const text = container.textContent ?? ''
    expect(container.querySelector('h3')?.textContent).toBe('Model downloads')
    expect(text).toContain('Whisper Tiny (English)')
    expect(text).toContain('Parakeet TDT 0.6B v3')
    expect(text).toContain('Qwen3.5-9B MLX 4-bit')
    expect(text).toContain('Thinking model')
    expect(text).not.toContain('Qwen3.6-35B-A3B')
    expect(container.querySelectorAll('.model-downloads__row')).toHaveLength(3)
  })

  it('starts one model from its own button and nothing else', async () => {
    installFetch()
    renderStep()
    await flush()

    await act(async () => { buttonByLabel('Download Parakeet TDT 0.6B v3')!.click() })
    await flush()

    expect(postedPaths()).toEqual(['/models/download'])
    const body = JSON.parse(String((fetchMock.mock.calls.find(([path]) => path === '/models/download')![1] as RequestInit).body))
    expect(body).toEqual({ request: { model_type: 'NVIDIA', variant: 'parakeet-tdt-0.6b-v3-quantized' } })
  })

  it('downloads all three models, thinking model included, from Download all', async () => {
    installFetch()
    renderStep()
    await flush()

    await act(async () => { buttonByText('Download all')!.click() })
    await flush()

    expect(postedPaths()).toEqual(['/models/download', '/models/download', '/models/download'])
  })

  it('shows no download button for a thinking model that is already on disk, and says everything is ready once all are', async () => {
    installFetch({ progress: voiceProgress('completed', 'completed'), option: localOption({ downloaded: true }) })
    renderStep()
    await flush()

    expect(buttonByLabel('Download Qwen3.5-9B MLX 4-bit')).toBeNull()
    expect(container.textContent).toContain('Every model is ready on this Mac.')
    expect(buttonByText('Download all')).toBeUndefined()
  })

  it('shows no chooser and no copy button in a normal build', async () => {
    installFetch()
    renderStep()
    await flush()

    expect(container.querySelector('.local-model-chooser')).toBeNull()
    expect(container.textContent).not.toContain('Copy')
  })

  it('offers the chooser and a copy from the normal Basil in a validation build, and copies instead of downloading', async () => {
    installFetch({ progress: voiceProgress('pending', 'pending', true), option: localOption({ choices: true, canCopy: true }) })
    renderStep()
    await flush()

    expect(container.querySelector('.local-model-chooser')).not.toBeNull()
    await act(async () => { buttonByText('Copy all from my Basil')!.click() })
    await flush()

    // Both voice models and the thinking model are held by the normal Basil, so all three are copied.
    expect(postedPaths()).toEqual([
      '/setup-assistant/model-access/validation/copy-model',
      '/setup-assistant/model-access/validation/copy-model',
      '/setup-assistant/model-access/validation/copy-model',
    ])
    expect(postedPaths()).not.toContain('/models/download')
  })

  it('asks the setup service for the chosen local model', async () => {
    installFetch({ option: localOption({ choices: true, modelId: 'Qwen-qwen36-35b-a3b-mlx-4bit' }) })
    renderStep(vi.fn(), 'Qwen-qwen36-35b-a3b-mlx-4bit')
    await flush()

    expect(fetchMock.mock.calls.map(([path]) => path)).toContain(`${OPTIONS_PREFIX}?local_model_id=Qwen-qwen36-35b-a3b-mlx-4bit`)
    expect(container.textContent).toContain('Qwen3.6-35B-A3B MLX 4-bit')
  })

  it('tells the person the setup service is unreachable and does not block them', async () => {
    installFetch({ progressFails: true, optionsFail: true })
    renderStep()
    await flush()

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('You can still continue.')
    expect(container.querySelectorAll('.model-downloads__row')).toHaveLength(0)
  })
})
