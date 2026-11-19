// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import type { ProfileDraft } from '@shared/contextImport/contextImportClient'
import { advancePolls, clickIn, jobStatus, makeClient, typeInto } from '@shared/contextImport/contextImportTestSupport'

import { initialState, reducer } from '@/state/setupAssistantStore/reducer'
import type { SetupAgentModelAccess } from '@/types'

import { importRouteNotice } from './importRouteNotice'
import { IntroContextImport, summarizeProfileImport } from './IntroContextImport'

const holder = vi.hoisted(() => ({ client: null as unknown }))

vi.mock('@/services/api', () => ({ setupContextImportClient: () => holder.client }))

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const LOCAL: SetupAgentModelAccess = { mode: 'local', local_model_id: 'qwen-7b', provider: null, model_id: null, resolved: true }

const DRAFT: ProfileDraft = {
  draft_id: 'draft-1',
  label: 'Pasted text',
  summary: 'You are a nurse who prefers brief emails.',
  warnings: [],
  files: [
    { name: 'essentials.md', current: '', proposed: '- Nurse', cap_bytes: 2048 },
    { name: 'user.md', current: '', proposed: '- Brief emails', cap_bytes: 4096 },
  ],
}

let container: HTMLElement
let root: Root

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

describe('setup context import step', () => {
  it('is collapsed by default, points to Settings for individual memories, and offers the profile import only', () => {
    holder.client = makeClient()
    act(() => { root.render(<IntroContextImport modelAccess={LOCAL} />) })

    const details = container.querySelector('details.intro-context-import') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Optional: bring in what you already have')
    expect(details.textContent).toContain('Personalization > Personal Context')
    expect(details.textContent).toContain('individual memories')
    expect(container.querySelector('[data-testid="profile-import"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="context-import"]')).toBeNull()
    expect(container.querySelector('[data-testid="context-import-route-notice"]')!.textContent).toBe('Your text stays on this Mac. The model you chose to run here reads it.')
  })

  it('sends the confirmed route with the profile job, and sends none when the route is not yet resolved', async () => {
    const client = makeClient()
    holder.client = client
    await act(async () => { root.render(<IntroContextImport modelAccess={LOCAL} />) })
    typeInto(container, '.context-import-textarea', 'I am a nurse.')
    await clickIn(container, '.context-import-review')
    expect(client.startProfileJob).toHaveBeenLastCalledWith('I am a nurse.', '', '', { mode: 'local', local_model_id: 'qwen-7b', provider: null, model_id: null, resolved: true })

    const second = makeClient()
    holder.client = second
    act(() => { root.unmount() })
    root = createRoot(container)
    await act(async () => { root.render(<IntroContextImport modelAccess={{ ...LOCAL, resolved: false }} />) })
    typeInto(container, '.context-import-textarea', 'I am a nurse.')
    await clickIn(container, '.context-import-review')

    expect(second.startProfileJob).toHaveBeenLastCalledWith('I am a nurse.', '', '', null)
  })

  it('tells the conversation a profile was saved, and forgets it after an undo', async () => {
    const client = makeClient({
      readJob: vi.fn().mockResolvedValue(jobStatus<ProfileDraft>({ kind: 'profile', state: 'done', result: DRAFT })),
      commitProfile: vi.fn().mockResolvedValue({ backup_id: 'profile-1', files_updated: ['essentials.md', 'user.md'], label: 'Pasted text' }),
      undoProfile: vi.fn().mockResolvedValue({ files_restored: ['essentials.md', 'user.md'] }),
    })
    holder.client = client
    const onContextImported = vi.fn()
    const onContextImportUndone = vi.fn()
    await act(async () => { root.render(<IntroContextImport modelAccess={LOCAL} onContextImported={onContextImported} onContextImportUndone={onContextImportUndone} />) })
    typeInto(container, '.context-import-textarea', 'I am a nurse.')
    await clickIn(container, '.context-import-review')
    await advancePolls(1)

    await clickIn(container, '.context-import-approve')
    expect(onContextImported).toHaveBeenCalledWith({ entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [], profile_updated: true, profile_summary: 'You are a nurse who prefers brief emails.' })

    const undoButton = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Undo this change')!
    await act(async () => { undoButton.click(); await Promise.resolve(); await Promise.resolve() })
    expect(onContextImportUndone).toHaveBeenCalledTimes(1)
  })

  it('does not tell the conversation anything when no file changed', () => {
    expect(summarizeProfileImport({ summary: 'x', filesUpdated: [], backupId: null })).toBeNull()
  })

  it('summarizes a saved profile with one sentence and never the text itself', () => {
    const summary = summarizeProfileImport({ summary: 'You are a nurse.', filesUpdated: ['user.md'], backupId: 'profile-1' })

    expect(summary).toEqual({ entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [], profile_updated: true, profile_summary: 'You are a nurse.' })
  })
})

describe('import route notice', () => {
  it('names where the text goes for each route', () => {
    expect(importRouteNotice(LOCAL)).toBe('Your text stays on this Mac. The model you chose to run here reads it.')
    expect(importRouteNotice({ mode: 'provider_key', provider: 'OpenAI', model_id: 'gpt', resolved: true })).toBe('Your text is sent to OpenAI, using your own key, so the model you chose there can read it.')
    expect(importRouteNotice({ mode: 'provider_key', resolved: true })).toContain('your chosen provider')
    expect(importRouteNotice({ mode: 'basil_cloud', resolved: true })).toContain('Basil\u2019s cloud service')
  })

  it('falls back to the Settings memory model when no route is confirmed', () => {
    expect(importRouteNotice(null)).toContain('memory model from Settings')
    expect(importRouteNotice({ ...LOCAL, resolved: false })).toContain('memory model from Settings')
  })
})

describe('imported context in the setup store', () => {
  const profileSummary = { entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [], profile_updated: true, profile_summary: 'You are a nurse.' }
  const recordsSummary = { entries_added: 5, facts_proposed: 3, fact_titles: ['Works as a nurse'], note_titles: ['Trip to Lisbon'] }

  it('records that a profile was saved, and keeps it when more is merged later', () => {
    const first = reducer(initialState, { type: 'merge_imported_context', summary: profileSummary })
    const second = reducer(first, { type: 'merge_imported_context', summary: recordsSummary })

    expect(initialState.importedContext).toBeNull()
    expect(first.importedContext).toEqual(profileSummary)
    expect(second.importedContext?.profile_updated).toBe(true)
    expect(second.importedContext?.profile_summary).toBe('You are a nurse.')
    expect(second.importedContext?.entries_added).toBe(5)
  })

  it('does not add profile fields to a records-only import', () => {
    const state = reducer(initialState, { type: 'merge_imported_context', summary: recordsSummary })

    expect(state.importedContext).toEqual(recordsSummary)
    expect(state.importedContext).not.toHaveProperty('profile_updated')
  })

  it('forgets only the profile on undo, and clears the whole note when nothing else was imported', () => {
    const both = reducer(reducer(initialState, { type: 'merge_imported_context', summary: profileSummary }), { type: 'merge_imported_context', summary: recordsSummary })

    expect(reducer(both, { type: 'clear_imported_profile' }).importedContext).toEqual(recordsSummary)
    expect(reducer(reducer(initialState, { type: 'merge_imported_context', summary: profileSummary }), { type: 'clear_imported_profile' }).importedContext).toBeNull()
    expect(reducer(initialState, { type: 'clear_imported_profile' })).toBe(initialState)
  })
})
