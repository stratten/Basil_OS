// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { useSetupAssistantStore } from '@/state/setupAssistantStore'

import { type SavedSetupSessionApi, useSavedSetupSession } from './useSavedSetupSession'

const api = vi.hoisted(() => ({ fetchSetupAssistantState: vi.fn(), discardSavedSetupSession: vi.fn() }))
vi.mock('@/services/api', () => api)

const ACCESS = { mode: 'provider_key', provider: 'anthropic', model_id: 'claude', resolved: true }

function savedState(overrides: Record<string, unknown> = {}) {
  return {
    state: {
      completed: false,
      pending_setup_assistant: true,
      resume_stage: 'conversation',
      resume_summary: 'Saved so far: profile.',
      resume_model_access: ACCESS,
      resume_interaction_style: ['Be brief'],
      resume_age_days: 2,
      resume_advisory_after_days: 3,
      session_goals: [{ id: 'a', title: 'Tell me about you', intent: '', kind: 'conversational', source: 'catalog', status: 'completed' }],
      ...overrides,
    },
  }
}

let container: HTMLElement
let root: Root
let saved: SavedSetupSessionApi
let store: ReturnType<typeof useSetupAssistantStore>
const startStream = vi.fn()
const onResumed = vi.fn()

function Harness() {
  store = useSetupAssistantStore()
  saved = useSavedSetupSession({ store, startStream, onResumed })
  return null
}

async function mount() {
  await act(async () => { root.render(<Harness />) })
  await act(async () => { await Promise.resolve() })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  api.discardSavedSetupSession.mockResolvedValue({})
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('useSavedSetupSession', () => {
  it('offers a saved session found when the window opens', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState())

    await mount()

    expect(saved.offeredSession?.agenda.map(item => item.id)).toEqual(['a'])
    expect(startStream).not.toHaveBeenCalled()
  })

  it('offers nothing when setup was finished, nothing is saved, or the state cannot be read', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState({ completed: true }))
    await mount()
    expect(saved.offeredSession).toBeNull()

    act(() => { root.unmount() })
    root = createRoot(container)
    api.fetchSetupAssistantState.mockRejectedValue(new Error('offline'))
    await mount()
    expect(saved.offeredSession).toBeNull()
  })

  it('restores the agenda, model, and style, then starts the conversation once with what was covered', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState())
    await mount()

    await act(async () => { saved.resume() })

    expect(onResumed).toHaveBeenCalledTimes(1)
    expect(store.state.setupStage).toBe('conversation')
    expect(store.state.setupAgentModelAccess).toEqual(ACCESS)
    expect(store.state.sessionAgenda.map(item => item.id)).toEqual(['a'])
    expect(store.state.interactionStyle).toEqual(['Be brief'])
    expect(saved.offeredSession).toBeNull()
    expect(startStream).toHaveBeenCalledTimes(1)
    const [message, facts, phase, stage] = startStream.mock.calls[0]
    expect(message).toContain('Saved so far: profile.')
    expect(message).toContain('Do not start over')
    expect(facts).toBeUndefined()
    expect([phase, stage]).toEqual(['agent_synthesis', 'conversation'])
  })

  it('starting from the top clears the offer and leaves the setup untouched', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState())
    await mount()

    await act(async () => { saved.startOver() })

    expect(saved.offeredSession).toBeNull()
    expect(store.state.setupStage).toBe('welcome')
    expect(store.state.sessionAgenda).toEqual([])
    expect(startStream).not.toHaveBeenCalled()
    expect(onResumed).not.toHaveBeenCalled()
  })

  it('starting from the top also forgets the saved session on the backend, and resuming does not', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState())
    await mount()
    await act(async () => { saved.resume() })
    expect(api.discardSavedSetupSession).not.toHaveBeenCalled()

    act(() => { root.unmount() })
    root = createRoot(container)
    await mount()
    await act(async () => { saved.startOver() })

    expect(api.discardSavedSetupSession).toHaveBeenCalledTimes(1)
  })

  it('still shows the normal first screen when forgetting the saved session fails', async () => {
    api.fetchSetupAssistantState.mockResolvedValue(savedState())
    api.discardSavedSetupSession.mockRejectedValue(new Error('offline'))
    await mount()

    await act(async () => { saved.startOver() })

    expect(saved.offeredSession).toBeNull()
  })
})
