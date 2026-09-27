import { memo, type MouseEvent } from 'react';
import type { MiniPanelRow } from '../types';

interface ScheduledRunRowProps {
  row: MiniPanelRow;
  onOpen: (agentTaskId: string, runId: string) => void;
  onDismiss: (runId: string) => void;
}

function ScheduledRunRowComponent({ row, onOpen, onDismiss }: ScheduledRunRowProps) {
  // Rows that haven't been assigned an agent_task_id yet
  // cannot be opened in the result widget (onOpen only fires
  // when row.agentTaskId is defined). Tag them visually as
  // ``--awaiting`` so the user understands the row is not clickable
  // yet -- without this the row looks identical to a clickable one
  // but silently does nothing on click, which reads as "broken".
  const awaitingAgentTask = !row.agentTaskId;
  const handleDismiss = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onDismiss(row.runId);
  };

  return (
    <div
      className={`mini-panel-row${awaitingAgentTask ? ' mini-panel-row--awaiting' : ''}`}
      onClick={() => {
        if (row.agentTaskId) onOpen(row.agentTaskId, row.runId);
      }}
      role="button"
      tabIndex={0}
      aria-disabled={awaitingAgentTask}
      title={awaitingAgentTask ? 'Waiting for agent task to start...' : 'Open in result widget'}
    >
      <div className={`mini-panel-row-status ${row.status}`} aria-label={row.status} />
      <div className="mini-panel-row-body">
        <div className="mini-panel-row-title">{row.title}</div>
        <div className="mini-panel-row-step">{row.currentStep}</div>
      </div>
      <button
        type="button"
        className="mini-panel-row-dismiss"
        onClick={handleDismiss}
        aria-label="Dismiss row"
        title="Dismiss"
      >
        ×
      </button>
    </div>
  );
}

export default memo(ScheduledRunRowComponent);
