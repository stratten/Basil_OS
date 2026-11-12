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

  it('shows a GGUF or MLX tag next to the size of local language models and no tag for other models', () => {
    sendInit({
      reasoningGroups: [
        {
          provider: 'Qwen',
          models: [
            { id: 'Qwen-gguf', modelType: 'Qwen', variantId: 'gguf', name: 'Qwen GGUF', capabilities: ['reasoning'], size: 5_000_000_000, format: 'GGUF', statusKind: 'downloadable' },
            { id: 'Qwen-mlx', modelType: 'Qwen', variantId: 'mlx', name: 'Qwen MLX', capabilities: ['reasoning'], size: 5_000_000_000, format: 'MLX', statusKind: 'downloadable' },
            { id: 'Qwen-plain', modelType: 'Qwen', variantId: 'plain', name: 'Qwen Plain', capabilities: ['reasoning'], size: 5_000_000_000, statusKind: 'downloadable' },
          ],
        },
      ],
    })
    const tags = Array.from(container.querySelectorAll('.models-settings-format-tag')).map((tag) => tag.textContent)
    expect(tags).toEqual(['GGUF', 'MLX'])
    const rows = Array.from(container.querySelectorAll('.models-settings-row'))
    expect(rows[2].querySelector('.models-settings-format-tag')).toBeNull()
    expect(rows[1].querySelector('.models-settings-row-footer-start .models-settings-format-tag')?.textContent).toBe('MLX')
    expect(rows[1].querySelector('.models-settings-row-footer-end .models-settings-format-tag')).toBeNull()
    const footerStart = rows[1].querySelector('.models-settings-row-footer-start')!
    expect(footerStart.firstElementChild?.className).toBe('models-settings-row-capabilities-chips')
    expect(footerStart.lastElementChild?.textContent).toBe('MLX')
  })

  it('shows speed, quality and memory with bars for a model that lists them, and nothing for one that does not', () => {
    sendInit({
      reasoningGroups: [
        {
          provider: 'Qwen',
          models: [
            { id: 'Qwen-rated', modelType: 'Qwen', variantId: 'rated', name: 'Qwen Rated', capabilities: ['reasoning'], size: 5_000_000_000, speedRating: 7, accuracyRating: 8, recommendedRam: '16GB', statusKind: 'downloadable' },
            { id: 'Qwen-partial', modelType: 'Qwen', variantId: 'partial', name: 'Qwen Partial', capabilities: ['reasoning'], size: 5_000_000_000, accuracyRating: 6, statusKind: 'downloadable' },
            { id: 'Qwen-plain', modelType: 'Qwen', variantId: 'plain', name: 'Qwen Plain', capabilities: ['reasoning'], size: 5_000_000_000, statusKind: 'downloadable' },
          ],
        },
      ],
    })
    const rows = Array.from(container.querySelectorAll('.models-settings-row'))
    const factsOf = (row: Element) => Array.from(row.querySelectorAll('.models-settings-row-fact')).map((fact) => fact.textContent)
    expect(factsOf(rows[0])).toEqual(['Speed7 out of 10', 'Quality8 out of 10', 'Memory16GB or more'])
    expect(factsOf(rows[1])).toEqual(['Quality6 out of 10'])
    expect(rows[2].querySelector('.models-settings-row-facts')).toBeNull()
    expect(rows[0].querySelector('.models-settings-row-header .models-settings-row-facts')).not.toBeNull()
    const barWidthsOf = (row: Element) => Array.from(row.querySelectorAll<HTMLElement>('.models-settings-fact-bar-fill')).map((fill) => fill.style.width)
    expect(barWidthsOf(rows[0])).toEqual(['70%', '80%', '25%'])
    const tooltipsOf = (row: Element) => Array.from(row.querySelectorAll('.models-settings-row-fact')).map((fact) => fact.getAttribute('data-tooltip'))
    expect(tooltipsOf(rows[0])).toEqual(['Speed: 7 out of 10', 'Quality: 8 out of 10', 'Memory: 16GB or more'])
    expect(rows[0].querySelector('.models-settings-row-fact dd')?.className).toBe('settings-visually-hidden')
    expect(barWidthsOf(rows[1])).toEqual(['60%'])
    expect(rows[0].querySelector('.models-settings-fact-bar')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('shows whether each model fits this Mac as an icon beside Memory, with the words only in the hover text', () => {
    const groups = [
      {
        provider: 'Qwen',
        models: [
          { id: 'Qwen-big', modelType: 'Qwen', variantId: 'big', name: 'Qwen Big', capabilities: ['reasoning'], size: 5_000_000_000, speedRating: 5, accuracyRating: 9, recommendedRam: '48GB', statusKind: 'downloadable' },
          { id: 'Qwen-tight', modelType: 'Qwen', variantId: 'tight', name: 'Qwen Tight', capabilities: ['reasoning'], size: 5_000_000_000, recommendedRam: '16GB', statusKind: 'downloadable' },
          { id: 'Qwen-small', modelType: 'Qwen', variantId: 'small', name: 'Qwen Small', capabilities: ['reasoning'], size: 5_000_000_000, recommendedRam: '8GB', statusKind: 'downloadable' },
          { id: 'Qwen-plain', modelType: 'Qwen', variantId: 'plain', name: 'Qwen Plain', capabilities: ['reasoning'], size: 5_000_000_000, statusKind: 'downloadable' },
        ],
      },
    ]
    sendInit({ reasoningGroups: groups, deviceMemoryGb: 12 })
    const rows = Array.from(container.querySelectorAll('.models-settings-row'))
    const iconOf = (row: Element) => row.querySelector('.models-settings-row-fact dt .models-settings-fit-icon')
    expect(iconOf(rows[0])?.className).toContain('models-settings-fit-icon-too-large')
    expect(iconOf(rows[1])?.className).toContain('models-settings-fit-icon-tight')
    expect(iconOf(rows[2])?.className).toContain('models-settings-fit-icon-comfortable')
    expect(iconOf(rows[3])).toBeNull()
    expect(rows[0].querySelectorAll('.models-settings-fit-icon').length).toBe(1)
    expect(rows[0].querySelector('.models-settings-row-footer')?.textContent).not.toMatch(/Too large|Tight fit|Runs well/)
    const memoryFact = rows[0].querySelector('.models-settings-row-fact:last-child')!
    expect(memoryFact.getAttribute('data-tooltip')).toBe('Memory: 48GB or more (This Mac has 12GB). Likely too large for this Mac.')
    expect(memoryFact.querySelector('dd')?.textContent).toBe('48GB or more. This Mac has 12GB. Likely too large for this Mac.')
    expect(rows[1].querySelector('.models-settings-row-fact')?.getAttribute('data-tooltip')).toBe('Memory: 16GB or more (This Mac has 12GB). A tight fit: it may run slowly or fail to load.')
    expect(rows[2].querySelector('.models-settings-row-fact')?.getAttribute('data-tooltip')).toBe('Memory: 8GB or more (This Mac has 12GB). Should run well on this Mac.')
    expect((memoryFact.querySelector('.models-settings-fact-bar-marker') as HTMLElement).style.left).toBe('19%')

    sendInit({ reasoningGroups: groups })
    expect(container.querySelector('.models-settings-fit-icon')).toBeNull()
    expect(container.querySelector('.models-settings-fact-bar-marker')).toBeNull()
    expect(container.querySelector('.models-settings-row-fact:last-child')?.getAttribute('data-tooltip')).toBe('Memory: 48GB or more')
  })

  it('switches to transcription models via a pure client-side tab with no bridge message', () => {
    sendInit()
    postMessage.mockClear()
    const transcriptionTab = Array.from(container.querySelectorAll('[role="tab"]')).find((tab) => tab.textContent === 'Transcription') as HTMLButtonElement
    act(() => { transcriptionTab.click() })
    expect(container.textContent).toContain('Parakeet')
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('honors a sidebar request for the Transcription capability', () => {
    act(() => { root.render(<ModelsSettingsApp requestedSubTab="transcription" />) })
    sendInit()
    expect(container.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('Transcription')
    expect(container.textContent).toContain('Parakeet')
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
    const downloadButton = Array.from(container.querySelectorAll('button')).find((button) => button.getAttribute('aria-label')?.startsWith('Download ')) as HTMLButtonElement
    act(() => { downloadButton.click() })
    const requestId = lastMessageOfType('requestDownloadModel')?.requestId
    expect(requestId).toBeTruthy()
    expect(downloadButton.getAttribute('aria-label')).toMatch(/^Starting download of /)
    expect(downloadButton.getAttribute('data-tooltip')).toBe('Starting...')
    expect(downloadButton.disabled).toBe(true)
    sendInit({
      type: 'snapshot',
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'downloading', progress: 0.1, totalDownloaded: 1_000_000, totalSize: 10_000_000 }, REASONING_GROUPS[0].models[1]] }],
    })
    act(() => { window.basilModelsSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' }) })
    expect(container.querySelector('.download-progress__percent')?.textContent).toBe('10%')
    expect(container.querySelector('.download-progress__amount')?.textContent).toBe('1.0 MB / 10.0 MB')
    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('10')
  })

  it('explains a download that has not moved yet, and drops the note once bytes arrive', () => {
    const waiting = 'Waiting for Hugging Face to start sending data (20s)...'
    sendInit({
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'downloading', progress: 0, statusMessage: waiting }, REASONING_GROUPS[0].models[1]] }],
    })
    expect(container.querySelector('.download-progress__note')?.textContent).toBe(waiting)

    sendInit({
      type: 'snapshot',
      reasoningGroups: [{ provider: 'Qwen', models: [{ ...REASONING_GROUPS[0].models[0], statusKind: 'downloading', progress: 0, statusMessage: 'Downloading model.gguf...', totalDownloaded: 2_000_000, totalSize: 10_000_000 }, REASONING_GROUPS[0].models[1]] }],
    })
    expect(container.querySelector('.download-progress__note')).toBeNull()
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

  it('deletes an available model and surfaces a canceled result without an error message', () => {
    sendInit()
    const deleteButton = Array.from(container.querySelectorAll('button')).find((button) => button.getAttribute('aria-label')?.startsWith('Delete ')) as HTMLButtonElement
    act(() => { deleteButton.click() })
    const requestId = lastMessageOfType('requestDeleteModel')?.requestId
    expect(deleteButton.getAttribute('aria-label')).toMatch(/^Deleting /)
    expect(deleteButton.getAttribute('data-tooltip')).toBe('Deleting...')
    expect(deleteButton.disabled).toBe(true)
    act(() => { window.basilModelsSettings!.onEvent({ type: 'intentResult', requestId, status: 'canceled' }) })
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
