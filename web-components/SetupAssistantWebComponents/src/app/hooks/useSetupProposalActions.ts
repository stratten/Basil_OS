import { useRef } from 'react'

import type {
  SetupPendingProposal,
  SetupUserAcknowledgmentDecision,
  useSetupAssistantStore,
} from '@/state/setupAssistantStore'
import type { SetupActionExecutionResponse, SetupToolApprovalState } from '@/types'

import {
  executeNativeBridgeToolCall,
  isNativeBridgeToolCall,
} from '../setupAssistantBridgeRouting'
import {
  postProposalDecision,
  summarizeExecutionResponse,
} from '../setupAssistantProposalApi'
import {
  MODEL_DOWNLOADS_STARTED_PROMPT,
  SETUP_CHANGE_RESOLVED_PROMPT,
  SETUP_CHANGES_BATCH_RESOLVED_PROMPT,
} from '../setupAssistantPrompts'
import type { SetupAgentStreamApi } from './useSetupAgentStream'

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
  // Approves several waiting receipts one after another and hands the conversation back to the agent once, with every outcome, instead of once per receipt.
  handleApproveAll: (proposalIds: string[]) => void
}

function buildModelDownloadsStartedOutcome(
  proposalId: string,
  response: SetupActionExecutionResponse | null,
): Record<string, unknown> {
  return {
    kind: 'model_downloads_started',
    proposal_id: proposalId,
    models: (response?.results ?? []).map(item => ({
      model_id: item.result_payload?.model_id ?? null,
      model_type: item.result_payload?.model_type ?? null,
      download_status: item.result_payload?.download_status ?? item.status,
      message: item.message,
    })),
  }
}

// How many resolved setup changes ride along on each re-engagement turn so the agent keeps context when the user approves several receipts in a row.
const MAX_RESOLVED_CHANGE_CONTEXT = 5

function buildSetupChangeResolvedOutcome(
  proposalId: string,
  pendingProposal: SetupPendingProposal,
  status: 'applied' | 'failed',
  message: string,
  batch = false,
): Record<string, unknown> {
  const toolCall = pendingProposal.receipt.tool_call
  return {
    kind: 'setup_change_resolved',
    ...(batch ? { batch: true } : {}),
    proposal_id: proposalId,
    tool_name: toolCall.tool_name,
    title: pendingProposal.receipt.title,
    status,
    message,
    payload: toolCall.payload ?? {},
  }
}

export function useSetupProposalActions({
  store,
  startStream,
}: {
  store: SetupAssistantStore
  startStream?: SetupAgentStreamApi['startStream']
}): SetupProposalActionsApi {
  const resolvedChangesRef = useRef<Record<string, unknown>[]>([])

  // When `batchOutcomes` is given, this receipt is one step of an Approve all: it adds no acknowledgment chip of its own and reports its outcome into the array instead of re-engaging the agent, so the caller can do both once for the whole batch.
  const decideReceipt = (
    proposalId: string,
    approvalState: SetupToolApprovalState,
    batchOutcomes?: Record<string, unknown>[],
  ): Promise<void> => {
    const pendingProposal = store.state.pendingProposals[proposalId]
    if (!pendingProposal) {
      store.setError('I could not find that setup proposal.')
      return Promise.resolve()
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
    if (!batchOutcomes && isAcknowledgmentDecision(approvalState)) {
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

    // Hands the conversation back to the agent with what just happened, so the user is never left with an approved chip and a silent agent.
    const reengageAfterResolved = (status: 'applied' | 'failed', message: string) => {
      if (batchOutcomes) {
        batchOutcomes.push(buildSetupChangeResolvedOutcome(proposalId, pendingProposal, status, message, true))
        return
      }
      if (!startStream) return
      resolvedChangesRef.current = [
        ...resolvedChangesRef.current,
        buildSetupChangeResolvedOutcome(proposalId, pendingProposal, status, message),
      ].slice(-MAX_RESOLVED_CHANGE_CONTEXT)
      startStream(
        SETUP_CHANGE_RESOLVED_PROMPT,
        undefined,
        'agent_synthesis',
        'conversation',
        resolvedChangesRef.current,
      )
    }

    return (async () => {
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
          // The browser sign-in finishes outside this window, so the agent is told it has only been opened and asks the user to say when it is done.
          if (batchOutcomes || toolCall.tool_name === 'start_connection_auth') {
            reengageAfterResolved('applied', result.message || 'The sign-in page was opened in the browser.')
          }
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
        if (!startStream && !batchOutcomes) return
        // The downloads run in the background, so the agent is handed the conversation back as soon as they are queued instead of waiting for them to finish or for the user to type something.
        if (toolCall.tool_name === 'start_model_downloads' && !batchOutcomes) {
          if (!result.failed && startStream) {
            startStream(
              MODEL_DOWNLOADS_STARTED_PROMPT,
              undefined,
              'agent_synthesis',
              'conversation',
              [buildModelDownloadsStartedOutcome(proposalId, response)],
            )
          }
          return
        }
        // Every other approved backend change (settings, saved preferences, appearance) also hands the conversation back, so the user is never left with an "Approved." chip and a silent agent.
        reengageAfterResolved(result.failed ? 'failed' : 'applied', result.message)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        store.setProposalState(proposalId, 'failed', 'That action needs attention.', message)
        store.setError(message)
        // A connection that could not start tells the agent why, so it can explain the manual alternative instead of leaving a red card with no guidance.
        if (batchOutcomes || pendingProposal.receipt.tool_call.tool_name === 'start_connection_auth') {
          reengageAfterResolved('failed', message)
        }
      }
    })()
  }

  const handleReceiptAction = (proposalId: string, approvalState: SetupToolApprovalState) => {
    void decideReceipt(proposalId, approvalState)
  }

  const handleApproveAll = (proposalIds: string[]) => {
    const approvableIds = proposalIds.filter(
      proposalId => store.state.pendingProposals[proposalId]?.approvalState === 'proposed',
    )
    if (approvableIds.length === 0) return

    store.addUserAcknowledgment({
      id: `approve-all-${Date.now()}`,
      sourceId: approvableIds.join(','),
      kind: 'receipt_decision',
      decision: 'approved',
      label: approvableIds.length === 1 ? ACKNOWLEDGMENT_LABELS.approved : `Approved all ${approvableIds.length}.`,
      createdAt: new Date().toISOString(),
    })

    void (async () => {
      const batchOutcomes: Record<string, unknown>[] = []
      // One after another, so two launches or two settings writes never race each other.
      for (const proposalId of approvableIds) {
        await decideReceipt(proposalId, 'approved', batchOutcomes)
      }
      if (batchOutcomes.length === 0 || !startStream) return
      resolvedChangesRef.current = [
        ...resolvedChangesRef.current,
        ...batchOutcomes,
      ].slice(-Math.max(MAX_RESOLVED_CHANGE_CONTEXT, batchOutcomes.length))
      startStream(
        SETUP_CHANGES_BATCH_RESOLVED_PROMPT,
        undefined,
        'agent_synthesis',
        'conversation',
        resolvedChangesRef.current,
      )
    })()
  }

  return { handleReceiptAction, handleApproveAll }
}
