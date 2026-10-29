import { describe, expect, it } from 'vitest'

import { initialState, reducer } from '../reducer'
import { applySetupAgentEvent } from './setupAgentEventReducer'
import type { SetupAgentEvent } from '@/types'

const chip = { id: 'wordy', label: 'Too wordy', message: 'They are too wordy.' }

function chipsEvent(payload: Record<string, unknown>): SetupAgentEvent {
  return { kind: 'chips_set', payload } as unknown as SetupAgentEvent
}

describe('chips_set multi-select handling', () => {
  it('records multi-select only when the event says so', () => {
    const multi = applySetupAgentEvent(initialState, chipsEvent({ chips: [chip], multi_select: true }))
    const single = applySetupAgentEvent(multi, chipsEvent({ chips: [chip], multi_select: false }))
    const missing = applySetupAgentEvent(multi, chipsEvent({ chips: [chip] }))

    expect(multi.currentChipsMultiSelect).toBe(true)
    expect(single.currentChipsMultiSelect).toBe(false)
    expect(missing.currentChipsMultiSelect).toBe(false)
  })

  it('clears the chips and the multi-select flag when the user sends a message', () => {
    const withChips = applySetupAgentEvent(initialState, chipsEvent({ chips: [chip], multi_select: true }))

    const afterSend = reducer(withChips, { type: 'append_user_message', content: 'hi' } as never)

    expect(afterSend.currentChips).toEqual([])
    expect(afterSend.currentChipsMultiSelect).toBe(false)
  })
})
