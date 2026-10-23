// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoriesSettingsApp } from './MemoriesSettingsApp'
import type { MemoriesSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const FIXTURE_SETTINGS: MemoriesSettingsFields = {
  enabledSources: ['agent_task', 'conversation'],
  historyDays: 30,
  cardingEnabled: true,
  cardingIntervalMinutes: 15,
  limitPerSourcePerPass: 500,
  narrativeEnabled: true,
  narrativeModel: '',
  narrativeMode: 'scheduled',
  narrativeScheduledTime: '02:00',
  narrativeIntervalMinutes: 30,
  narrativeBatchSize: 50,
  narrativeMaxAttempts: 3,
  narrativeMaxRecords: 0,
}

function sendInit(overrides: Partial<Parameters<NonNullable<typeof window.basilMemoriesSettings>['onEvent']>[0]> = {}) {
  act(() => {
    window.basilMemoriesSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      settings: FIXTURE_SETTINGS,
      stats: null,
      narrativeProgress: null,
      availableModels: [],
      ...overrides,
    } as never)
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilMemoriesSettingsBridge: { postMessage } } }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<MemoriesSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('MemoriesSettingsApp', () => {
  it('shows a loading state before init arrives', () => {
    expect(container.querySelector('.memories-status')?.textContent).toBe('Loading Memories settings...')
  })

  it('renders the shell once init arrives', () => {
    sendInit()
    expect(container.querySelector('.memories-shell')).not.toBeNull()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    expect(container.querySelector('#memories-collecting-heading')?.parentElement?.textContent).toContain('Collection adds eligible activity to your timeline without using a model. Summary processing later uses your selected model to turn collected activity into short recaps.')
  })

  it('shows a retry button on load error', () => {
    act(() => {
      window.basilMemoriesSettings!.onEvent({ type: 'loadError', message: 'Failed to load Memories settings.' })
    })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load Memories settings.')
    expect(container.querySelector('.memories-error button')?.textContent).toBe('Retry')
  })

  it('optimistically applies a toggle change and posts the full settings object', () => {
    sendInit()
    const toggle = container.querySelector<HTMLInputElement>('.memories-card input[type="checkbox"]')!
    act(() => { toggle.click() })
    expect(toggle.checked).toBe(false)
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'requestUpdateSettings', settings: expect.objectContaining({ cardingEnabled: false }) }),
    )
  })

  it('disables Collect now while a request is in flight and re-enables on intentResult', () => {
    sendInit()
    const collectButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Collect now')!
    act(() => { collectButton.click() })
    expect(collectButton.textContent).toBe('Collecting…')
    const call = postMessage.mock.calls.find(([message]) => message.type === 'requestCollectNow')!
    const requestId = call[0].requestId
    act(() => {
      window.basilMemoriesSettings!.onEvent({ type: 'intentResult', requestId, status: 'success', message: 'Collection pass completed.' })
    })
    expect(Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Collect now')).not.toBeUndefined()
    expect(container.querySelector('.memories-collection-completion')?.textContent).toBe('Collection completed.')
  })

  it('polls narrative progress after Summarize now and stops once the run reports inactive', () => {
    vi.useFakeTimers()
    sendInit()
    const summarizeButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Summarize now')!
    act(() => { summarizeButton.click() })
    expect(summarizeButton.textContent).toBe('Summarizing…')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestNarrativeProgress' }))
    const progressCall = postMessage.mock.calls.find(([message]) => message.type === 'requestNarrativeProgress')!
    act(() => {
      window.basilMemoriesSettings!.onEvent({
        type: 'progress',
        requestId: progressCall[0].requestId,
        narrativeProgress: {
          active: true, total: 10, processed: 3, finalized: 3, stillOpen: 0, failed: 0, remaining: 7,
          etaSeconds: 42, lastError: null, canceling: false, analysisConcurrency: null, processingStrategy: null,
        },
      })
    })
    expect(container.querySelector('.memories-progress')).not.toBeNull()
    act(() => {
      window.basilMemoriesSettings!.onEvent({
        type: 'progress',
        requestId: progressCall[0].requestId,
        narrativeProgress: {
          active: false, total: 10, processed: 10, finalized: 10, stillOpen: 0, failed: 0, remaining: 0,
          etaSeconds: null, lastError: null, canceling: false, analysisConcurrency: null, processingStrategy: null,
        },
      })
    })
    expect(Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Summarize now')).not.toBeUndefined()
    expect(container.querySelector('.memories-progress')).toBeNull()
    expect(container.querySelector('.memories-summary-completion')?.textContent).toBe('Summary pass complete: 10 finalized.')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRefreshStats' }))
    const nextSummarizeButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Summarize now')!
    act(() => { nextSummarizeButton.click() })
    expect(container.querySelector('.memories-summary-completion')).toBeNull()
    vi.useRealTimers()
  })

  it('shows the settings-save error message inline without reverting the optimistic change', () => {
    sendInit()
    const toggle = container.querySelector<HTMLInputElement>('.memories-card input[type="checkbox"]')!
    act(() => { toggle.click() })
    const call = postMessage.mock.calls.find(([message]) => message.type === 'requestUpdateSettings')!
    act(() => {
      window.basilMemoriesSettings!.onEvent({ type: 'intentResult', requestId: call[0].requestId, status: 'error', message: 'Error: failed to save Memories settings' })
    })
    expect(toggle.checked).toBe(false)
    expect(container.querySelector('.memories-status-error')?.textContent).toBe('Error: failed to save Memories settings')
  })
})
