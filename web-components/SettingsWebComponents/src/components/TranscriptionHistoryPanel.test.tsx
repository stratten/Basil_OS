// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionHistoryPanel } from './TranscriptionHistoryPanel'
import type { TranscriptionModelOptionFields, TranscriptionRecordFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function setNativeInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

const BASE_FIELDS = {
  isLoading: false,
  error: null,
  timeFrameId: 'week' as const,
  searchText: '',
  currentlyPlayingId: null,
  activeRetranscriptionId: null,
  retranscriptionProgressMessage: null,
  retranscriptionProgressFraction: null,
  currentGlobalTranscriptionModelId: 'whisper-1',
  availableRetranscriptionModels: [] as TranscriptionModelOptionFields[],
  transcriptions: [] as TranscriptionRecordFields[],
}

function initEvent(overrides: Partial<typeof BASE_FIELDS> = {}) {
  return {
    type: 'init' as const,
    protocolVersion: 1 as const,
    ...BASE_FIELDS,
    ...overrides,
    timeFrameOptions: [{ id: 'week' as const, label: '7 Days' }, { id: 'all' as const, label: 'All Time' }],
  }
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionHistoryBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<TranscriptionHistoryPanel />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('TranscriptionHistoryPanel', () => {
  it('shows the empty state when there are no transcriptions', () => {
    act(() => { window.basilTranscriptionHistory!.onEvent(initEvent()) })
    expect(container.querySelector('.transcription-history-empty')).not.toBeNull()
  })

  it('renders a row per transcription and sends requestPlayAudio when Play is clicked', () => {
    act(() => {
      window.basilTranscriptionHistory!.onEvent(initEvent({
        transcriptions: [{
          id: 'tx-1',
          formattedDate: 'Sep 2, 2026',
          formattedLastTranscribedDate: null,
          formattedDuration: '0:42',
          displayText: 'Hello world',
          modelName: 'whisper-1',
          status: 'completed',
          errorMessage: null,
        }],
      }))
    })
    const items = container.querySelectorAll('.transcription-history-item')
    expect(items.length).toBe(1)
    const playButton = Array.from(items[0].querySelectorAll('button')).find((b) => b.textContent === 'Play')!
    act(() => { playButton.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestPlayAudio', transcriptionId: 'tx-1' }))
  })

  it('requires a second click to confirm delete', () => {
    act(() => {
      window.basilTranscriptionHistory!.onEvent(initEvent({
        transcriptions: [{
          id: 'tx-1',
          formattedDate: 'Sep 2, 2026',
          formattedLastTranscribedDate: null,
          formattedDuration: '0:42',
          displayText: 'Hello world',
          modelName: 'whisper-1',
          status: 'completed',
          errorMessage: null,
        }],
      }))
    })
    const deleteButton = container.querySelector<HTMLButtonElement>('.transcription-history-delete-button')!
    expect(deleteButton.textContent).toBe('Delete')
    act(() => { deleteButton.click() })
    expect(deleteButton.textContent).toBe('Confirm Delete?')
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestDeleteTranscription' }))
    act(() => { deleteButton.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestDeleteTranscription', transcriptionId: 'tx-1' }))
    expect(deleteButton.disabled).toBe(true)
    act(() => { deleteButton.click() })
    expect(postMessage.mock.calls.filter(([message]) => message.type === 'requestDeleteTranscription')).toHaveLength(1)
  })

  it('sends one search request after 500 ms of idle typing', () => {
    vi.useFakeTimers()
    act(() => { window.basilTranscriptionHistory!.onEvent(initEvent()) })
    const search = container.querySelector<HTMLInputElement>('.transcription-history-search')!
    act(() => {
      setNativeInputValue(search, 'meet')
      vi.advanceTimersByTime(300)
      setNativeInputValue(search, 'meeting')
      vi.advanceTimersByTime(499)
    })
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestSetSearchText' }))
    expect(search.value).toBe('meeting')
    act(() => { vi.advanceTimersByTime(1) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestSetSearchText', text: 'meeting' }))
    expect(postMessage.mock.calls.filter(([message]) => message.type === 'requestSetSearchText')).toHaveLength(1)
  })

  it('clears an active search through the accessible icon control', () => {
    vi.useFakeTimers()
    act(() => { window.basilTranscriptionHistory!.onEvent(initEvent({ searchText: 'meeting' })) })
    const clearButton = container.querySelector<HTMLButtonElement>('[aria-label="Clear transcription search"]')!
    expect(clearButton.querySelector('svg')).not.toBeNull()
    act(() => { clearButton.click() })
    expect(container.querySelector<HTMLInputElement>('.transcription-history-search')!.value).toBe('')
    act(() => { vi.advanceTimersByTime(500) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestSetSearchText', text: '' }))
  })

  it('offers retranscription models in an action menu and sends the chosen ID', () => {
    act(() => {
      window.basilTranscriptionHistory!.onEvent(initEvent({
        transcriptions: [{
          id: 'tx-1',
          formattedDate: 'Sep 2, 2026',
          formattedLastTranscribedDate: null,
          formattedDuration: '0:42',
          displayText: 'Hello world',
          modelName: 'whisper-1',
          status: 'completed',
          errorMessage: null,
        }],
        availableRetranscriptionModels: [
          { id: 'whisper-1', displayName: 'Whisper', isApiModel: false, provider: null },
          { id: 'whisper-api', displayName: 'Whisper API', isApiModel: true, provider: 'openai' },
        ],
      }))
    })
    const retranscribeButton = container.querySelector<HTMLButtonElement>('[aria-label="Retranscribe"]')!
    act(() => { retranscribeButton.click() })
    expect(container.querySelector('[role="menu"]')?.textContent).toContain('Retranscribe with current model (Whisper)')
    const apiModelButton = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')).find((button) => button.textContent === 'Whisper API')!
    act(() => { apiModelButton.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRetranscribe', transcriptionId: 'tx-1', modelId: 'whisper-api' }))
  })

  it('closes the retranscription menu when the user clicks outside it', () => {
    act(() => {
      window.basilTranscriptionHistory!.onEvent(initEvent({
        transcriptions: [{
          id: 'tx-1',
          formattedDate: 'Sep 2, 2026',
          formattedLastTranscribedDate: null,
          formattedDuration: '0:42',
          displayText: 'Hello world',
          modelName: 'whisper-1',
          status: 'completed',
          errorMessage: null,
        }],
        availableRetranscriptionModels: [{ id: 'whisper-1', displayName: 'Whisper', isApiModel: false, provider: null }],
      }))
    })
    const retranscribeButton = container.querySelector<HTMLButtonElement>('[aria-label="Retranscribe"]')!
    act(() => { retranscribeButton.click() })
    expect(container.querySelector('[role="menu"]')).not.toBeNull()
    act(() => { document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
    expect(container.querySelector('[role="menu"]')).toBeNull()
  })
})
