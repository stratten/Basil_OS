import { Fragment, useEffect, useRef, type CSSProperties } from 'react';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import { PausedGlyph, SpeechBubbleGlyph, YourTurnGlyph } from '../interaction/InteractionExchange';
import { interactionSummary } from '../interaction/userInteractions';
import type { AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { presentRunStatus, RUN_STATUS_TONE_CLASS } from './agentRunMapPresentation';

function RailGlyph({ stage }: { stage: AgentRunOverviewPresentation['stages'][number] }) {
  if (stage.kind === 'interaction') {
    if (stage.interaction?.kind === 'pause') return <PausedGlyph />;
    return stage.state === 'waiting' ? <YourTurnGlyph /> : <SpeechBubbleGlyph />;
  }
  if (stage.state === 'failed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>;
  }
  if (stage.artifactCount > 0) {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg>;
  }
  if (stage.state === 'completed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.2 4.2L19 7.5" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /><path d="M12 8v4l2.5 2.5" /></svg>;
}

function railStageTitle(stage: AgentRunOverviewPresentation['stages'][number]): string {
  if (stage.kind === 'interaction' && stage.interaction) {
    const summary = interactionSummary(stage.interaction);
    return stage.state === 'waiting' ? `Your turn: ${summary}` : summary;
  }
  const state = stage.state === 'completed'
    ? 'completed'
    : stage.state === 'failed'
      ? 'needs attention'
      : stage.state === 'active'
        ? 'in progress'
        : stage.state;
  const documents = stage.artifactCount > 0
    ? `, ${stage.artifactCount} document${stage.artifactCount === 1 ? '' : 's'}`
    : '';
  return `${stage.label}: ${state}${documents}`;
}

interface AgentRunRailProps {
  overview: AgentRunOverviewPresentation;
  artifactCount?: number;
  runId?: string;
  isProcessing?: boolean;
  onExpand: () => void;
  runs?: AgentTaskRunFocusSummary[];
  locationRunId?: string;
  onNavigateRun?: (runId: string) => void;
}

const STARTING_STAGE: AgentRunOverviewPresentation['stages'][number] = {
  id: 'overview:starting',
  kind: 'phase',
  label: 'Starting',
  state: 'active',
  startedAt: '',
  artifactCount: 0,
};

export function AgentRunRail({
  overview,
  artifactCount = overview.artifactCount,
  runId,
  isProcessing = false,
  onExpand,
  runs = [],
  locationRunId,
  onNavigateRun,
}: AgentRunRailProps) {
  const phaseCount = overview.stages.filter(stage => stage.kind === 'phase').length;
  const interactionCount = overview.stages.filter(stage => stage.kind === 'interaction').length;
  const documentLabel = artifactCount === 1 ? 'document' : 'documents';
  const interactionLabel = interactionCount > 0
    ? `, ${interactionCount} ${interactionCount === 1 ? 'exchange' : 'exchanges'} with you`
    : '';
  const ariaLabel = `Expand ${overview.terminalState} run overview, ${phaseCount} phases${interactionLabel}, ${artifactCount} ${documentLabel}`;
  const stages = overview.stages.length === 0 && isProcessing ? [STARTING_STAGE] : overview.stages;
  const showTurns = runs.length > 1 && Boolean(onNavigateRun);
  const expandedRunId = runs.some(run => run.id === runId)
    ? runId
    : runs.some(run => run.id === locationRunId)
      ? locationRunId
      : undefined;
  const expandedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const expanded = expandedRef.current;
    if (expanded && typeof expanded.scrollIntoView === 'function') {
      expanded.scrollIntoView({ block: 'nearest' });
    }
  }, [expandedRunId]);

  const flowToggle = (
    <button
      type="button"
      className="agent-run-rail-toggle"
      onClick={onExpand}
      aria-label={ariaLabel}
      aria-current={showTurns && expandedRunId === locationRunId ? 'location' : undefined}
    >
      <span className="agent-run-rail-flow" aria-hidden="true">
        {stages.map((stage, index) => (
          <span
            className={`agent-run-rail-flow-stage agent-run-rail-flow-stage--${stage.kind} is-${stage.state}`}
            key={`${runId ?? 'run'}:${stage.id}`}
            style={{
              '--run-rail-enter-delay': `${index * 50}ms`,
              '--run-rail-connector-delay': `${(index + 1) * 50 + 130}ms`,
            } as CSSProperties}
            data-tooltip={railStageTitle(stage)}
            data-tooltip-placement="left"
          >
            <RailGlyph stage={stage} />
            {stage.artifactCount > 0 && <span className="agent-run-rail-artifact-mark" aria-label={`${stage.artifactCount} document${stage.artifactCount === 1 ? '' : 's'}`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg></span>}
          </span>
        ))}
      </span>
    </button>
  );

  if (!showTurns || !onNavigateRun) {
    return (
      <aside className="agent-run-rail" aria-label="Run overview">
        {flowToggle}
      </aside>
    );
  }

  const expandedRun = runs.find(run => run.id === expandedRunId);
  const expandedStatus = expandedRun ? presentRunStatus(expandedRun) : undefined;
  const expandedTurn = (
    <div className="agent-run-rail-turn-expanded" ref={expandedRef}>
      {expandedRun && expandedStatus && (
        <span
          className="agent-run-rail-turn-number"
          aria-hidden="true"
          data-tooltip={`${expandedRun.label}: ${expandedStatus.label}`}
          data-tooltip-placement="left"
        >
          {expandedRun.ordinal}
        </span>
      )}
      {flowToggle}
    </div>
  );

  return (
    <aside
      className="agent-run-rail agent-run-rail--turns"
      aria-label="Run overview"
      onClick={event => {
        if (!(event.target instanceof Element) || !event.target.closest('button')) {
          onExpand();
        }
      }}
    >
      <nav className="agent-run-rail-turns" aria-label="Turns">
        {runs.map(run => {
          if (run.id === expandedRunId) {
            return <Fragment key={run.id}>{expandedTurn}</Fragment>;
          }
          const status = presentRunStatus(run);
          const isLocation = run.id === locationRunId;
          return (
            <button
              type="button"
              key={run.id}
              className={`agent-run-rail-turn ${RUN_STATUS_TONE_CLASS[status.tone]}${isLocation ? ' is-location' : ''}`}
              aria-current={isLocation ? 'location' : undefined}
              aria-label={`Go to ${run.label}, ${status.label}`}
              data-tooltip={`${run.label}: ${status.label}`}
              data-tooltip-placement="left"
              onClick={() => onNavigateRun(run.id)}
            >
              {run.ordinal}
            </button>
          );
        })}
        {expandedRunId === undefined && expandedTurn}
      </nav>
    </aside>
  );
}
