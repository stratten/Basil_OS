// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useOptimisticSettings, type OptimisticSettings } from './useOptimisticSettings'

interface Fixture {
  a: boolean
  b: boolean
  name: string
}

const CONFIRMED: Fixture = { a: false, b: false, name: 'one' }

function setup() {
  const hook = renderHook(() => useOptimisticSettings<Fixture>())
  act(() => { hook.result.current.receiveSnapshot(CONFIRMED) })
  return hook
}

function change(hook: { result: { current: OptimisticSettings<Fixture> } }, patch: Partial<Fixture>, requestId: string) {
  act(() => {
    hook.result.current.setSettings({ ...hook.result.current.settings!, ...patch })
    hook.result.current.track(requestId)
  })
}

describe('useOptimisticSettings', () => {
  it('applies a change optimistically and reports saving until native resolves it', () => {
    const hook = setup()
    expect(hook.result.current.isSaving).toBe(false)
    change(hook, { a: true }, 'r1')
    expect(hook.result.current.settings).toEqual({ a: true, b: false, name: 'one' })
    expect(hook.result.current.isSaving).toBe(true)
    let outcome = ''
    act(() => { outcome = hook.result.current.resolveIntent('r1', 'success') })
    expect(outcome).toBe('success')
    expect(hook.result.current.isSaving).toBe(false)
    expect(hook.result.current.settings).toEqual({ a: true, b: false, name: 'one' })
  })

  it('keeps pending changes when an unrelated snapshot arrives', () => {
    const hook = setup()
    change(hook, { a: true }, 'r1')
    act(() => { hook.result.current.receiveSnapshot({ a: false, b: true, name: 'two' }) })
    expect(hook.result.current.settings).toEqual({ a: true, b: true, name: 'two' })
  })

  it('reverts only the failed field', () => {
    const hook = setup()
    change(hook, { a: true }, 'r1')
    change(hook, { b: true }, 'r2')
    let outcome = ''
    act(() => { outcome = hook.result.current.resolveIntent('r1', 'error') })
    expect(outcome).toBe('error')
    expect(hook.result.current.settings).toEqual({ a: false, b: true, name: 'one' })
    expect(hook.result.current.isSaving).toBe(true)
  })

  it('does not revert a field that a newer pending request still owns', () => {
    const hook = setup()
    change(hook, { name: 'two' }, 'r1')
    change(hook, { name: 'three' }, 'r2')
    act(() => { hook.result.current.resolveIntent('r1', 'error') })
    expect(hook.result.current.settings?.name).toBe('three')
  })

  it('reverts to the most recently confirmed value', () => {
    const hook = setup()
    change(hook, { name: 'two' }, 'r1')
    act(() => { hook.result.current.resolveIntent('r1', 'success') })
    change(hook, { name: 'three' }, 'r2')
    act(() => { hook.result.current.resolveIntent('r2', 'error') })
    expect(hook.result.current.settings?.name).toBe('two')
  })

  it('reports unmatched request IDs without changing state', () => {
    const hook = setup()
    let outcome = ''
    act(() => { outcome = hook.result.current.resolveIntent('missing', 'error') })
    expect(outcome).toBe('unmatched')
    expect(hook.result.current.settings).toEqual(CONFIRMED)
  })

  it('returns to the unloaded state when native sends a null snapshot', () => {
    const hook = setup()
    change(hook, { a: true }, 'r1')
    act(() => { hook.result.current.receiveSnapshot(null) })
    expect(hook.result.current.settings).toBeNull()
    act(() => { hook.result.current.resolveIntent('r1', 'error') })
    expect(hook.result.current.settings).toBeNull()
  })
})
