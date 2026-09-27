// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionSettingsPanel } from './TranscriptionSettingsPanel'
import type { TranscriptionSettingsFields, TranscriptionUnloadDelayOption } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onSettingsChange: (settings: TranscriptionSettingsFields) => void
let onTrackRequest: (id: string) => void

const BASE_SETTINGS: TranscriptionSettingsFields = {
  selectedModel: 'whisper-1',
  apiModels: [{ id: 'whisper-1', displayName: 'Whisper', isApiModel: true, provider: 'openai' }],
  localModels: [{ id: 'parakeet', displayName: 'parakeet', isApiModel: false, provider: null }],
  unloadDelaySeconds: 60,
  autoPasteTranscription: false,
  autoCloseOnPaste: false,
  startMeetingDetectionAtStartup: false,
  enablePushToTalk: false,
  pushToTalkThresholdMs: 750,
  textReplacements: [],
}

const UNLOAD_DELAY_OPTIONS: TranscriptionUnloadDelayOption[] = [
  { seconds: 60, label: '1 minute' },
  { seconds: 300, label: '5 minutes' },
]

function render(settings: TranscriptionSettingsFields, disabled = false) {
  act(() => {
    root.render(
      <TranscriptionSettingsPanel
        settings={settings}
        unloadDelayOptions={UNLOAD_DELAY_OPTIONS}
        disabled={disabled}
        onSettingsChange={onSettingsChange}
        onTrackRequest={onTrackRequest}
      />
    )
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  onSettingsChange = vi.fn<(settings: TranscriptionSettingsFields) => void>()
  onTrackRequest = vi.fn<(id: string) => void>()
  window.webkit = { messageHandlers: { basilTranscriptionSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('TranscriptionSettingsPanel', () => {
  it('sends requestUpdateAutoPaste when the Auto Paste switch is toggled', () => {
    render(BASE_SETTINGS)
    const autoPasteInput = container.querySelector<HTMLInputElement>('#transcription-auto-paste')!
    act(() => { autoPasteInput.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateAutoPaste', enabled: true }))
    expect(onTrackRequest).toHaveBeenCalledTimes(1)
    expect(onSettingsChange).toHaveBeenCalledWith({ ...BASE_SETTINGS, autoPasteTranscription: true })
  })

  it('locks every setting control while a request is pending', () => {
    render(BASE_SETTINGS, true)
    const autoPasteInput = container.querySelector<HTMLInputElement>('#transcription-auto-paste')!
    expect(autoPasteInput.disabled).toBe(true)
    expect(container.querySelector<HTMLButtonElement>('.transcription-model-select')!.disabled).toBe(true)
    act(() => { autoPasteInput.click() })
    expect(postMessage).not.toHaveBeenCalled()
  })

  it('sends requestUpdateSelectedModel when the Default Model select changes', () => {
    render(BASE_SETTINGS)
    const select = container.querySelector<HTMLButtonElement>('.transcription-model-select')!
    act(() => { select.click() })
    const parakeetOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'parakeet')!
    act(() => { parakeetOption.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateSelectedModel', modelId: 'parakeet' }))
  })

  it('sends requestUpdateMeetingDetectionStartup when the launch switch is toggled', () => {
    render(BASE_SETTINGS)
    const startupInput = container.querySelector<HTMLInputElement>('#transcription-start-meeting-detection')!
    act(() => { startupInput.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateMeetingDetectionStartup', enabled: true }))
  })

  it('commits a push-to-talk threshold change on blur', () => {
    render({ ...BASE_SETTINGS, enablePushToTalk: true })
    const thresholdInput = container.querySelector<HTMLInputElement>('#transcription-ptt-threshold')!
    const setInputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    act(() => {
      thresholdInput.focus()
      setInputValue.call(thresholdInput, '1200')
      thresholdInput.dispatchEvent(new Event('input', { bubbles: true }))
      thresholdInput.blur()
    })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdatePushToTalkThreshold', thresholdMs: 1200 }))
  })
})
