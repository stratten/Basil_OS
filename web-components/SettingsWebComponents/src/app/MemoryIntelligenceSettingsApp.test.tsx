// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryIntelligenceSettingsApp } from './MemoryIntelligenceSettingsApp'
import type { MemoryDocument, MemoryIntelligenceSettings, MemoryProposal } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SETTINGS: MemoryIntelligenceSettings = {
  memoryAfterTaskEnabled: false,
  memoryDailyEnabled: false,
  memoryDailyTimeLocal: '03:00',
  memoryProcessingModel: null,
}

const PROPOSAL: MemoryProposal = {
  id: 'proposal-1',
  targetFileName: 'preferences.md',
  entry: 'User prefers concise replies.',
  why: 'Observed across 3 tasks.',
  confidence: 'high',
  createdAt: '2026-08-20',
}

const DOCUMENT: MemoryDocument = {
  fileName: 'preferences.md',
  sizeBytes: 512,
  capBytes: 2048,
  updatedAt: '2026-08-20',
}

function findButton(text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent === text)!
}

function sendInit(overrides: Partial<{ settings: MemoryIntelligenceSettings; proposals: MemoryProposal[]; documents: MemoryDocument[] }> = {}) {
  act(() => {
    window.basilMemoryIntelligenceSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      settings: overrides.settings ?? SETTINGS,
      proposals: overrides.proposals ?? [PROPOSAL],
      documents: overrides.documents ?? [DOCUMENT],
      availableModels: [{ id: 'gpt-5', displayName: 'GPT-5' }],
    })
  })
}

describe('MemoryIntelligenceSettingsApp', () => {
  beforeEach(() => {
    postMessage = vi.fn()
    window.webkit = { messageHandlers: { basilMemoryIntelligenceSettingsBridge: { postMessage } } }
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<MemoryIntelligenceSettingsApp />) })
    sendInit()
  })

  afterEach(() => {
    act(() => { root.unmount() })
    container.remove()
  })

  it('hydrates settings, proposals, and documents from the init event', () => {
    expect(container.querySelector('.memory-intelligence-list-title')?.textContent).toBe('preferences.md')
    expect(container.querySelectorAll('.memory-intelligence-list')).toHaveLength(2)
  })

  it('renders the off-state cadence summary when both cadences are disabled', () => {
    expect(container.querySelector('.memory-intelligence-cadence')?.textContent)
      .toBe('Off. Basil will not propose memory updates unless you enable it.')
  })

  it('sends a correlated setting update when a toggle changes', () => {
    const toggle = container.querySelector<HTMLInputElement>('#memory-after-task-enabled')!
    act(() => { toggle.click() })
    const message = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'updateSetting')
    expect(message).toMatchObject({ field: 'memoryAfterTaskEnabled', value: true })
  })

  it('runs intelligence now and surfaces the resulting status message', () => {
    act(() => { findButton('Run now').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'runIntelligenceNow').requestId
    act(() => {
      window.basilMemoryIntelligenceSettings!.onEvent({
        type: 'intentResult',
        requestId,
        status: 'success',
        message: 'Added 2 memory proposal(s) and 0 skill candidate(s).',
      })
    })
    expect(container.querySelector('.memory-intelligence-status-info')?.textContent).toBe('Added 2 memory proposal(s) and 0 skill candidate(s).')
  })

  it('surfaces a failed mutation as an alert', () => {
    act(() => { findButton('Run now').click() })
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'runIntelligenceNow').requestId
    act(() => {
      window.basilMemoryIntelligenceSettings!.onEvent({
        type: 'intentResult',
        requestId,
        status: 'error',
        message: 'Memory intelligence ran, but the refreshed lists are unavailable.',
      })
    })
    expect(container.querySelector('.memory-intelligence-status-error')?.getAttribute('role')).toBe('alert')
  })

  it('declines a proposal and does not emit more than one request for rapid clicks', () => {
    act(() => {
      const declineButton = findButton('Decline')
      declineButton.click()
      declineButton.click()
    })
    expect(postMessage.mock.calls.filter(([value]) => value.type === 'declineProposal')).toHaveLength(1)
  })
})

describe('MemoryIntelligenceSettingsApp additional coverage', () => {
  beforeEach(() => {
    postMessage = vi.fn()
    window.webkit = { messageHandlers: { basilMemoryIntelligenceSettingsBridge: { postMessage } } }
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    act(() => { root.render(<MemoryIntelligenceSettingsApp />) })
  })

  afterEach(() => {
    act(() => { root.unmount() })
    container.remove()
  })

  it('opens a memory file without a request id, always enabled even while busy', () => {
    sendInit()
    act(() => { findButton('Run now').click() })
    const openButtons = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).filter((b) => b.textContent === 'Open')
    const fileOpen = openButtons[openButtons.length - 1]
    act(() => { fileOpen.click() })
    const openMessage = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'openMemoryFile')
    expect(openMessage).toEqual({ type: 'openMemoryFile', fileName: 'preferences.md' })
  })

  it('renders empty-state copy when there are no proposals or documents', () => {
    sendInit({ proposals: [], documents: [] })
    expect(container.querySelector('.memory-intelligence-empty')?.textContent).toBe('No pending proposals.')
    expect(Array.from(container.querySelectorAll('.memory-intelligence-empty')).map((el) => el.textContent))
      .toEqual(['No pending proposals.', 'No memory files found.'])
  })

  it('shows an unavailable configured evaluator model without changing it', () => {
    sendInit({
      settings: { ...SETTINGS, memoryProcessingModel: 'retired-model' },
    })
    const trigger = container.querySelector<HTMLButtonElement>('.memory-intelligence-select')!
    expect(trigger.textContent).toContain('retired-model (unavailable)')
    act(() => { trigger.click() })
    const options = Array.from(document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option'))
    expect(options.some((option) => option.textContent === 'retired-model (unavailable)')).toBe(true)
  })

  it('shows a retry button on load error', () => {
    act(() => {
      window.basilMemoryIntelligenceSettings!.onEvent({ type: 'loadError', message: 'Failed to load Personal Context settings.' })
    })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load Personal Context settings.')
    expect(findButton('Retry')).not.toBeNull()
  })
})
