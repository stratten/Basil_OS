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

function typeInto(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')?.set
  act(() => {
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function contextTrigger(label: string) {
  return container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!
}

function openContextMenu(label: string) {
  act(() => { contextTrigger(label).click() })
  return Array.from(document.querySelectorAll<HTMLButtonElement>('[role="listbox"] [role="option"]'))
}

function chooseContext(label: string, optionLabel: string) {
  const option = openContextMenu(label).find((candidate) => candidate.textContent === optionLabel)!
  act(() => { option.click() })
}

function recipientChips() {
  return Array.from(container.querySelectorAll('.writing-examples-recipient-chip')).map((chip) => chip.textContent)
}

function findButton(label: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === label)
}

function tabMarker(label: string) {
  const tab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((candidate) => candidate.textContent === label)!
  return tab.querySelector('.writing-examples-filter-tab-marker')
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
    expect(container.querySelector('.writing-examples-recipient-label')?.textContent).toBe('To:')
    expect(recipientChips()).toEqual(['jordan@example.com'])
    expect(container.querySelector('.writing-examples-list-preview')?.classList.contains('writing-examples-markdown-collapsed')).toBe(true)
    const viewFullTextButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'View Full Text')!
    act(() => { viewFullTextButton.click() })
    const preview = container.querySelector('.writing-examples-list-preview')!
    expect(preview.textContent?.trim()).toBe(SAMPLE.content)
    expect(preview.classList.contains('writing-examples-markdown-collapsed')).toBe(false)
  })

  it('renders sample Markdown as formatted, sanitized HTML', () => {
    sendInit({
      activeFilter: 'document',
      samples: [{ ...SAMPLE, contextType: 'document', content: '**Bold** point\n\n- first\n- second\n\n<script>alert(1)</script>\n\nSee [site](https://example.com)' }],
    })
    const preview = container.querySelector('.writing-examples-list-preview')!
    expect(preview.querySelector('strong')?.textContent).toBe('Bold')
    expect(Array.from(preview.querySelectorAll('li')).map((item) => item.textContent)).toEqual(['first', 'second'])
    expect(preview.querySelector('script')).toBeNull()
    const link = preview.querySelector('a')!
    const click = new MouseEvent('click', { bubbles: true, cancelable: true })
    act(() => { link.dispatchEvent(click) })
    expect(click.defaultPrevented).toBe(true)
  })

  it('shows each comma or semicolon separated recipient as its own chip', () => {
    sendInit({ activeFilter: 'email_reply', samples: [{ ...SAMPLE, recipient: 'Ana <ana@example.com>, ben@example.com; ,  ' }] })
    expect(recipientChips()).toEqual(['Ana <ana@example.com>', 'ben@example.com'])
  })

  it('does not render a recipient row when recipient is null', () => {
    sendInit({ activeFilter: 'email_reply', samples: [{ ...SAMPLE, recipient: null }] })
    expect(container.querySelector('.writing-examples-list-recipient')).toBeNull()
  })

  it('opens the add form, submits a manual sample, and closes after success', () => {
    sendInit({ activeFilter: 'document' })
    const addButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Add Sample')!
    act(() => { addButton.click() })
    const contentInput = container.querySelector<HTMLTextAreaElement>('#writing-examples-add-content')!
    typeInto(contentInput, 'A manually added writing sample.')
    const saveButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Save Sample')!
    act(() => { saveButton.click() })
    const message = lastMessageOfType('requestAddSample')
    expect(message).toEqual(expect.objectContaining({
      content: 'A manually added writing sample.',
      contextType: 'document',
    }))
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: message.requestId, status: 'success' }) })
    expect(container.querySelector('#writing-examples-add-content')).toBeNull()
  })

  it('edits a sample inline, posts the updated text, and exits edit mode after success', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const editButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Edit')!
    act(() => { editButton.click() })
    const editInput = container.querySelector<HTMLTextAreaElement>('.writing-examples-list-row .writing-examples-textarea')!
    typeInto(editInput, 'Updated sample content.')
    const saveButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Save')!
    act(() => { saveButton.click() })
    const message = lastMessageOfType('requestUpdateSample')
    expect(message).toEqual(expect.objectContaining({ id: SAMPLE.id, content: 'Updated sample content.' }))
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: message.requestId, status: 'success' }) })
    expect(container.querySelector('.writing-examples-list-row .writing-examples-textarea')).toBeNull()
  })

  it('leaves edit mode when the context filter changes', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const editButton = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Edit')!
    act(() => { editButton.click() })
    expect(container.querySelector('textarea[aria-label="Edit writing sample"]')).not.toBeNull()
    const documentTab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find((tab) => tab.textContent === 'Document')!
    act(() => { documentTab.click() })
    sendInit({ activeFilter: 'document', samples: [SAMPLE] })
    expect(container.querySelector('textarea[aria-label="Edit writing sample"]')).toBeNull()
  })

  it('sends requestDeleteSample with a requestId and disables actions while pending', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    expect(lastMessageOfType('requestDeleteSample')).toEqual(expect.objectContaining({ id: 'sample-1' }))
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows no error banner when a delete is canceled by the native confirmation', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    const requestId = lastMessageOfType('requestDeleteSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId, status: 'canceled' }) })
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

  it('edits context and recipient and marks both contexts as changed', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    act(() => { findButton('Edit')!.click() })
    expect(contextTrigger('Sample context').dataset.value).toBe('email_reply')
    expect(recipientChips()).toEqual(['jordan@example.com'])
    expect(container.querySelector('.writing-examples-list-recipient')).toBeNull()

    chooseContext('Sample context', 'Document')
    expect(contextTrigger('Sample context').dataset.value).toBe('document')
    act(() => { container.querySelector<HTMLButtonElement>('button[aria-label="Remove jordan@example.com"]')!.click() })
    act(() => { findButton('Save')!.click() })

    const message = lastMessageOfType('requestUpdateSample')
    expect(message).toEqual(expect.objectContaining({ id: SAMPLE.id, contextType: 'document', recipient: '' }))
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: message.requestId, status: 'success' }) })

    expect(tabMarker('Email Reply')).not.toBeNull()
    expect(tabMarker('Document')).not.toBeNull()
    expect(container.querySelector('.writing-examples-stale-notice')?.textContent).toContain('changed since the last analysis')
  })

  it('keeps a legacy context selectable when editing a sample stored under it', () => {
    sendInit({ activeFilter: 'all', samples: [{ ...SAMPLE, contextType: 'slack' }] })
    act(() => { findButton('Edit')!.click() })
    expect(contextTrigger('Sample context').dataset.value).toBe('slack')
    expect(openContextMenu('Sample context').map((option) => option.textContent)).toContain('slack')
  })

  it('shows the reanalyze prompt after deletion and clears it after successful analysis', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    act(() => { findButton('Delete')!.click() })
    const deleteRequestId = lastMessageOfType('requestDeleteSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: deleteRequestId, status: 'success' }) })

    expect(container.querySelector('.writing-examples-stale-notice')).not.toBeNull()
    expect(tabMarker('Email Reply')).not.toBeNull()
    act(() => { findButton('Reanalyze')!.click() })
    const analyzeMessage = lastMessageOfType('analyzeStyle')
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: analyzeMessage.requestId, status: 'success' }) })

    expect(container.querySelector('.writing-examples-stale-notice')).toBeNull()
    expect(tabMarker('Email Reply')).toBeNull()
  })

  it('does not flag a context when a mutation fails or is canceled', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    act(() => { findButton('Delete')!.click() })
    const failedId = lastMessageOfType('requestDeleteSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: failedId, status: 'error', message: 'Failed to delete sample.' }) })
    act(() => { findButton('Delete')!.click() })
    const canceledId = lastMessageOfType('requestDeleteSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId: canceledId, status: 'canceled' }) })

    expect(container.querySelector('.writing-examples-stale-notice')).toBeNull()
    expect(tabMarker('Email Reply')).toBeNull()
  })

  it('marks every concrete context after Delete All from the All tab', () => {
    sendInit({ activeFilter: 'all', samples: [SAMPLE] })
    act(() => { findButton('Delete All Samples')!.click() })
    const requestId = lastMessageOfType('requestDeleteAllSamples').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' }) })

    expect(tabMarker('All')).toBeNull()
    expect(tabMarker('Email Reply')).not.toBeNull()
    expect(tabMarker('Email Compose')).not.toBeNull()
    expect(tabMarker('Social Media')).not.toBeNull()
    expect(tabMarker('Document')).not.toBeNull()
  })

  it('offers only the four concrete contexts when editing a current sample', () => {
    sendInit({ activeFilter: 'email_reply', samples: [SAMPLE] })
    expect(container.querySelector('.writing-examples-stale-notice')).toBeNull()
    act(() => { findButton('Edit')!.click() })
    expect(openContextMenu('Sample context').map((option) => option.textContent)).toEqual(['Email Reply', 'Email Compose', 'Social Media', 'Document'])
  })

  it('builds recipient chips from typed commas, Enter, blur, and Backspace, and submits them joined', () => {
    sendInit({ activeFilter: 'email_reply' })
    act(() => { findButton('Add Sample')!.click() })
    chooseContext('New sample context', 'Email Compose')
    const draft = container.querySelector<HTMLInputElement>('#writing-examples-add-recipient')!
    typeInto(draft, 'ana@example.com, ')
    expect(recipientChips()).toEqual(['ana@example.com'])
    expect(draft.value).toBe('')
    typeInto(draft, 'ben@example.com')
    act(() => { draft.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) })
    typeInto(draft, 'ANA@example.com;')
    expect(recipientChips()).toEqual(['ana@example.com', 'ben@example.com'])
    act(() => { draft.dispatchEvent(new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true })) })
    expect(recipientChips()).toEqual(['ana@example.com'])
    typeInto(draft, 'cy@example.com')
    act(() => { draft.dispatchEvent(new FocusEvent('focusout', { bubbles: true })) })
    expect(recipientChips()).toEqual(['ana@example.com', 'cy@example.com'])

    typeInto(container.querySelector<HTMLTextAreaElement>('#writing-examples-add-content')!, 'Hello both.')
    act(() => { findButton('Save Sample')!.click() })
    expect(lastMessageOfType('requestAddSample')).toEqual(expect.objectContaining({
      contextType: 'email_compose',
      recipient: 'ana@example.com, cy@example.com',
    }))
  })

  it('marks only the added context after a manual add and shows an Analyzing state on Reanalyze', () => {
    sendInit({ activeFilter: 'social_media' })
    act(() => { findButton('Add Sample')!.click() })
    typeInto(container.querySelector<HTMLTextAreaElement>('#writing-examples-add-content')!, 'A new social post.')
    act(() => { findButton('Save Sample')!.click() })
    const requestId = lastMessageOfType('requestAddSample').requestId
    act(() => { window.basilWritingExamplesSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' }) })

    expect(tabMarker('Social Media')).not.toBeNull()
    expect(tabMarker('Document')).toBeNull()
    const notice = container.querySelector('.writing-examples-stale-notice')!
    expect(notice.getAttribute('role')).toBe('status')
    act(() => { findButton('Reanalyze')!.click() })
    expect(lastMessageOfType('analyzeStyle')).toEqual(expect.objectContaining({ filter: 'social_media' }))
    expect(notice.querySelector('button')?.textContent).toBe('Analyzing...')
  })
})
