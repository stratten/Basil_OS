import type { DerivedAgentTaskArtifacts } from '../artifacts/artifactDerivation';
import { PausedGlyph, SpeechBubbleGlyph, YourTurnGlyph } from '../interaction/InteractionExchange';
import { interactionResponseLabel, interactionSummary } from '../interaction/userInteractions';
import type { AgentRunOverviewPresentation, AgentRunOverviewStage, AgentRunStage } from './agentRunPresentation';

export const EMPTY_RUN_ARTIFACTS: DerivedAgentTaskArtifacts = {
  all: [],
  produced: [],
  retrieved: [],
  ungrouped: [],
};

export function RunStageGlyph({ stage }: { stage: Pick<AgentRunStage, 'kind' | 'state' | 'interaction'> }) {
  if (stage.kind === 'interaction') {
    if (stage.interaction?.kind === 'pause') return <PausedGlyph />;
    return stage.state === 'waiting' ? <YourTurnGlyph /> : <SpeechBubbleGlyph />;
  }
  if (stage.state === 'failed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>;
  }
  if (stage.kind === 'artifact') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg>;
  }
  if (stage.state === 'completed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.2 4.2L19 7.5" /></svg>;
  }
  if (stage.kind === 'tool') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /><path d="M12 8v4l2.5 2.5" /></svg>;
}

function RunStageContent({ stage, terminalStateLabel }: {
  stage: AgentRunOverviewStage;
  terminalStateLabel: string;
}) {
  return (
    <>
      <span className="run-card-stage-glyph" aria-hidden="true"><RunStageGlyph stage={stage} /></span>
      <span className="run-card-stage-label">{stage.label}</span>
      {stage.kind === 'outcome' ? (
        <span className="run-card-stage-evidence">{terminalStateLabel}</span>
      ) : stage.kind === 'interaction' && stage.interaction ? (
        <span className="run-card-stage-evidence" title={interactionSummary(stage.interaction)}>
          {stage.state === 'waiting' && <span className="run-card-your-turn">Your turn</span>}
          {interactionResponseLabel(stage.interaction)}
        </span>
      ) : stage.state === 'waiting' ? (
        <span className="run-card-stage-evidence">
          <span className="run-card-your-turn">Your turn</span>
          Waiting on you
        </span>
      ) : stage.artifactCount > 0 ? (
        <span className="run-card-stage-evidence">{stage.artifactCount} document{stage.artifactCount === 1 ? '' : 's'}</span>
      ) : null}
    </>
  );
}

export function RunCard({
  artifacts,
  presentation,
  isProcessing,
  onPreviewArtifact,
  onSelectStage,
  ariaLabel = 'Run overview',
}: {
  artifacts: DerivedAgentTaskArtifacts;
  presentation: AgentRunOverviewPresentation;
  isProcessing: boolean;
  onPreviewArtifact: (artifactId: string) => void;
  onSelectStage?: (stage: AgentRunOverviewStage) => void;
  ariaLabel?: string;
}) {
  const terminalStateLabel = isProcessing
    ? 'Working now'
    : presentation.terminalState === 'completed'
      ? 'Ready for review'
      : presentation.stoppedByUser
        ? 'Stopped by you'
        : 'Needs attention';

  return (
    <section className="run-card" aria-label={ariaLabel}>
      {presentation.stages.length > 0 ? (
        <ol className="run-card-stages">
          {presentation.stages.map(stage => {
            const stageClassName = `run-card-stage run-card-stage--${stage.kind} is-${stage.state}`;
            if (!onSelectStage) {
              return (
                <li className={stageClassName} key={stage.id}>
                  <RunStageContent stage={stage} terminalStateLabel={terminalStateLabel} />
                </li>
              );
            }
            return (
              <li className="run-card-stage-item" key={stage.id}>
                <button
                  type="button"
                  className={`${stageClassName} run-card-stage--navigable`}
                  onClick={() => onSelectStage(stage)}
                >
                  <RunStageContent stage={stage} terminalStateLabel={terminalStateLabel} />
                </button>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="run-card-empty">{isProcessing ? 'Waiting for the first meaningful stage.' : 'No high-level stages were recorded.'}</p>
      )}
      {artifacts.produced.length > 0 && (
        <div className="run-card-artifacts" aria-label="Created documents">
          {artifacts.produced.map(artifact => (
            <button className="run-card-artifact" type="button" key={artifact.artifactId} onClick={() => onPreviewArtifact(artifact.artifactId)} aria-label={`Preview ${artifact.displayName}`}>
              <RunStageGlyph stage={{ kind: 'artifact', state: 'completed' }} />
              <span>{artifact.displayName}</span>
              {artifact.review && artifact.review.revisionCount > 1 && (
                <span className="run-card-artifact-badge">v{artifact.review.revisionCount}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
