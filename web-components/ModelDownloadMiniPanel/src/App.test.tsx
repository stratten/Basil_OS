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
      { modelId: 'Qwen-qwen35-9b-q4km', status: 'downloading', progress: 40, totalDownloaded: 400, totalSize: 1000, isRetrying: false },
      { modelId: 'OpenAI-whisper-tiny.en', status: 'completed', progress: 100, totalDownloaded: null, totalSize: null, isRetrying: false },
      { modelId: 'unrecognized-model', status: 'queued', progress: 0, totalDownloaded: null, totalSize: null, isRetrying: false },
    ]) }))

    expect([...container.querySelectorAll('.model-row-title')].map(element => element.textContent)).toEqual(['Fast Transcription', 'Local Reasoning', 'unrecognized-model'])
    expect(container.textContent).toContain('400 bytes / 1.0 KB')
    const data = container.querySelector('.model-row .download-progress__data')!
    expect(Array.from(data.children).map(child => child.textContent)).toEqual(['400 bytes / 1.0 KB', '40%'])
    expect(container.querySelector('.model-row-action')!.textContent).not.toContain('%')
    expect(container.querySelectorAll('.download-progress')).toHaveLength(2)
    expect(container.textContent).toContain('Queued')
    expect(container.querySelector('[aria-label="Retry unrecognized-model"]')).toBeNull()
  })

  it('says why a download has not moved yet, only until bytes arrive', () => {
    const waiting = 'Waiting for Hugging Face to start sending data (20s)...'
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([
      { modelId: 'Qwen-qwen35-9b-q4km', status: 'downloading', progress: 0, totalDownloaded: 0, totalSize: 0, isRetrying: false, message: waiting },
      { modelId: 'NVIDIA-parakeet-tdt-0.6b-v3-quantized', status: 'downloading', progress: 0, totalDownloaded: 5_000_000, totalSize: 670_000_000, isRetrying: false, message: 'Downloading model...' },
    ]) }))

    const notes = [...container.querySelectorAll('.download-progress__note')]
    expect(notes.map(note => note.textContent)).toEqual([waiting])
  })

  it('shows completed state and invokes native dismiss', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([], { isComplete: true, quantizedPercentage: 100 }) }))

    expect(container.textContent).toContain('Models ready')
    const dismiss = container.querySelector<HTMLButtonElement>('[aria-label="Dismiss model download panel"]')!
    act(() => dismiss.click())
    expect(state.dismissPanel).toHaveBeenCalledOnce()
  })

  it('puts the close control first in the header, drawn as a centered vector glyph', () => {
    act(() => state.initHandler!({ theme, fonts, snapshot: makeSnapshot([]) }))

    const header = container.querySelector('.model-download-header')!
    const dismiss = header.querySelector<HTMLButtonElement>('[aria-label="Dismiss model download panel"]')!
    expect(header.firstElementChild).toBe(dismiss)
    expect(dismiss.textContent).toBe('')
    const glyph = dismiss.querySelector('svg')!
    expect(glyph.getAttribute('viewBox')).toBe('0 0 22 22')
    const circle = glyph.querySelector('circle')!
    expect([circle.getAttribute('cx'), circle.getAttribute('cy')]).toEqual(['11', '11'])
    const strokes = [...glyph.querySelectorAll('line')]
    expect(strokes).toHaveLength(2)
    expect(strokes.map(line => [line.getAttribute('x1'), line.getAttribute('y1'), line.getAttribute('x2'), line.getAttribute('y2')])).toEqual([
      ['7.5', '7.5', '14.5', '14.5'],
      ['14.5', '7.5', '7.5', '14.5'],
    ])
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
