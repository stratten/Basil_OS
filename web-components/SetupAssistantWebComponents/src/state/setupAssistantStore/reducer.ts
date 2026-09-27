/*
 * Setup assistant store reducer (core)
 *
 * Owns only two things:
 *   - `initialState`: the store seed.
 *   - `reducer()`: the main action switch that maps every
 *     `SetupAssistantAction.type` onto a state transition.
 *
 * If a helper isn't in this file, it lives in `./helpers/`:
 *   - helpers/setupAgentEventReducer.ts      (inner switch for `apply_event` -> SSE events)
 *   - helpers/messageBubbleHelpers.ts        (addInline* / addUserAcknowledgment placement)
 *   - helpers/proposalAndArtifactHelpers.ts  (artifact, proposal/receipt, wrap-up slice mutators)
 *   - helpers/agendaHelpers.ts               (sessionAgenda + pendingAgendaConfirmations transitions)
 *   - helpers/ssePayloadNormalizers.ts       (snake_case -> camelCase trust-boundary translators)
 *
 * `index.ts` is unchanged and only ever sees `initialState` and
 * `reducer` from this file, so consumers outside this folder
 * (BasilConversation.tsx, SetupAssistantApp.tsx, the hooks, etc.) are
 * unaffected by anything in `./helpers/`.
 */

import type {
  SetupAssistantAction,
  SetupAssistantState,
} from './types'

import {
  addAgendaConfirmationRequest,
  applyAgendaMarks,
  resolveAgendaConfirmation,
  setSessionAgenda,
} from './helpers/agendaHelpers'
import {
  addInlineDillDraft,
  addUserAcknowledgment,
} from './helpers/messageBubbleHelpers'
import {
  applyWrapUpProposed,
  updateProposalState,
} from './helpers/proposalAndArtifactHelpers'
import { applySetupAgentEvent } from './helpers/setupAgentEventReducer'


export const initialState: SetupAssistantState = {
  setupStage: 'welcome',
  setupAgentModelAccess: {
    mode: 'default_proxy',
    custom_model_id: null,
    local_model_id: null,
  },
  observations: [],
  messages: [],
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
}

export function reducer(
  state: SetupAssistantState,
  action: SetupAssistantAction,
): SetupAssistantState {
  switch (action.type) {
    case 'set_stage':
      return { ...state, setupStage: action.setupStage }
    case 'set_model_access':
      return { ...state, setupAgentModelAccess: action.setupAgentModelAccess }
    case 'append_user_message':
      return {
        ...state,
        currentChips: [],
        messages: [
          ...state.messages,
          {
            id: `user-${Date.now()}`,
            role: 'user',
            content: action.content,
            createdAt: new Date().toISOString(),
            inlineReceipts: [],
          },
        ],
      }
    case 'apply_event':
      return applySetupAgentEvent(state, action.event)
    case 'set_error':
      return { ...state, errorMessage: action.errorMessage, isStreaming: false, lastStreamActivity: null }
    case 'set_proposal_state':
      return updateProposalState(
        state,
        action.proposalId,
        action.approvalState,
        action.statusMessage,
        action.errorMessage,
        action.appearanceChange,
      )
    case 'set_discovery_facts':
      return { ...state, discoveryFacts: action.discoveryFacts }
    case 'mark_setup_skipped':
      return { ...state, wasSkipped: true, setupStage: 'wrap_up', isStreaming: false, lastStreamActivity: null }
    case 'set_is_finalizing_wrap_up':
      return { ...state, isFinalizingWrapUp: action.isFinalizingWrapUp }
    case 'set_finalize_error':
      return { ...state, finalizeError: action.finalizeError }
    case 'set_wrap_up_proposal':
      return applyWrapUpProposed(state, action.proposal)
    case 'register_tracked_agent_task':
      if (state.trackedAgentTasks[action.agentTaskId]) {
        return state
      }
      return {
        ...state,
        trackedAgentTasks: {
          ...state.trackedAgentTasks,
          [action.agentTaskId]: {
            agentTaskId: action.agentTaskId,
            registeredAt: Date.now(),
            lastStatus: null,
            lastResultMessage: null,
            lastObservationAt: 0,
            isTerminal: false,
          },
        },
      }
    case 'observe_tracked_agent_task': {
      const existing = state.trackedAgentTasks[action.agentTaskId]
      if (!existing) return state
      return {
        ...state,
        trackedAgentTasks: {
          ...state.trackedAgentTasks,
          [action.agentTaskId]: {
            ...existing,
            lastStatus: action.status,
            lastResultMessage: action.resultMessage,
            lastObservationAt: action.observedAt,
            isTerminal: action.isTerminal || existing.isTerminal,
          },
        },
      }
    }
    case 'clear_tracked_agent_task': {
      if (!state.trackedAgentTasks[action.agentTaskId]) return state
      const next = { ...state.trackedAgentTasks }
      delete next[action.agentTaskId]
      return { ...state, trackedAgentTasks: next }
    }
    case 'register_tracked_assistant_session':
      if (state.trackedAssistantSessions[action.assistantSessionId]) {
        return state
      }
      return {
        ...state,
        trackedAssistantSessions: {
          ...state.trackedAssistantSessions,
          [action.assistantSessionId]: {
            assistantSessionId: action.assistantSessionId,
            registeredAt: Date.now(),
            lastStatus: null,
            lastResultText: null,
            lastObservationAt: 0,
            isTerminal: false,
          },
        },
      }
    case 'observe_tracked_assistant_session': {
      const existing = state.trackedAssistantSessions[action.assistantSessionId]
      // Same permissive policy as observe_tracked_agent_task: if the
      // registration hasn't landed yet (the Dill draft can complete fast
      // enough to beat the bridge action-result round-trip), silently
      // no-op for the tracking slice. The caller still fires the
      // re-engagement turn regardless, so the agent reaction path is
      // unaffected; only the inflight-UI state is missing.
      if (!existing) return state
      return {
        ...state,
        trackedAssistantSessions: {
          ...state.trackedAssistantSessions,
          [action.assistantSessionId]: {
            ...existing,
            lastStatus: action.status,
            lastResultText: action.resultText,
            lastObservationAt: action.observedAt,
            isTerminal: action.isTerminal || existing.isTerminal,
          },
        },
      }
    }
    case 'clear_tracked_assistant_session': {
      if (!state.trackedAssistantSessions[action.assistantSessionId]) return state
      const next = { ...state.trackedAssistantSessions }
      delete next[action.assistantSessionId]
      return { ...state, trackedAssistantSessions: next }
    }
    case 'add_inline_dill_draft':
      return addInlineDillDraft(state, action.draft)
    case 'add_user_acknowledgment':
      return addUserAcknowledgment(state, action.acknowledgment)
    case 'set_session_agenda':
      return setSessionAgenda(state, action.items)
    case 'apply_agenda_marks':
      return applyAgendaMarks(state, action.marks)
    case 'add_agenda_confirmation_request':
      return addAgendaConfirmationRequest(state, action.confirmation)
    case 'resolve_agenda_confirmation':
      return resolveAgendaConfirmation(
        state,
        action.confirmationId,
        action.resolution,
        action.resolvedAt,
      )
    case 'set_agenda_sidebar_collapsed':
      return { ...state, isAgendaSidebarCollapsed: action.collapsed }
    default:
      return state
  }
}
