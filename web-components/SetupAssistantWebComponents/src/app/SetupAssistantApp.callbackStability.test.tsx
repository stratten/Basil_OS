// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SetupAssistantApp } from './SetupAssistantApp'

const testState = vi.hoisted(() => ({
  listeners: new Set<() => void>(),
  agendaRenders: 0,
  artifactRenders: 0,
  state: {
    setupStage: 'conversation' as const,
    setupAgentModelAccess: null,
    observations: [],
    messages: [],
    activeArtifact: undefined,
    artifacts: [],
    pendingProposals: {},
    currentChips: [],
    isStreaming: false,
    discoveryFacts: [],
    wasSkipped: false,
    isFinalizingWrapUp: false,
    finalizeError: null,
    latestProgressNarration: null,
    lastStreamActivity: null,
    trackedAgentTasks: {},
    trackedAssistantSessions: {},
    sessionAgenda: [],
    pendingAgendaConfirmations: {},
    isAgendaSidebarCollapsed: false,
  } as any,
}))

const store = vi.hoisted(() => ({
  state: testState.state,
  setStage: vi.fn(),
  appendUserMessage: vi.fn(),
  setModelAccess: vi.fn(),
  setAgendaSidebarCollapsed: vi.fn(),
  applyEvent: vi.fn((event: { kind: string; payload: { message?: string } }) => {
    if (event.kind === 'progress_narration') {
      testState.state.latestProgressNarration = {
        message: event.payload.message ?? '',
        at: 1,
      }
      testState.listeners.forEach(listener => listener())
    }
  }),
}))

vi.mock('@/state/setupAssistantStore', async () => {
  const { useSyncExternalStore } = await import('react')
  return {
    useSetupAssistantStore: () => {
      useSyncExternalStore(
        (listener) => {
          testState.listeners.add(listener)
          return () => testState.listeners.delete(listener)
        },
        () => testState.state.latestProgressNarration,
      )
      return store
    },
  }
})

vi.mock('./hooks/useSetupAgentStream', () => ({
  useSetupAgentStream: () => ({
    startStream: vi.fn(),
    abort: vi.fn(),
    buildRequest: vi.fn(),
    isOrientationAgentSettled: false,
    resetOrientationSettled: vi.fn(),
  }),
}))

vi.mock('./hooks/useSetupObservations', () => ({
  useSetupObservations: () => ({ handleAgendaConfirmationResolved: vi.fn() }),
}))

vi.mock('./hooks/useSetupDiscovery', () => ({
  useSetupDiscovery: () => ({
    fetchDiscoveryFactsForOrientation: vi.fn(),
    collectOptionalEmailMetadataIfUseful: vi.fn(),
    isDiscoveryFetching: false,
  }),
}))

vi.mock('./hooks/useSetupProposalActions', () => ({
  useSetupProposalActions: () => ({ handleReceiptAction: vi.fn() }),
}))

vi.mock('./hooks/useSetupCompletion', () => ({
  useSetupCompletion: () => ({ handleFinish: vi.fn(), handleSkip: vi.fn() }),
}))

vi.mock('@/components/agenda/SetupAgendaSidebar', async () => {
  const { memo } = await import('react')
  return {
    SetupAgendaSidebar: memo(() => {
      testState.agendaRenders += 1
      return <aside />
    }),
  }
})

vi.mock('@/components/conversation/BasilArtifactPanel', async () => {
  const { memo } = await import('react')
  return {
    BasilArtifactPanel: memo(() => {
      testState.artifactRenders += 1
      return <aside />
    }),
  }
})

vi.mock('@/components/conversation/BasilConversation', () => ({
  BasilConversation: () => <section />,
}))

vi.mock('@/components/layout/SetupShell', () => ({
  SetupShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@/components/transitions/StageTransition', () => ({
  StageTransition: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@/services/bridge', () => ({
  closeSetupAssistant: vi.fn(),
  notifySetupAssistantReady: vi.fn(),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

beforeEach(() => {
  testState.listeners.clear()
  testState.agendaRenders = 0
  testState.artifactRenders = 0
  testState.state.latestProgressNarration = null
  store.applyEvent.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(<SetupAssistantApp />)
  })
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
})

describe('SetupAssistantApp callback stability', () => {
  it('keeps the static agenda and closed artifact panel isolated from stream progress', () => {
    expect(testState.agendaRenders).toBe(1)
    expect(testState.artifactRenders).toBe(1)

    act(() => {
      store.applyEvent({
        kind: 'progress_narration',
        payload: { message: 'Checking the next setup step' },
      })
    })

    expect(testState.agendaRenders).toBe(1)
    expect(testState.artifactRenders).toBe(1)
  })

  it('offers Done with setup as the conversation step action', () => {
    const labels = Array.from(container.querySelectorAll('button')).map(button => button.textContent?.trim())
    expect(labels).toContain('Done with setup')
  })
})
