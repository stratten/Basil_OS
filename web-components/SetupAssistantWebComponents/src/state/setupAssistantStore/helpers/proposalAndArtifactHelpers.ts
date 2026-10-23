/*
 * Proposal, artifact, and wrap-up slice mutators
 *
 * Owns transitions for `state.pendingProposals`, `state.artifacts` /
 * `state.activeArtifact`, the receipts embedded inside both
 * `messages[].inlineReceipts` and `artifact.rows[].receipt`, and the
 * `state.wrapUpProposal` slice. These domains are colocated because:
 *
 *   - `updateProposalState` walks `artifact.rows` to update receipts
 *     that live there in addition to receipts attached to message
 *     bubbles, so the proposal/receipt and artifact slices share a
 *     mutation routine.
 *   - `addArtifactRow` reads `row.receipt` (when present) and writes
 *     into `pendingProposals` so that newly-arrived artifact rows are
 *     visible to the proposal lifecycle without a separate event.
 *   - `applyWrapUpProposed` is a small adjacent slice mutator with
 *     the same shape (one slice in, full state out) and is consumed
 *     by both `reducer.ts` (`set_wrap_up_proposal` action) and
 *     `setupAgentEventReducer.ts` (`wrap_up_proposed` event).
 *
 * Sibling files in the same `helpers/` folder:
 *   - setupAgentEventReducer.ts     (calls into these for artifact / proposal / wrap-up SSE events)
 *   - messageBubbleHelpers.ts       (bubble-placement helpers)
 *   - agendaHelpers.ts              (agenda slice mutators)
 *   - ssePayloadNormalizers.ts      (SSE payload trust-boundary converters)
 *
 * The parent `reducer.ts` lives one level up and imports from this
 * file via `./helpers/proposalAndArtifactHelpers`.
 */

import type {
  SetupAppearanceChangeSummary,
  SetupArtifact,
  SetupArtifactRow,
  SetupConsentReceipt,
  SetupSuggestionChip,
  SetupToolApprovalState,
  SetupWrapUpProposal,
} from '@/types'

import type { SetupAssistantState } from '../types'


export function openArtifact(
  state: SetupAssistantState,
  artifact: SetupArtifact,
): SetupAssistantState {
  return {
    ...state,
    activeArtifact: artifact,
    artifacts: [
      ...state.artifacts.filter(existing => existing.id !== artifact.id),
      artifact,
    ],
  }
}

export function addArtifactRow(
  state: SetupAssistantState,
  artifactId: string,
  row?: SetupArtifactRow,
): SetupAssistantState {
  if (!artifactId || !row) return state
  const updateArtifact = (artifact: SetupArtifact): SetupArtifact => (
    artifact.id === artifactId
      ? { ...artifact, rows: [...artifact.rows, row] }
      : artifact
  )
  const receipt = row.receipt
  const pendingProposals = receipt
    ? {
      ...state.pendingProposals,
      [receipt.proposal_id]: {
        proposalId: receipt.proposal_id,
        receipt,
        approvalState: receipt.approval_state,
      },
    }
    : state.pendingProposals

  return {
    ...state,
    pendingProposals,
    activeArtifact: state.activeArtifact ? updateArtifact(state.activeArtifact) : state.activeArtifact,
    artifacts: state.artifacts.map(updateArtifact),
  }
}

export function closeArtifact(
  state: SetupAssistantState,
  artifactId: string,
): SetupAssistantState {
  return {
    ...state,
    activeArtifact: state.activeArtifact?.id === artifactId
      ? { ...state.activeArtifact, is_open: false }
      : state.activeArtifact,
    artifacts: state.artifacts.map(artifact => (
      artifact.id === artifactId ? { ...artifact, is_open: false } : artifact
    )),
  }
}

export function updateProposalState(
  state: SetupAssistantState,
  proposalId: string,
  approvalState: SetupToolApprovalState,
  statusMessage?: string | null,
  errorMessage?: string | null,
  appearanceChange?: SetupAppearanceChangeSummary | null,
): SetupAssistantState {
  if (!proposalId) return state
  const pendingProposal = state.pendingProposals[proposalId]
  if (!pendingProposal) return state
  const receipt = updateReceiptState(
    pendingProposal.receipt,
    approvalState,
    statusMessage,
    errorMessage,
    appearanceChange,
  )

  const updateArtifact = (artifact: SetupArtifact): SetupArtifact => ({
    ...artifact,
    rows: artifact.rows.map(row => (
      row.receipt?.proposal_id === proposalId
        ? {
          ...row,
          receipt: updateReceiptState(row.receipt, approvalState, statusMessage, errorMessage, appearanceChange),
        }
        : row
    )),
  })

  return {
    ...state,
    pendingProposals: {
      ...state.pendingProposals,
      [proposalId]: {
        ...pendingProposal,
        approvalState,
        statusMessage,
        errorMessage,
        receipt,
      },
    },
    messages: state.messages.map(message => ({
      ...message,
      inlineReceipts: message.inlineReceipts.map(inlineReceipt => (
        inlineReceipt.proposal_id === proposalId
          ? updateReceiptState(inlineReceipt, approvalState, statusMessage, errorMessage, appearanceChange)
          : inlineReceipt
      )),
    })),
    activeArtifact: state.activeArtifact ? updateArtifact(state.activeArtifact) : state.activeArtifact,
    artifacts: state.artifacts.map(updateArtifact),
  }
}

export function updateReceiptState(
  receipt: SetupConsentReceipt,
  approvalState: SetupToolApprovalState,
  statusMessage?: string | null,
  errorMessage?: string | null,
  appearanceChange?: SetupAppearanceChangeSummary | null,
): SetupConsentReceipt {
  return {
    ...receipt,
    approval_state: approvalState,
    ui_status_message: statusMessage ?? null,
    ui_error_message: errorMessage ?? null,
    appearance_change: appearanceChange ?? receipt.appearance_change ?? null,
  }
}

export function applyWrapUpProposed(
  state: SetupAssistantState,
  payload: SetupWrapUpProposal,
): SetupAssistantState {
  const recap = typeof payload?.recap === 'string' ? payload.recap : ''
  const recommendedNextSteps = Array.isArray(payload?.recommended_next_steps)
    ? payload.recommended_next_steps as SetupSuggestionChip[]
    : []
  const optionalBreadth = typeof payload?.optional_breadth === 'string'
    ? payload.optional_breadth
    : null
  if (!recap.trim()) return state
  return {
    ...state,
    wrapUpProposal: {
      recap,
      recommended_next_steps: recommendedNextSteps,
      optional_breadth: optionalBreadth,
    },
  }
}
