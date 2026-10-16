import type { ExecutionApprovalRequest } from '../../types';

interface Props {
  approval: ExecutionApprovalRequest;
}

/** False only when the backend said this approval can never be remembered; older backends send nothing and keep the checkbox. */
export function approvalCanBeRemembered(approval: ExecutionApprovalRequest): boolean {
  return approval.whitelist?.eligible !== false;
}

/** The agent's own account of what the command does, and its honest advice about remembering it. */
export default function ApprovalExplanationSection({ approval }: Props) {
  const advice = approval.whitelist?.advice;

  if (!approval.purpose && !approval.purpose_missing) return null;

  return (
    <div className="approval-section approval-explanation">
      {approval.purpose ? (
        <>
          <div className="approval-explanation__label">What this does</div>
          <p className="approval-explanation__text">{approval.purpose}</p>
          <div className="approval-explanation__source">The agent&apos;s explanation</div>
        </>
      ) : (
        <p className="approval-explanation__missing" role="note">
          The agent did not explain this command. Read it carefully before approving.
        </p>
      )}
      {advice && (
        <div className="approval-explanation__advice">
          <span className="approval-explanation__advice-label">The agent&apos;s recommendation:</span>{' '}
          <strong>{advice.recommend ? 'Remember this choice' : 'Ask me each time'}</strong>
          <span className="approval-explanation__advice-reason"> &mdash; {advice.reason}</span>
          {advice.downgraded && (
            <div className="approval-explanation__downgraded">Basil overrode the agent here because this kind of command can never be remembered.</div>
          )}
        </div>
      )}
    </div>
  );
}
