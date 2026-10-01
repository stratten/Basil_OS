import { useEffect, useState } from 'react';
import type { MeetingActionProposalDTO } from '../bridge/types';
import { dismissProposal, openProposalAgentTask, openProposalTodo, promoteAllProposalsToTodos, promoteProposalToTodo, restoreProposal, startProposalNow, updateProposal } from '../bridge/meetingBridge';

const HANDLED_STATUSES = new Set(['submitted', 'completed', 'added_to_todos']);
const DISMISSED_STATUS = 'dismissed';
const ACTIONABLE_STATUSES = new Set(['proposed', 'failed']);
const AUTO_COLLAPSE_STATUSES = new Set(['submitting', 'starting', 'submitted', 'completed', 'dismissed', 'added_to_todos']);
const TODO_STATUS_LABELS: Record<string, string> = {
  candidate: 'Candidate',
  open: 'Open',
  in_progress: 'In progress',
  ready_for_review: 'Ready for review',
  completed: 'Completed',
  dismissed: 'Dismissed',
  canceled: 'Canceled',
};

export default function SuggestedActionWorkspace({ proposals }: { proposals: MeetingActionProposalDTO[] }) {
  const active = proposals.filter((proposal) => !HANDLED_STATUSES.has(proposal.executionStatus) && proposal.executionStatus !== DISMISSED_STATUS);
  const handled = proposals.filter((proposal) => HANDLED_STATUSES.has(proposal.executionStatus));
  const dismissed = proposals.filter((proposal) => proposal.executionStatus === DISMISSED_STATUS);
  const bulkEligible = proposals.filter((proposal) => (
    ACTIONABLE_STATUSES.has(proposal.executionStatus)
    && proposal.draftPrompt.trim().length > 0
    && !proposalHasTodo(proposal)
  ));
  const [bulkRequested, setBulkRequested] = useState<number | null>(null);
  const [bulkSawSubmitting, setBulkSawSubmitting] = useState(false);
  const submittingCount = proposals.filter((proposal) => proposal.executionStatus === 'submitting').length;

  useEffect(() => {
    if (bulkRequested === null) return;
    if (submittingCount > 0) setBulkSawSubmitting(true);
    if (bulkSawSubmitting && submittingCount === 0) {
      setBulkRequested(null);
      setBulkSawSubmitting(false);
    }
  }, [bulkRequested, bulkSawSubmitting, submittingCount]);

  const showBulk = bulkEligible.length > 0 || bulkRequested !== null;
  const bulkCount = bulkRequested ?? bulkEligible.length;
  const bulkCompleted = bulkRequested === null ? 0 : bulkRequested - submittingCount;

  return (
    <div className={`meeting-suggested-action-workspace${showBulk ? ' has-bulk-action' : ''}`}>
      {proposals.length === 0 && <p className="meeting-proposals-empty-state">No suggested actions for this analysis.</p>}
      {showBulk && (
        <div className="meeting-proposals-bulk-actions">
          <button
            type="button"
            className="meeting-proposals-bulk-button"
            disabled={bulkRequested !== null}
            onClick={() => {
              setBulkRequested(bulkEligible.length);
              setBulkSawSubmitting(false);
              promoteAllProposalsToTodos();
            }}
          >
            {bulkRequested !== null ? `Adding ${bulkCompleted} of ${bulkRequested}…` : `Add all ${bulkCount} to To-Dos`}
          </button>
        </div>
      )}
      {active.map((proposal) => (
        <ProposalCard key={proposal.id} proposal={proposal} />
      ))}
      {handled.length > 0 && (
        <details className="meeting-handled-proposals">
          <summary className="meeting-proposal-group-summary">
            <GroupDisclosureChevron />
            <span>Added to To-Dos ({handled.length})</span>
          </summary>
          {handled.map((proposal) => (
            <ProposalCard key={proposal.id} proposal={proposal} />
          ))}
        </details>
      )}
      {dismissed.length > 0 && (
        <details className="meeting-dismissed-proposals">
          <summary className="meeting-proposal-group-summary">
            <GroupDisclosureChevron />
            <span>Dismissed ({dismissed.length})</span>
          </summary>
          {dismissed.map((proposal) => (
            <ProposalCard key={proposal.id} proposal={proposal} />
          ))}
        </details>
      )}
    </div>
  );
}

function ProposalCard({ proposal }: { proposal: MeetingActionProposalDTO }) {
  const [localDraft, setLocalDraft] = useState(proposal.draftPrompt);
  const [manualCollapsed, setManualCollapsed] = useState<boolean | null>(null);
  const autoCollapsed = proposal.executionStatus === 'failed' ? false : AUTO_COLLAPSE_STATUSES.has(proposal.executionStatus);
  const isCollapsed = manualCollapsed ?? autoCollapsed;
  const status = proposal.executionStatus;
  const hasTodo = proposalHasTodo(proposal);
  const canMutate = ACTIONABLE_STATUSES.has(status) || status === 'submitting' || status === 'starting';
  const canStart = localDraft.trim().length > 0 && ACTIONABLE_STATUSES.has(status);
  const canAdd = localDraft.trim().length > 0 && ACTIONABLE_STATUSES.has(status) && !hasTodo;
  useEffect(() => setLocalDraft(proposal.draftPrompt), [proposal.draftPrompt]);
  useEffect(() => { setManualCollapsed(null); }, [proposal.executionStatus]);

  return (
    <div className={`meeting-proposal-card${isCollapsed ? ' meeting-proposal-card--collapsed' : ''}`}>
      <button
        type="button"
        className="meeting-proposal-card-disclosure"
        aria-expanded={!isCollapsed}
        onClick={() => setManualCollapsed(!isCollapsed)}
      >
        <svg
          className={`meeting-proposal-card-chevron${isCollapsed ? ' is-collapsed' : ''}`}
          width="12"
          height="12"
          viewBox="0 0 22 22"
          fill="none"
          style={{ transformBox: 'view-box', transformOrigin: 'center' }}
          aria-hidden="true"
        >
          <path d="M7 9l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <CapabilityIcon capabilityType={proposal.capabilityType} />
        <span className="meeting-proposal-source-task">{proposal.sourceTask}</span>
        {compactStatus(proposal) && <span className="meeting-proposal-card-status">{compactStatus(proposal)}</span>}
      </button>
      {(hasTodo || proposal.submittedAgentTaskId) && (
        <div className="meeting-proposal-linked-work" aria-label="Linked work">
          {hasTodo && (
            <div className="meeting-proposal-linked-work-row">
              <span>To-Do{proposal.todoStatus ? `: ${formatTodoStatus(proposal.todoStatus)}` : ''}</span>
              <button type="button" className="meeting-proposal-linked-work-link" onClick={() => openProposalTodo(proposal.todoId!)}>Open To-Do</button>
            </div>
          )}
          {proposal.submittedAgentTaskId && (
            <div className="meeting-proposal-linked-work-row">
              <span>Agent task{proposal.liveAgentStatus ? `: ${formatAgentStatus(proposal.liveAgentStatus)}` : ''}</span>
              <button type="button" className="meeting-proposal-linked-work-link" onClick={() => openProposalAgentTask(proposal.submittedAgentTaskId!)}>Open Agent Task</button>
            </div>
          )}
        </div>
      )}
      {!isCollapsed && (
        <>
          <p className="meeting-proposal-meta">
            <span className="meeting-proposal-capability">{proposal.capabilityType.replace(/_/g, ' ')}</span>
            <span>{Math.round(proposal.confidence * 100)}% confidence</span>
          </p>
          <p className="meeting-proposal-why">{proposal.whyBasilCanHelp}</p>
          {proposal.missingInformation.length > 0 && (
            <p className="meeting-proposal-missing-info">Needs: {proposal.missingInformation.join(', ')}</p>
          )}
          {proposal.sourceContext && (
            <details className="meeting-proposal-context">
              <summary>
                <span>Transcript context</span>
                {proposal.sourceTimestamp !== null && (
                  <time className="meeting-proposal-context-time" dateTime={`PT${proposal.sourceTimestamp}S`}>
                    {formatTimestamp(proposal.sourceTimestamp)}
                  </time>
                )}
              </summary>
              <blockquote>{proposal.sourceContext}</blockquote>
            </details>
          )}
          <section className="meeting-proposal-agent-task" aria-label="Proposed task">
            <span className="meeting-proposal-agent-task-label">Proposed task</span>
            {proposal.isEditingDraft ? (
              <textarea
                className="meeting-proposal-draft-input"
                value={localDraft}
                onChange={(event) => {
                  setLocalDraft(event.target.value);
                  updateProposal(proposal.id, { draftPrompt: event.target.value });
                }}
              />
            ) : (
              <p className="meeting-proposal-draft-preview" onClick={() => updateProposal(proposal.id, { isEditingDraft: true })}>
                {proposal.draftPrompt}
              </p>
            )}
          </section>
          {proposal.lastError && <p className="meeting-proposal-error" role="alert">{proposal.lastError}</p>}
          {proposal.liveAgentStatus && <span className="meeting-proposal-live-status">{proposal.liveAgentStatus}</span>}
          <div className="meeting-proposal-actions">
            {status === 'dismissed' ? (
              <button type="button" className="meeting-proposal-action-secondary" onClick={() => restoreProposal(proposal.id)}>Restore</button>
            ) : canMutate ? (
              <>
                <button type="button" className="meeting-proposal-action-primary" disabled={!canStart} onClick={() => startProposalNow(proposal.id)}>
                  {status === 'starting' ? 'Starting…' : hasTodo && status === 'failed' ? 'Retry start' : 'Start now'}
                </button>
                <button type="button" className="meeting-proposal-action-secondary" disabled={!canAdd} onClick={() => promoteProposalToTodo(proposal.id)}>
                  {status === 'submitting' ? 'Adding…' : hasTodo ? 'In To-Dos' : 'Add to To-Dos'}
                </button>
                <button type="button" className="meeting-proposal-action-secondary" onClick={() => updateProposal(proposal.id, { isEditingDraft: !proposal.isEditingDraft })}>
                  {proposal.isEditingDraft ? 'Done editing' : 'Edit'}
                </button>
                <button type="button" className="meeting-proposal-action-dismiss" onClick={() => dismissProposal(proposal.id)}>Dismiss</button>
              </>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function GroupDisclosureChevron() {
  return (
    <svg className="meeting-proposal-group-chevron" width="12" height="12" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <path d="M7 9l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function proposalHasTodo(proposal: MeetingActionProposalDTO): boolean {
  return typeof proposal.todoId === 'string' && proposal.todoId.length > 0;
}

function formatTodoStatus(status: string): string {
  return TODO_STATUS_LABELS[status] ?? status.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
}

function formatAgentStatus(status: string): string {
  if (status === 'awaiting_user_input' || status === 'needs_clarification') return 'Needs input';
  return formatTodoStatus(status);
}

function compactStatus(proposal: MeetingActionProposalDTO): string | null {
  const live = proposal.liveAgentStatus;
  if (live === 'awaiting_user_input' || live === 'needs_clarification') return 'Needs input';
  if (live === 'completed' || proposal.executionStatus === 'completed') return 'Completed';
  if (live === 'failed' || proposal.executionStatus === 'failed') return 'Failed';
  if (live === 'processing' || live === 'capturing' || live === 'routing' || proposal.executionStatus === 'submitted') return 'In progress';
  if (proposal.executionStatus === 'submitting') return 'Adding';
  if (proposal.executionStatus === 'starting') return 'Starting';
  if (proposal.executionStatus === 'added_to_todos') return 'In To-Dos';
  return null;
}

function formatTimestamp(seconds: number): string {
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
}

function CapabilityIcon({ capabilityType }: { capabilityType: string }) {
  if (capabilityType.includes('email')) {
    return <svg className="meeting-proposal-capability-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><rect x="2" y="3.5" width="12" height="9" rx="1.5" /><path d="m2.8 4.5 5.2 4 5.2-4" strokeLinejoin="round" /></svg>;
  }
  if (capabilityType.includes('calendar')) {
    return <svg className="meeting-proposal-capability-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true"><rect x="2.2" y="3.5" width="11.6" height="10" rx="1.5" /><path d="M5 1.8v3M11 1.8v3M2.5 6.3h11" /></svg>;
  }
  return <svg className="meeting-proposal-capability-icon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M6.2 1.5c.4 2.5 1.7 3.8 4.2 4.2-2.5.4-3.8 1.7-4.2 4.2-.4-2.5-1.7-3.8-4.2-4.2 2.5-.4 3.8-1.7 4.2-4.2Zm5.2 7.2c.2 1.5 1 2.3 2.5 2.5-1.5.2-2.3 1-2.5 2.5-.2-1.5-1-2.3-2.5-2.5 1.5-.2 2.3-1 2.5-2.5Z" /></svg>;
}
