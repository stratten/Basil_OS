// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { ActivityCaptureSettingsApp } from './ActivityCaptureSettingsApp'
import type { ActivityCaptureNativeEvent } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

function initEvent(overrides: Partial<Extract<ActivityCaptureNativeEvent, { type: 'init' }>> = {}): ActivityCaptureNativeEvent {
  return {
    type: 'init',
    protocolVersion: 1,
    settings: {
      enabled: true, frequencySeconds: 300, idleThresholdSeconds: 120, postWakeGraceSeconds: 5,
      excludedBundleIds: ['com.apple.Terminal'], processingModel: '', processingMode: 'realtime',
      scheduledProcessingTime: '02:00', processingMaxRecords: 0, autoCleanupEnabled: false,
      retentionDays: 30, cleanupHour: 2, cleanupMinute: 0, maxStorageMb: 500,
    },
    status: {
      isSchedulerRunning: true, nextCaptureTime: null, todaysCaptures: 4,
      totalCapturesLast7Days: 20, totalCapturesLast30Days: 80, pendingCaptures: 0,
      failedCaptures: 0, skippedCaptureCount: 0, compactedCaptureCount: 0, lastPolicyDecision: null,
    },
    stats: { totalFiles: 10, totalSizeBytes: 2_000_000, filesLast7Days: 3, filesLast30Days: 8 },
    processingProgress: null,
    availableModels: [],
    availableApps: [],
    excludedApps: [],
    retentionDayOptions: [0, 7, 14, 30, 60, 90, 180, 365],
    maxStorageOptions: [50, 100, 200, 500, 1000, 2000, 5000],
    ...overrides,
  }
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilActivityCaptureSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<ActivityCaptureSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('ActivityCaptureSettingsApp', () => {
  it('shows a loading state before init and renders the shell after init', () => {
    expect(container.textContent).toContain('Loading Activity Capture settings...')
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent()) })
    expect(container.querySelector('.activity-capture-shell')).not.toBeNull()
    expect(container.querySelector('.activity-capture-badge-running')?.textContent).toBe('Running')
  })

  it('surfaces a load error with a retry action that re-sends reactReady', () => {
    act(() => { window.basilActivityCaptureSettings!.onEvent({ type: 'loadError', message: 'Failed to load Activity Capture settings.' }) })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load Activity Capture settings.')
    postMessage.mockClear()
    act(() => { container.querySelector<HTMLButtonElement>('button')!.click() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('optimistically updates the capture frequency and posts the matching field request', () => {
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent()) })
    const select = container.querySelector<HTMLButtonElement>('[aria-label="Capture Frequency"]')!
    act(() => { select.click() })
    const option = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((element) => element.textContent === '1 Minute')!
    act(() => { option.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateFrequencySeconds', frequencySeconds: 60 }))
  })

  it('runs Test Capture through its own correlated requestId and clears the pending state on intentResult', () => {
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent()) })
    const testButton = Array.from(container.querySelectorAll('button')).find((btn) => btn.textContent === 'Test Capture')!
    act(() => { testButton.click() })
    expect(testButton.textContent).toBe('Capturing…')
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestTestCapture').requestId
    act(() => { window.basilActivityCaptureSettings!.onEvent({ type: 'intentResult', requestId, status: 'success', message: 'Test capture completed successfully: Finder - Untitled' }) })
    expect(testButton.textContent).toBe('Test Capture')
    expect(container.querySelector('.activity-capture-status-message')?.textContent).toBe('Test capture completed successfully: Finder - Untitled')
  })

  it('drives Process Backlog into an active progress bar with a working Cancel button, then stops polling on completion', () => {
    vi.useFakeTimers()
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent()) })
    const processButton = Array.from(container.querySelectorAll('button')).find((btn) => btn.textContent === 'Process Backlog')!
    act(() => { processButton.click() })
    const processRequestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestProcessBacklog').requestId
    act(() => { window.basilActivityCaptureSettings!.onEvent({ type: 'intentResult', requestId: processRequestId, status: 'success' }) })
    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'progress',
        processingProgress: { active: true, total: 10, processed: 2, succeeded: 2, failed: 0, remaining: 8, etaSeconds: 120, cancelRequested: false, processingStrategy: null, analysisConcurrency: null },
      })
    })
    expect(container.querySelector('.activity-capture-progress')?.textContent).toContain('2 of 10 processed')
    const cancelButton = Array.from(container.querySelectorAll('button')).find((btn) => btn.textContent === 'Cancel')!
    act(() => { cancelButton.click() })
    const cancelRequestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestCancelProcessing').requestId
    expect(cancelRequestId).toBeTruthy()
    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'progress',
        processingProgress: { active: false, total: 10, processed: 10, succeeded: 9, failed: 1, remaining: 0, etaSeconds: null, cancelRequested: true, processingStrategy: null, analysisConcurrency: null },
      })
    })
    expect(Array.from(container.querySelectorAll('button')).find((btn) => btn.textContent === 'Process Backlog')).not.toBeUndefined()
    expect(container.querySelector('.activity-capture-cancel-button')).toBeNull()
    expect(container.querySelector('.activity-capture-progress')).toBeNull()
  })

  it('sends Clear Backlog and treats a native "canceled" intentResult as a no-op, without a status refresh', () => {
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent({ status: { isSchedulerRunning: true, nextCaptureTime: null, todaysCaptures: 0, totalCapturesLast7Days: 0, totalCapturesLast30Days: 0, pendingCaptures: 3, failedCaptures: 1, skippedCaptureCount: 0, compactedCaptureCount: 0, lastPolicyDecision: null } })) })
    const clearButton = Array.from(container.querySelectorAll('button')).find((btn) => btn.textContent === 'Clear Backlog')!
    act(() => { clearButton.click() })
    expect(clearButton.textContent).toBe('Clearing…')
    const requestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestClearBacklog').requestId
    postMessage.mockClear()
    act(() => { window.basilActivityCaptureSettings!.onEvent({ type: 'intentResult', requestId, status: 'canceled' }) })
    expect(clearButton.textContent).toBe('Clear Backlog')
    expect(postMessage).not.toHaveBeenCalledWith({ type: 'requestStatus' })
    expect(container.querySelector('.activity-capture-status-message')).toBeNull()
  })

  it('shows excluded apps as removable chips and supports picking from the pre-populated running-apps list', () => {
    act(() => {
      window.basilActivityCaptureSettings!.onEvent(initEvent({
        availableApps: [
          { bundleId: 'com.apple.Terminal', name: 'Terminal', iconDataUrl: 'data:image/png;base64,AAA' },
          { bundleId: 'com.apple.finder', name: 'Finder', iconDataUrl: null },
          { bundleId: 'com.apple.Safari', name: 'Safari', iconDataUrl: null },
        ],
      }))
    })

    expect(container.querySelector('.activity-capture-exclusions-chip')?.textContent).toContain('Terminal')

    const searchInput = container.querySelector<HTMLInputElement>('.activity-capture-exclusions-search-input')!
    postMessage.mockClear()
    act(() => { searchInput.focus() })
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestAvailableApps' })

    const dropdownItem = Array.from(container.querySelectorAll('.activity-capture-exclusions-dropdown-item')).find((el) => el.textContent?.includes('Finder'))!
    act(() => { dropdownItem.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestAddExcludedBundleId', bundleId: 'com.apple.finder' }))
    expect(Array.from(container.querySelectorAll('.activity-capture-exclusions-chip')).some((el) => el.textContent?.includes('Finder'))).toBe(true)

    const removeButton = Array.from(container.querySelectorAll('.activity-capture-exclusions-chip-remove')).find((btn) => btn.closest('.activity-capture-exclusions-chip')?.textContent?.includes('Terminal'))!
    postMessage.mockClear()
    act(() => { removeButton.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRemoveExcludedBundleId', bundleId: 'com.apple.Terminal' }))
    expect(Array.from(container.querySelectorAll('.activity-capture-exclusions-chip')).some((el) => el.textContent?.includes('Terminal'))).toBe(false)
  })

  it('debounces exclusion search text into a requestSearchApps call and only accepts the matching response', () => {
    vi.useFakeTimers()
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent()) })
    const searchInput = container.querySelector<HTMLInputElement>('.activity-capture-exclusions-search-input')!
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!

    act(() => {
      nativeSetter.call(searchInput, 'Paral')
      searchInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(postMessage.mock.calls.map(([value]) => value).some((value) => value.type === 'requestSearchApps')).toBe(false)

    act(() => { vi.advanceTimersByTime(200) })
    const searchCall = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestSearchApps')
    expect(searchCall).toEqual(expect.objectContaining({ query: 'Paral' }))

    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'searchAppsResults',
        requestId: 'stale-request-id',
        apps: [{ bundleId: 'com.stale.app', name: 'Stale App', iconDataUrl: null }],
      })
    })
    expect(Array.from(container.querySelectorAll('.activity-capture-exclusions-dropdown-item')).some((el) => el.textContent?.includes('Stale App'))).toBe(false)

    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'searchAppsResults',
        requestId: searchCall!.requestId,
        apps: [{ bundleId: 'com.parallels.desktop', name: 'Parallels Desktop', iconDataUrl: null }],
      })
    })
    expect(Array.from(container.querySelectorAll('.activity-capture-exclusions-dropdown-item')).some((el) => el.textContent?.includes('Parallels Desktop'))).toBe(true)
  })

  it('keeps the excluded chip showing the app name and icon even after the search that found it is cleared', () => {
    vi.useFakeTimers()
    act(() => { window.basilActivityCaptureSettings!.onEvent(initEvent({ availableApps: [] })) })
    const searchInput = container.querySelector<HTMLInputElement>('.activity-capture-exclusions-search-input')!
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!

    act(() => {
      nativeSetter.call(searchInput, 'Paral')
      searchInput.dispatchEvent(new Event('input', { bubbles: true }))
      vi.advanceTimersByTime(200)
    })
    const searchRequestId = postMessage.mock.calls.map(([value]) => value).find((value) => value.type === 'requestSearchApps').requestId
    act(() => {
      window.basilActivityCaptureSettings!.onEvent({
        type: 'searchAppsResults',
        requestId: searchRequestId,
        apps: [{ bundleId: 'com.parallels.desktop.console', name: 'Parallels Desktop', iconDataUrl: 'data:image/png;base64,BBB' }],
      })
    })
    const dropdownItem = Array.from(container.querySelectorAll('.activity-capture-exclusions-dropdown-item')).find((el) => el.textContent?.includes('Parallels Desktop'))!
    act(() => { dropdownItem.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

    const chip = Array.from(container.querySelectorAll('.activity-capture-exclusions-chip')).find((el) => el.textContent?.toLowerCase().includes('parallels'))!
    expect(chip.textContent).toContain('Parallels Desktop')
    expect(chip.textContent).not.toContain('com.parallels.desktop.console')
    expect(chip.querySelector('img.activity-capture-exclusions-icon')).not.toBeNull()
    expect(chip.querySelector('.activity-capture-exclusions-icon-placeholder')).toBeNull()
  })

  it('resolves the name and icon of an already-excluded app straight from the init payload, even when that app is not currently running', () => {
    act(() => {
      window.basilActivityCaptureSettings!.onEvent(initEvent({
        availableApps: [],
        excludedApps: [{ bundleId: 'com.apple.Terminal', name: 'Terminal', iconDataUrl: 'data:image/png;base64,CCC' }],
      }))
    })

    const chip = Array.from(container.querySelectorAll('.activity-capture-exclusions-chip')).find((el) => el.textContent?.includes('Terminal'))!
    expect(chip.textContent).toContain('Terminal')
    expect(chip.textContent).not.toContain('com.apple.Terminal')
    expect(chip.querySelector('img.activity-capture-exclusions-icon')).not.toBeNull()
    expect(chip.querySelector('.activity-capture-exclusions-icon-placeholder')).toBeNull()
  })
})
