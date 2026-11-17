// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { ContextImportClient, ImportModelAccess, ProfileDraft } from './contextImportClient'
import { advancePolls, clickIn, jobStatus, makeClient, typeInto } from './contextImportTestSupport'
import { ProfileImportPanel } from './ProfileImportPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const NOTICE = 'Your text stays on this Mac. The model you chose to run here reads it.'
const ESSENTIALS_EDIT = 'textarea[id="profile-edit-essentials.md"]'
const USER_EDIT = 'textarea[id="profile-edit-user.md"]'

let container: HTMLElement
let root: Root

const DRAFT: ProfileDraft = {
  draft_id: 'draft-1',
  label: 'me.md',
  summary: 'You are a designer in Boston who likes short answers.',
  warnings: [],
  files: [
    { name: 'essentials.md', current: '- Lives in Boston', proposed: '- Lives in Boston\n- Designer', cap_bytes: 2048 },
    { name: 'user.md', current: '', proposed: '- Likes short answers', cap_bytes: 4096 },
  ],
}

const SAVED = { backup_id: 'profile-abc', files_updated: ['essentials.md', 'user.md'], label: 'me.md' }

function draftClient(overrides: Partial<ContextImportClient> = {}, draft: ProfileDraft = DRAFT): ContextImportClient {
  return makeClient({
    readJob: vi.fn().mockResolvedValue(jobStatus<ProfileDraft>({ kind: 'profile', state: 'done', chunks_done: 2, message: 'Finished.', result: draft })),
    commitProfile: vi.fn().mockResolvedValue(SAVED),
    undoProfile: vi.fn().mockResolvedValue({ files_restored: ['essentials.md', 'user.md'] }),
    ...overrides,
  })
}

async function render(client: ContextImportClient, props: { modelAccess?: ImportModelAccess | null; onImported?: () => void; onUndone?: () => void } = {}) {
  await act(async () => {
    root.render(<ProfileImportPanel client={client} routeNotice={NOTICE} {...props} />)
    await Promise.resolve()
  })
}

async function reachReview(client: ContextImportClient, props: Parameters<typeof render>[1] = {}) {
  await render(client, props)
  typeInto(container, '.context-import-textarea', 'I am a designer in Boston.')
  await clickIn(container, '.context-import-review')
  await advancePolls(1)
}

const saveButton = () => container.querySelector<HTMLButtonElement>('.context-import-approve')!
const checkbox = (name: string) => container.querySelector<HTMLInputElement>(`[data-testid="profile-file-${name}"] input[type="checkbox"]`)!

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

describe('ProfileImportPanel', () => {
  it('shows where the text goes before anything is sent, and starts a profile job with the confirmed route', async () => {
    const access: ImportModelAccess = { mode: 'local', local_model_id: 'qwen', provider: null, model_id: null, resolved: true }
    const client = draftClient()
    await render(client, { modelAccess: access })

    expect(container.querySelector('[data-testid="context-import-route-notice"]')!.textContent).toBe(NOTICE)
    expect(container.textContent).toContain('nothing is saved until you approve it')
    expect(container.querySelector<HTMLButtonElement>('.context-import-review')!.disabled).toBe(true)
    typeInto(container, '.context-import-textarea', 'I am a designer in Boston.')
    await clickIn(container, '.context-import-review')

    expect(client.startProfileJob).toHaveBeenCalledWith('I am a designer in Boston.', '', '', access)
  })

  it('shows the draft beside what is there now, and writes nothing before the person saves', async () => {
    const client = draftClient()
    await reachReview(client)

    const review = container.querySelector('[data-testid="profile-import-review"]')!
    expect(review.textContent).toContain('You are a designer in Boston who likes short answers.')
    expect(container.querySelector('[data-testid="profile-current-essentials.md"]')!.textContent).toBe('- Lives in Boston')
    expect(container.querySelector('[data-testid="profile-current-user.md"]')!.textContent).toBe('Nothing yet.')
    expect(container.querySelector<HTMLTextAreaElement>(ESSENTIALS_EDIT)!.value).toBe('- Lives in Boston\n- Designer')
    expect(container.querySelector<HTMLTextAreaElement>(USER_EDIT)!.value).toBe('- Likes short answers')
    expect(container.querySelector('[data-testid="profile-bytes-essentials.md"]')!.textContent).toBe('28 of 2048 bytes')
    expect(client.commitProfile).not.toHaveBeenCalled()
  })

  it('saves the edited text for both files, reports it, and tells the caller', async () => {
    const client = draftClient()
    const onImported = vi.fn()
    await reachReview(client, { onImported })
    typeInto(container, ESSENTIALS_EDIT, '- Lives in Boston\n- Product designer')

    await clickIn(container, '.context-import-approve')

    expect(client.commitProfile).toHaveBeenCalledWith('draft-1', '- Lives in Boston\n- Product designer', '- Likes short answers')
    expect(container.querySelector('[data-testid="profile-import-done"]')!.textContent).toContain('Saved. Updated Essentials and About you.')
    expect(onImported).toHaveBeenCalledWith({ summary: DRAFT.summary, filesUpdated: ['essentials.md', 'user.md'], backupId: 'profile-abc' })
  })

  it('sends a blank for a file the person unticked, so that file is left alone', async () => {
    const client = draftClient()
    await reachReview(client)

    act(() => { checkbox('user.md').click() })
    await clickIn(container, '.context-import-approve')

    expect(client.commitProfile).toHaveBeenCalledWith('draft-1', '- Lives in Boston\n- Designer', '')
  })

  it('leaves a file the model suggests no change for unticked, and cannot be saved when nothing is ticked', async () => {
    const unchanged: ProfileDraft = { ...DRAFT, files: [{ name: 'essentials.md', current: '- Same', proposed: '- Same', cap_bytes: 2048 }, { name: 'user.md', current: '- Also same', proposed: '- Also same', cap_bytes: 4096 }] }
    await reachReview(draftClient({}, unchanged))

    expect(checkbox('essentials.md').checked).toBe(false)
    expect(container.querySelector('[data-testid="profile-file-essentials.md"]')!.textContent).toContain('no change suggested')
    expect(saveButton().disabled).toBe(true)
  })

  it('blocks saving while a ticked file is over its byte limit or blank, and says how far over it is', async () => {
    const tight: ProfileDraft = { ...DRAFT, files: [{ name: 'essentials.md', current: '- a', proposed: '- b', cap_bytes: 20 }, DRAFT.files[1]] }
    await reachReview(draftClient({}, tight))

    typeInto(container, ESSENTIALS_EDIT, 'x'.repeat(30))
    expect(container.querySelector('[data-testid="profile-bytes-essentials.md"]')!.textContent).toBe('30 of 20 bytes. Shorten it to save.')
    expect(saveButton().disabled).toBe(true)

    typeInto(container, ESSENTIALS_EDIT, '   ')
    expect(saveButton().disabled).toBe(true)

    typeInto(container, ESSENTIALS_EDIT, 'short')
    expect(saveButton().disabled).toBe(false)
  })

  it('keeps the review and its edits when saving fails, and saves on retry', async () => {
    const commitProfile = vi.fn()
      .mockRejectedValueOnce(new Error('essentials.md is 3000 bytes, and its limit is 2048. Shorten it and save again.'))
      .mockResolvedValueOnce(SAVED)
    await reachReview(draftClient({ commitProfile }))
    typeInto(container, ESSENTIALS_EDIT, '- My edit')

    await clickIn(container, '.context-import-approve')
    expect(container.querySelector('.context-import-error')!.textContent).toContain('Shorten it and save again.')
    expect(container.querySelector<HTMLTextAreaElement>(ESSENTIALS_EDIT)!.value).toBe('- My edit')

    await clickIn(container, '.context-import-approve')
    expect(container.querySelector('[data-testid="profile-import-done"]')).not.toBeNull()
  })

  it('says nothing was saved when the backend reports no file changed, and offers no Undo', async () => {
    const commitProfile = vi.fn().mockResolvedValue({ backup_id: null, files_updated: [], label: 'me.md' })
    await reachReview(draftClient({ commitProfile }))

    await clickIn(container, '.context-import-approve')

    const done = container.querySelector('[data-testid="profile-import-done"]')!
    expect(done.textContent).toContain('Nothing changed, so nothing was saved.')
    expect(done.textContent).not.toContain('Undo this change')
  })

  it('undoes a saved profile once and tells the caller', async () => {
    const client = draftClient()
    const onUndone = vi.fn()
    await reachReview(client, { onUndone })
    await clickIn(container, '.context-import-approve')
    const undoButton = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Undo this change')!

    await act(async () => { undoButton.click(); await Promise.resolve(); await Promise.resolve() })

    expect(client.undoProfile).toHaveBeenCalledWith('profile-abc')
    expect(onUndone).toHaveBeenCalledTimes(1)
    const done = container.querySelector('[data-testid="profile-import-done"]')!
    expect(done.textContent).toContain('Your profile is back the way it was.')
    expect(done.textContent).not.toContain('Undo this change')
  })

  it('shows an undo failure and keeps the Undo button for another try', async () => {
    const client = draftClient({ undoProfile: vi.fn().mockRejectedValue(new Error('That profile backup was not found.')) })
    await reachReview(client)
    await clickIn(container, '.context-import-approve')
    const undoButton = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Undo this change')!

    await act(async () => { undoButton.click(); await Promise.resolve(); await Promise.resolve() })

    expect(container.querySelector('.context-import-error')!.textContent).toContain('was not found')
    expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Undo this change')).toBe(true)
  })

  it('shows the model failure and the cancel outcome in plain words and keeps the text', async () => {
    const failed = vi.fn().mockResolvedValueOnce(jobStatus({ kind: 'profile', state: 'failed', message: 'x', error: 'I read your text but found nothing lasting about you to add to your profile.' }))
    await render(makeClient({ readJob: failed }))
    typeInto(container, '.context-import-textarea', 'hello')
    await clickIn(container, '.context-import-review')
    await advancePolls(1)

    expect(container.querySelector('.context-import-error')!.textContent).toContain('found nothing lasting')
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('hello')
  })

  it('cancels a reading profile import and says nothing was saved', async () => {
    const readJob = vi.fn().mockResolvedValueOnce(jobStatus({ kind: 'profile', state: 'canceled', message: 'Canceled. Nothing was saved.' }))
    const client = makeClient({ readJob })
    await render(client)
    typeInto(container, '.context-import-textarea', 'hello')
    await clickIn(container, '.context-import-review')

    await clickIn(container, '.context-import-progress .secondary-button')
    await advancePolls(1)

    expect(client.cancelJob).toHaveBeenCalledWith('job-1')
    expect(container.textContent).toContain('Canceled. Nothing was saved.')
  })

  it('returns to an empty input when the review is canceled, without saving', async () => {
    const client = draftClient()
    await reachReview(client)

    const cancel = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Cancel')!
    await act(async () => { cancel.click(); await Promise.resolve() })

    expect(client.commitProfile).not.toHaveBeenCalled()
    expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('')
  })

  describe('reading a screenshot', () => {
    const pickImages = async (files: File[]) => {
      const input = container.querySelector<HTMLInputElement>('input[aria-label="Choose screenshots to read"]')!
      Object.defineProperty(input, 'files', { value: files, configurable: true })
      await act(async () => {
        input.dispatchEvent(new Event('change', { bubbles: true }))
      })
      // jsdom's FileReader finishes on a timer, which the fake clock owns.
      for (let step = 0; step < 5; step += 1) {
        await act(async () => { await vi.advanceTimersByTimeAsync(20) })
      }
    }
    const picture = (name = 'prompt.png', type = 'image/png', size = 8) => new File([new Uint8Array(size)], name, { type })

    it('puts the text read from a screenshot into the box for review and says to check it', async () => {
      const client = draftClient({ readImages: vi.fn().mockResolvedValue({ text: 'Always answer briefly.' }) })
      await render(client, { modelAccess: { mode: 'basil_cloud', resolved: true } })

      await pickImages([picture()])

      expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('Always answer briefly.')
      expect(container.textContent).toContain('I read this from your screenshot. Check it')
      const [images, access] = (client.readImages as ReturnType<typeof vi.fn>).mock.calls[0]
      expect(images[0].mime_type).toBe('image/png')
      expect(typeof images[0].data_base64).toBe('string')
      expect(access).toEqual({ mode: 'basil_cloud', resolved: true })
    })

    it('adds to text that is already in the box instead of replacing it', async () => {
      const client = draftClient({ readImages: vi.fn().mockResolvedValue({ text: 'From the picture.' }) })
      await render(client)
      typeInto(container, '.context-import-textarea', 'Already here.')

      await pickImages([picture()])

      expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('Already here.\n\nFrom the picture.')
    })

    it('shows the backend explanation when the chosen route cannot read pictures, and leaves the box alone', async () => {
      const explanation = 'The model you chose runs on this Mac and can only read text, so it cannot read a screenshot. Paste the text instead.'
      const client = draftClient({ readImages: vi.fn().mockRejectedValue(new Error(explanation)) })
      await render(client)
      typeInto(container, '.context-import-textarea', 'Keep me.')

      await pickImages([picture()])

      expect(container.querySelector('[role="alert"]')!.textContent).toBe(explanation)
      expect(container.querySelector<HTMLTextAreaElement>('.context-import-textarea')!.value).toBe('Keep me.')
    })

    it('refuses too many or too large pictures before sending anything', async () => {
      const client = draftClient()
      await render(client)

      await pickImages(Array.from({ length: 7 }, (_, index) => picture(`p${index}.png`)))
      expect(container.querySelector('[role="alert"]')!.textContent).toContain('at most 6')

      await pickImages([picture('huge.png', 'image/png', 5_000_001)])
      expect(container.querySelector('[role="alert"]')!.textContent).toContain('huge.png')
      expect(client.readImages).not.toHaveBeenCalled()
    })
  })
})
