import { describe, expect, it } from 'vitest'

import { describeImportedContext } from './importedContextCard'

const base = { entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [] }

describe('describeImportedContext', () => {
  it('has nothing to say when there is no import or it added nothing', () => {
    expect(describeImportedContext(null)).toBeNull()
    expect(describeImportedContext(undefined)).toBeNull()
    expect(describeImportedContext(base)).toBeNull()
  })

  it('uses the model summary for a saved profile and adds the counts of notes and facts', () => {
    const card = describeImportedContext({ ...base, entries_added: 3, facts_proposed: 1, profile_updated: true, profile_summary: 'You are a designer.' })!

    expect(card.label).toBe('From what you imported')
    expect(card.title).toBe('Your profile is already in place')
    expect(card.detail).toBe('You are a designer. 3 notes are in your searchable history. 1 fact is waiting for your approval.')
  })

  it('falls back to a plain sentence when a saved profile has no summary', () => {
    expect(describeImportedContext({ ...base, profile_updated: true, profile_summary: '  ' })!.detail).toBe('You saved a profile from what you imported.')
  })

  it('describes imported records alone with singular and plural wording', () => {
    expect(describeImportedContext({ ...base, entries_added: 1 })!).toEqual({
      label: 'From what you imported',
      title: 'Your imported context is in place',
      detail: '1 note is in your searchable history.',
    })
    expect(describeImportedContext({ ...base, facts_proposed: 2 })!.detail).toBe('2 facts are waiting for your approval.')
  })
})
