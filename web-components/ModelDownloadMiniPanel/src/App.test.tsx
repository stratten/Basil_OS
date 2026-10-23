// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import App from './App'
import type { PanelSnapshot } from './types'

const state = vi.hoisted(() => ({
  initHandler: undefined as ((config: any) => void) | undefined,
  snapshotHandler: undefined as ((snapshot: PanelSnapshot) => void) | undefined,
  dismissPanel: vi.fn(),
  retryModel: vi.fn(),
  cancelModel: vi.fn(),
  requestResize: vi.fn(),
}))

vi.mock('./services/bridge', () => ({
  registerInitHandler: (handler: (config: any) => void) => { state.initHandler = handler },
  registerSnapshotHandler: (handler: (snapshot: PanelSnapshot) => void) => { state.snapshotHandler = handler },
  registerThemeHandler: () => undefined,
  notifyRendererReady: vi.fn(),
  dismissPanel: state.dismissPanel,
  retryModel: state.retryModel,
  cancelModel: state.cancelModel,
  requestResize: state.requestResize,
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
globalThis.requestAnimationFrame = callback => {
  callback(0)
  return 0
}

let container: HTMLElement
let root: Root

const theme = { backgroundPrimary: '#fff', primary: '#00f', secondary: '#111', textPrimary: '#000', successBase: '#080', warningBase: '#a60', recordingBase: '#c00' }
const fonts = { fontFamily: 'Arial', fontFamilyMedium: 'Arial', fontFamilyBold: 'Arial' }
const makeSnapshot = (models: PanelSnapshot['models'], values: Partial<PanelSnapshot> = {}): PanelSnapshot => ({
  phaseMessage: 'Downloading models',
  isComplete: false,
  quantizedPercentage: 33,
  appIconDataUrl: null,
  models,
  ...values,
})

beforeEach(() => {
  state.dismissPanel.mockClear()
  state.retryModel.mockClear()
  state.cancelModel.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<App />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ModelDownloadMiniPanel', () => {
  it('renders model progress in canonical order, preserving unknown models', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([
      { modelId: 'Qwen-qwen3-8b-instruct-q4km', status: 'downloading', progress: 40, totalDownloaded: 400, totalSize: 1000, isRetrying: false },
      { modelId: 'OpenAI-whisper-tiny.en', status: 'completed', progress: 100, totalDownloaded: null, totalSize: null, isRetrying: false },
      { modelId: 'unrecognized-model', status: 'queued', progress: 0, totalDownloaded: null, totalSize: null, isRetrying: false },
    ]) }))

    expect([...container.querySelectorAll('.model-row-title')].map(element => element.textContent)).toEqual(['Fast Transcription', 'Local Reasoning', 'unrecognized-model'])
    expect(container.textContent).toContain('400 bytes / 1.0 KB')
    expect(container.textContent).toContain('Queued')
    expect(container.querySelector('[aria-label="Retry unrecognized-model"]')).toBeNull()
  })

  it('shows completed state and invokes native dismiss', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([], { isComplete: true, quantizedPercentage: 100 }) }))

    expect(container.textContent).toContain('Models ready')
    const dismiss = container.querySelector<HTMLButtonElement>('[aria-label="Dismiss model download panel"]')!
    act(() => dismiss.click())
    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })

  it('deduplicates a retry click until the native snapshot acknowledges it', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([
      { modelId: 'OpenAI-whisper-tiny.en', status: 'failed', progress: 0, totalDownloaded: null, totalSize: null, isRetrying: false },
    ]) }))
    const retry = container.querySelector<HTMLButtonElement>('[aria-label="Retry Fast Transcription"]')!
    act(() => retry.click())

    expect(state.retryModel).toHaveBeenCalledOnce()
    expect(container.querySelector('[aria-label="Retry Fast Transcription"]')).toBeNull()
    expect(container.textContent).toContain('Starting...')
  })

  it('sends cancellation and exposes the explanation content', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([
      { modelId: 'NVIDIA-parakeet-tdt-0.6b-v3-quantized', status: 'downloading', progress: 50, totalDownloaded: null, totalSize: null, isRetrying: false },
    ]) }))
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Stop Quality Transcription download"]')!.click())
    act(() => container.querySelector<HTMLButtonElement>('.explanation-toggle')!.click())

    expect(state.cancelModel).toHaveBeenCalledWith('NVIDIA-parakeet-tdt-0.6b-v3-quantized')
    expect(container.textContent).toContain('Downloading in the background')
  })
})
