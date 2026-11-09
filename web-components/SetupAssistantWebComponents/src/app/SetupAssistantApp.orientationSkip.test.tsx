// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SetupAssistantApp } from './SetupAssistantApp'

const harness = vi.hoisted(() => ({
  listeners: new Set<() => void>(),
  version: 0,
  startStream: vi.fn(),
  resolveDiscovery: (() => {}) as (facts: unknown[]) => void,
  state: {
    setupStage: 'intro_and_privacy',
    setupAgentModelAccess: null,
    observations: [],
    messages: [],
    activeArtifact: undefined,
    artifacts: [],
    pendingProposals: {},
    currentChips: [],
    isStreaming: false,
    importedContext: { entries_added: 0, facts_proposed: 0, fact_titles: [], note_titles: [], profile_updated: true, profile_summary: 'You are a designer in Boston.' },
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

vi.mock('@/state/setupAssistantStore', async () => {
  const { useSyncExternalStore } = await import('react')
  const store = {
    get state() { return harness.state },
    setStage: (stage: string) => {
      harness.state = { ...harness.state, setupStage: stage }
      harness.version += 1
      harness.listeners.forEach(listener => listener())
    },
    setInteractionStyle: vi.fn(),
    appendUserMessage: vi.fn(),
    setModelAccess: vi.fn(),
    setAgendaSidebarCollapsed: vi.fn(),
    applyEvent: vi.fn(),
    mergeImportedContext: vi.fn(),
    clearImportedProfile: vi.fn(),
  }
  return {
    useSetupAssistantStore: () => {
      useSyncExternalStore(
        listener => {
          harness.listeners.add(listener)
          return () => harness.listeners.delete(listener)
        },
        () => harness.version,
      )
      return store
    },
  }
})

vi.mock('./hooks/useSetupAgentStream', () => ({
  useSetupAgentStream: () => ({
    startStream: harness.startStream,
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
    fetchDiscoveryFactsForOrientation: () => new Promise<unknown[]>(resolve => { harness.resolveDiscovery = resolve }),
    collectOptionalEmailMetadataIfUseful: vi.fn(),
    isDiscoveryFetching: true,
  }),
}))

vi.mock('./hooks/useSetupProposalActions', () => ({
  useSetupProposalActions: () => ({ handleReceiptAction: vi.fn() }),
}))

vi.mock('./hooks/useSetupCompletion', () => ({
  useSetupCompletion: () => ({ handleFinish: vi.fn(), handleSkip: vi.fn() }),
}))

vi.mock('@/components/intro/IntroAndPrivacy', () => ({
  IntroAndPrivacy: ({ onContinue }: { onContinue: (message: string) => void }) => (
    <button type="button" data-testid="intro-continue" onClick={() => onContinue('')}>Intro continue</button>
  ),
}))

vi.mock('@/components/discovery/OrientationInterstitial', () => ({
  OrientationInterstitial: ({ importedContext, onReadyForConversation }: { importedContext: { profile_summary?: string } | null; onReadyForConversation: () => void }) => (
    <div>
      <span data-testid="orientation-import">{importedContext?.profile_summary ?? ''}</span>
      <button type="button" data-testid="orientation-continue" onClick={onReadyForConversation}>Orientation continue</button>
    </div>
  ),
}))

vi.mock('@/components/agenda/SetupAgendaSidebar', () => ({ SetupAgendaSidebar: () => <aside /> }))
vi.mock('@/components/conversation/BasilArtifactPanel', () => ({ BasilArtifactPanel: () => <aside /> }))
vi.mock('@/components/conversation/BasilConversation', () => ({ BasilConversation: () => <section /> }))
vi.mock('@/components/layout/SetupShell', () => ({ SetupShell: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/transitions/StageTransition', () => ({ StageTransition: ({ children }: { children: ReactNode }) => <>{children}</> }))

vi.mock('@/services/bridge', () => ({
  closeSetupAssistant: vi.fn(),
  notifySetupAssistantReady: vi.fn(),
  isSetupNativeBridgeAvailable: vi.fn(() => false),
  resolveSetupHotkeys: vi.fn(),
}));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

const press = (testId: string) => act(() => { container.querySelector<HTMLElement>(`[data-testid="${testId}"]`)!.click() })
const streamPhases = () => harness.startStream.mock.calls.map(call => call[2])

beforeEach(() => {
  harness.startStream.mockClear()
  harness.state = { ...harness.state, setupStage: 'intro_and_privacy' }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<SetupAssistantApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SetupAssistantApp leaving orientation early', () => {
  it('hands the imported context to the orientation step', () => {
    press('intro-continue')

    expect(container.querySelector('[data-testid="orientation-import"]')!.textContent).toBe('You are a designer in Boston.')
  })

  it('starts the orientation stream once the discovery sweep finishes while the person is still waiting', async () => {
    press('intro-continue')

    await act(async () => { harness.resolveDiscovery([]) })

    expect(streamPhases()).toEqual(['deterministic_discovery'])
  })

  it('does not start the orientation stream over the conversation when the person continued before the sweep finished', async () => {
    press('intro-continue')
    press('orientation-continue')
    expect(streamPhases()).toEqual(['agent_synthesis'])

    await act(async () => { harness.resolveDiscovery([]) })

    expect(streamPhases()).toEqual(['agent_synthesis'])
  })
})
