// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { type SetupCompletionApi, useSetupCompletion } from './useSetupCompletion'

const api = vi.hoisted(() => ({
  completeSetupAssistant: vi.fn(() => Promise.resolve({})),
  finalizeSetupAssistant: vi.fn(() => new Promise(() => {})),
  skipSetupAssistant: vi.fn(() => Promise.resolve({})),
}))

vi.mock('@/services/api', () => api)

type FakeStore = ReturnType<typeof createStore>

function createStore(stateOverrides: Record<string, unknown> = {}) {
  return {
    state: {
      setupStage: 'conversation',
      pendingProposals: {},
      sessionAgenda: [],
      wrapUpProposal: undefined,
      ...stateOverrides,
    } as Record<string, unknown>,
    setStage: vi.fn(),
    setError: vi.fn(),
    markSetupSkipped: vi.fn(),
    setIsFinalizingWrapUp: vi.fn(),
    setFinalizeError: vi.fn(),
    setWrapUpProposal: vi.fn(),
  }
}

let container: HTMLElement
let root: Root
let completion: SetupCompletionApi | null = null
const abort = vi.fn()

function Harness({ store }: { store: FakeStore }) {
  completion = useSetupCompletion({ store: store as never, buildRequest: vi.fn() as never, abort })
  return null
}

function mount(store: FakeStore): SetupCompletionApi {
  act(() => { root.render(<Harness store={store} />) })
  return completion!
}

const completedAgendaItem = {
  id: 'agenda-1',
  title: 'Try a voice command',
  intent: 'Run one voice command end to end',
  kind: 'demo',
  source: 'agent',
  status: 'completed',
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  completion = null
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('useSetupCompletion', () => {
  it('completes setup without a recap when no setup step landed', () => {
    const store = createStore()
    mount(store).handleFinish()

    expect(abort).toHaveBeenCalledTimes(1)
    expect(store.setStage).toHaveBeenCalledWith('wrap_up')
    expect(api.completeSetupAssistant).toHaveBeenCalledTimes(1)
    expect(api.finalizeSetupAssistant).not.toHaveBeenCalled()
    expect(store.setIsFinalizingWrapUp).not.toHaveBeenCalled()
  })

  it('prepares a recap once an agenda item was completed', () => {
    const store = createStore({ sessionAgenda: [completedAgendaItem] })
    mount(store).handleFinish()

    expect(api.completeSetupAssistant).toHaveBeenCalledTimes(1)
    expect(store.setIsFinalizingWrapUp).toHaveBeenCalledWith(true)
    expect(api.finalizeSetupAssistant).toHaveBeenCalledTimes(1)
  })

  it('prepares a recap once a proposal was approved', () => {
    const store = createStore({
      pendingProposals: { 'proposal-1': { proposalId: 'proposal-1', approvalState: 'approved', receipt: {} } },
    })
    mount(store).handleFinish()

    expect(api.finalizeSetupAssistant).toHaveBeenCalledTimes(1)
  })

  it('does not recap for agenda items that were only skipped or deferred', () => {
    const store = createStore({
      sessionAgenda: [
        { ...completedAgendaItem, id: 'agenda-2', status: 'skipped' },
        { ...completedAgendaItem, id: 'agenda-3', status: 'deferred' },
      ],
      pendingProposals: { 'proposal-2': { proposalId: 'proposal-2', approvalState: 'skipped', receipt: {} } },
    })
    mount(store).handleFinish()

    expect(api.completeSetupAssistant).toHaveBeenCalledTimes(1)
    expect(api.finalizeSetupAssistant).not.toHaveBeenCalled()
  })

  it('does not re-finalize when the conversation already produced a recap', () => {
    const store = createStore({
      sessionAgenda: [completedAgendaItem],
      wrapUpProposal: { recap: 'Already summarized.', recommended_next_steps: [] },
    })
    mount(store).handleFinish()

    expect(api.completeSetupAssistant).toHaveBeenCalledTimes(1)
    expect(api.finalizeSetupAssistant).not.toHaveBeenCalled()
  })

  it('ignores Done outside the conversation stage', () => {
    const store = createStore({ setupStage: 'orientation', sessionAgenda: [completedAgendaItem] })
    mount(store).handleFinish()

    expect(abort).not.toHaveBeenCalled()
    expect(store.setStage).not.toHaveBeenCalled()
    expect(api.completeSetupAssistant).not.toHaveBeenCalled()
    expect(api.finalizeSetupAssistant).not.toHaveBeenCalled()
  })

  it('skips from any stage without requesting a recap', () => {
    const store = createStore({ setupStage: 'intro_and_privacy', sessionAgenda: [completedAgendaItem] })
    mount(store).handleSkip()

    expect(abort).toHaveBeenCalledTimes(1)
    expect(store.markSetupSkipped).toHaveBeenCalledTimes(1)
    expect(api.skipSetupAssistant).toHaveBeenCalledTimes(1)
    expect(api.completeSetupAssistant).not.toHaveBeenCalled()
    expect(api.finalizeSetupAssistant).not.toHaveBeenCalled()
  })
})
