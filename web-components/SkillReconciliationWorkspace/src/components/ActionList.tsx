import type { ProposedAction, SessionSnapshot } from '../types';
import { KIND_LABELS, actionTitle } from '../app/actionMeta';

interface ActionListProps {
  actions: ProposedAction[];
  snapshot: SessionSnapshot;
  selectedId: string | null;
  onSelect: (actionId: string) => void;
}

// Distinct observation count backing an action: the union of source task ids
// across the pending candidates it draws from (idempotent, no double counting).
function observationCount(action: ProposedAction, snapshot: SessionSnapshot): number {
  const byId = new Map(snapshot.pending_candidates.map((candidate) => [candidate.id, candidate]));
  const taskIds = new Set<string>();
  for (const candidateId of action.source_candidate_ids) {
    const candidate = byId.get(candidateId);
    if (!candidate) continue;
    for (const taskId of candidate.source_task_ids) {
      if (taskId) taskIds.add(taskId);
    }
  }
  return taskIds.size;
}

export function ActionList({ actions, snapshot, selectedId, onSelect }: ActionListProps) {
  return (
    <div className="action-list-pane">
      {actions.map((action) => {
        const seen = observationCount(action, snapshot);
        return (
          <div
            key={action.id}
            className={`action-row${action.id === selectedId ? ' selected' : ''}`}
            onClick={() => onSelect(action.id)}
          >
            <span className="action-row-title">{actionTitle(action)}</span>
            <div className="action-row-meta">
              {seen > 0 && <span className="seen-badge">seen {seen}x</span>}
              <span className={`risk-badge kind-${action.kind}`}>{KIND_LABELS[action.kind]}</span>
              <span className={`decision-badge ${action.decision}`}>{action.decision}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
