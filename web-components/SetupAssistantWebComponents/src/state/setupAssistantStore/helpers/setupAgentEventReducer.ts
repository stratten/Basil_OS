/*
 * Setup agent event reducer (SSE event sub-reducer)
 *
 * The parent `reducer.ts` delegates `case 'apply_event'` here. This
 * file holds the inner switch that maps every `SetupAgentEvent.kind`
 * coming over the SSE stream onto a state transition, plus the two
 * message-streaming helpers (`completeMessage`, `appendMessageDelta`)
 * that only this router consumes, plus the two tiny payload
 * utilities (`stringPayload`, `createStreamActivity`) used pervasively
 * within this file.
 *
 * Everything else is delegated to a sibling helper file in the same
 * `helpers/` folder:
 *   - messageBubbleHelpers.ts       (addInlineReceipt, addInlineEmailContext, addInlineSetupVisual)
 *   - proposalAndArtifactHelpers.ts (openArtifact, addArtifactRow, closeArtifact, updateProposalState, applyWrapUpProposed)
 *   - agendaHelpers.ts              (setSessionAgenda, applyAgendaMarks, addAgendaConfirmationRequest)
 *   - ssePayloadNormalizers.ts      (normalizeAgendaItemsFromSse, normalizeAgendaMarkFromSse, normalizeAgendaConfirmationFromSse, normalizeInlineVisualFromSse)
 *
 * Does NOT import from `../reducer` (would create a cycle: the parent
 * reducer imports this file, this file would import the parent).
 */

import type {
  SetupAgentEvent,
  SetupArtifact,
  SetupArtifactRow,
  SetupConsentReceipt,
  SetupInlineEmailContext,
  SetupOrientationObservation,
  SetupToolApprovalState,
  SetupWrapUpProposal,
} from '@/types'

import type {
  SetupAssistantState,
  SetupStreamActivity,
} from '../types'

import {
  setSessionAgenda,
  applyAgendaMarks,
  addAgendaConfirmationRequest,
} from './agendaHelpers'
import {
  addInlineReceipt,
  addInlineEmailContext,
  addInlineSetupVisual,
} from './messageBubbleHelpers'
import {
  openArtifact,
  addArtifactRow,
  closeArtifact,
  updateProposalState,
  applyWrapUpProposed,
} from './proposalAndArtifactHelpers'
import {
  normalizeAgendaConfirmationFromSse,
  normalizeAgendaItemsFromSse,
  normalizeAgendaMarkFromSse,
  normalizeInlineVisualFromSse,
  normalizeSuggestionChipsFromSse,
} from './ssePayloadNormalizers'


export function applySetupAgentEvent(
  state: SetupAssistantState,
  event: SetupAgentEvent,
): SetupAssistantState {
  switch (event.kind) {
    case 'turn_started':
      return {
        ...state,
        isStreaming: true,
        errorMessage: undefined,
        lastStreamActivity: null,
        latestProgressNarration: null,
      }
    case 'observation_added':
      return {
        ...state,
        observations: [...state.observations, event.payload as unknown as SetupOrientationObservation],
      }
    case 'progress_narration': {
      const message = stringPayload(event.payload.message).trim()
      if (!message) return state
      return {
        ...state,
        latestProgressNarration: { message, at: Date.now() },
      }
    }
    case 'chips_set':
      return {
        ...state,
        currentChips: normalizeSuggestionChipsFromSse(event.payload.chips),
        lastStreamActivity: createStreamActivity('Pulling in next steps.'),
      }
    case 'message_started': {
      const messageId = stringPayload(event.payload.id, `basil-${Date.now()}`)
      return {
        ...state,
        lastStreamActivity: null,
        messages: [
          ...state.messages,
          {
            id: messageId,
            role: 'basil',
            content: '',
            createdAt: new Date().toISOString(),
            streaming: true,
            inlineReceipts: [],
          },
        ],
      }
    }
    case 'message_delta':
      return appendMessageDelta(
        state,
        stringPayload(event.payload.id),
        stringPayload(event.payload.delta),
      )
    case 'message_completed':
      return { ...completeMessage(state, event), lastStreamActivity: null }
    case 'inline_receipt_added':
      return {
        ...addInlineReceipt(state, event.payload.receipt as SetupConsentReceipt),
        lastStreamActivity: createStreamActivity('Drafting an option.'),
      }
    case 'inline_email_context':
      return {
        ...addInlineEmailContext(state, event.payload as unknown as SetupInlineEmailContext),
        lastStreamActivity: createStreamActivity('Pulling that email in to look at together.'),
      }
    case 'artifact_opened':
      return {
        ...openArtifact(state, event.payload as unknown as SetupArtifact),
        lastStreamActivity: createStreamActivity('Pulling up some options on the side.'),
      }
    case 'artifact_row_added':
      return addArtifactRow(
        state,
        stringPayload(event.payload.artifact_id),
        event.payload.row as SetupArtifactRow,
      )
    case 'artifact_closed':
      return closeArtifact(state, stringPayload(event.payload.artifact_id))
    case 'proposal_status_changed':
      return updateProposalState(
        state,
        stringPayload(event.payload.proposal_id),
        stringPayload(event.payload.approval_state, 'proposed') as SetupToolApprovalState,
      )
    case 'wrap_up_proposed':
      return {
        ...applyWrapUpProposed(state, event.payload as unknown as SetupWrapUpProposal),
        lastStreamActivity: createStreamActivity('Putting the recap together.'),
      }
    case 'agenda_proposed': {
      const proposal = event.payload?.proposal as
        | { items?: unknown[] }
        | undefined
      const items = normalizeAgendaItemsFromSse(proposal?.items)
      return {
        ...setSessionAgenda(state, items),
        lastStreamActivity: createStreamActivity('Laying out what we should cover.'),
      }
    }
    case 'agenda_item_marked': {
      const markPayload = event.payload?.mark as
        | {
          id?: unknown
          status?: unknown
          completion_basis?: unknown
        }
        | undefined
      const mark = normalizeAgendaMarkFromSse(markPayload)
      if (!mark) return state
      return applyAgendaMarks(state, [mark])
    }
    case 'agenda_confirmation_requested': {
      const confirmation = normalizeAgendaConfirmationFromSse(
        event.payload?.confirmation,
      )
      if (!confirmation) return state
      return addAgendaConfirmationRequest(state, confirmation)
    }
    case 'setup_visual_shown': {
      const visual = normalizeInlineVisualFromSse(event.payload?.visual)
      if (!visual) return state
      return {
        ...addInlineSetupVisual(state, visual),
        lastStreamActivity: createStreamActivity('Pulling up an image to show you.'),
      }
    }
    case 'turn_complete':
      return { ...state, isStreaming: false, lastStreamActivity: null }
    case 'error':
      return {
        ...state,
        isStreaming: false,
        lastStreamActivity: null,
        errorMessage: stringPayload(event.payload.message, 'Basil could not finish that setup step.'),
      }
    default:
      return state
  }
}

function completeMessage(state: SetupAssistantState, event: SetupAgentEvent): SetupAssistantState {
  const messageId = stringPayload(event.payload.id, `basil-${Date.now()}`)
  const content = stringPayload(event.payload.content)
  const existingIndex = state.messages.findIndex(message => message.id === messageId)

  if (existingIndex >= 0) {
    const messages = state.messages.map(message => (
      message.id === messageId
        ? { ...message, content: content || message.content, streaming: false }
        : message
    ))
    return { ...state, messages }
  }

  return {
    ...state,
    messages: [
      ...state.messages,
      {
        id: messageId,
        role: 'basil',
        content,
        createdAt: new Date().toISOString(),
        streaming: false,
        inlineReceipts: [],
      },
    ],
  }
}

function appendMessageDelta(
  state: SetupAssistantState,
  messageId: string,
  delta: string,
): SetupAssistantState {
  if (!messageId || !delta) return state

  return {
    ...state,
    lastStreamActivity: null,
    messages: state.messages.map(message => (
      message.id === messageId
        ? { ...message, content: `${message.content}${delta}`, streaming: true }
        : message
    )),
  }
}

function stringPayload(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function createStreamActivity(label: string): SetupStreamActivity {
  return { label, at: Date.now() }
}
