import type {
  SetupUserAcknowledgmentDecision,
  useSetupAssistantStore,
} from '@/state/setupAssistantStore'
import type { SetupToolApprovalState } from '@/types'

import {
  executeNativeBridgeToolCall,
  isNativeBridgeToolCall,
} from '../setupAssistantBridgeRouting'
import {
  postProposalDecision,
  summarizeExecutionResponse,
} from '../setupAssistantProposalApi'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>
type AcknowledgmentApprovalState = Extract<SetupUserAcknowledgmentDecision, SetupToolApprovalState>

// Right-aligned acknowledgment chip copy for each user-driven decision.
// Approve has dead air to fill (the receipt's "executed" pill flips,
// then there's a multi-second gap before the launched experience —
// Dill draft, Paprika task, etc. — produces visible output); Defer and
// Skip are paired here for transcript consistency so any explicit user
// action on a receipt produces a chronological right-side record.
// First-person, terminal-punctuated to read like a real action the
// user took, not an agent-side status update.
const ACKNOWLEDGMENT_LABELS: Record<AcknowledgmentApprovalState, string> = {
  approved: 'Approved.',
  deferred: 'Save for later.',
  skipped: 'Not now.',
}

function isAcknowledgmentDecision(
  state: SetupToolApprovalState,
): state is AcknowledgmentApprovalState {
  return state === 'approved' || state === 'deferred' || state === 'skipped'
}

// Owns the single biggest behavioral path in the setup assistant:
// turning the user's Approve / Defer / Decline / Suggest-something-else
// click on a consent receipt into the right side effect, and then
// reflecting the result back into the receipt's UI status.
//
// Three execution branches collapse into one handler:
//   1. Non-approve decisions (deferred / skipped) -> mark approving,
//      POST the decision, mark final state with a soft status string.
//   2. Approved + native-bridge tool call (launch_agent_task,
//      launch_assistant_session, start_connection_auth) -> route to
//      Swift, capture any returned id, register it for tracking, mark
//      executed when the bridge action result resolves.
//   3. Approved + backend tool call -> mark approving, POST the
//      decision, summarize the structured execution response into a
//      success/failure status.
//
// Errors anywhere in the flow land in the same recovery path: the
// receipt switches to 'failed' with the error message attached, and
// the global error banner surfaces a copy.

export interface SetupProposalActionsApi {
  handleReceiptAction: (proposalId: string, approvalState: SetupToolApprovalState) => void
}

export function useSetupProposalActions({
  store,
}: {
  store: SetupAssistantStore
}): SetupProposalActionsApi {
  const handleReceiptAction = (proposalId: string, approvalState: SetupToolApprovalState) => {
    const pendingProposal = store.state.pendingProposals[proposalId]
    if (!pendingProposal) {
      store.setError('I could not find that setup proposal.')
      return
    }

    // Drop a right-aligned acknowledgment chip into the chronological
    // conversation flow as a record that the user took this action.
    // Fires synchronously (before the async lifecycle below) so the
    // chip lands in the same frame as the click — primarily to fill
    // the Approve-to-result dead air on side-effectful approvals like
    // Dill drafting and Paprika task launches. The chip is filtered
    // out of the agent's chat_history in useSetupAgentStream's
    // buildRequest, so this is purely a UI receipt — the agent
    // continues to learn what happened via execution_outcomes and the
    // receipt's own approval_state.
    if (isAcknowledgmentDecision(approvalState)) {
      const createdAt = new Date().toISOString()
      store.addUserAcknowledgment({
        id: `${proposalId}-${approvalState}-${Date.now()}`,
        sourceId: proposalId,
        kind: 'receipt_decision',
        decision: approvalState,
        label: ACKNOWLEDGMENT_LABELS[approvalState],
        createdAt,
      })
    }

    void (async () => {
      try {
        if (approvalState !== 'approved') {
          store.setProposalState(proposalId, 'approving', 'Updating this setup choice...')
          await postProposalDecision(proposalId, approvalState)
          store.setProposalState(
            proposalId,
            approvalState,
            approvalState === 'deferred'
              ? 'Saved for later.'
              : 'Skipped for now.',
          )
          return
        }

        store.setProposalState(proposalId, 'approving', 'Preparing the approved action...')
        const toolCall = pendingProposal.receipt.tool_call

        if (isNativeBridgeToolCall(toolCall)) {
          store.setProposalState(proposalId, 'executing', 'Opening the approved Basil experience...')
          const result = await executeNativeBridgeToolCall(toolCall)
          // If this was a launch_agent_task launch, the Swift host returns the
          // newly-minted agentTaskId in resultPayload. Register it so the
          // observation listener can re-engage the setup agent on progress
          // and terminal updates instead of leaving the conversation pinned
          // at "executed".
          if (toolCall.tool_name === 'launch_agent_task') {
            const launchedAgentTaskId = typeof result.resultPayload?.agentTaskId === 'string'
              ? result.resultPayload.agentTaskId
              : null
            if (launchedAgentTaskId) {
              store.registerTrackedAgentTask(launchedAgentTaskId)
            }
          }
          // Sibling registration for setup-launched Dill sessions. The
          // Swift bridge defers its action-result dispatch until the
          // AssistantSession view model allocates a backend session id
          // and surfaces it here in resultPayload.assistantSessionId.
          // Registering enables the assistant-session observation
          // listener to update the inflight UI on terminal — even if
          // the terminal observation races the registration, the
          // re-engagement turn still fires from the listener.
          if (toolCall.tool_name === 'launch_assistant_session') {
            const launchedAssistantSessionId = typeof result.resultPayload?.assistantSessionId === 'string'
              ? result.resultPayload.assistantSessionId
              : null
            if (launchedAssistantSessionId) {
              store.registerTrackedAssistantSession(launchedAssistantSessionId)
            }
          }
          store.setProposalState(proposalId, 'executed', result.message || 'Approved action opened.')
          return
        }

        store.setProposalState(proposalId, 'executing', 'Applying the approved setup change...')
        const response = await postProposalDecision(proposalId, approvalState)
        const result = summarizeExecutionResponse(response)
        store.setProposalState(
          proposalId,
          result.failed ? 'failed' : 'executed',
          result.message,
          result.failed ? result.message : null,
          result.appearanceChange,
        )
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        store.setProposalState(proposalId, 'failed', 'That action needs attention.', message)
        store.setError(message)
      }
    })()
  }

  return { handleReceiptAction }
}
