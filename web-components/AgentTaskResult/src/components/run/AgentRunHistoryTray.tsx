import { useId, useState } from 'react';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';

interface AgentRunHistoryTrayProps {
  runs: AgentTaskRunFocusSummary[];
  focusedRunId: string;
  onSelect: (runId: string) => void;
}

type RunPresentationTone = 'processing' | 'waiting' | 'failed' | 'note' | 'completed';

interface RunPresentation {
  label: string;
  tone: RunPresentationTone;
}

const TONE_DOT_CLASS: Record<RunPresentationTone, string> = {
  processing: 'is-processing',
  waiting: 'is-awaitingInput',
  failed: 'is-failed',
  note: 'is-completed',
  completed: 'is-completed',
};

// A run whose direct write verified its artifact but only carries an
// agent-generated "partial" advisory (warning severity) completed its
// requested effect; it must not present with the same red marker as an
// actual execution/verification failure.
function presentRunStatus(run: AgentTaskRunFocusSummary): RunPresentation {
  if (run.isProcessing || run.taskStatus === 'routing' || run.taskStatus === 'capturing') {
    return { label: 'In progress', tone: 'processing' };
  }
  if (run.taskStatus === 'awaitingInput') {
    return { label: 'Waiting for input', tone: 'waiting' };
  }
  const isVerifiedContinuityNote = run.hasVerifiedArtifactOutput
    && run.outcome === 'partial'
    && run.resultSeverity === 'warning';
  if (isVerifiedContinuityNote) {
    return { label: 'Completed with note', tone: 'note' };
  }
  if (run.taskStatus === 'failed') {
    return { label: 'Needs attention', tone: 'failed' };
  }
  return { label: 'Completed', tone: 'completed' };
}

export function AgentRunHistoryTray({
  runs,
  focusedRunId,
  onSelect,
}: AgentRunHistoryTrayProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const dateDisplayStyle = useDateDisplayStyle();
  const contentId = useId();

  if (runs.length <= 1) return null;

  return (
    <section className="agent-run-history-tray" aria-label="Task history">
      <button
        type="button"
        className="agent-run-history-toggle"
        aria-expanded={isExpanded}
        aria-controls={contentId}
        onClick={() => setIsExpanded(expanded => !expanded)}
      >
        <span>Task history · {runs.length} runs</span>
        <span className="agent-run-history-toggle-glyph" aria-hidden="true">{isExpanded ? '⌄' : '›'}</span>
      </button>
      {isExpanded && (
        <ol className="agent-run-history-list" id={contentId}>
          {runs.map(run => {
            const isFocused = run.id === focusedRunId;
            const documentLabel = run.documentCount === 1 ? '1 doc' : `${run.documentCount} docs`;
            const presentation = presentRunStatus(run);

            return (
              <li className={`agent-run-history-item${isFocused ? ' is-focused' : ''}`} key={run.id}>
                <button
                  type="button"
                  className="agent-run-history-row"
                  aria-pressed={isFocused}
                  aria-label={`${run.label}: ${run.requestText}. ${run.documentCount > 0 ? `${documentLabel}. ` : ''}${presentation.label}.`}
                  onClick={() => onSelect(run.id)}
                >
                  <span className="agent-run-history-ordinal" aria-hidden="true">{run.ordinal}</span>
                  <span className="agent-run-history-summary">
                    <span className="agent-run-history-label">{run.label}</span>
                    <span className="agent-run-history-request"> — {run.requestText}</span>
                    {presentation.tone === 'note' && (
                      <span className="agent-run-history-note" aria-hidden="true">Note</span>
                    )}
                  </span>
                  {run.documentCount > 0 && <span className="agent-run-history-documents">{documentLabel}</span>}
                  <time className="agent-run-history-time" dateTime={run.timestamp}>
                    {formatHistoryTimestamp(run.timestamp, dateDisplayStyle)}
                  </time>
                  <span
                    className={`agent-run-history-status ${TONE_DOT_CLASS[presentation.tone]}`}
                    aria-label={presentation.label}
                  />
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
