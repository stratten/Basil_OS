import { describe, expect, it } from 'vitest'

import { applySetupAgentEvent } from './setupAgentEventReducer'
import { normalizeLocalModelFailureFromSse } from './ssePayloadNormalizers'
import { initialState } from '../reducer'

const PAYLOAD = {
  type: 'local_model_failure',
  kind: 'memory',
  message: 'Your Mac ran out of memory while running qwen.gguf.',
  detail: 'llama_decode returned -3 with a context of 32768 tokens',
  actions: [
    { id: 'retry', label: 'Try again' },
    { id: 'unknown_action', label: 'Do something odd' },
    { id: 'report', label: '' },
    { id: 'show_logs', label: 'Show logs' },
    { id: 'report', label: 'Report a problem' },
  ],
}

describe('normalizeLocalModelFailureFromSse', () => {
  it('keeps known actions with labels and drops the rest', () => {
    expect(normalizeLocalModelFailureFromSse(PAYLOAD)).toEqual({
      kind: 'memory',
      message: 'Your Mac ran out of memory while running qwen.gguf.',
      detail: 'llama_decode returned -3 with a context of 32768 tokens',
      actions: [
        { id: 'retry', label: 'Try again' },
        { id: 'show_logs', label: 'Show logs' },
        { id: 'report', label: 'Report a problem' },
      ],
    })
  })

  it.each([undefined, null, 'text', 5, {}, { kind: 'memory' }, { kind: 'mystery', message: 'x' }, { kind: 'memory', message: '  ' }])(
    'rejects an unusable payload: %j',
    raw => {
      expect(normalizeLocalModelFailureFromSse(raw)).toBeUndefined()
    },
  )
})

describe('setup agent error events', () => {
  const at = '2026-11-07T00:00:00Z'

  it('store the failure beside the message', () => {
    const next = applySetupAgentEvent(initialState, {
      kind: 'error',
      payload: { message: PAYLOAD.message, local_model_failure: PAYLOAD },
      created_at: at,
    })

    expect(next.errorMessage).toBe(PAYLOAD.message)
    expect(next.localModelFailure?.kind).toBe('memory')
  })

  it('leave no failure for an ordinary error', () => {
    const next = applySetupAgentEvent(initialState, { kind: 'error', payload: { message: 'Something else' }, created_at: at })

    expect(next.errorMessage).toBe('Something else')
    expect(next.localModelFailure).toBeUndefined()
  })

  it('clear the failure when the next turn starts', () => {
    const failed = applySetupAgentEvent(initialState, {
      kind: 'error',
      payload: { message: PAYLOAD.message, local_model_failure: PAYLOAD },
      created_at: at,
    })

    const retrying = applySetupAgentEvent(failed, { kind: 'turn_started', payload: {}, created_at: at })

    expect(retrying.localModelFailure).toBeUndefined()
    expect(retrying.errorMessage).toBeUndefined()
  })
})
