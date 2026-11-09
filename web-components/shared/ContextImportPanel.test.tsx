// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { ContextImportPanel } from './ContextImportPanel'
import type { ContextImportClient, ContextImportPreview } from './contextImportClient'
import { advancePolls, chooseFileIn, clickIn, jobStatus, makeClient, typeInto } from './contextImportTestSupport'
import { MAX_IMPORT_FILE_BYTES } from './ImportSourceInput'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const NOTICE = 'Your text stays on this Mac. The model you chose to run here reads it.'

let container: HTMLElement
let root: Root

const PREVIEW: ContextImportPreview = {
  preview_id: 'preview-1',
  label: 'me.md',
  source_format: 'model',
  total: 4,
  counts: { dated: 2, undated: 1, stable_fact: 1 },
  samples: {
    dated: [{ title: 'Ran', text: 'Ran a marathon', occurred_at: '2019-06-01T00:00:00+00:00', section: '' }],
    undated: [{ title: 'Garden', text: 'My garden note', occurred_at: null, section: '' }],
    stable_fact: [{ title: 'Boston', text: 'I live in Boston', occurred_at: null, section: 'About me' }],
  },
  earliest: '2019-06-01T00:00:00+00:00',
  latest: '2020-01-01T00:00:00+00:00',
  warnings: ['1 of 2 parts could not be read and were skipped.'],
}

const COMMITTED = { batch_id: 'import-1', label: 'me.md', entries_added: 3, entries_already_present: 0, proposals_queued: 1, proposals_already_known: 0, memory_file_warning: null }

function doneClient(overrides: Partial<ContextImportClient> = {}): ContextImportClient {
  return makeClient({
    readJob: vi.fn().mockResolvedValue(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, message: 'Finished.', result: PREVIEW })),
    commit: vi.fn().mockResolvedValue(COMMITTED),
    ...overrides,
  })
}

async function render(client: ContextImportClient, props: { showPastImports?: boolean; onImported?: () => void } = {}) {
  await act(async () => {
    root.render(<ContextImportPanel client={client} routeNotice={NOTICE} {...props} />)
    await Promise.resolve()
  })
}

async function reachReview(client: ContextImportClient) {
  await render(client)
  typeInto(container, '.context-import-textarea', '- a note')
  await clickIn(container, '.context-import-review')
  await advancePolls(1)
}

beforeEach(() => {
  vi.useFakeTimers()
  container = document.createElement('div')
  // The dialogs portal into the Basil window surface, as they do in the app, so they stay inside the container the tests query.
  container.className = 'basil-webkit-window-surface'
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('ContextImportPanel', () => {
  it('shows the entry copy and the route notice, says a model reads the text, and keeps Review disabled until there is text', async () => {
    await render(makeClient())

    expect(container.textContent).toContain('Drop your personal info here if you have it available.')
    expect(container.textContent).toContain('nothing is saved until you approve it')
    expect(container.textContent).toContain('A model reads it')
    expect(container.textContent).not.toContain('no AI model involved')
    expect(container.querySelector('[data-testid="context-import-route-notice"]')!.textContent).toBe(NOTICE)
    expect(container.querySelector<HTMLButtonElement>('.context-import-review')!.disabled).toBe(true)
    typeInto(container, '.context-import-textarea', '  \n ')
    expect(container.querySelector<HTMLButtonElement>('.context-import-review')!.disabled).toBe(true)
    typeInto(container, '.context-import-textarea', '- a note')
    expect(container.querySelector<HTMLButtonElement>('.context-import-review')!.disabled).toBe(false)
  })

  it('opens the hidden file input from its own Choose a file button, so no browser file control with a file icon is shown', async () => {
    await render(makeClient())
    const input = container.querySelector<HTMLInputElement>('.context-import-file')!
    const openChooser = vi.spyOn(input, 'click').mockImplementation(() => {})
    const chooseButton = [...container.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === 'Choose a file')!

    expect(chooseButton.className).toContain('secondary-button')
    await act(async () => { chooseButton.click() })

    expect(openChooser).toHaveBeenCalledTimes(1)
  })

  it('shows real progress while the model reads, then the review by category with dates, samples and warnings, writing nothing before approval', async () => {
    const readJob = vi.fn()
      .mockResolvedValueOnce(jobStatus({ chunks_done: 1, message: 'Read part 1 of 2.' }))
      .mockResolvedValueOnce(jobStatus<ContextImportPreview>({ state: 'done', chunks_done: 2, result: PREVIEW }))
    const client = makeClient({ readJob })
    await render(client)
    typeInto(container, '.context-import-textarea', '- a note')

    await clickIn(container, '.context-import-review')

    expect(client.startRecordsJob).toHaveBeenCalledWith('- a note', '', '')
    expect(container.querySelector('[data-testid="context-import-progress"]')!.textContent).toContain('Starting.')
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.disabled).toBe(true)

    await advancePolls(1)
    expect(container.querySelector('[data-testid="context-import-progress"]')!.textContent).toContain('Read part 1 of 2. (1 of 2)')

    await advancePolls(1)
    expect(client.commit).not.toHaveBeenCalled()
    const review = container.querySelector('[data-testid="context-import-review"]')!
    expect(review.textContent).toContain('2 dated entries, from Jun 1, 2019 to Jan 1, 2020')
    expect(review.textContent).toContain('1 undated note')
    expect(review.textContent).toContain('1 fact about you')
    expect(review.textContent).toContain('Ran a marathon')
    expect(review.textContent).toContain('1 of 2 parts could not be read and were skipped.')
    expect(review.textContent).toContain('None becomes always-known until you approve it there')
  })

  it('approves only the categories that are still ticked, then reports what happened', async () => {
    const client = doneClient()
    const onImported = vi.fn()
    await render(client, { onImported })
    typeInto(container, '.context-import-textarea', '- a note')
    await clickIn(container, '.context-import-review')
    await advancePolls(1)

    act(() => { container.querySelectorAll<HTMLInputElement>('.context-import-category input')[1].click() })
    await clickIn(container, '.context-import-approve')

    expect(client.commit).toHaveBeenCalledWith('preview-1', ['dated', 'stable_fact'])
    expect(onImported).toHaveBeenCalledTimes(1)
    const done = container.querySelector('[data-testid="context-import-done"]')!
    expect(done.textContent).toContain('Added 3 entries')
    expect(done.textContent).toContain('1 fact is waiting for your approval')
  })

  it('cannot be approved with every category unticked', async () => {
    await reachReview(doneClient())

    container.querySelectorAll<HTMLInputElement>('.context-import-category input').forEach(box => { act(() => { box.click() }) })

    expect(container.querySelector<HTMLButtonElement>('.context-import-approve')!.disabled).toBe(true)
  })

  it('shows the model failure message and stays on the input with the text kept, so the person can retry', async () => {
    const readJob = vi.fn().mockResolvedValueOnce(jobStatus({ state: 'failed', message: 'x', error: 'The model stopped giving readable answers, so I stopped. Nothing was saved.' }))
    await render(makeClient({ readJob }))
    typeInto(container, '.context-import-textarea', '- a note')

    await clickIn(container, '.context-import-review')
    await advancePolls(1)

    expect(container.querySelector('.context-import-error')!.textContent).toContain('Nothing was saved.')
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('- a note')
    expect(container.querySelector<HTMLButtonElement>('.context-import-review')!.disabled).toBe(false)
  })

  it('shows the message when a job cannot be started, for example one is already reading', async () => {
    const client = makeClient({ startRecordsJob: vi.fn().mockRejectedValue(new Error('Another import is still reading. Wait for it to finish, or cancel it first.')) })
    await render(client)
    typeInto(container, '.context-import-textarea', '- a note')

    await clickIn(container, '.context-import-review')

    expect(container.querySelector('.context-import-error')!.textContent).toContain('Another import is still reading')
    expect(container.querySelector('[data-testid="context-import-progress"]')).toBeNull()
  })

  it('cancels a reading import, keeps the text, and says nothing was saved', async () => {
    const readJob = vi.fn().mockResolvedValueOnce(jobStatus({ state: 'canceled', message: 'Canceled. Nothing was saved.' }))
    const client = makeClient({ readJob })
    await render(client)
    typeInto(container, '.context-import-textarea', '- a note')
    await clickIn(container, '.context-import-review')

    await clickIn(container, '.context-import-progress .secondary-button')
    expect(client.cancelJob).toHaveBeenCalledWith('job-1')
    expect(container.querySelector('[data-testid="context-import-progress"]')!.textContent).toContain('Stopping.')
    await advancePolls(1)

    expect(container.textContent).toContain('Canceled. Nothing was saved.')
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('- a note')
    expect(container.querySelector('[data-testid="context-import-progress"]')).toBeNull()
  })

  it('keeps the review open and shows the error when saving fails, so the user can retry', async () => {
    const commit = vi.fn().mockRejectedValueOnce(new Error('The import could not be saved.')).mockResolvedValueOnce({ ...COMMITTED, entries_added: 1, proposals_queued: 0 })
    await reachReview(doneClient({ commit }))

    await clickIn(container, '.context-import-approve')
    expect(container.querySelector('.context-import-error')!.textContent).toContain('could not be saved')
    expect(container.querySelector('[data-testid="context-import-review"]')).not.toBeNull()

    await clickIn(container, '.context-import-approve')
    expect(container.querySelector('[data-testid="context-import-done"]')).not.toBeNull()
  })

  it('shows an expired-preview message from the backend and stays on the review', async () => {
    const commit = vi.fn().mockRejectedValue(new Error('This import preview has expired. Choose the file or paste the text again.'))
    await reachReview(doneClient({ commit }))

    await clickIn(container, '.context-import-approve')

    expect(container.querySelector('.context-import-error')!.textContent).toContain('has expired')
    expect(container.querySelector('[data-testid="context-import-review"]')).not.toBeNull()
  })

  it('refuses a file larger than one import may be before reading it', async () => {
    vi.useRealTimers()
    await render(makeClient())
    const big = new File(['x'], 'huge.csv')
    Object.defineProperty(big, 'size', { value: MAX_IMPORT_FILE_BYTES + 1 })

    await chooseFileIn(container, big)

    expect(container.querySelector('.context-import-error')!.textContent).toContain('Split it and import the parts one at a time')
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('')
  })

  it('loads a chosen file into the box and sends its name as the filename and label', async () => {
    vi.useRealTimers()
    const client = makeClient({ readJob: vi.fn().mockResolvedValue(jobStatus({})) })
    await render(client)

    await chooseFileIn(container, new File(['Date,Note\n2024-01-01,Hi'], 'log.csv', { type: 'text/csv' }))
    expect(container.textContent).toContain('Loaded log.csv.')
    await clickIn(container, '.context-import-review')

    expect(client.startRecordsJob).toHaveBeenCalledWith('Date,Note\n2024-01-01,Hi', 'log.csv', 'log.csv')
  })

  it('lists past imports only when asked and undoes one after a confirmation', async () => {
    const batch = { batch_id: 'import-1', imported_at: '2026-01-02T00:00:00+00:00', label: 'me.md', entry_count: 3 }
    const client = makeClient({ listBatches: vi.fn().mockResolvedValueOnce([batch]).mockResolvedValueOnce([]) })
    await render(client, { showPastImports: true })

    expect(container.textContent).toContain('me.md, 3 entries')
    await clickIn(container, '.context-import-batch .secondary-button')
    expect(client.undo).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Remove 3')

    await clickIn(container, '.context-import-batch-confirm .primary-button')

    expect(client.undo).toHaveBeenCalledWith('import-1')
    expect(container.textContent).toContain('Nothing has been imported yet.')
  })

  it('does not request past imports in the setup variant', async () => {
    const client = makeClient()
    await render(client)

    expect(client.listBatches).not.toHaveBeenCalled()
    expect(container.querySelector('.context-import-past')).toBeNull()
  })

  it('says so when past imports cannot be loaded', async () => {
    await render(makeClient({ listBatches: vi.fn().mockRejectedValue(new Error('Past imports could not be listed.')) }), { showPastImports: true })

    expect(container.querySelector('.context-import-past .context-import-error')!.textContent).toContain('could not be listed')
  })
})
