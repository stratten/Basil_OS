import type { CSSProperties } from 'react';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';

function RailGlyph({ stage }: { stage: AgentRunOverviewPresentation['stages'][number] }) {
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
  onExpand: () => void;
}

export function AgentRunRail({ overview, artifactCount = overview.artifactCount, onExpand }: AgentRunRailProps) {
  const phaseCount = overview.stages.filter(stage => stage.kind === 'phase').length;
  const documentLabel = artifactCount === 1 ? 'document' : 'documents';
  const ariaLabel = `Expand ${overview.terminalState} run overview, ${phaseCount} phases, ${artifactCount} ${documentLabel}`;

  return (
    <aside className="agent-run-rail" aria-label="Run overview">
      <button type="button" className="agent-run-rail-toggle" onClick={onExpand} aria-label={ariaLabel}>
        <span className="agent-run-rail-flow" aria-hidden="true">
          {overview.stages.map((stage, index) => (
            <span
              className={`agent-run-rail-flow-stage agent-run-rail-flow-stage--${stage.kind} is-${stage.state}`}
              key={stage.id}
              style={{
                '--run-rail-enter-delay': `${index * 50}ms`,
                '--run-rail-connector-delay': `${(index + 1) * 50 + 130}ms`,
              } as CSSProperties}
            >
              <RailGlyph stage={stage} />
              <span className="agent-run-rail-stage-tooltip">{railStageTitle(stage)}</span>
              {stage.artifactCount > 0 && <span className="agent-run-rail-artifact-mark" aria-label={`${stage.artifactCount} document${stage.artifactCount === 1 ? '' : 's'}`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg></span>}
            </span>
          ))}
        </span>
      </button>
    </aside>
  );
}
