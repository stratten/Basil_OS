import {
  type SetupAgendaConfirmationResolution,
  type SetupAgentTaskObservationTurnRequest,
  type SetupAssistantSessionObservationTurnRequest,
  useAgentTaskObservationListener,
  useAssistantSessionObservationListener,
  type useSetupAssistantStore,
} from '@/state/setupAssistantStore'

import {
  AGENDA_CONFIRMATION_RESOLVED_PROMPT,
  AGENT_TASK_PROGRESS_PROMPT,
  AGENT_TASK_TERMINAL_PROMPT,
  ASSISTANT_SESSION_TERMINAL_PROMPT,
} from '../setupAssistantPrompts'
import type { SetupAgentStreamApi } from './useSetupAgentStream'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

const AGENDA_CONFIRMATION_ACKNOWLEDGMENT_LABELS: Record<SetupAgendaConfirmationResolution, string> = {
  confirmed: 'Makes sense.',
  not_quite: 'Not quite.',
  skipped: 'Skip this.',
}

export interface SetupObservationsApi {
  // Invoked by AgendaConfirmationCard when the user clicks Yes / Not quite
  // / Skip. Updates the store and fires a re-engagement turn so the agent
  // can react via the system prompt's agenda_confirmation_resolved rules.
  handleAgendaConfirmationResolved: (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => void
}

// Wires both bridge-driven observation listeners (agent task + assistant
// session) and turns each terminal/progress observation into a
// re-engagement turn for the setup agent. Returns void — the hook is
// purely a side-effect installer; the work it does (updating tracking
// state, inserting inline draft cards, kicking the agent for the next
// reply) is all reactive to events from the Swift side.
//
// Keeping the two handlers together (instead of one hook per observation
// kind) reflects how they're used: both turn into execution_outcomes
// entries for the next agent turn via `startStream`, and both manage a
// matching tracked-* slice on the store. Splitting them would force the
// caller to coordinate two near-identical hook invocations.

export function useSetupObservations({
  store,
  startStream,
}: {
  store: SetupAssistantStore
  startStream: SetupAgentStreamApi['startStream']
}): SetupObservationsApi {
  const handleAgentTaskObservation = (request: SetupAgentTaskObservationTurnRequest) => {
    const { agentTaskId, outcome, isTerminal } = request
    store.observeTrackedAgentTask(
      agentTaskId,
      outcome.status,
      outcome.result_message ?? outcome.current_step ?? null,
      isTerminal,
    )
    if (isTerminal) {
      store.clearTrackedAgentTask(agentTaskId)
    }
    const prompt = isTerminal ? AGENT_TASK_TERMINAL_PROMPT : AGENT_TASK_PROGRESS_PROMPT
    startStream(
      prompt,
      undefined,
      'agent_synthesis',
      'conversation',
      [outcome as unknown as Record<string, unknown>],
    )
  }

  const handleAssistantSessionObservation = (request: SetupAssistantSessionObservationTurnRequest) => {
    const { assistantSessionId, outcome, isTerminal } = request
    // Mirrors handleAgentTaskObservation: update the tracking slice
    // (silent no-op if the registration hasn't landed yet), then fire a
    // re-engagement turn with the structured outcome attached to
    // execution_outcomes so the setup agent reacts via the system
    // prompt's assistant_session_terminal rules.
    store.observeTrackedAssistantSession(
      assistantSessionId,
      outcome.status,
      outcome.result_text ?? outcome.error_message ?? null,
      isTerminal,
    )
    if (isTerminal) {
      // Persist the draft as an inline card BEFORE the re-engagement
      // turn fires. addInlineDillDraft attaches the card to the last
      // Basil message (or appends a fresh empty one), and the
      // subsequent agent turn appends as a new bubble underneath — so
      // the conversation reads as receipt -> draft card -> agent
      // commentary instead of receipt -> agent commentary with no
      // visible anchor for what Dill actually produced. We also clear
      // the tracking entry here so the card's own `resultText` copy
      // (carried on the SetupInlineDillDraft) is the durable source.
      const cardStatus: 'completed' | 'failed' = outcome.status === 'failed' ? 'failed' : 'completed'
      store.addInlineDillDraft({
        assistantSessionId,
        status: cardStatus,
        resultText: outcome.result_text,
        errorMessage: outcome.error_message,
        createdAt: new Date().toISOString(),
      })
      store.clearTrackedAssistantSession(assistantSessionId)
    }
    // Only terminal observations exist today (see the bridge file's
    // rationale), so we always use the terminal prompt. If progress
    // events are added later, add the prompt branch here.
    startStream(
      ASSISTANT_SESSION_TERMINAL_PROMPT,
      undefined,
      'agent_synthesis',
      'conversation',
      [outcome as unknown as Record<string, unknown>],
    )
  }

  useAgentTaskObservationListener(handleAgentTaskObservation)
  useAssistantSessionObservationListener(handleAssistantSessionObservation)

  const handleAgendaConfirmationResolved = (
    confirmationId: string,
    resolution: SetupAgendaConfirmationResolution,
  ) => {
    // Snapshot the confirmation before resolving so we can include its
    // agenda_item_id and prompt in the re-engagement turn's
    // execution_outcome. After dispatch the entry is moved out of the
    // pending map and into the conversation message's frozen state, so
    // reading it post-dispatch would miss it.
    const existing = store.state.pendingAgendaConfirmations[confirmationId]
    if (!existing || existing.resolution) return

    store.resolveAgendaConfirmation(confirmationId, resolution)
    store.addUserAcknowledgment({
      id: `${confirmationId}-${resolution}-${Date.now()}`,
      sourceId: confirmationId,
      kind: 'agenda_confirmation',
      decision: resolution,
      label: AGENDA_CONFIRMATION_ACKNOWLEDGMENT_LABELS[resolution],
      createdAt: new Date().toISOString(),
    })

    const outcome = {
      kind: 'agenda_confirmation_resolved',
      confirmation_id: confirmationId,
      agenda_item_id: existing.agendaItemId,
      resolution,
      prompt: existing.prompt,
    }
    startStream(
      AGENDA_CONFIRMATION_RESOLVED_PROMPT,
      undefined,
      'agent_synthesis',
      'conversation',
      [outcome as unknown as Record<string, unknown>],
    )
  }

  return { handleAgendaConfirmationResolved }
}
