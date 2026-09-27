import type { ScheduledAgentTaskRun } from '../../types';
import { formatTimestamp12h } from './scheduledAgentTaskHelpers';

interface Props {
  runs: ScheduledAgentTaskRun[];
  // When provided AND a run carries a agent_task_id, the row becomes a
  // clickable button that routes back into the result widget through
  // the parent (App)'s agentStore — same flow used by the Swift
  // bridge's ``showExistingAgentTask``. Omitted (or nullish) means the
  // rows render as plain non-interactive metadata.
  onViewAgentTask?: (agentTaskId: string) => void;
}

// Scrollable list of recent run records for a scheduled agent task.
// Displayed below the read-view detail panel; bounded height keeps a
// long history from pushing the surrounding detail surface offscreen
// while still allowing the user to scroll back through every run.
//
// Each row that has been linked to an executed agentTask (via the
// scheduled-run executor) becomes navigable: clicking or hitting
// Enter/Space routes to ``onViewAgentTask(agentTaskId)``. We deliberately
// don't gate navigability on the run's status — a cancelled or
// failed run that reached the executor far enough to mint a
// agent_task_id is still worth opening, since the user usually wants to
// see the partial output / error trace in the result widget.
export default function ScheduledRunHistoryList({ runs, onViewAgentTask }: Props) {
  return (
    <>
      <div className="current-agent-task-label">Run History</div>
      <div
        style={{
          maxHeight: 300,
          overflow: 'auto',
          border: '1px solid var(--separator-color)',
          borderRadius: 6,
          fontFamily: 'var(--font-family-light)',
        }}
      >
        {runs.length === 0 ? (
          <div
            style={{
              padding: 10,
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-family-light)',
              fontSize: 'var(--font-size-callout)',
            }}
          >
            No runs yet.
          </div>
        ) : (
          runs.map(run => {
            const navigable = Boolean(run.agent_task_id) && Boolean(onViewAgentTask);
            const handleOpen = () => {
              if (navigable && run.agent_task_id) {
                onViewAgentTask!(run.agent_task_id);
              }
            };
            return (
              <div
                key={run.id}
                role={navigable ? 'button' : undefined}
                tabIndex={navigable ? 0 : undefined}
                onClick={navigable ? handleOpen : undefined}
                onKeyDown={
                  navigable
                    ? (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleOpen();
                        }
                      }
                    : undefined
                }
                title={navigable ? 'Open this run in the result view' : undefined}
                style={{
                  padding: '8px 10px',
                  borderBottom: '1px solid var(--separator-color)',
                  cursor: navigable ? 'pointer' : 'default',
                  transition: 'background 100ms ease',
                }}
                onMouseEnter={navigable ? (e) => { e.currentTarget.style.background = 'var(--background-tertiary)'; } : undefined}
                onMouseLeave={navigable ? (e) => { e.currentTarget.style.background = 'transparent'; } : undefined}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <strong
                    style={{
                      fontFamily: 'var(--font-family-medium)',
                      fontSize: 'var(--font-size-status-small)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    {run.status}
                  </strong>
                  <span
                    style={{
                      fontFamily: 'var(--font-family-light)',
                      fontSize: 'var(--font-size-status-tiny)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {/*
                      Prefer the actual run start time (started_at) so the
                      row reflects when the work actually happened. Falls
                      back to the planned trigger time (scheduled_for) for
                      rows that haven't run yet -- e.g. status='scheduled'
                      future rows or status='missed' rows where the run
                      was swept before it could fire -- with a small
                      "scheduled" suffix so the user can tell the two
                      semantics apart.
                    */}
                    {run.started_at
                      ? formatTimestamp12h(run.started_at)
                      : `${formatTimestamp12h(run.scheduled_for)} (scheduled)`}
                  </span>
                </div>
                {run.error_message && (
                  <div
                    style={{
                      color: 'var(--error-base)',
                      fontFamily: 'var(--font-family-light)',
                      fontSize: 'var(--font-size-status-small)',
                      marginTop: 2,
                    }}
                  >
                    {run.error_message}
                  </div>
                )}
                {navigable && (
                  <div
                    style={{
                      fontFamily: 'var(--font-family-light)',
                      fontSize: 'var(--font-size-status-tiny)',
                      color: 'var(--accent-base, var(--text-tertiary))',
                      marginTop: 2,
                    }}
                  >
                    Open result →
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </>
  );
}
