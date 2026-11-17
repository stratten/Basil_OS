// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ModelDownloadRows, resetModelDownloadMemory } from './ModelDownloadRows'
import type { StarterDownloadRow } from './starterDownloads'

function makeRow(overrides: Partial<StarterDownloadRow> = {}): StarterDownloadRow {
  return {
    id: 'OpenAI-whisper-tiny.en',
    modelType: 'OpenAI',
    variant: 'whisper-tiny.en',
    title: 'Whisper Tiny (English)',
    role: 'Fast voice model',
    detail: 'Turns your speech into text quickly, in English (151MB)',
    state: 'pending',
    percent: 0,
    downloadedBytes: null,
    totalBytes: null,
    isVoiceModel: true,
    canCopy: false,
    ...overrides,
  }
}

let container: HTMLDivElement
let root: Root

function render(rows: StarterDownloadRow[]) {
  act(() => {
    root.render(<ModelDownloadRows rows={rows} startingIds={new Set()} error={null} onStart={vi.fn()} onStartAll={vi.fn()} />)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  resetModelDownloadMemory()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('ModelDownloadRows', () => {
  it('leads each row with a role badge that is tinted by kind, before the model name', () => {
    render([
      makeRow(),
      makeRow({ id: 'Qwen-qwen', title: 'Qwen3.6-35B-A3B MLX 4-bit', role: 'Thinking model', detail: 'The model that does my thinking (20GB)', isVoiceModel: false }),
    ])

    const rows = Array.from(container.querySelectorAll('.model-downloads__row'))
    const voiceIdentity = rows[0].querySelector('.model-downloads__identity')!
    expect(voiceIdentity.children[0].className).toBe('model-downloads__role model-downloads__role--voice')
    expect(voiceIdentity.children[0].textContent).toBe('Fast voice model')
    expect(voiceIdentity.children[1].className).toBe('model-downloads__name')
    expect(rows[1].querySelector('.model-downloads__role')?.className).toBe('model-downloads__role model-downloads__role--thinking')
    expect(rows[1].querySelector('.model-downloads__role')?.textContent).toBe('Thinking model')
  })

  it('says Ready for a model it watched finish and Already on this computer for one that was finished when first shown', () => {
    render([
      makeRow({ state: 'downloading', percent: 40 }),
      makeRow({ id: 'Qwen-qwen', title: 'Qwen', role: 'Thinking model', isVoiceModel: false, state: 'completed', percent: 100 }),
    ])
    render([
      makeRow({ state: 'completed', percent: 100 }),
      makeRow({ id: 'Qwen-qwen', title: 'Qwen', role: 'Thinking model', isVoiceModel: false, state: 'completed', percent: 100 }),
    ])

    const states = Array.from(container.querySelectorAll('.model-downloads__state')).map(node => node.textContent)
    expect(states).toEqual(['Ready', 'Already on this computer'])
  })

  it('keeps saying Ready after the list is shown again on another screen', () => {
    render([makeRow({ state: 'failed' })])
    act(() => { root.unmount() })
    root = createRoot(container)
    render([makeRow({ state: 'completed', percent: 100 })])

    expect(container.querySelector('.model-downloads__state')?.textContent).toBe('Ready')
  })

  it('keeps every field of a row: role, name, description with its size, and the matching action', () => {
    render([makeRow({ canCopy: true, state: 'failed' })])

    const row = container.querySelector('.model-downloads__row')!
    expect(row.textContent).toContain('Fast voice model')
    expect(row.textContent).toContain('Whisper Tiny (English)')
    expect(row.textContent).toContain('Turns your speech into text quickly, in English (151MB)')
    expect(row.textContent).toContain('Failed')
    expect(Array.from(row.querySelectorAll('button')).map(button => button.textContent)).toEqual(['Retry', 'Copy from my Basil'])
  })
})
