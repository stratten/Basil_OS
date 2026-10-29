import type { ExecutionApprovalRequest } from '../types';
import ApprovalOverlay from './ApprovalOverlay';
import CommandInputRequestCard from './CommandInputRequestCard';

interface Props {
  agentTaskId: string;
  approvals: ExecutionApprovalRequest[];
  rememberChoice: boolean;
}

function ApprovalItem({
  agentTaskId,
  approval,
  rememberChoice,
  embedded,
}: {
  agentTaskId: string;
  approval: ExecutionApprovalRequest;
  rememberChoice: boolean;
  embedded: boolean;
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
    />
  );
}

export default function ApprovalSetOverlay({
  agentTaskId,
  approvals,
  rememberChoice,
}: Props) {
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
      <ApprovalItem
        agentTaskId={agentTaskId}
        approval={approvals[0]}
        rememberChoice={rememberChoice}
        embedded={false}
      />
    );
  }

  const includesCommandInput = approvals.some(approval => approval.execution_type === 'command_input');
  const title = includesCommandInput
    ? `${approvals.length} Requests Need Your Response`
    : `${approvals.length} Command Approvals Required`;

  return (
    <div className="overlay-backdrop">
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
      </section>
    </div>
  );
}
