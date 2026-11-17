import { describe, expect, it } from 'vitest'

import {
  buildResumeSeedMessage,
  buildResumeSummary,
  buildSavedSessionFields,
  describeSessionAge,
  parseSavedSetupSession,
  shouldSuggestStartingOver,
} from './savedSession'

const ACCESS = { mode: 'provider_key', provider: 'anthropic', model_id: 'claude', resolved: true }

function savedState(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    completed: false,
    pending_setup_assistant: true,
    resume_stage: 'conversation',
    resume_summary: 'Saved so far: profile.',
    resume_model_access: ACCESS,
    resume_interaction_style: ['Lead with the answer'],
    resume_age_days: 1,
    resume_advisory_after_days: 3,
    session_goals: [
      { id: 'a', title: 'Tell me about you', intent: 'profile', kind: 'conversational', source: 'catalog', status: 'completed', completion_basis: 'saved' },
      { id: 'b', title: 'Connect mail', intent: 'mail', kind: 'action', source: 'agent', status: 'in_progress' },
    ],
    ...overrides,
  }
}

describe('parseSavedSetupSession', () => {
  it('reads the stage, model, style, agenda, and age', () => {
    const session = parseSavedSetupSession(savedState())

    expect(session?.stage).toBe('conversation')
    expect(session?.modelAccess).toEqual(ACCESS)
    expect(session?.interactionStyle).toEqual(['Lead with the answer'])
    expect(session?.ageDays).toBe(1)
    expect(session?.agenda.map(item => item.id)).toEqual(['a', 'b'])
    expect(session?.agenda[0].completionBasis).toBe('saved')
  })

  it('does not treat whatever was being worked on as still being worked on', () => {
    expect(parseSavedSetupSession(savedState())?.agenda[1].status).toBe('pending')
  })

  it.each([
    ['nothing saved', null],
    ['setup already finished', savedState({ completed: true })],
    ['no pending flag', savedState({ pending_setup_assistant: false })],
    ['a stage that cannot be continued', savedState({ resume_stage: 'welcome' })],
    ['no stage', savedState({ resume_stage: null })],
    ['a model that was never confirmed', savedState({ resume_model_access: { ...ACCESS, resolved: false } })],
    ['no model', savedState({ resume_model_access: null })],
  ])('offers nothing for %s', (_label, state) => {
    expect(parseSavedSetupSession(state as Record<string, unknown> | null)).toBeNull()
  })

  it('drops malformed agenda entries and fills in unknown kinds and statuses', () => {
    const session = parseSavedSetupSession(savedState({
      session_goals: [
        'nonsense',
        { id: 5, title: 'bad id' },
        { id: 'ok', title: 'Fine', kind: 'unheard-of', status: 'weird' },
      ],
    }))

    expect(session?.agenda).toEqual([
      { id: 'ok', title: 'Fine', intent: '', kind: 'conversational', source: 'agent', status: 'pending' },
    ])
  })

  it('uses sensible defaults when the age fields are missing', () => {
    const session = parseSavedSetupSession(savedState({ resume_age_days: undefined, resume_advisory_after_days: undefined }))

    expect(session?.ageDays).toBe(0)
    expect(session?.advisoryAfterDays).toBe(3)
  })
})

describe('age advice', () => {
  it('suggests starting over from three days on and never before', () => {
    const at = (ageDays: number) => shouldSuggestStartingOver(parseSavedSetupSession(savedState({ resume_age_days: ageDays }))!)

    expect(at(0)).toBe(false)
    expect(at(2)).toBe(false)
    expect(at(3)).toBe(true)
    expect(at(40)).toBe(true)
  })

  it('says how long ago in plain words', () => {
    expect(describeSessionAge(0)).toBe('earlier today')
    expect(describeSessionAge(1)).toBe('yesterday')
    expect(describeSessionAge(5)).toBe('5 days ago')
  })
})

describe('what is saved with a skip', () => {
  const agenda = [
    { id: 'a', title: 'Tell me about you', intent: '', kind: 'conversational' as const, source: 'catalog' as const, status: 'completed' as const },
    { id: 'b', title: 'Connect mail', intent: '', kind: 'action' as const, source: 'agent' as const, status: 'skipped' as const },
  ]

  it('records the stage, model, style, and a readable summary from the conversation', () => {
    const fields = buildSavedSessionFields(
      { setupStage: 'conversation', setupAgentModelAccess: ACCESS, sessionAgenda: agenda, interactionStyle: ['Be brief'] } as never,
      ['Saved your profile'],
    )

    expect(fields.resume_stage).toBe('conversation')
    expect(fields.resume_model_access).toEqual(ACCESS)
    expect(fields.resume_summary).toBe('Saved so far: Saved your profile.\nAgenda:\n- Tell me about you (done)\n- Connect mail (skipped)')
  })

  it.each(['welcome', 'express', 'intro_and_privacy', 'wrap_up'])('saves nothing to resume from during %s', stage => {
    const fields = buildSavedSessionFields(
      { setupStage: stage, setupAgentModelAccess: ACCESS, sessionAgenda: agenda, interactionStyle: [] } as never,
      [],
    )

    expect(fields).toEqual({ resume_stage: null, resume_summary: null, resume_model_access: null, resume_interaction_style: [] })
  })

  it('saves nothing when the model was never confirmed', () => {
    const fields = buildSavedSessionFields(
      { setupStage: 'conversation', setupAgentModelAccess: { ...ACCESS, resolved: false }, sessionAgenda: agenda, interactionStyle: [] } as never,
      [],
    )

    expect(fields.resume_stage).toBeNull()
  })

  it('keeps a very long agenda within the length the backend keeps', () => {
    const many = Array.from({ length: 400 }, (_, index) => ({ ...agenda[0], id: `i${index}`, title: `Item number ${index} with a long title` }))

    expect(buildResumeSummary(many, []).length).toBeLessThanOrEqual(1800)
  })
})

describe('buildResumeSeedMessage', () => {
  it('tells the agent what was covered and not to start over', () => {
    const message = buildResumeSeedMessage(parseSavedSetupSession(savedState({ resume_age_days: 4 }))!)

    expect(message).toContain('4 days ago')
    expect(message).toContain('Saved so far: profile.')
    expect(message).toContain('Do not start over')
    expect(message).toContain('next item that is not done')
  })
})
