import { useEffect, useId, useMemo, useRef } from 'react';
import type { DerivedAgentTaskArtifacts } from '../artifacts/artifactDerivation';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { deriveAgentRunMapTurns, RUN_STATUS_TONE_CLASS } from './agentRunMapPresentation';
import { EMPTY_RUN_ARTIFACTS, RunCard } from './RunCard';
import { navigationTargetForStage, type RunNavigationTarget } from './runNavigation';

interface AgentRunMapProps {
  runs: AgentTaskRunFocusSummary[];
  focusedRunId: string;
  locationRunId: string;
  currentRunId: string;
  peekedRunIds: string[];
  focusedPresentation: AgentRunOverviewPresentation;
  focusedIsProcessing: boolean;
  artifacts: DerivedAgentTaskArtifacts;
  onPreviewArtifact: (artifactId: string) => void;
  onNavigateRun: (runId: string, target: RunNavigationTarget) => void;
  onTogglePeekRun: (runId: string) => void;
  onOpenRunDocuments: (runId: string) => void;
  onJumpToLatestRun: () => void;
}

export function AgentRunMap({
  runs,
  focusedRunId,
  locationRunId,
  currentRunId,
  peekedRunIds,
  focusedPresentation,
  focusedIsProcessing,
  artifacts,
  onPreviewArtifact,
  onNavigateRun,
  onTogglePeekRun,
  onOpenRunDocuments,
  onJumpToLatestRun,
}: AgentRunMapProps) {
  const idPrefix = useId();
  const listRef = useRef<HTMLOListElement>(null);
  const turns = useMemo(() => deriveAgentRunMapTurns(runs), [runs]);
  const currentRun = runs.find(run => run.id === currentRunId);
  const showJumpToLatest = Boolean(currentRun?.isProcessing) && locationRunId !== currentRunId;

  useEffect(() => {
    const locationTurn = listRef.current?.querySelector<HTMLElement>('.agent-run-map-turn.is-location');
    if (locationTurn && typeof locationTurn.scrollIntoView === 'function') {
      locationTurn.scrollIntoView({ block: 'nearest' });
    }
  }, [locationRunId]);

  return (
    <nav className="agent-run-map" aria-label="Task map">
      <div className="agent-run-map-header">
        <span className="agent-run-map-title">Task map · {runs.length} turns</span>
        {showJumpToLatest && (
          <button type="button" className="agent-run-map-jump" onClick={onJumpToLatestRun}>
            Jump to latest
          </button>
        )}
      </div>
      <ol className="agent-run-map-turns" ref={listRef}>
        {turns.map((turn, index) => {
          const runId = turn.run.id;
          const bodyId = `${idPrefix}-turn-${index}`;
          const isLocation = runId === locationRunId;
          const isFocused = runId === focusedRunId;
          const isPeeked = peekedRunIds.includes(runId);
          const isExpanded = isLocation || isFocused || isPeeked;
          const canTogglePeek = !isLocation && !isFocused;
          const attention = isExpanded ? null : turn.attention;
          const documentLabel = isFocused ? null : turn.documentLabel;

          return (
            <li
              key={runId}
              className={`agent-run-map-turn${isLocation ? ' is-location' : ''}${isExpanded ? ' is-expanded' : ''}`}
            >
              <div className="agent-run-map-turn-header">
                {canTogglePeek ? (
                  <button
                    type="button"
                    className="agent-run-map-turn-toggle"
                    aria-expanded={isPeeked}
                    aria-controls={isPeeked ? bodyId : undefined}
                    aria-label={`${isPeeked ? 'Collapse' : 'Expand'} ${turn.run.label} run history`}
                    onClick={() => onTogglePeekRun(runId)}
                  >
                    <span aria-hidden="true">{isPeeked ? '⌄' : '›'}</span>
                  </button>
                ) : (
                  <span className="agent-run-map-turn-toggle agent-run-map-turn-toggle--static" aria-hidden="true">⌄</span>
                )}
                <button
                  type="button"
                  className="agent-run-map-turn-link"
                  aria-current={isLocation ? 'location' : undefined}
                  aria-label={`${turn.run.label}: ${turn.requestText}. ${turn.status.label}.${isLocation ? ' You are here.' : ''}`}
                  onClick={() => onNavigateRun(runId, { kind: 'run' })}
                >
                  <span className="agent-run-map-ordinal" aria-hidden="true">{turn.run.ordinal}</span>
                  <span className="agent-run-map-summary">
                    <span className="agent-run-map-label">{turn.run.label}</span>
                    <span className="agent-run-map-request">{turn.requestText}</span>
                  </span>
                  <span className={`agent-run-map-status ${RUN_STATUS_TONE_CLASS[turn.status.tone]}`} aria-hidden="true" />
                </button>
              </div>
              {(attention || documentLabel) && (
                <div className="agent-run-map-turn-meta">
                  {attention && (
                    <span className={`agent-run-map-attention is-${attention.kind}`}>{attention.label}</span>
                  )}
                  {documentLabel && (
                    <button
                      type="button"
                      className="agent-run-map-documents"
                      aria-label={`Open ${documentLabel} from ${turn.run.label}`}
                      onClick={() => onOpenRunDocuments(runId)}
                    >
                      {documentLabel}
                    </button>
                  )}
                </div>
              )}
              {isExpanded && (
                <div className="agent-run-map-turn-body" id={bodyId}>
                  <RunCard
                    ariaLabel={`${turn.run.label} overview`}
                    artifacts={isFocused ? artifacts : EMPTY_RUN_ARTIFACTS}
                    presentation={isFocused ? focusedPresentation : turn.overview}
                    isProcessing={isFocused ? focusedIsProcessing : turn.run.isProcessing}
                    onPreviewArtifact={onPreviewArtifact}
                    onSelectStage={stage => onNavigateRun(runId, navigationTargetForStage(stage))}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
