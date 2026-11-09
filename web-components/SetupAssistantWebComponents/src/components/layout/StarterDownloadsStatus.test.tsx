// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { StarterDownloadsStatus } from './StarterDownloadsStatus'

const fetchStarterDownloadProgress = vi.fn()
const startLocalModelDownload = vi.fn()
const copyLocalModelFromNormalBasil = vi.fn()
vi.mock('@/services/api', () => ({
  fetchStarterDownloadProgress: () => fetchStarterDownloadProgress(),
  copyLocalModelFromNormalBasil: (modelType: string, variant: string) => copyLocalModelFromNormalBasil(modelType, variant),
  startLocalModelDownload: (modelType: string, variant: string) => startLocalModelDownload(modelType, variant),
}))

const TINY = 'OpenAI-whisper-tiny.en'
const PARAKEET = 'NVIDIA-parakeet-tdt-0.6b-v3-quantized'
const REASONING = 'Qwen-qwen35-9b-mlx-4bit'

function progress(tiny: string, parakeet: string, reasoning: string, reasoningPercent = 0, canCopy = false) {
  return {
    all_complete: [tiny, parakeet, reasoning].every(status => status === 'completed'),
    models: {
      [TINY]: { status: tiny, progress: tiny === 'completed' ? 100 : 0, description: 'Fast English transcription (151MB)', display_name: 'Whisper Tiny (English)', can_copy_from_normal_basil: canCopy },
      [PARAKEET]: { status: parakeet, progress: parakeet === 'completed' ? 100 : 0, description: 'High-quality multilingual transcription (670MB)', display_name: 'Parakeet TDT 0.6B v3', can_copy_from_normal_basil: canCopy },
      [REASONING]: { status: reasoning, progress: reasoningPercent, description: 'Reasoning model for suggestions (5.6GB)', display_name: 'Qwen3.5-9B MLX 4-bit', can_copy_from_normal_basil: canCopy },
    },
  }
}

let container: HTMLElement
let root: Root

async function flush() {
  await act(async () => { await Promise.resolve() })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  fetchStarterDownloadProgress.mockReset()
  startLocalModelDownload.mockReset()
  copyLocalModelFromNormalBasil.mockReset()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

async function renderPanel() {
  act(() => { root.render(<StarterDownloadsStatus />) })
  await flush()
}

function buttonByLabel(label: string) {
  return container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
}

function buttonByText(text: string) {
  return [...container.querySelectorAll('button')].find(element => element.textContent === text)
}

describe('StarterDownloadsStatus', () => {
  it('names each model and shows its own state, including a failure and a running percentage', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'error', 'downloading', 42))

    await renderPanel()

    const text = container.textContent ?? ''
    expect(text).toContain('Whisper Tiny (English)')
    expect(text).toContain('Fast voice model')
    expect(text).toContain('Ready')
    expect(text).toContain('Parakeet TDT 0.6B v3')
    expect(text).toContain('Failed')
    expect(text).toContain('Qwen3.5-9B MLX 4-bit')
    expect(text).toContain('Thinking model')
    expect(text).toContain('42%')
    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('42')
  })

  it('shows the amount downloaded next to the percentage when the backend reports it, and the percentage alone when it does not', async () => {
    const reported = progress('completed', 'completed', 'downloading', 42)
    reported.models[REASONING] = { ...reported.models[REASONING], total_downloaded: 2_386_000_000, total_size: 5_680_000_000 } as typeof reported.models[typeof REASONING]
    fetchStarterDownloadProgress.mockResolvedValue(reported)
    await renderPanel()

    expect(container.querySelector('.download-progress__amount')?.textContent).toBe('2.4 GB / 5.7 GB')
    expect(container.querySelector('.download-progress__percent')?.textContent).toBe('42%')

    act(() => { root.unmount() })
    root = createRoot(container)
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'completed', 'downloading', 42))
    await renderPanel()

    expect(container.querySelector('.download-progress__amount')).toBeNull()
    expect(container.querySelector('.download-progress__percent')?.textContent).toBe('42%')
  })

  it('renders nothing when every download is ready', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'completed', 'completed'))

    await renderPanel()

    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when the status cannot be read', async () => {
    fetchStarterDownloadProgress.mockRejectedValue(new Error('offline'))

    await renderPanel()

    expect(container.innerHTML).toBe('')
  })

  it('starts one model from its own button and no other', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'pending', 'pending'))
    startLocalModelDownload.mockResolvedValue({ model_id: PARAKEET, status: 'queued' })
    await renderPanel()

    const button = buttonByLabel('Download Parakeet TDT 0.6B v3')
    expect(button).not.toBeNull()
    await act(async () => { button!.click() })
    await flush()

    expect(startLocalModelDownload).toHaveBeenCalledTimes(1)
    expect(startLocalModelDownload).toHaveBeenCalledWith('NVIDIA', 'parakeet-tdt-0.6b-v3-quantized')
  })

  it('offers Download all only when more than one model can start, and starts every one of them', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'pending', 'pending'))
    startLocalModelDownload.mockResolvedValue({ model_id: 'x', status: 'queued' })
    await renderPanel()

    const all = buttonByText('Download all')
    expect(all).toBeDefined()
    await act(async () => { all!.click() })
    await flush()

    expect(startLocalModelDownload).toHaveBeenCalledTimes(2)
    expect(startLocalModelDownload).toHaveBeenCalledWith('NVIDIA', 'parakeet-tdt-0.6b-v3-quantized')
    expect(startLocalModelDownload).toHaveBeenCalledWith('Qwen', 'qwen35-9b-mlx-4bit')
  })

  it('offers a copy from the normal Basil only when the backend says it can, and copies instead of downloading', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'pending', 'pending', 0, true))
    copyLocalModelFromNormalBasil.mockResolvedValue({ model_id: 'x', status: 'queued' })
    await renderPanel()

    await act(async () => { buttonByText('Copy all from my Basil')!.click() })
    await flush()

    expect(startLocalModelDownload).not.toHaveBeenCalled()
    expect(copyLocalModelFromNormalBasil).toHaveBeenCalledTimes(2)
    expect(copyLocalModelFromNormalBasil).toHaveBeenCalledWith('Qwen', 'qwen35-9b-mlx-4bit')
  })

  it('never shows a copy button when the backend does not offer one', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'pending', 'pending'))
    await renderPanel()

    expect(container.textContent).not.toContain('Copy')
  })

  it('hides Download all when only one model can start', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('completed', 'completed', 'pending'))
    await renderPanel()

    expect(buttonByText('Download all')).toBeUndefined()
    expect(buttonByLabel('Download Qwen3.5-9B MLX 4-bit')).not.toBeNull()
  })

  it('labels a failed model Retry and reports a start error', async () => {
    fetchStarterDownloadProgress.mockResolvedValue(progress('error', 'completed', 'completed'))
    startLocalModelDownload.mockRejectedValue(new Error('No space left on device'))
    await renderPanel()

    const button = buttonByLabel('Retry Whisper Tiny (English)')
    expect(button).not.toBeNull()
    expect(button!.textContent).toBe('Retry')
    await act(async () => { button!.click() })
    await flush()

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('No space left on device')
  })

  it('keeps polling while a download runs and stops once all are ready', async () => {
    fetchStarterDownloadProgress
      .mockResolvedValueOnce(progress('completed', 'completed', 'downloading', 10))
      .mockResolvedValueOnce(progress('completed', 'completed', 'completed'))
    await renderPanel()
    expect(container.textContent).toContain('10%')

    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    await flush()

    expect(container.innerHTML).toBe('')
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(fetchStarterDownloadProgress).toHaveBeenCalledTimes(2)
  })
})
