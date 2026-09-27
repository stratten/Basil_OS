// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ModelsSettingsApp } from './ModelsSettingsApp'
import type { ModelProviderGroup } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let transcriptionApiModelsPostMessage: ReturnType<typeof vi.fn>
let reasoningApiModelsPostMessage: ReturnType<typeof vi.fn>
let customModelsPostMessage: ReturnType<typeof vi.fn>

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

const REASONING_GROUPS: ModelProviderGroup[] = [
  {
    provider: 'Qwen',
    models: [
      { id: 'Qwen-a', modelType: 'Qwen', variantId: 'a', name: 'Qwen A', capabilities: ['reasoning'], size: 4_000_000_000, statusKind: 'downloadable' },
      { id: 'Qwen-b', modelType: 'Qwen', variantId: 'b', name: 'Qwen B', capabilities: ['reasoning'], size: 2_000_000_000, statusKind: 'available' },
    ],
  },
]

const TRANSCRIPTION_GROUPS: ModelProviderGroup[] = [
  { provider: 'NVIDIA', models: [{ id: 'NVIDIA-a', modelType: 'NVIDIA', variantId: 'a', name: 'Parakeet', capabilities: ['transcription'], size: 640_000_000, statusKind: 'downloadable' }] },
]

function sendInit(overrides: Record<string, unknown> = {}) {
  act(() => {
    window.basilModelsSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      isLoadingModels: false,
      localVisionFallbackEnabled: false,
      isLocalVisionFallbackModelInstalled: false,
      reasoningGroups: REASONING_GROUPS,
      transcriptionGroups: TRANSCRIPTION_GROUPS,
      ...overrides,
    } as any)
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  transcriptionApiModelsPostMessage = vi.fn()
  reasoningApiModelsPostMessage = vi.fn()
  customModelsPostMessage = vi.fn()
  window.webkit = {
    messageHandlers: {
      basilModelsSettingsBridge: { postMessage },
      basilTranscriptionApiModelsBridge: { postMessage: transcriptionApiModelsPostMessage },
      basilReasoningApiModelsBridge: { postMessage: reasoningApiModelsPostMessage },
      basilCustomModelsBridge: { postMessage: customModelsPostMessage },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ModelsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ModelsSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.models-settings-status')?.textContent).toBe('Loading model settings...')
  })

  it('renders reasoning models by default after init', () => {
    sendInit()
    expect(container.textContent).toContain('Qwen A')
    expect(container.textContent).not.toContain('Parakeet')
  })

  it('switches to transcription models via a pure client-side tab with no bridge message', () => {
    sendInit()
    postMessage.mockClear()
    const transcriptionTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Transcription') as HTMLButtonElement
    act(() => { transcriptionTab.click() })
    expect(container.textContent).toContain('Parakeet')
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('defaults the Transcription capability to the Local Models sub-tab and mounts the API Models panel only on demand', () => {
    sendInit()
    const transcriptionTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Transcription') as HTMLButtonElement
    act(() => { transcriptionTab.click() })
    expect(container.querySelector('.transcription-api-models-panel')).toBeNull()
    expect(transcriptionApiModelsPostMessage).not.toHaveBeenCalled()

    const apiModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'API Models') as HTMLButtonElement
    act(() => { apiModelsTab.click() })
    expect(container.textContent).not.toContain('Parakeet')
    expect(transcriptionApiModelsPostMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })

    const localModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Local Models') as HTMLButtonElement
    act(() => { localModelsTab.click() })
    expect(container.textContent).toContain('Parakeet')
  })

  it('defaults the Reasoning capability to the Local Models sub-tab and mounts the API Models panel only on demand', () => {
    sendInit()
    expect(container.querySelector('.reasoning-api-models-panel')).toBeNull()
    expect(reasoningApiModelsPostMessage).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Qwen A')

    const apiModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'API Models') as HTMLButtonElement
    act(() => { apiModelsTab.click() })
    expect(container.textContent).not.toContain('Qwen A')
    expect(container.querySelector('#models-settings-vision-fallback-toggle')).toBeNull()
    expect(reasoningApiModelsPostMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })

    const localModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Local Models') as HTMLButtonElement
    act(() => { localModelsTab.click() })
    expect(container.textContent).toContain('Qwen A')
  })

  it('mounts the Custom Models panel only on demand under the Reasoning capability', () => {
    sendInit()
    expect(container.querySelector('.custom-models-panel')).toBeNull()
    expect(customModelsPostMessage).not.toHaveBeenCalled()

    const customModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Custom Models') as HTMLButtonElement
    act(() => { customModelsTab.click() })
    expect(container.textContent).not.toContain('Qwen A')
    expect(customModelsPostMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })

    const localModelsTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Local Models') as HTMLButtonElement
    act(() => { localModelsTab.click() })
    expect(container.textContent).toContain('Qwen A')
  })

  it('does not offer a Custom Models sub-tab under the Transcription capability', () => {
    sendInit()
    const transcriptionTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Transcription') as HTMLButtonElement
    act(() => { transcriptionTab.click() })
    const tabs = Array.from(container.querySelectorAll('[role="tab"]')).map((tab) => tab.textContent)
    expect(tabs).not.toContain('Custom Models')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilModelsSettings!.onEvent({ type: 'loadError', message: 'Could not load models.' }) })
    expect(container.querySelector('.models-settings-error p')?.textContent).toBe('Could not load models.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.models-settings-error .secondary-button')!.click() })
    expect(lastMessageOfType('reactReady')).toEqual({ type: 'reactReady', protocolVersion: 1 })
  })

  it('starts a download, disables that row only, and shows progress after snapshot', () => {
    sendInit()
    const downloadButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Download') as HTMLButtonElement
    act(() => { downloadButton.click() })
    const requestId = lastMessageOfType('requestDownloadModel')?.requestId
    expect(requestId).toBeTruthy()
    expect(downloadButton.textContent).toBe('Starting...')
    expect(downloadButton.disabled).toBe(true)
    sendInit({
      type: 'snapshot',
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'downloading', progress: 0.1 }, REASONING_GROUPS[0].models[1]] }],
    })
    act(() => { window.basilModelsSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' }) })
    expect(container.querySelector('.models-settings-progress-label')?.textContent).toBe('10%')
  })

  it('accumulates and displays the last three download log lines', () => {
    sendInit({
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'downloading', progress: 0.3 }, REASONING_GROUPS[0].models[1]] }],
    })
    act(() => {
      window.basilModelsSettings!.onEvent({ type: 'downloadLogLine', modelId: 'Qwen-a', message: 'line 1' })
      window.basilModelsSettings!.onEvent({ type: 'downloadLogLine', modelId: 'Qwen-a', message: 'line 2' })
      window.basilModelsSettings!.onEvent({ type: 'downloadLogLine', modelId: 'Qwen-a', message: 'line 3' })
      window.basilModelsSettings!.onEvent({ type: 'downloadLogLine', modelId: 'Qwen-a', message: 'line 4' })
    })
    expect(container.textContent).not.toContain('line 1')
    expect(container.textContent).toContain('line 4')
  })

  it('shows a per-model error with Retry and re-issues a download request on click', () => {
    sendInit({
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'error', errorMessage: 'Disk full' }, REASONING_GROUPS[0].models[1]] }],
    })
    expect(container.querySelector('.models-settings-error-message')?.textContent).toBe('Disk full')
    const retryButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Retry') as HTMLButtonElement
    act(() => { retryButton.click() })
    expect(lastMessageOfType('requestDownloadModel')?.modelId).toBe('Qwen-a')
  })

  it('deletes an available model and surfaces a cancelled result without an error message', () => {
    sendInit()
    const deleteButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Delete') as HTMLButtonElement
    act(() => { deleteButton.click() })
    const requestId = lastMessageOfType('requestDeleteModel')?.requestId
    expect(deleteButton.textContent).toBe('Deleting...')
    expect(deleteButton.disabled).toBe(true)
    act(() => { window.basilModelsSettings!.onEvent({ type: 'intentResult', requestId, status: 'cancelled' }) })
    expect(container.querySelector('.models-settings-status-error')).toBeNull()
    expect(deleteButton.disabled).toBe(false)
  })

  it('toggles Agent Vision Fallback optimistically and sends the desired enabled value', () => {
    sendInit({ isLocalVisionFallbackModelInstalled: true })
    const checkbox = container.querySelector<HTMLInputElement>('.basil-switch-input')!
    act(() => { checkbox.click() })
    expect(lastMessageOfType('requestUpdateVisionFallback')).toEqual(expect.objectContaining({ enabled: true }))
    expect(checkbox.checked).toBe(true)
  })

  it('disables the vision fallback toggle when the model is not installed', () => {
    sendInit({ isLocalVisionFallbackModelInstalled: false })
    expect(container.querySelector<HTMLInputElement>('.basil-switch-input')!.disabled).toBe(true)
  })
})
