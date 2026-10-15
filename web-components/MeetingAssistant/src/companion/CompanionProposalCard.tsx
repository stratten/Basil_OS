import { memo, useState } from 'react';
import { openCompanionAssistantSession, openProposalAgentTask, openProposalTodo } from '../bridge/meetingBridge';
import { MeetingMarkdown } from '../lib/markdown';
import { formatItemTime } from './CompanionItemCard';
import { PROPOSAL_ACTION_LABELS } from './companionProposals';
import type { CompanionItem, CompanionProposalDecision, CompanionProposalInfo, CompanionProposalResult } from './types';

interface CompanionProposalCardProps {
  item: CompanionItem;
  /** The researched answer this proposal came from, sent to an Assistant Session as its starting context. */
  contextText: string;
  onDecide: (itemId: string, decision: CompanionProposalDecision) => Promise<CompanionProposalResult | null>;
}

function outcomeText(proposal: CompanionProposalInfo): string | null {
  const automatic = proposal.auto_started ? ' It started by itself because of a watch you created.' : '';
  switch (proposal.state) {
    case 'started':
      return proposal.action === 'agent_task' ? `Sent to an Agent Task.${automatic}` : `Added to your To-Do list.${automatic}`;
    case 'handed_off':
      return 'Opened in an Assistant Session.';
    case 'dismissed':
      return 'Dismissed.';
    default:
      return null;
  }
}

/** One follow-up the Companion proposed. Nothing starts until the user approves it here, except when a watch the user created was allowed to start it. */
function CompanionProposalCard({ item, contextText, onDecide }: CompanionProposalCardProps) {
  const [busy, setBusy] = useState<CompanionProposalDecision | null>(null);
  const proposal = item.proposal;
  if (!proposal) return null;

  const label = PROPOSAL_ACTION_LABELS[proposal.action];
  const open = proposal.state === 'proposed' || proposal.state === 'failed';
  const outcome = outcomeText(proposal);

  const decide = async (decision: CompanionProposalDecision) => {
    setBusy(decision);
    const result = await onDecide(item.id, decision);
    setBusy(null);
    if (decision === 'approve' && result?.state === 'handed_off') openCompanionAssistantSession(result.instruction, contextText);
  };

  return (
    <article className="companion-item companion-item--proposal" aria-label={`Proposed ${label} at ${formatItemTime(item)}`}>
      <header className="companion-item-header">
        <span className="companion-item-kind">Proposed {label}</span>
        {proposal.authority === 'watch' && <span className="meeting-status-message">From a watch you set</span>}
        <span className="meeting-transcription-state" title="Where this happened in the meeting">{formatItemTime(item)}</span>
      </header>
      <p className="companion-proposal-title">{proposal.title}</p>
      <div className="companion-item-body">
        <MeetingMarkdown content={proposal.instruction} />
      </div>
      {outcome !== null && <p className="companion-item-note">{outcome}</p>}
      {proposal.state === 'failed' && (
        <p className="companion-proposal-error" role="alert">{proposal.error ?? 'The action could not be started.'}</p>
      )}
      <footer className="companion-item-actions">
        {open && (
          <button type="button" className="meeting-record-button companion-proposal-approve" disabled={busy !== null} onClick={() => void decide('approve')}>
            {busy === 'approve' ? 'Starting…' : proposal.state === 'failed' ? 'Try Again' : 'Approve'}
          </button>
        )}
        {open && (
          <button type="button" className="meeting-history-load-more-button" disabled={busy !== null} onClick={() => void decide('dismiss')}>
            Dismiss
          </button>
        )}
        {proposal.state === 'started' && proposal.todo_id && (
          <button type="button" className="meeting-history-load-more-button" onClick={() => openProposalTodo(proposal.todo_id as string)}>Open To-Do</button>
        )}
        {proposal.state === 'started' && proposal.agent_task_id && (
          <button type="button" className="meeting-history-load-more-button" onClick={() => openProposalAgentTask(proposal.agent_task_id as string)}>Open Agent Task</button>
        )}
      </footer>
    </article>
  );
}

export default memo(CompanionProposalCard);
