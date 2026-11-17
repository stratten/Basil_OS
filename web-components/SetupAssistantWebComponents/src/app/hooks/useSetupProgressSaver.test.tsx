// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { useSetupAssistantStore } from '@/state/setupAssistantStore'

import { PROGRESS_SAVE_DELAY_MS, useSetupProgressSaver } from './useSetupProgressSaver'

const api = vi.hoisted(() => ({ saveSetupProgress: vi.fn() }))
vi.mock('@/services/api', () => api)

const ACCESS = { mode: 'provider_key', provider: 'anthropic', model_id: 'claude', resolved: true }
const AGENDA = [{ id: 'a', title: 'Tell me about you', intent: '', kind: 'conversational' as const, source: 'catalog' as const, status: 'pending' as const }]

let container: HTMLElement
let root: Root
let store: ReturnType<typeof useSetupAssistantStore>

function Harness() {
  store = useSetupAssistantStore()
  useSetupProgressSaver({ store })
  return null
}

async function mount() {
  await act(async () => { root.render(<Harness />) })
}

async function pass(ms: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  vi.clearAllMocks()
  api.saveSetupProgress.mockResolvedValue(undefined)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
  vi.useRealTimers()
})

describe('useSetupProgressSaver', () => {
  it('saves nothing before the session has reached somewhere it could be picked up', async () => {
    await mount()
    await pass(PROGRESS_SAVE_DELAY_MS * 3)

    act(() => { store.setStage('express') })
    await pass(PROGRESS_SAVE_DELAY_MS * 3)

    expect(api.saveSetupProgress).not.toHaveBeenCalled()
  })

  it('saves nothing in the conversation until a thinking model has been chosen', async () => {
    await mount()

    act(() => { store.setStage('conversation') })
    await pass(PROGRESS_SAVE_DELAY_MS * 3)

    expect(api.saveSetupProgress).not.toHaveBeenCalled()
  })

  it('saves the stage, agenda and model once the conversation is under way, without anyone choosing Skip', async () => {
    await mount()

    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, ['Be brief']) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)

    expect(api.saveSetupProgress).toHaveBeenCalledTimes(1)
    const [payload, options] = api.saveSetupProgress.mock.calls[0]
    expect(payload.resume_stage).toBe('conversation')
    expect(payload.resume_model_access).toEqual(ACCESS)
    expect(payload.resume_interaction_style).toEqual(['Be brief'])
    expect(payload.session_goals.map((goal: { id: string }) => goal.id)).toEqual(['a'])
    expect(options).toBeUndefined()
  })

  it('does not save the same state twice and saves again when something changes', async () => {
    await mount()
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, []) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)
    await pass(PROGRESS_SAVE_DELAY_MS * 5)
    expect(api.saveSetupProgress).toHaveBeenCalledTimes(1)

    act(() => { store.restoreSavedSession(ACCESS as never, [{ ...AGENDA[0], status: 'completed' }], []) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)

    expect(api.saveSetupProgress).toHaveBeenCalledTimes(2)
    expect(api.saveSetupProgress.mock.calls[1][0].session_goals[0].status).toBe('completed')
  })

  it('makes a burst of changes one save', async () => {
    await mount()
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, []) })
    await pass(PROGRESS_SAVE_DELAY_MS / 2)
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, ['Be brief']) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)

    expect(api.saveSetupProgress).toHaveBeenCalledTimes(1)
    expect(api.saveSetupProgress.mock.calls[0][0].resume_interaction_style).toEqual(['Be brief'])
  })

  it('tries again on the next change after a failed save and never throws', async () => {
    api.saveSetupProgress.mockRejectedValueOnce(new Error('backend not ready'))
    await mount()
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, []) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)

    act(() => { store.restoreSavedSession(ACCESS as never, [{ ...AGENDA[0], status: 'completed' }], []) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)

    expect(api.saveSetupProgress).toHaveBeenCalledTimes(2)
  })

  it('stops saving once setup moves to wrap-up, and drops a save still waiting', async () => {
    await mount()
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, []) })
    await pass(PROGRESS_SAVE_DELAY_MS + 10)
    api.saveSetupProgress.mockClear()

    act(() => { store.restoreSavedSession(ACCESS as never, [{ ...AGENDA[0], status: 'completed' }], []) })
    act(() => { store.setStage('wrap_up') })
    await pass(PROGRESS_SAVE_DELAY_MS * 3)

    expect(api.saveSetupProgress).not.toHaveBeenCalled()
  })

  it('saves a change made in the last moments when the window is closing', async () => {
    await mount()
    act(() => { store.restoreSavedSession(ACCESS as never, AGENDA, []) })
    await pass(PROGRESS_SAVE_DELAY_MS / 3)
    expect(api.saveSetupProgress).not.toHaveBeenCalled()

    act(() => { window.dispatchEvent(new Event('pagehide')) })

    expect(api.saveSetupProgress).toHaveBeenCalledTimes(1)
    expect(api.saveSetupProgress.mock.calls[0][1]).toEqual({ keepalive: true })
    await pass(PROGRESS_SAVE_DELAY_MS * 3)
    expect(api.saveSetupProgress).toHaveBeenCalledTimes(1)
  })
})
