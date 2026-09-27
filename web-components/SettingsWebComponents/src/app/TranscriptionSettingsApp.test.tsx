// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionSettingsApp } from './TranscriptionSettingsApp'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const INIT_EVENT = {
  type: 'init' as const,
  protocolVersion: 1 as const,
  settings: {
    selectedModel: 'whisper-1',
    apiModels: [{ id: 'whisper-1', displayName: 'Whisper', isApiModel: true, provider: 'openai' }],
    localModels: [{ id: 'parakeet', displayName: 'parakeet', isApiModel: false, provider: null }],
    unloadDelaySeconds: 60,
    autoPasteTranscription: false,
    autoCloseOnPaste: false,
    startMeetingDetectionAtStartup: false,
    enablePushToTalk: false,
    pushToTalkThresholdMs: 750,
    textReplacements: [] as { source: string; replacement: string }[],
  },
  unloadDelayOptions: [{ seconds: 60, label: '1 minute' }, { seconds: 300, label: '5 minutes' }],
}

function findTab(label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('.settings-subtabs-tab')).find((button) => button.textContent === label)!
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilTranscriptionSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<TranscriptionSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('TranscriptionSettingsApp', () => {
  it('shows a loading state before init arrives, then the loaded shell with three sub-tabs', () => {
    expect(container.querySelector('.transcription-settings-loading')).not.toBeNull()
    act(() => { window.basilTranscriptionSettings!.onEvent(INIT_EVENT) })
    expect(container.querySelector('.transcription-settings-panel')).not.toBeNull()
    expect(Array.from(container.querySelectorAll('.settings-subtabs-tab')).map((tab) => tab.textContent)).toEqual(['Settings', 'History', 'Replacements'])
  })

  it('surfaces a load error with a working retry button', () => {
    act(() => { window.basilTranscriptionSettings!.onEvent({ type: 'loadError', message: 'Could not load transcription settings.' }) })
    expect(container.querySelector('.transcription-settings-error')?.textContent).toContain('Could not load transcription settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('.transcription-settings-error button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('surfaces an intentResult error from a setting update', () => {
    act(() => { window.basilTranscriptionSettings!.onEvent(INIT_EVENT) })
    const autoPasteInput = container.querySelector<HTMLInputElement>('#transcription-auto-paste')!
    let requestId = ''
    postMessage.mockImplementation((message: { type: string; requestId?: string }) => {
      if (message.type === 'requestUpdateAutoPaste') requestId = message.requestId ?? ''
    })
    act(() => { autoPasteInput.click() })
    act(() => {
      window.basilTranscriptionSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to save the setting.' })
    })
    expect(container.querySelector('.transcription-settings-error')?.textContent).toBe('Failed to save the setting.')
  })

  it('defaults to the Settings sub-tab and switches to Replacements and History when selected', () => {
    act(() => { window.basilTranscriptionSettings!.onEvent(INIT_EVENT) })
    expect(findTab('Settings').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('#transcription-sub-panel-settings')?.classList.contains('transcription-sub-tab-hidden')).toBe(false)
    expect(container.querySelector('#transcription-sub-panel-replacements')?.classList.contains('transcription-sub-tab-hidden')).toBe(true)

    act(() => { findTab('Replacements').click() })
    expect(findTab('Replacements').getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('#transcription-sub-panel-replacements')?.classList.contains('transcription-sub-tab-hidden')).toBe(false)
    expect(container.querySelector('#transcription-sub-panel-settings')?.classList.contains('transcription-sub-tab-hidden')).toBe(true)
    expect(container.querySelector('h2')?.textContent).toBe('Model Settings')
    expect(Array.from(container.querySelectorAll('h2')).map((heading) => heading.textContent)).toContain('Text replacements')

    act(() => { findTab('History').click() })
    act(() => {
      window.basilTranscriptionHistory!.onEvent({
        type: 'init',
        protocolVersion: 1,
        isLoading: false,
        error: null,
        timeFrameId: 'week',
        searchText: '',
        currentlyPlayingId: null,
        activeRetranscriptionId: null,
        retranscriptionProgressMessage: null,
        retranscriptionProgressFraction: null,
        currentGlobalTranscriptionModelId: 'whisper-1',
        availableRetranscriptionModels: [],
        transcriptions: [],
        timeFrameOptions: [{ id: 'week', label: '7 Days' }],
      })
    })
    expect(container.querySelector('.transcription-history-panel')).not.toBeNull()
  })

  it('adds a text replacement rule from the Replacements sub-tab and keeps it after re-selecting the tab', () => {
    act(() => { window.basilTranscriptionSettings!.onEvent(INIT_EVENT) })
    act(() => { findTab('Replacements').click() })

    const sourceInput = container.querySelector<HTMLInputElement>('#transcription-replacement-source')!
    const replacementInput = container.querySelector<HTMLInputElement>('#transcription-replacement-target')!
    const setInputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      setInputValue.call(sourceInput, 'slash')
      sourceInput.dispatchEvent(new Event('input', { bubbles: true }))
      setInputValue.call(replacementInput, '/')
      replacementInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const addButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === 'Add')!
    act(() => { addButton.click() })

    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateTextReplacements', rules: [{ source: 'slash', replacement: '/' }] })
    )

    act(() => { findTab('Settings').click() })
    act(() => { findTab('Replacements').click() })
    expect(container.querySelector('.transcription-text-replacement-source')?.textContent).toBe('slash')
  })
})
