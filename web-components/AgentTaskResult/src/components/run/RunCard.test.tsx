import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import { EMPTY_RUN_ARTIFACTS, RunCard } from './RunCard';

const waitingOverview: AgentRunOverviewPresentation = {
  terminalState: 'active',
  activityCount: 2,
  artifactCount: 0,
  stages: [
    {
      id: 'overview:execution',
      kind: 'phase',
      label: 'Completing task',
      state: 'waiting',
      startedAt: '2026-10-05T10:00:00Z',
      artifactCount: 0,
    },
    {
      id: 'overview:interaction:user_interaction_cp',
      kind: 'interaction',
      label: 'Basil asked',
      state: 'waiting',
      startedAt: '2026-10-05T10:00:01Z',
      artifactCount: 0,
      interaction: {
        id: 'cp',
        entryId: 'user_interaction_cp',
        kind: 'clarification',
        status: 'waiting',
        prompt: 'Which hotel?',
        askedAt: '2026-10-05T10:00:01Z',
        responseHidden: false,
        options: [],
      },
    },
  ],
};

describe('RunCard', () => {
  it("marks waiting stages as the user's turn", () => {
    const markup = renderToStaticMarkup(
      <RunCard artifacts={EMPTY_RUN_ARTIFACTS} presentation={waitingOverview} isProcessing={false} onPreviewArtifact={() => undefined} />,
    );

    expect(markup.match(/class="run-card-your-turn"/g)).toHaveLength(2);
    expect(markup).toContain('Waiting on you');
    expect(markup).toContain('Waiting for your answer');
    expect(markup).toContain('M9.2 9.2');
  });

  it('says a stopped run was stopped by the user', () => {
    const markup = renderToStaticMarkup(
      <RunCard
        artifacts={EMPTY_RUN_ARTIFACTS}
        presentation={{
          terminalState: 'failed',
          stoppedByUser: true,
          activityCount: 1,
          artifactCount: 0,
          stages: [{ id: 'overview:outcome:failed', kind: 'outcome', label: 'Run stopped', state: 'failed', startedAt: '', artifactCount: 0 }],
        }}
        isProcessing={false}
        onPreviewArtifact={() => undefined}
      />,
    );

    expect(markup).toContain('Run stopped');
    expect(markup).toContain('Stopped by you');
    expect(markup).not.toContain('Needs attention');
  });
});
