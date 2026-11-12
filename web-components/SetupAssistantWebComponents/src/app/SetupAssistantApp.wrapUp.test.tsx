// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SetupAssistantApp } from './SetupAssistantApp'

const harness = vi.hoisted(() => ({
  bridge: { reportProblem: vi.fn(), showDiagnosticLogs: vi.fn() },
  wrapUpProps: [] as Array<Record<string, unknown>>,
  shellProps: [] as Array<Record<string, unknown>>,
  state: {} as any,
}))

const MEMORY_FAILURE = {
  kind: 'memory',
  message: 'The local model ran out of memory on this Mac.',
  detail: 'llama_decode returned -3',
  actions: [{ id: 'retry', label: 'Retry model' }],
}

function baseState(overrides: Record<string, unknown>) {
  return {
    setupStage: 'wrap_up',
    setupAgentModelAccess: null,
    observations: [],
    messages: [],
    activeArtifact: undefined,
    artifacts: [],
    pendingProposals: {},
    currentChips: [],
    isStreaming: false,
    importedContext: null,
    interactionStyle: [],
    discoveryFacts: [],
    wasSkipped: false,
    isFinalizingWrapUp: false,
    finalizeError: null,
    errorMessage: undefined,
    localModelFailure: undefined,
    latestProgressNarration: null,
    lastStreamActivity: null,
    trackedAgentTasks: {},
    trackedAssistantSessions: {},
    sessionAgenda: [],
    pendingAgendaConfirmations: {},
    isAgendaSidebarCollapsed: false,
    ...overrides,
  }
}

vi.mock('@/state/setupAssistantStore', () => {
  const store = {
    get state() { return harness.state },
    setStage: vi.fn(),
    setInteractionStyle: vi.fn(),
    appendUserMessage: vi.fn(),
    setModelAccess: vi.fn(),
    setAgendaSidebarCollapsed: vi.fn(),
    applyEvent: vi.fn(),
    mergeImportedContext: vi.fn(),
    clearImportedProfile: vi.fn(),
  }
  return { useSetupAssistantStore: () => store }
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
  useSetupProposalActions: () => ({ handleReceiptAction: vi.fn(), handleApproveAll: vi.fn() }),
}))
vi.mock('./hooks/useSetupCompletion', () => ({
  useSetupCompletion: () => ({ handleFinish: vi.fn(), handleSkip: vi.fn() }),
}))

vi.mock('@/components/wrapup/SetupWrapUpPanel', () => ({
  SetupWrapUpPanel: (props: Record<string, unknown>) => {
    harness.wrapUpProps.push(props)
    return <section data-testid="wrap-up-panel" />
  },
}))
vi.mock('@/components/layout/StarterDownloadsStatus', () => ({ StarterDownloadsStatus: () => null }))
vi.mock('@/components/layout/SetupStepActions', () => ({ SetupStepActions: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/layout/SetupShell', () => ({
  SetupShell: (props: { children: ReactNode } & Record<string, unknown>) => {
    harness.shellProps.push(props)
    return <>{props.children}</>
  },
}))
vi.mock('@/components/transitions/StageTransition', () => ({ StageTransition: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/agenda/SetupAgendaSidebar', () => ({ SetupAgendaSidebar: () => <aside /> }))
vi.mock('@/components/conversation/BasilArtifactPanel', () => ({ BasilArtifactPanel: () => <aside /> }))
vi.mock('@/components/conversation/BasilConversation', () => ({ BasilConversation: () => <section data-testid="conversation" /> }))

vi.mock('@/services/bridge', () => ({
  closeSetupAssistant: vi.fn(),
  notifySetupAssistantReady: vi.fn(),
  isSetupNativeBridgeAvailable: vi.fn(() => false),
  resolveSetupHotkeys: vi.fn(),
  reportProblem: harness.bridge.reportProblem,
  showDiagnosticLogs: harness.bridge.showDiagnosticLogs,
}))

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLElement
let root: Root

function renderApp(overrides: Record<string, unknown>) {
  harness.state = baseState(overrides)
  act(() => { root.render(<SetupAssistantApp />) })
}

const lastWrapUpProps = () => harness.wrapUpProps[harness.wrapUpProps.length - 1]

beforeEach(() => {
  harness.wrapUpProps.length = 0
  harness.shellProps.length = 0
  harness.bridge.reportProblem.mockClear()
  harness.bridge.showDiagnosticLogs.mockClear()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('SetupAssistantApp wrap-up problem handling', () => {
  it('hands a typed local model failure to the wrap-up panel and hides the retry banner', () => {
    renderApp({ localModelFailure: MEMORY_FAILURE, errorMessage: 'Basil could not finish that setup step.' })

    expect(container.querySelector('.local-model-failure-banner')).toBeNull()
    expect(container.querySelector('.error-banner')).toBeNull()
    expect(lastWrapUpProps().problem).toEqual({ message: MEMORY_FAILURE.message, detail: MEMORY_FAILURE.detail })
  })

  it('hands a generic error to the wrap-up panel and hides the error banner', () => {
    renderApp({ errorMessage: 'The connection dropped.' })

    expect(container.querySelector('.error-banner')).toBeNull()
    expect(lastWrapUpProps().problem).toEqual({ message: 'The connection dropped.', detail: null })
  })

  it('passes no problem when nothing failed', () => {
    renderApp({})

    expect(lastWrapUpProps().problem).toBeNull()
  })

  it('wires Show logs and Report a problem to the native bridge with the return code', () => {
    renderApp({ localModelFailure: MEMORY_FAILURE })

    ;(lastWrapUpProps().onShowLogs as (detail?: string) => void)('llama_decode returned -3')
    ;(lastWrapUpProps().onReport as (detail?: string) => void)('llama_decode returned -3')

    expect(harness.bridge.showDiagnosticLogs).toHaveBeenCalledWith('setup_assistant', 'llama_decode returned -3')
    expect(harness.bridge.reportProblem).toHaveBeenCalledWith('setup_assistant', 'llama_decode returned -3')
  })

  it('gives the shell a footer Report a problem action that tells the native side which screen it came from', () => {
    renderApp({ setupStage: 'conversation' })

    const shell = harness.shellProps[harness.shellProps.length - 1]
    ;(shell.onReportProblem as () => void)()

    expect(harness.bridge.reportProblem).toHaveBeenCalledWith('setup_assistant_footer')
  })

  it('hands the saved reply preferences and the import to the wrap-up panel', () => {
    const importedContext = { entries_added: 2, facts_proposed: 0, fact_titles: [], note_titles: [] }
    renderApp({ interactionStyle: ['Keep replies short.'], importedContext })

    expect(lastWrapUpProps().savedInteractionStyle).toEqual(['Keep replies short.'])
    expect(lastWrapUpProps().importedContext).toEqual(importedContext)
  })

  it('still shows the retry banner during the conversation', () => {
    renderApp({ setupStage: 'conversation', localModelFailure: MEMORY_FAILURE })

    expect(container.querySelector('.local-model-failure-banner')!.textContent).toContain(MEMORY_FAILURE.message)
    expect(container.querySelector('[data-testid="conversation"]')).not.toBeNull()
  })

  it('still shows the generic error banner during the conversation', () => {
    renderApp({ setupStage: 'conversation', errorMessage: 'The connection dropped.' })

    expect(container.querySelector('.error-banner')!.textContent).toBe('The connection dropped.')
  })
})
