import { memo, type MouseEvent } from 'react';
import type { MiniPanelRow } from '../types';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import { dotClassOfPhase, phaseOfRow, stepTextOfRow } from '../runPresentation';

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
  // The dot and the line under the title come from the agent task's own phase and outcome, read the way every window reads a task: a run
  // that is blocked on the user says so instead of showing a stale step, and a partial result is never drawn as a failure.
  const phase = phaseOfRow(row);
  const needsInput = phase.kind === 'awaiting';
  const statusClass = dotClassOfPhase(phase);
  const stepText = stepTextOfRow(row, phase);
  const handleDismiss = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onDismiss(row.runId);
  };

  return (
    <div
      className={`mini-panel-row${awaitingAgentTask ? ' mini-panel-row--awaiting' : ''}${needsInput ? ' mini-panel-row--needs-input' : ''}`}
      onClick={() => {
        if (row.agentTaskId) onOpen(row.agentTaskId, row.runId);
      }}
      role="button"
      tabIndex={0}
      aria-disabled={awaitingAgentTask}
      title={awaitingAgentTask ? 'Waiting for the Paprika task to start...' : undefined}
    >
      <div className={`mini-panel-row-status ${statusClass}`} aria-label={needsInput ? 'needs approval' : phase.label} />
      <div className="mini-panel-row-body">
        <div className="mini-panel-row-title">{plainMarkdownText(row.title)}</div>
        <div className="mini-panel-row-step">{stepText}</div>
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
