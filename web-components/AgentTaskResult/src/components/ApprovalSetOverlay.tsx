import { useState } from 'react';
import { StopCircleIcon, WorkLogCircleIcon } from '@shared/CircleControlIcons';
import type { ExecutionApprovalRequest } from '../types';
import ApprovalOverlay from './ApprovalOverlay';
import ApprovalDock from './approval/ApprovalDock';
import CommandInputRequestCard from './CommandInputRequestCard';
import { DecisionActions, DecisionButton } from './interaction/DecisionButton';

interface Props {
  agentTaskId: string;
  approvals: ExecutionApprovalRequest[];
  rememberChoice: boolean;
  /** Ends the whole task, the same action as the header Stop. */
  onStopTask?: () => void;
  isStopping?: boolean;
}

function ApprovalItem({
  agentTaskId,
  approval,
  rememberChoice,
  embedded,
  onMinimize,
  onStopTask,
  isStopping,
}: {
  agentTaskId: string;
  approval: ExecutionApprovalRequest;
  rememberChoice: boolean;
  embedded: boolean;
  onMinimize?: () => void;
  onStopTask?: () => void;
  isStopping?: boolean;
}) {
  if (approval.execution_type === 'command_input') {
    return <CommandInputRequestCard agentTaskId={agentTaskId} approval={approval} embedded={embedded} />;
  }
  return (
    <ApprovalOverlay
      agentTaskId={agentTaskId}
      approval={approval}
      rememberChoice={rememberChoice}
      embedded={embedded}
      onMinimize={onMinimize}
      onStopTask={onStopTask}
      isStopping={isStopping}
    />
  );
}

/** First non-empty line of what is being approved, for the docked bar. The full text stays in the approval itself. */
function approvalDockSummary(approvals: ExecutionApprovalRequest[]): string {
  if (approvals.length > 1) return `${approvals.length} requests are waiting for your decision`;
  const approval = approvals[0];
  const subject = approval.provider_permission?.subject?.command;
  const text = (typeof subject === 'string' && subject) || approval.command || approval.reason || '';
  return text.split('\n').map(line => line.trim()).find(Boolean) ?? '';
}

export default function ApprovalSetOverlay({
  agentTaskId,
  approvals,
  rememberChoice,
  onStopTask,
  isStopping = false,
}: Props) {
  // The dock belongs to one particular set of approvals. When a different set arrives the full approval comes back by itself, so a new request is never left hidden behind a bar the user opened for the previous one.
  const approvalSetKey = approvals.map(approval => approval.approval_id).join('|');
  const [dockedSetKey, setDockedSetKey] = useState<string | null>(null);
  const docked = dockedSetKey === approvalSetKey;
  const minimize = () => setDockedSetKey(approvalSetKey);
  const restore = () => setDockedSetKey(null);

  // The full approval stays mounted while docked, only hidden, so a typed note and the Remember tick survive the round trip.
  const dock = docked ? (
    <div className="overlay-backdrop overlay-backdrop--docked">
      <ApprovalDock
        count={approvals.length}
        summary={approvalDockSummary(approvals)}
        onRestore={restore}
        onStopTask={onStopTask}
        isStopping={isStopping}
      />
    </div>
  ) : null;

  // The common case is exactly one pending approval. Render it directly
  // (non-embedded, so it owns its own overlay-backdrop/overlay-card) rather
  // than nesting it inside this component's own aggregate card: the two
  // used to stack two full cards -- two copies of "Command Approval
  // Required", two lots of padding, and a maxHeight constraint on top of
  // ApprovalOverlay's own -- which is what clipped the action buttons and
  // left an oversized blank strip beneath them. Only fall back to the
  // aggregate wrapper below when there are genuinely multiple simultaneous
  // approvals to stack.
  if (approvals.length === 1) {
    return (
      <>
        {dock}
        <div hidden={docked}>
          <ApprovalItem
            agentTaskId={agentTaskId}
            approval={approvals[0]}
            rememberChoice={rememberChoice}
            embedded={false}
            onMinimize={minimize}
            onStopTask={onStopTask}
            isStopping={isStopping}
          />
        </div>
      </>
    );
  }

  const includesCommandInput = approvals.some(approval => approval.execution_type === 'command_input');
  const title = includesCommandInput
    ? `${approvals.length} Requests Need Your Response`
    : `${approvals.length} Command Approvals Required`;

  return (
    <>
      {dock}
      <div className="overlay-backdrop" hidden={docked}>
        <section
          className="overlay-card"
          aria-label={`${approvals.length} command approval requests`}
          style={{ maxWidth: 'clamp(360px, 60vw, 640px)', maxHeight: '82vh', overflowY: 'auto' }}
        >
          <div className="overlay-title">
            {title}
          </div>
          <div style={{ display: 'grid', gap: 'var(--padding-m)' }}>
            {approvals.map(approval => (
              <ApprovalItem
                key={approval.approval_id}
                agentTaskId={agentTaskId}
                approval={approval}
                rememberChoice={rememberChoice}
                embedded
              />
            ))}
          </div>
          <DecisionActions className="approval-set-footer">
            <DecisionButton
              tone="neutral"
              icon={<WorkLogCircleIcon />}
              label="See work so far"
              onClick={minimize}
              lead={!onStopTask}
              title="look over what Basil has done before you decide"
            />
            {onStopTask && (
              <DecisionButton
                tone="stop"
                icon={<StopCircleIcon />}
                label={isStopping ? 'Stopping' : 'Stop task'}
                onClick={onStopTask}
                disabled={isStopping}
                lead
                title="ends the whole task, the same as Stop in the header"
              />
            )}
          </DecisionActions>
        </section>
      </div>
    </>
  );
}
