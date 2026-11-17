import { useState } from 'react';
import ExpandableClamp from '@shared/ExpandableClamp';
import type { ScheduledAgentTaskRun } from '../../types';
import MarkdownRenderer from '../MarkdownRenderer';
import { formatRunDuration, formatTimestamp12h } from './scheduledAgentTaskHelpers';
import { deriveRunPhase, statusToneOfPhase } from '../run/runPhase';

// "missed" and "canceled" arrive as the backend's lowercase run status words; shown as a capitalized phrase, the way every other status label reads.
export function humanizeRunStatus(status: string): string {
  const words = status.replace(/[_-]+/g, ' ').trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : status;
}

// A run that reached an agent task is drawn exactly like that task anywhere else: the same phase reading, label and dot.
// A run that never reached one (missed, skipped, failed to start) keeps its own run status word.
export function RunStatusMark({ run }: { run: ScheduledAgentTaskRun }) {
  if (!run.agent_task_status) return <>{humanizeRunStatus(run.status)}</>;
  const phase = deriveRunPhase({
    status: run.agent_task_status,
    outcome: run.outcome ?? undefined,
    verificationStatus: run.verification_status === 'pending' || run.verification_status === 'resolved' ? run.verification_status : undefined,
  });
  const tone = statusToneOfPhase(phase);
  return (
    <span className="scheduled-run__mark">
      {tone === 'live' ? (
        <span className="execution-live-beacon" aria-hidden="true" />
      ) : (
        <span className={`run-status-dot run-status-dot--${tone}${tone === 'partial' ? ' outcome-partial-mark' : ''}`} aria-hidden="true" />
      )}
      {phase.label}
    </span>
  );
}

const MESSAGE_CLAMP_LINES = 4;
const MESSAGE_CLAMP_MIN_CHARS = 240;

// A run's error or notice is the agent's own markdown text, drawn the way a history card draws the same text. A long one folds to a few lines with a Show more button, so one chatty run cannot take over the list. Clicks and keys inside the message stay inside it, so reading, selecting or following a link never opens the run.
function RunMessage({ text, tone }: { text: string; tone: 'error' | 'notice' }) {
  const [expanded, setExpanded] = useState(false);
  const clampable = text.length > MESSAGE_CLAMP_MIN_CHARS || text.split('\n').length > MESSAGE_CLAMP_LINES;
  return (
    <div className={`scheduled-run__message scheduled-run__message--${tone}`} onClick={event => event.stopPropagation()} onKeyDown={event => event.stopPropagation()}>
      {clampable ? (
        <ExpandableClamp expanded={expanded} collapsedLines={MESSAGE_CLAMP_LINES}>
          <MarkdownRenderer content={text} />
        </ExpandableClamp>
      ) : (
        <MarkdownRenderer content={text} />
      )}
      {clampable && (
        <button type="button" className="scheduled-run__toggle" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}

interface Props {
  runs: ScheduledAgentTaskRun[];
  // When provided AND a run carries a agent_task_id, the row becomes a
  // clickable button that routes back into the result widget through
  // the parent (App)'s agentStore — same flow used by the Swift
  // bridge's ``showExistingAgentTask``. Omitted (or nullish) means the
  // rows render as plain non-interactive metadata.
  onViewAgentTask?: (agentTaskId: string) => void;
}

// The recent run records of a scheduled agent task, below the detail panel. The list grows with the page rather than scrolling inside it, because the detail view already scrolls.
//
// Each row that has been linked to an executed agentTask (via the
// scheduled-run executor) becomes navigable: clicking or hitting
// Enter/Space routes to ``onViewAgentTask(agentTaskId)``. We deliberately
// don't gate navigability on the run's status — a canceled or
// failed run that reached the executor far enough to mint a
// agent_task_id is still worth opening, since the user usually wants to
// see the partial output / error trace in the result widget.
export default function ScheduledRunHistoryList({ runs, onViewAgentTask }: Props) {
  return (
    <section aria-label="Run History">
      <h3 className="scheduled-runs__heading">Run History</h3>
      <div className="scheduled-runs">
        {runs.length === 0 ? (
          <div className="scheduled-runs__empty">No runs yet.</div>
        ) : (
          runs.map(run => {
            const navigable = Boolean(run.agent_task_id) && Boolean(onViewAgentTask);
            const duration = formatRunDuration(run.started_at, run.completed_at);
            const handleOpen = () => {
              if (navigable && run.agent_task_id) {
                onViewAgentTask!(run.agent_task_id);
              }
            };
            return (
              <div
                key={run.id}
                className={navigable ? 'scheduled-run is-navigable' : 'scheduled-run'}
                role={navigable ? 'button' : undefined}
                tabIndex={navigable ? 0 : undefined}
                onClick={navigable ? handleOpen : undefined}
                onKeyDown={
                  navigable
                    ? (e) => {
                        // Only the row itself opens the run, not a control inside it.
                        if (e.target !== e.currentTarget) return;
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          handleOpen();
                        }
                      }
                    : undefined
                }
                title={navigable ? 'Open this run in the result view' : undefined}
              >
                <div className="scheduled-run__head">
                  <span className="scheduled-run__status">
                    <RunStatusMark run={run} />
                  </span>
                  <span className="scheduled-run__when">
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
                    {duration ? `, took ${duration}` : ''}
                  </span>
                </div>
                {run.error_message && <RunMessage text={run.error_message} tone="error" />}
                {run.notice && <RunMessage text={run.notice} tone="notice" />}
                {navigable && <div className="scheduled-run__open">Open result →</div>}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
