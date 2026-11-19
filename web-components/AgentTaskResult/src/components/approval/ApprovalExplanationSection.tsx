import type { ExecutionApprovalRequest } from '../../types';

interface Props {
  approval: ExecutionApprovalRequest;
}

/** False only when the backend said this approval can never be remembered; older backends send nothing and keep the checkbox. */
export function approvalCanBeRemembered(approval: ExecutionApprovalRequest): boolean {
  return approval.whitelist?.eligible !== false;
}

/** The agent's own account of what the command does. Its advice about remembering sits beside the Remember checkbox, where the decision is made, rather than in this box. */
export default function ApprovalExplanationSection({ approval }: Props) {
  if (!approval.purpose && !approval.purpose_missing) return null;

  return (
    <div className="approval-section approval-explanation">
      {approval.purpose ? (
        <>
          <div className="approval-explanation__label">What this does</div>
          <p className="approval-explanation__text">{approval.purpose}</p>
          <div className="approval-explanation__source">{approval.purpose_source === 'basil' ? "Basil's explanation" : "The agent's explanation"}</div>
        </>
      ) : (
        <p className="approval-explanation__missing" role="note">
          The agent did not explain this command. Read it carefully before approving.
        </p>
      )}
    </div>
  );
}
