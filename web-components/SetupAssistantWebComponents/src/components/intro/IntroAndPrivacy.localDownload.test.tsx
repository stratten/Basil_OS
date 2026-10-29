// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { IntroAndPrivacy, LOCAL_DOWNLOAD_POLL_INTERVAL_MS } from './IntroAndPrivacy'

const OPTIONS_PATH = '/setup-assistant/model-access/options'
const PROGRESS_PATH = '/models/predefined/Qwen/qwen35-9b-q4km/download/progress'

let container: HTMLElement
let root: Root
let fetchMock: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown) {
  return { ok: true, text: vi.fn().mockResolvedValue(JSON.stringify(body)) }
}

function localOption(downloaded: boolean) {
  return {
    mode: 'local',
    available: downloaded,
    unavailable_reason: downloaded ? null : 'Not downloaded yet.',
    requires_provider_key_input: false,
    local_model_id: 'Qwen-qwen35-9b-q4km',
    display_name: 'Qwen3.5-9B',
    downloaded,
    download_size_description: '5.68GB',
    local_model_type: 'Qwen',
    local_model_variant: 'qwen35-9b-q4km',
  }
}

const providerKeyOption = { mode: 'provider_key', available: true, requires_provider_key_input: true, provider_models: [] }
const signedOutCloudOption = {
  mode: 'basil_cloud',
  available: false,
  unavailable_reason: 'Sign in to Basil Cloud to use this route.',
  requires_provider_key_input: false,
  requires_sign_in: true,
}
const ineligibleCloudOption = {
  mode: 'basil_cloud',
  available: false,
  unavailable_reason: 'Out of credits.',
  requires_provider_key_input: false,
  requires_sign_in: false,
}

async function renderStep() {
  await act(async () => {
    root.render(
      <IntroAndPrivacy selectedModelAccess={null} onSelectModelAccess={vi.fn()} onContinue={vi.fn()} />,
    )
    await Promise.resolve()
    await Promise.resolve()
  })
}

function downloadButton() {
  return Array.from(container.querySelectorAll('button')).find(button => button.textContent?.startsWith('Download '))
}

beforeEach(() => {
  vi.useFakeTimers()
  fetchMock = vi.fn()
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
  vi.useRealTimers()
})

describe('IntroAndPrivacy local model download', () => {
  it('offers a download for a local model that is not on disk and none once it is', async () => {
    fetchMock.mockImplementation((path: string) => {
      if (path === OPTIONS_PATH) return Promise.resolve(jsonResponse({ options: [localOption(false), providerKeyOption] }))
      return Promise.resolve(jsonResponse({ status: 'not_started', progress: 0 }))
    })
    await renderStep()

    expect(downloadButton()?.textContent).toBe('Download Qwen3.5-9B (5.68GB)')
    expect(container.textContent).toContain('Not downloaded yet.')
    expect(container.querySelector<HTMLButtonElement>('.choice-option--local')?.disabled).toBe(true)

    act(() => { root.unmount() })
    root = createRoot(container)
    fetchMock.mockReset()
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ options: [localOption(true), providerKeyOption] })))
    await renderStep()

    expect(downloadButton()).toBeUndefined()
    expect(container.querySelector<HTMLButtonElement>('.choice-option--local')?.disabled).toBe(false)
  })

  it('starts the download, shows progress, and makes the route selectable when the disk confirms it', async () => {
    let pollCount = 0
    let onDisk = false
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path === OPTIONS_PATH) return Promise.resolve(jsonResponse({ options: [localOption(onDisk), providerKeyOption] }))
      if (path === '/models/download' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ model_id: 'Qwen-qwen35-9b-q4km', status: 'queued' }))
      }
      if (path === PROGRESS_PATH) {
        pollCount += 1
        if (pollCount === 1) return Promise.resolve(jsonResponse({ status: 'not_started', progress: 0 }))
        if (pollCount === 2) return Promise.resolve(jsonResponse({ status: 'downloading', progress: 0.42 }))
        onDisk = true
        return Promise.resolve(jsonResponse({ status: 'completed', progress: 1 }))
      }
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    await renderStep()

    await act(async () => {
      downloadButton()!.click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenCalledWith('/models/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request: { model_type: 'Qwen', variant: 'qwen35-9b-q4km' } }),
    })
    expect(container.textContent).toContain('Downloading… 42%')
    expect(container.textContent).toContain('You can keep going with another route')
    expect(container.querySelector<HTMLButtonElement>('.choice-option--provider_key')?.disabled).toBe(false)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(LOCAL_DOWNLOAD_POLL_INTERVAL_MS)
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(downloadButton()).toBeUndefined()
    expect(container.textContent).not.toContain('Downloading…')
    expect(container.querySelector<HTMLButtonElement>('.choice-option--local')?.disabled).toBe(false)
  })

  it('shows the retry message when the download ends but the model is still not on disk', async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path === OPTIONS_PATH) return Promise.resolve(jsonResponse({ options: [localOption(false), providerKeyOption] }))
      if (path === '/models/download' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ model_id: 'Qwen-qwen35-9b-q4km', status: 'queued' }))
      }
      if (path === PROGRESS_PATH) return Promise.resolve(jsonResponse({ status: 'failed', progress: 0.1 }))
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    await renderStep()

    await act(async () => {
      downloadButton()!.click()
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(container.textContent).toContain('The download stopped before it finished. Try again.')
    expect(downloadButton()).toBeDefined()
  })

  it('shows the backend reason when the download cannot be started', async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path === OPTIONS_PATH) return Promise.resolve(jsonResponse({ options: [localOption(false), providerKeyOption] }))
      if (path === '/models/download' && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          text: vi.fn().mockResolvedValue(JSON.stringify({ detail: 'Download manager not initialized; backend still starting.' })),
        })
      }
      return Promise.resolve(jsonResponse({ status: 'not_started', progress: 0 }))
    })
    await renderStep()

    await act(async () => {
      downloadButton()!.click()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(container.textContent).toContain('Download manager not initialized; backend still starting.')
    expect(downloadButton()).toBeDefined()
  })

  it('resumes an in-flight download instead of offering a second start', async () => {
    fetchMock.mockImplementation((path: string) => {
      if (path === OPTIONS_PATH) return Promise.resolve(jsonResponse({ options: [localOption(false), providerKeyOption] }))
      if (path === PROGRESS_PATH) return Promise.resolve(jsonResponse({ status: 'downloading', progress: 0.5 }))
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    await renderStep()
    await act(async () => { await Promise.resolve() })

    expect(container.textContent).toContain('Downloading… 50%')
    expect(downloadButton()).toBeUndefined()
  })

  it('always shows Basil Cloud with its reason: a signed-out account can open the account dialog, an ineligible one cannot be chosen', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({
      options: [localOption(true), providerKeyOption, signedOutCloudOption],
    })))
    await renderStep()
    const signedOutRow = container.querySelector<HTMLButtonElement>('.choice-option--basil_cloud')
    expect(signedOutRow).not.toBeNull()
    expect(signedOutRow!.disabled).toBe(false)
    expect(container.textContent).toContain('Sign in to Basil Cloud to use this route.')

    act(() => { root.unmount() })
    root = createRoot(container)
    fetchMock.mockReset()
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({
      options: [localOption(true), providerKeyOption, ineligibleCloudOption],
    })))
    await renderStep()
    expect(container.querySelector<HTMLButtonElement>('.choice-option--basil_cloud')?.disabled).toBe(true)
    expect(container.textContent).toContain('Out of credits.')
  })
})
