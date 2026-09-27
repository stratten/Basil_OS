import { useMemo, useReducer } from 'react'

import type {
  SetupAgentEvent,
  SetupAgentModelAccess,
  SetupAppearanceChangeSummary,
  SetupDiscoveryFact,
  SetupToolApprovalState,
  SetupWrapUpProposal,
} from '@/types'

import { initialState, reducer } from './reducer'
import type {
  SetupAgendaConfirmationResolution,
  SetupInlineDillDraft,
  SetupStage,
  SetupUserAcknowledgment,
} from './types'

// Public barrel. Every name a consumer imports today comes through here
// so the public import path `@/state/setupAssistantStore` stays stable
// regardless of how the internal modules are reorganized later.
export * from './types'
export {
  useAgentTaskObservationListener,
  useAssistantSessionObservationListener,
} from './observationListeners'

export function useSetupAssistantStore() {
  const [state, dispatch] = useReducer(reducer, initialState)

  return useMemo(() => ({
    state,
    dispatch,
    setStage: (setupStage: SetupStage) => dispatch({ type: 'set_stage', setupStage }),
    setModelAccess: (setupAgentModelAccess: SetupAgentModelAccess) => (
      dispatch({ type: 'set_model_access', setupAgentModelAccess })
    ),
    appendUserMessage: (content: string) => dispatch({ type: 'append_user_message', content }),
    applyEvent: (event: SetupAgentEvent) => dispatch({ type: 'apply_event', event }),
    setError: (errorMessage?: string) => dispatch({ type: 'set_error', errorMessage }),
    setProposalState: (
      proposalId: string,
      approvalState: SetupToolApprovalState,
      statusMessage?: string | null,
      errorMessage?: string | null,
      appearanceChange?: SetupAppearanceChangeSummary | null,
    ) => (
      dispatch({
        type: 'set_proposal_state',
        proposalId,
        approvalState,
        statusMessage,
        errorMessage,
        appearanceChange,
      })
    ),
    setDiscoveryFacts: (discoveryFacts: SetupDiscoveryFact[]) => (
      dispatch({ type: 'set_discovery_facts', discoveryFacts })
    ),
    markSetupSkipped: () => dispatch({ type: 'mark_setup_skipped' }),
    setIsFinalizingWrapUp: (isFinalizingWrapUp: boolean) => (
      dispatch({ type: 'set_is_finalizing_wrap_up', isFinalizingWrapUp })
    ),
    setFinalizeError: (finalizeError: string | null) => (
      dispatch({ type: 'set_finalize_error', finalizeError })
    ),
    setWrapUpProposal: (proposal: SetupWrapUpProposal) => (
      dispatch({ type: 'set_wrap_up_proposal', proposal })
    ),
    registerTrackedAgentTask: (agentTaskId: string) => (
      dispatch({ type: 'register_tracked_agent_task', agentTaskId })
    ),
    observeTrackedAgentTask: (
      agentTaskId: string,
      status: string,
      resultMessage: string | null,
      isTerminal: boolean,
    ) => (
      dispatch({
        type: 'observe_tracked_agent_task',
        agentTaskId,
        status,
        resultMessage,
        isTerminal,
        observedAt: Date.now(),
      })
    ),
    clearTrackedAgentTask: (agentTaskId: string) => (
      dispatch({ type: 'clear_tracked_agent_task', agentTaskId })
    ),
    registerTrackedAssistantSession: (assistantSessionId: string) => (
      dispatch({ type: 'register_tracked_assistant_session', assistantSessionId })
    ),
    observeTrackedAssistantSession: (
      assistantSessionId: string,
      status: string,
      resultText: string | null,
      isTerminal: boolean,
    ) => (
      dispatch({
        type: 'observe_tracked_assistant_session',
        assistantSessionId,
        status,
        resultText,
        isTerminal,
        observedAt: Date.now(),
      })
    ),
    clearTrackedAssistantSession: (assistantSessionId: string) => (
      dispatch({ type: 'clear_tracked_assistant_session', assistantSessionId })
    ),
    addInlineDillDraft: (draft: SetupInlineDillDraft) => (
      dispatch({ type: 'add_inline_dill_draft', draft })
    ),
    resolveAgendaConfirmation: (
      confirmationId: string,
      resolution: SetupAgendaConfirmationResolution,
    ) => (
      dispatch({
        type: 'resolve_agenda_confirmation',
        confirmationId,
        resolution,
        resolvedAt: new Date().toISOString(),
      })
    ),
    setAgendaSidebarCollapsed: (collapsed: boolean) => (
      dispatch({ type: 'set_agenda_sidebar_collapsed', collapsed })
    ),
    addUserAcknowledgment: (acknowledgment: SetupUserAcknowledgment) => (
      dispatch({ type: 'add_user_acknowledgment', acknowledgment })
    ),
  }), [state])
}
