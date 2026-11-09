import { describe, expect, it } from 'vitest'

import { initialState, reducer } from './reducer'

describe('express comfort in the setup store', () => {
  it('starts with no comfort level, which is the manual path', () => {
    expect(initialState.expressComfort).toBeNull()
  })

  it('records the chosen level without touching anything else', () => {
    const next = reducer(initialState, { type: 'set_express_comfort', expressComfort: 'all_in' })

    expect(next.expressComfort).toBe('all_in')
    expect({ ...next, expressComfort: null }).toEqual(initialState)
  })

  it('clears the level again', () => {
    const chosen = reducer(initialState, { type: 'set_express_comfort', expressComfort: 'balanced' })

    expect(reducer(chosen, { type: 'set_express_comfort', expressComfort: null }).expressComfort).toBeNull()
  })

  it('accepts the express stage', () => {
    expect(reducer(initialState, { type: 'set_stage', setupStage: 'express' }).setupStage).toBe('express')
  })
})
