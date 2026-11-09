// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { ContextImportPanel } from './ContextImportPanel'
import type { ContextImportClient, ContextImportPreview, ProfileDraft } from './contextImportClient'
import { advancePolls, clickIn, jobStatus, makeClient, typeInto } from './contextImportTestSupport'
import { ProfileImportPanel } from './ProfileImportPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const NOTICE = 'Your text stays on this Mac. The model you chose to run here reads it.'

const PREVIEW: ContextImportPreview = {
  preview_id: 'preview-1',
  label: 'me.md',
  source_format: 'model',
  total: 1,
  counts: { dated: 0, undated: 1, stable_fact: 0 },
  samples: { dated: [], undated: [{ title: 'Garden', text: 'My garden note', occurred_at: null, section: '' }], stable_fact: [] },
  earliest: null,
  latest: null,
  warnings: [],
}

const DRAFT: ProfileDraft = {
  draft_id: 'draft-1',
  label: 'me.md',
  summary: 'You are a designer in Boston.',
  warnings: [],
  files: [{ name: 'essentials.md', current: '- Lives in Boston', proposed: '- Lives in Boston\n- Designer', cap_bytes: 2048 }],
}

let container: HTMLElement
let root: Root

beforeEach(() => {
  vi.useFakeTimers()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
})

const dialog = () => document.querySelector('[role="dialog"]')
const pressEscape = () => act(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
const pressBackdrop = () => act(() => { document.querySelector('.basil-modal-backdrop')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })) })

async function renderRecords(client: ContextImportClient) {
  await act(async () => {
    root.render(<ContextImportPanel client={client} routeNotice={NOTICE} />)
    await Promise.resolve()
  })
  typeInto(document.body, '.context-import-textarea', '- a note')
  await clickIn(document.body, '.context-import-review')
}

async function renderProfile(client: ContextImportClient) {
  await act(async () => {
    root.render(<ProfileImportPanel client={client} routeNotice={NOTICE} />)
    await Promise.resolve()
  })
  typeInto(document.body, '.context-import-textarea', 'I am a designer in Boston.')
  await clickIn(document.body, '.context-import-review')
}

describe('import dialogs', () => {
  it('moves a records import into a dialog with its stages while the model works, and takes it away for the review', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ stage: 'reading', tokens_written: 400, chunks_done: 0, message: 'Reading part 1 of 2.' }))
      .mockResolvedValueOnce(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, result: PREVIEW }))
    await renderRecords(makeClient({ readJob }))

    expect(dialog()!.textContent).toContain('Reading your text')
    expect(dialog()!.querySelector('[data-testid="context-import-progress"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="context-import-progress"]')).toBeNull()

    await advancePolls(1)
    expect(dialog()!.textContent).toContain('Reading part 1 of 2. (0 of 2)')
    expect(dialog()!.textContent).toContain('about 300 words so far')
    expect(dialog()!.querySelector('[data-testid="context-import-thinking"]')).toBeNull()

    await advancePolls(1)
    expect(dialog()!.textContent).toContain('Review what I found')
    expect(dialog()!.classList.contains('basil-modal-dialog--wide')).toBe(true)
    expect(dialog()!.querySelector('[data-testid="context-import-review"]')).not.toBeNull()
    expect(dialog()!.querySelector('[data-testid="context-import-progress"]')).toBeNull()
  })

  it('does not cancel a working import or close a review on Escape or a backdrop press', async () => {
    const client = makeClient({
      readJob: vi.fn().mockResolvedValueOnce(jobStatus({ chunks_done: 0 })).mockResolvedValue(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, result: PREVIEW })),
    })
    await renderRecords(client)

    pressEscape()
    pressBackdrop()
    expect(client.cancelJob).not.toHaveBeenCalled()
    expect(dialog()!.textContent).toContain('Reading your text')

    await advancePolls(2)
    pressEscape()
    pressBackdrop()
    expect(dialog()!.textContent).toContain('Review what I found')
    expect(client.commit).not.toHaveBeenCalled()
  })

  it('closes the review dialog only through its own Cancel button, back to an empty input', async () => {
    await renderRecords(makeClient({ readJob: vi.fn().mockResolvedValue(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, result: PREVIEW })) }))
    await advancePolls(1)

    await clickIn(document.body, '.context-import-actions .secondary-button')

    expect(dialog()).toBeNull()
    expect(document.body.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('')
  })

  it('shows a save failure inside the open review dialog rather than on the page behind it', async () => {
    const client = makeClient({
      readJob: vi.fn().mockResolvedValue(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, result: PREVIEW })),
      commit: vi.fn().mockRejectedValue(new Error('The preview expired.')),
    })
    await renderRecords(client)
    await advancePolls(1)

    await clickIn(document.body, '.context-import-approve')

    expect(dialog()!.querySelector('[role="alert"]')!.textContent).toBe('The preview expired.')
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('shows a failed read on the page after the dialog has gone', async () => {
    await renderRecords(makeClient({ readJob: vi.fn().mockResolvedValue(jobStatus({ state: 'failed', error: 'The model did not give readable answers.' })) }))
    await advancePolls(1)

    expect(dialog()).toBeNull()
    expect(container.querySelector('[role="alert"]')!.textContent).toBe('The model did not give readable answers.')
  })

  it('shows the four profile stages in a dialog, then the draft in a wide review dialog, and keeps the done block on the page', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ kind: 'profile', stage: 'writing', message: 'Writing your profile.', chunks_done: 2 }))
      .mockResolvedValueOnce(jobStatus<ProfileDraft>({ kind: 'profile', state: 'done', chunks_done: 2, result: DRAFT }))
    const client = makeClient({ readJob, commitProfile: vi.fn().mockResolvedValue({ backup_id: 'profile-abc', files_updated: ['essentials.md'], label: 'me.md' }) })
    await renderProfile(client)

    expect(dialog()!.textContent).toContain('Drafting your profile')
    expect(dialog()!.querySelectorAll('.context-import-stage')).toHaveLength(4)

    await advancePolls(1)
    expect(dialog()!.querySelector('.context-import-stage--active')!.textContent).toBe('Writing your profile')

    await advancePolls(1)
    expect(dialog()!.textContent).toContain('Review your profile draft')
    expect(dialog()!.classList.contains('basil-modal-dialog--wide')).toBe(true)

    await clickIn(document.body, '.context-import-approve')
    expect(dialog()).toBeNull()
    expect(container.querySelector('[data-testid="profile-import-done"]')!.textContent).toContain('Saved. Updated Essentials.')
    expect(container.querySelector('[data-testid="profile-import-done"]')!.textContent).toContain('Undo this change')
  })

  it('shows the model\'s thinking inside the working dialog as it arrives', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ kind: 'profile', stage: 'reading', tokens_written: 900, thinking: 'She is a product designer.', message: 'Reading part 1 of 1.' }))
      .mockResolvedValueOnce(jobStatus({ kind: 'profile', stage: 'reading', tokens_written: 1400, thinking: 'She is a product designer. She dislikes Jira.', message: 'Reading part 1 of 1.' }))
    await renderProfile(makeClient({ readJob }))

    await advancePolls(1)
    expect(dialog()!.querySelector('[data-testid="context-import-thinking"]')!.textContent).toBe('She is a product designer.')

    await advancePolls(1)
    expect(dialog()!.querySelector('[data-testid="context-import-thinking"]')!.textContent).toBe('She is a product designer. She dislikes Jira.')
    expect(dialog()!.textContent).not.toContain('words so far')
  })
})
