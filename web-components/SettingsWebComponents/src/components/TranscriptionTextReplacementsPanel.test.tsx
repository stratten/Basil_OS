// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { TranscriptionTextReplacementsPanel } from './TranscriptionTextReplacementsPanel'
import type { TranscriptionTextReplacementFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onRulesChange: (rules: TranscriptionTextReplacementFields[]) => void
let onTrackRequest: (id: string) => void

function render(rules: TranscriptionTextReplacementFields[], disabled = false) {
  act(() => {
    root.render(
      <TranscriptionTextReplacementsPanel
        rules={rules}
        disabled={disabled}
        onRulesChange={onRulesChange}
        onTrackRequest={onTrackRequest}
      />
    )
  })
}

function setValue(input: HTMLInputElement, value: string) {
  const setInputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    setInputValue.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  onRulesChange = vi.fn<(rules: TranscriptionTextReplacementFields[]) => void>()
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

describe('TranscriptionTextReplacementsPanel', () => {
  it('adds a text replacement rule and sends the full replacement list', () => {
    render([])
    const sourceInput = container.querySelector<HTMLInputElement>('#transcription-replacement-source')!
    const replacementInput = container.querySelector<HTMLInputElement>('#transcription-replacement-target')!
    setValue(sourceInput, 'slash')
    setValue(replacementInput, '/')
    const addButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === 'Add')!
    act(() => { addButton.click() })

    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'requestUpdateTextReplacements',
        rules: [{ source: 'slash', replacement: '/' }],
      })
    )
    expect(onRulesChange).toHaveBeenCalledWith([{ source: 'slash', replacement: '/' }])
    expect(onTrackRequest).toHaveBeenCalledTimes(1)
    // onRulesChange is a mock here (this is a prop-driven unit test), so the
    // rendered list still reflects the `rules` prop passed in, not the
    // submitted value -- the full round trip through a re-render with the
    // updated list is covered by TranscriptionSettingsApp.test.tsx.
    expect(sourceInput.value).toBe('')
    expect(replacementInput.value).toBe('')
  })

  it('rejects an empty spoken phrase without sending an update', () => {
    render([])
    const addButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === 'Add')!

    act(() => { addButton.click() })

    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateTextReplacements' }))
    expect(container.querySelector('.transcription-settings-error')?.textContent).toBe('Enter the spoken phrase to match.')
  })

  it('rejects a duplicate spoken phrase without sending an update', () => {
    render([{ source: 'slash', replacement: '/' }])
    const sourceInput = container.querySelector<HTMLInputElement>('#transcription-replacement-source')!
    setValue(sourceInput, 'Slash')
    const addButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === 'Add')!

    act(() => { addButton.click() })

    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateTextReplacements' }))
    expect(container.querySelector('.transcription-settings-error')?.textContent).toBe('A rule for this phrase already exists.')
  })

  it('removes a text replacement rule and sends the shortened list', () => {
    render([{ source: 'slash', replacement: '/' }])
    const removeButton = container.querySelector<HTMLButtonElement>('.transcription-text-replacement-remove')!

    act(() => { removeButton.click() })

    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateTextReplacements', rules: [] })
    )
    expect(onRulesChange).toHaveBeenCalledWith([])
  })

  it('disables all controls while a request is pending', () => {
    render([{ source: 'slash', replacement: '/' }], true)
    expect(container.querySelector<HTMLInputElement>('#transcription-replacement-source')!.disabled).toBe(true)
    expect(container.querySelector<HTMLButtonElement>('.transcription-text-replacement-remove')!.disabled).toBe(true)
  })
})
