import type { SessionStatus } from '../types';

interface CommitBarProps {
  acceptedCount: number;
  pendingCount: number;
  committing: boolean;
  status: SessionStatus;
  onCommit: () => void;
  onClose: () => void;
}

export function CommitBar({
  acceptedCount,
  pendingCount,
  committing,
  status,
  onCommit,
  onClose,
}: CommitBarProps) {
  const committed = status === 'committed';
  return (
    <div className="commit-bar">
      <span className="commit-summary">
        {committed ? (
          <>Committed — you can close the workspace.</>
        ) : (
          <>
            <strong>{acceptedCount}</strong> accepted
            {pendingCount > 0 ? <> · {pendingCount} still pending</> : null}
          </>
        )}
      </span>
      <div className="commit-actions">
        <button className="action-btn" onClick={onClose}>
          {committed ? 'Close' : 'Discard & Close'}
        </button>
        <button
          className="action-btn success"
          onClick={onCommit}
          disabled={committing || committed || acceptedCount === 0}
        >
          {committing ? 'Committing…' : 'Commit accepted'}
        </button>
      </div>
    </div>
  );
}
