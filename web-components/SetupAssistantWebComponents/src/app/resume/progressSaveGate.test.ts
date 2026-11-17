import { describe, expect, it, vi } from 'vitest'

import { afterProgressSave, trackProgressSave } from './progressSaveGate'

describe('progress save gate', () => {
  it('runs the action at once when nothing is in flight', () => {
    const action = vi.fn()

    afterProgressSave(action)

    expect(action).toHaveBeenCalledTimes(1)
  })

  it('holds the action until a save in flight has landed', async () => {
    let finish: () => void = () => undefined
    const save = trackProgressSave(new Promise<void>(resolve => { finish = resolve }))
    const action = vi.fn()

    afterProgressSave(action)
    expect(action).not.toHaveBeenCalled()
    finish()
    await save

    await Promise.resolve()
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('still runs the action when the save in flight failed', async () => {
    const save = trackProgressSave(Promise.reject(new Error('down')))
    save.catch(() => undefined)
    const action = vi.fn()

    afterProgressSave(action)
    await Promise.resolve()
    await Promise.resolve()

    expect(action).toHaveBeenCalledTimes(1)
  })

  it('runs at once again after the save has landed', async () => {
    await trackProgressSave(Promise.resolve())
    await Promise.resolve()
    const action = vi.fn()

    afterProgressSave(action)

    expect(action).toHaveBeenCalledTimes(1)
  })
})
