// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { WritingExamplesSettingsApp } from './WritingExamplesSettingsApp'
import type { WritingExampleSample } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const SAMPLE: WritingExampleSample = {
  id: 'sample-1',
  contextType: 'email_reply',
  content: 'Thanks for reaching out, I will follow up tomorrow.',
  recipient: 'jordan@example.com',
  createdAt: '2026-08-01T10:00:00Z',
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map(([message]) => message).reverse().find((message) => message.type === type)
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilWritingExamplesSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<WritingExamplesSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

function sendInit(overrides: Partial<{ activeFilter: string; samples: WritingExampleSample[]; isLoadingSamples: boolean }> = {}) {
  act(() => {
    window.basilWritingExamplesSettings!.onEvent({
      type: 'init',
      protocolVersion: 1,
      activeFilter: (overrides.activeFilter ?? 'all') as any,
      samples: overrides.samples ?? [],
      styleProfile: null,
      isLoadingSamples: overrides.isLoadingSamples ?? false,
    })
  })
}

describe('WritingExamplesSettingsApp', () => {
  it('shows a loading state before the first init/snapshot event arrives', () => {
    expect(container.querySelector('.writing-examples-status')?.textContent).toBe('Loading Writing Examples settings...')
  })

  it('renders the empty state for the active filter once loaded with no samples', () => {
    sendInit()
    expect(container.querySelector('.writing-examples-samples-section .writing-examples-empty')?.textContent).toContain('No writing samples found')
  })

  it('sends setContextFilter with no requestId when a filter tab is clicked', () => {
    sendInit()
    act(() => { container.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="false"]')!.click() })
    const message = lastMessageOfType('setContextFilter')
    expect(message).toEqual({ type: 'setContextFilter', filter: 'email_reply' })
  })

  it('hides the style section for the "all" filter and shows it otherwise', () => {
    sendInit({ activeFilter: 'all' })
    expect(container.querySelector('.writing-examples-style-section')).toBeNull()
    sendInit({ activeFilter: 'email_reply' })
    expect(container.querySelector('.writing-examples-style-section')).not.toBeNull()
  })

  it('renders samples with recipient and lets View Full Text expand the content', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    expect(container.querySelector('.writing-examples-list-recipient')?.textContent).toBe('To: jordan@example.com')
    const viewFullTextButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'View Full Text')!
    act(() => { viewFullTextButton.click() })
    expect(container.querySelector('.writing-examples-list-preview')?.textContent).toBe(SAMPLE.content)
  })

  it('does not render a recipient row when recipient is null', () => {
    sendInit({ activeFilter: 'email_reply', samples: [{ ...SAMPLE, recipient: null }] })
    expect(container.querySelector('.writing-examples-list-recipient')).toBeNull()
  })

  it('sends requestDeleteSample with a requestId and disables actions while pending', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    expect(lastMessageOfType('requestDeleteSample')).toEqual(expect.objectContaining({ id: 'sample-1' }))
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows no error banner when a delete is cancelled by the native confirmation', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    const requestId = lastMessageOfType('requestDeleteSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId, status: 'cancelled' }) })
    expect(container.querySelector('.writing-examples-status-error')).toBeNull()
    expect((deleteButton as HTMLButtonElement).disabled).toBe(false)
  })

  it('reconciles the successful delete snapshot before re-enabling actions', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete') as HTMLButtonElement
    act(() => { deleteButton.click() })
    const requestId = lastMessageOfType('requestDeleteSample').requestId
    act(() => {
      window.basilWritingExamplesSettings!.onEvent({
        type: 'snapshot',
        activeFilter: 'email_reply',
        samples: [],
        styleProfile: null,
        isLoadingSamples: false,
      })
    })
    expect(container.querySelector('.writing-examples-samples-section .writing-examples-empty')?.textContent).toContain('No writing samples found')
    expect(deleteButton.isConnected).toBe(false)
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' }) })
    expect(container.querySelector<HTMLButtonElement>('.writing-examples-delete-all-button')!.disabled).toBe(true)
  })

  it('disables Analyze for the "all" filter', () => {
    sendInit({ activeFilter: 'all' })
    expect(container.querySelector('.writing-examples-style-section')).toBeNull()
  })

  it('sends analyzeStyle for a non-"all" filter and shows an Analyzing state', () => {
    sendInit({ activeFilter: 'document' })
    const analyzeButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Analyze')!
    act(() => { analyzeButton.click() })
    expect(lastMessageOfType('analyzeStyle')).toEqual(expect.objectContaining({ filter: 'document' }))
    expect(analyzeButton.textContent).toBe('Analyzing...')
  })

  it('disables Delete All Samples when the list is empty and enables it once populated', () => {
    sendInit({ activeFilter: 'email_reply', samples: [] })
    const deleteAllButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete All Samples') as HTMLButtonElement
    expect(deleteAllButton.disabled).toBe(true)
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    expect(deleteAllButton.disabled).toBe(false)
  })

  it('copies content via the bridge and shows a temporary Copied state', () => {
    vi.useFakeTimers()
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const copyButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Copy')!
    act(() => { copyButton.click() })
    expect(lastMessageOfType('copySampleToClipboard')).toEqual({ type: 'copySampleToClipboard', content: SAMPLE.content })
    expect(copyButton.textContent).toBe('Copied')
    act(() => { vi.advanceTimersByTime(1300) })
    expect(copyButton.textContent).toBe('Copy')
  })

  it('shows a loading row while isLoadingSamples is true without clearing prior samples visually as an error', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    sendInit({ activeFilter: 'document', samples: [SAMPLE], isLoadingSamples: true })
    expect(container.querySelector('.writing-examples-status')?.textContent).toBe('Loading writing samples...')
  })

  it('surfaces a load error with a retry action', () => {
    sendInit({ activeFilter: 'document' })
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'loadError', message: 'Failed to load Writing Examples settings.' }) })
    expect(container.querySelector('.writing-examples-error p')?.textContent).toBe('Failed to load Writing Examples settings.')
    const retryButton = container.querySelector<HTMLButtonElement>('.writing-examples-error .secondary-button')!
    act(() => { retryButton.click() })
    expect(lastMessageOfType('setContextFilter')).toEqual({ type: 'setContextFilter', filter: 'document' })
  })
})
