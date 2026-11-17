import type { SetupAssistantState } from '@/state/setupAssistantStore'
import type { SetupAssistantCompletionRequest } from '@/types'

import { buildSavedSessionFields, type SavedSessionFields } from './savedSession'

type ProgressSource = Pick<SetupAssistantState, 'pendingProposals' | 'sessionAgenda' | 'setupStage' | 'setupAgentModelAccess' | 'interactionStyle'>

/** What setup has done so far and the agenda as it stands. Done, Skip, and the as-you-go save all send this. */
export function buildCompletionPayload(state: Pick<ProgressSource, 'pendingProposals' | 'sessionAgenda'>): SetupAssistantCompletionRequest {
  const proposals = Object.values(state.pendingProposals)
  return {
    configured: proposals
      .filter(proposal => proposal.approvalState === 'executed' || proposal.approvalState === 'approved')
      .map(proposal => proposal.proposalId),
    skipped: proposals.filter(proposal => proposal.approvalState === 'skipped').map(proposal => proposal.proposalId),
    deferred: proposals.filter(proposal => proposal.approvalState === 'deferred').map(proposal => proposal.proposalId),
    // Snapshot of the agenda. The backend keeps it with the persisted setup state so a later resume can pick up where the person left off and so analytics can see which catalog items landed. Empty when the agent never reached `propose_session_agenda`, which the backend tolerates.
    session_goals: state.sessionAgenda.map(item => ({
      id: item.id,
      title: item.title,
      intent: item.intent,
      kind: item.kind,
      source: item.source,
      status: item.status,
      completion_basis: item.completionBasis ?? null,
    })),
  }
}

/** The titles of the setup steps that actually ran, for the saved summary. */
export function executedReceiptTitles(state: Pick<ProgressSource, 'pendingProposals'>): string[] {
  return Object.values(state.pendingProposals)
    .filter(proposal => proposal.approvalState === 'executed')
    .map(proposal => proposal.receipt.title)
}

export type SetupProgressPayload = SetupAssistantCompletionRequest & SavedSessionFields

/** The as-you-go save, or null when the session is not yet somewhere it could be picked up from (before orientation, or before a thinking model is chosen). */
export function buildProgressPayload(state: ProgressSource): SetupProgressPayload | null {
  const saved = buildSavedSessionFields(state, executedReceiptTitles(state))
  if (!saved.resume_stage) return null
  return { ...buildCompletionPayload(state), ...saved }
}
