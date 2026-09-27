import type { ExecutionApprovalRequest } from '../types';
import ApprovalOverlay from './ApprovalOverlay';

interface Props {
  agentTaskId: string;
  approvals: ExecutionApprovalRequest[];
  rememberChoice: boolean;
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
      <ApprovalOverlay
        agentTaskId={agentTaskId}
        approval={approvals[0]}
        rememberChoice={rememberChoice}
      />
    );
  }

  return (
    <div className="overlay-backdrop">
      <section
        className="overlay-card"
        aria-label={`${approvals.length} command approval requests`}
        style={{ maxWidth: 'clamp(360px, 60vw, 640px)', maxHeight: '82vh', overflowY: 'auto' }}
      >
        <div className="overlay-title">
          {`${approvals.length} Command Approvals Required`}
        </div>
        <div style={{ display: 'grid', gap: 'var(--padding-m)' }}>
          {approvals.map(approval => (
            <ApprovalOverlay
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
