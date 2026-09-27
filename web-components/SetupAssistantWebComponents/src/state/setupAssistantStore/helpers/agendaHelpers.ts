/*
 * Agenda slice mutators
 *
 * Owns every transition for `state.sessionAgenda` and
 * `state.pendingAgendaConfirmations`. Called from both `reducer.ts`
 * (for direct dispatcher actions like `set_session_agenda` and
 * `resolve_agenda_confirmation`) and from `setupAgentEventReducer.ts`
 * (for agent-driven SSE events like `agenda_proposed` and
 * `agenda_item_marked`). The same helper lives in one place so the
 * "agenda mutation rules" — wholesale replace vs. per-item mark vs.
 * confirmation lifecycle — stay greppable.
 *
 * Sibling files in the same `helpers/` folder:
 *   - setupAgentEventReducer.ts     (calls into these for agenda-related SSE events)
 *   - messageBubbleHelpers.ts       (bubble-placement helpers)
 *   - proposalAndArtifactHelpers.ts (artifact + proposal/receipt slice mutators)
 *   - ssePayloadNormalizers.ts      (SSE payload trust-boundary converters)
 *
 * The parent `reducer.ts` lives one level up and imports from this
 * file via `./helpers/agendaHelpers`.
 */

import type {
  SetupAgendaConfirmationRequest,
  SetupAgendaConfirmationResolution,
  SetupAgendaItemMark,
  SetupAssistantState,
  SetupSessionAgendaItem,
} from '../types'


// --- Session agenda transitions --------------------------------------------
// `propose_session_agenda` replaces the agenda wholesale, which clears any
// in-flight confirmation cards (they would no longer correspond to any item
// the user can see in the sidebar). For per-item updates the agent uses
// `mark_agenda_item`, which routes through `applyAgendaMarks` and leaves
// existing structure intact.

export function setSessionAgenda(
  state: SetupAssistantState,
  items: SetupSessionAgendaItem[],
): SetupAssistantState {
  return {
    ...state,
    sessionAgenda: items,
    pendingAgendaConfirmations: {},
    messages: state.messages.map(message => (
      message.inlineAgendaConfirmations && message.inlineAgendaConfirmations.length > 0
        ? { ...message, inlineAgendaConfirmations: undefined }
        : message
    )),
  }
}

export function applyAgendaMarks(
  state: SetupAssistantState,
  marks: SetupAgendaItemMark[],
): SetupAssistantState {
  if (!marks.length) return state
  const marksById = new Map<string, SetupAgendaItemMark>()
  for (const mark of marks) {
    if (mark && typeof mark.id === 'string' && mark.id.length > 0) {
      marksById.set(mark.id, mark)
    }
  }
  if (marksById.size === 0) return state
  return {
    ...state,
    sessionAgenda: state.sessionAgenda.map(item => {
      const mark = marksById.get(item.id)
      if (!mark) return item
      return {
        ...item,
        status: mark.status,
        completionBasis: mark.completionBasis ?? item.completionBasis,
      }
    }),
  }
}

/*
 * Inline AgendaConfirmationCards are pinned to their own Basil bubble at
 * the moment they're requested, mirroring the `addInlineDillDraft`
 * placement rationale: the card represents a question the agent is asking
 * *right now*, distinct from whatever the agent was just saying. Putting
 * it in its own bubble keeps the chronological reading clean ("Basil
 * walked me through the menu bar item -> Basil asked if that landed")
 * rather than back-attaching the card into a previous bubble where it
 * would visually predate the question itself.
 */
export function addAgendaConfirmationRequest(
  state: SetupAssistantState,
  confirmation: SetupAgendaConfirmationRequest,
): SetupAssistantState {
  if (!confirmation || !confirmation.id) return state
  if (state.pendingAgendaConfirmations[confirmation.id]) return state
  return {
    ...state,
    pendingAgendaConfirmations: {
      ...state.pendingAgendaConfirmations,
      [confirmation.id]: confirmation,
    },
    messages: [
      ...state.messages,
      {
        id: `basil-agenda-confirm-${confirmation.id}-${Date.now()}`,
        role: 'basil',
        content: '',
        createdAt: new Date().toISOString(),
        inlineReceipts: [],
        inlineAgendaConfirmations: [confirmation],
      },
    ],
  }
}

export function resolveAgendaConfirmation(
  state: SetupAssistantState,
  confirmationId: string,
  resolution: SetupAgendaConfirmationResolution,
  resolvedAt: string,
): SetupAssistantState {
  const existing = state.pendingAgendaConfirmations[confirmationId]
  if (!existing) return state
  if (existing.resolution) return state
  const resolved: SetupAgendaConfirmationRequest = {
    ...existing,
    resolution,
    resolvedAt,
  }
  const nextPending = { ...state.pendingAgendaConfirmations }
  delete nextPending[confirmationId]
  return {
    ...state,
    pendingAgendaConfirmations: nextPending,
    messages: state.messages.map(message => {
      if (!message.inlineAgendaConfirmations) return message
      const hasMatch = message.inlineAgendaConfirmations.some(
        candidate => candidate.id === confirmationId,
      )
      if (!hasMatch) return message
      return {
        ...message,
        inlineAgendaConfirmations: message.inlineAgendaConfirmations.map(candidate => (
          candidate.id === confirmationId ? resolved : candidate
        )),
      }
    }),
  }
}
